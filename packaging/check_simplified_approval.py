"""Local fictional fixtures only; exercises draft, immediate completion and reversal."""
import argparse,json
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import expect,sync_playwright
parser=argparse.ArgumentParser()
parser.add_argument('--base-url',default='http://127.0.0.1:18086')
parser.add_argument('--output',type=Path,default=Path('test-results/simplified-approval-browser'))
args=parser.parse_args();base=args.base_url.rstrip('/')
if urlsplit(base).hostname not in {'localhost','127.0.0.1'}:parser.error('Use local fictional fixtures only.')
args.output.mkdir(parents=True,exist_ok=True)
errors=[];bad_assets=[];results=[]

def login(page,user):
    page.goto(base+'/login/')
    page.locator('[name=username]').fill(user)
    page.locator('[name=password]').fill('simplified-qa-only')
    page.locator('[data-login-form] button[type=submit]').click()
    page.wait_for_url(base+'/')

def fits(page):
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'),page.url

def personal_used(page):
    page.goto(base+'/balances/?year=2026')
    headers=page.locator('.employee-leave-table th').all_text_contents()
    text=page.locator('.employee-leave-table tbody tr').first.locator('td').nth(headers.index('개인 사용연차')).inner_text()
    return Decimal(text.replace('일','').replace(',',''))

with sync_playwright() as pw:
    browser=pw.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
    for index,width in enumerate([320,390,768,1366]):
        context=browser.new_context(viewport={'width':width,'height':900},locale='ko-KR',is_mobile=width<600,has_touch=width<1080)
        page=context.new_page()
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.on('response',lambda response:bad_assets.append(response.url) if '/static/' in response.url and response.status>=400 else None)
        login(page,'reviewer');before=personal_used(page)
        page.goto(base+'/compose/?kind=leave')
        expect(page.locator('#route-preview')).to_contain_text('QA 팀장 간소결재')
        expect(page.locator('#id_reviewer')).to_have_value('4')
        expect(page.locator('#id_approver')).to_have_value('4')
        assert page.locator('#id_approval_mode option').all_text_contents()==['규정 기본','검토 생략','본인 전결']
        page.locator('#id_approval_mode').select_option('skip')
        expect(page.locator('#route-preview')).to_contain_text('기안 → 승인')
        expect(page.locator('#reviewer-field')).to_be_hidden()
        expect(page.locator('#approver-field')).to_be_visible()
        page.locator('#id_approval_mode').select_option('self')
        expect(page.locator('#route-preview')).to_contain_text('제출 즉시 완료')
        expect(page.locator('#reviewer-field')).to_be_hidden();expect(page.locator('#approver-field')).to_be_hidden()
        expect(page.locator('#submit-label')).to_have_text('전결로 제출·완료')
        day=f'2026-11-{9+index:02d}'
        page.locator('#id_start_date').fill(day);page.locator('#id_end_date').fill(day)
        page.locator('#id_reason').fill(f'QA {width}px 전결 검증')
        fits(page);page.screenshot(path=str(args.output/f'compose-{width}.png'),full_page=True)
        page.get_by_role('button',name='임시저장',exact=True).click()
        expect(page.locator('.badge.large')).to_contain_text('임시저장')
        edit=page.get_by_role('link',name='이어서 작성').get_attribute('href')
        assert personal_used(page)==before
        page.goto(base+edit)
        expect(page.locator('#route-preview')).to_contain_text('제출 즉시 완료')
        page.get_by_role('button',name='전결로 제출·완료',exact=True).click()
        expect(page.locator('.badge.large')).to_contain_text('결재완료')
        expect(page.locator('[data-stage=review]')).to_have_count(0)
        expect(page.locator('[data-stage=approval]')).to_contain_text('본인 전결')
        expect(page.locator('.history-list')).to_contain_text('본인 전결')
        detail=page.url;fits(page)
        page.screenshot(path=str(args.output/f'completed-{width}.png'),full_page=True)
        assert personal_used(page)==before+1
        page.goto(detail)
        cancel=page.locator('form[data-document-action=cancel_approval]')
        cancel.locator('[name=reason]').fill('QA 전결 취소 검증')
        cancel.get_by_role('button').click()
        page.locator('#confirmation-go').click()
        expect(page.locator('.badge.large')).to_contain_text('취소')
        assert personal_used(page)==before
        context.close()
        for user,allowed in [('employee',None),('sales',['규정 기본','검토 생략'])]:
            c=browser.new_context(viewport={'width':width,'height':900},locale='ko-KR');p=c.new_page();login(p,user)
            p.goto(base+'/compose/?kind=leave');expect(p.locator('#route-preview')).not_to_contain_text('확인하고 있습니다')
            if allowed is None:expect(p.locator('#approval-mode-picker')).to_have_count(0)
            else:assert p.locator('#id_approval_mode option').all_text_contents()==allowed
            fits(p);c.close()
        results.append({'width':width,'passed':True,'checks':['fixed people','skip-only','senior self draft/complete/cancel','one charge/restoration','junior restriction','no overflow']})
    context=browser.new_context(viewport={'width':1366,'height':900});page=context.new_page();login(page,'accounting')
    page.goto(base+'/regulations/')
    expect(page.locator('#id_allow_skip_review')).to_be_visible();expect(page.locator('#id_allow_self_approval')).to_be_visible()
    page.locator('#sim-author').select_option('3');page.locator('#sim-kind').select_option('leave');page.locator('#sim-mode').select_option('self')
    page.locator('#rule-simulator').get_by_role('button').click()
    expect(page.locator('#rule-simulator-result')).to_contain_text('본인 전결')
    fits(page);page.screenshot(path=str(args.output/'regulations-1366.png'),full_page=True)
    context.close();browser.close()
assert not errors,errors
assert not bad_assets,bad_assets
(args.output/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
print(json.dumps({'viewports':len(results),'passed':True,'javascript_errors':errors,'failed_assets':bad_assets}))
