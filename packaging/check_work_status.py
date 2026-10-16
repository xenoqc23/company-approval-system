"""Check the UI against the isolated work-status seed_demo fixture only."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import expect, sync_playwright

parser = argparse.ArgumentParser()
parser.add_argument('--base-url', default='http://127.0.0.1:18086')
parser.add_argument('--output', type=Path, default=Path('test-results/work-status-browser'))
args = parser.parse_args()
base = args.base_url.rstrip('/')
if urlsplit(base).hostname not in {'127.0.0.1', 'localhost'}:
    parser.error('Use local fictional accounts only.')
args.output.mkdir(parents=True, exist_ok=True)
results, errors, bad_assets = [], [], []


def fits(page):
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), page.url


def login(page, username):
    page.goto(base + '/login/')
    page.locator('[name=username]').fill(username)
    page.locator('[name=password]').fill('manual-leave-test-only')
    page.locator('[data-login-form] button[type=submit]').click()
    page.wait_for_url(base + '/')


with sync_playwright() as pw:
    browser = pw.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
    for width in [320, 390, 768, 1366]:
        context = browser.new_context(viewport={'width':width, 'height':900}, locale='ko-KR',
            is_mobile=width < 600, has_touch=width < 1080)
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('response', lambda response: bad_assets.append(response.url)
            if '/static/' in response.url and response.status >= 400 else None)
        login(page, 'accounting')
        expect(page.locator('.pending-approval-summary')).to_contain_text('미결 0건')
        fits(page)
        page.goto(base + '/balances/?year=2026')
        headers = page.locator('.employee-leave-table th').all_text_contents()
        assert '개인 사용연차' in headers
        row = page.locator('.employee-leave-table tbody tr').filter(has=page.locator('a.leave-employee-link strong', has_text='이서연'))
        expect(row.locator('td').nth(headers.index('개인 사용연차'))).to_have_text('4일')
        expect(row.locator('td').nth(headers.index('공통사용연차'))).to_have_text('1')
        expect(row.locator('td').nth(headers.index('잔여연차'))).to_have_text('10일')
        fits(page)
        page.screenshot(path=str(args.output / f'balances-{width}.png'), full_page=True)
        page.goto(base + '/calendar/?year=2026&month=11')
        fits(page)
        cell = page.locator('.month-calendar td.common-leave-day')
        expect(cell).to_have_count(1)
        assert cell.locator('.calendar-day-number').inner_text() == '4'
        color = cell.locator('.calendar-day-number').evaluate('(el)=>getComputedStyle(el).color')
        legend = page.locator('.legend.company').evaluate('(el)=>getComputedStyle(el,"::before").backgroundColor')
        assert color == legend == 'rgb(176, 110, 22)'
        assert cell.locator('.calendar-event.company').evaluate('(el)=>getComputedStyle(el).borderLeftColor') == color
        manual = page.locator('.calendar-event.leave').filter(has_text='직접 등록')
        assert manual.count() == 4  # Desktop grid and mobile agenda each contain both fixtures.
        assert 'QA private' not in page.locator('body').inner_text()
        if width < 600:
            expect(page.locator('.mobile-calendar-agenda')).to_be_visible()
            agenda = page.locator('.mobile-agenda-day.common-leave-day h3')
            expect(agenda).to_be_visible()
            assert agenda.evaluate('(el)=>getComputedStyle(el).color') == color
        page.screenshot(path=str(args.output / f'calendar-{width}.png'), full_page=True)
        context.close()
        context = browser.new_context(viewport={'width':width, 'height':900}, locale='ko-KR')
        page = context.new_page()
        login(page, 'reviewer')
        counter = page.locator('.pending-approval-summary')
        assert counter.locator('strong').inner_text() != '0건'
        expect(counter).to_have_class('pending-approval-summary has-pending')
        fits(page)
        page.screenshot(path=str(args.output / f'pending-{width}.png'), full_page=True)
        counter.click()
        page.wait_for_url(base + '/documents/?mode=pending')
        expect(page.locator('h1')).to_contain_text('결재함')
        page.goto(base + '/calendar/?year=2026&month=11')
        assert page.locator('a.calendar-event.leave').filter(has_text='직접 등록').count() == 0
        assert 'QA private' not in page.content()
        context.close()
        results.append({'width':width, 'passed':True,
            'checks':['zero/actionable pending and link', 'personal/common numeric split',
                'manual calendar/privacy/permissions', 'matching company date color', 'no page overflow']})
    browser.close()
assert not errors, errors
assert not bad_assets, bad_assets
(args.output / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
print(json.dumps({'viewports':len(results), 'passed':True, 'javascript_errors':errors, 'failed_assets':bad_assets}, ensure_ascii=False))
