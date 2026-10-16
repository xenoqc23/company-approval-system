"""Browser checks against a local, isolated seed_demo database only."""
import argparse
from datetime import date, timedelta
from decimal import Decimal
import json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import expect, sync_playwright

parser = argparse.ArgumentParser()
parser.add_argument('--base-url', default='http://127.0.0.1:18086')
parser.add_argument('--output', type=Path, default=Path('test-results/manual-leave-browser'))
args = parser.parse_args()
base = args.base_url.rstrip('/')
if urlsplit(base).hostname not in {'127.0.0.1', 'localhost'}:
    parser.error('Use a local server with fictional seed_demo accounts only.')
args.output.mkdir(parents=True, exist_ok=True)
results, errors = [], []


def totals(page):
    return [Decimal(text.replace('일','').replace(',',''))
            for text in page.locator('.leave-summary strong').all_text_contents()]


def no_overflow(page):
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1')


with sync_playwright() as pw:
    browser = pw.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
    for index, width in enumerate([320, 390, 768, 1366]):
        context = browser.new_context(viewport={'width':width, 'height':900}, locale='ko-KR',
                                      is_mobile=width < 600, has_touch=width < 1080)
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(base+'/login/')
        page.locator('[name=username]').fill('accounting')
        page.locator('[name=password]').fill('manual-leave-test-only')
        page.locator('[data-login-form] button[type=submit]').click()
        page.wait_for_url(base+'/')
        history = base+'/balances/2/history/?year=2026'
        new = base+'/balances/2/manual-leave/?year=2026'
        page.goto(history)
        before = totals(page)
        page.get_by_role('link', name='연차 사용 직접 등록', exact=True).click()
        no_overflow(page)
        expect(page.locator('[name=start_time]')).to_be_hidden()
        day = date(2026,11,2)+timedelta(days=index)
        reason = f'가상 검증 {width}px 종이 신청서 접수'
        page.locator('[name=used_date]').fill(str(day))
        page.locator('[name=reason]').fill(reason)
        request = page.locator('[data-manual-leave-form]').evaluate('(form) => Object.fromEntries(new FormData(form))')
        page.screenshot(path=str(args.output/f'form-{width}.png'), full_page=True)
        page.get_by_role('button', name='사용 등록 · 잔여연차 차감', exact=True).click()
        page.wait_for_url('**/balances/2/history/?year=2026')
        expect(page.locator('.manual-history-table tbody tr').filter(has_text=reason)).to_have_count(1)
        assert totals(page) == [before[0],before[1]+1,before[2]-1]
        no_overflow(page)
        page.screenshot(path=str(args.output/f'history-{width}.png'), full_page=True)
        # Retransmission of the original form must be idempotent.
        repeat = context.request.post(new, form=request, headers={'Origin':base, 'Referer':new}, max_redirects=0)
        assert repeat.status == 302
        page.goto(history)
        assert totals(page) == [before[0],before[1]+1,before[2]-1]
        row = page.locator('.manual-history-table tbody tr').filter(has_text=reason)
        row.locator('summary').click()
        row.locator('[name=reason]').fill('가상 검증 등록 취소')
        row.get_by_role('button', name='1일 복원하고 취소', exact=True).click()
        page.wait_for_url('**mode=all')
        assert totals(page) == before
        row = page.locator('.manual-history-table tbody tr').filter(has_text=reason)
        expect(row).to_contain_text('등록 취소')
        expect(row).to_contain_text('가상 검증 등록 취소')
        expect(row.locator('form')).to_have_count(0)
        no_overflow(page)
        results.append({'width':width, 'scenario':'annual registration, replay, cancel, retained history and balance restoration', 'passed':True})

        page.goto(new)
        page.locator('[name=used_date]').fill(str(day))
        page.locator('[name=leave_type]').select_option('am')
        expect(page.locator('[name=start_time]')).to_be_visible()
        assert page.locator('[name=start_time]').evaluate('(input) => input.required')
        page.locator('[name=start_time]').fill('09:00')
        page.locator('[name=end_time]').fill('12:00')
        page.locator('[name=reason]').fill(f'가상 검증 {width}px 반차')
        page.get_by_role('button', name='사용 등록 · 잔여연차 차감', exact=True).click()
        page.wait_for_url('**/balances/2/history/?year=2026')
        assert totals(page) == [before[0],before[1]+Decimal('.5'),before[2]-Decimal('.5')]
        # A different request with an overlapping date is refused, retaining form input.
        page.goto(new)
        page.locator('[name=used_date]').fill(str(day))
        page.locator('[name=reason]').fill('가상 검증 중복 등록 금지')
        page.get_by_role('button', name='사용 등록 · 잔여연차 차감', exact=True).click()
        expect(page.locator('.manual-leave-form .message.error')).to_contain_text('경리 직접 등록한 휴가')
        expect(page.locator('[name=reason]')).to_have_value('가상 검증 중복 등록 금지')
        page.goto(history)
        assert totals(page) == [before[0],before[1]+Decimal('.5'),before[2]-Decimal('.5')]
        row = page.locator('.manual-history-table tbody tr').filter(has_text=f'가상 검증 {width}px 반차')
        row.locator('summary').click()
        row.locator('[name=reason]').fill('가상 검증 반차 취소')
        row.get_by_role('button', name='0.5일 복원하고 취소', exact=True).click()
        page.wait_for_url('**mode=all')
        assert totals(page) == before
        results.append({'width':width, 'scenario':'half-day times, overlapping date rejection, retained form and exact restoration', 'passed':True})
        page.goto(base+'/balances/?year=2026')
        expect(page.get_by_role('link', name='연차 사용 직접 등록', exact=True).first).to_be_visible()
        no_overflow(page)
        context.close()

    # Native form submission also works when JavaScript is disabled.
    context = browser.new_context(java_script_enabled=False)
    page = context.new_page()
    page.goto(base+'/login/')
    page.locator('[name=username]').fill('accounting')
    page.locator('[name=password]').fill('manual-leave-test-only')
    page.locator('[data-login-form] button[type=submit]').click()
    page.wait_for_url(base+'/')
    page.goto(base+'/balances/2/manual-leave/?year=2026')
    page.locator('[name=used_date]').fill('2026-11-06')
    page.locator('[name=reason]').fill('가상 검증 JavaScript 없이 등록')
    page.get_by_role('button', name='사용 등록 · 잔여연차 차감', exact=True).click()
    page.wait_for_url('**/balances/2/history/?year=2026')
    row = page.locator('.manual-history-table tbody tr').filter(has_text='가상 검증 JavaScript 없이 등록')
    expect(row).to_have_count(1)
    row.locator('summary').click()
    row.locator('[name=reason]').fill('가상 검증 끝')
    row.get_by_role('button', name='1일 복원하고 취소', exact=True).click()
    page.wait_for_url('**mode=all')
    results.append({'scenario':'native registration and cancellation without JavaScript', 'passed':True})
    context.close()
    browser.close()

assert not errors, errors
report = {'passed':len(results), 'results':results, 'javascript_errors':errors,
          'data':'fictional seed_demo only', 'static_delivery':'DEBUG=0, WhiteNoise compressed manifest'}
(args.output/'browser-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(json.dumps(report, ensure_ascii=False, indent=2))
