"""Local fictional seed_demo only: common rules, regulated stock and retained-history deletion."""
import argparse,json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import expect,sync_playwright
p=argparse.ArgumentParser();p.add_argument('--base-url',default='http://127.0.0.1:18087');p.add_argument('--output',type=Path,default=Path('test-results/common-rules-browser'));args=p.parse_args()
base=args.base_url.rstrip('/')
if urlsplit(base).hostname not in {'127.0.0.1','localhost'}:p.error('Use local fictional fixtures only.')
args.output.mkdir(parents=True,exist_ok=True)
NAME='QA 모든 문서 공통';errors=[];bad=[];pending=[];results=[]

def fits(page):assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),page.url

def login(page,user):
    page.goto(base+'/login/');page.locator('[name=username]').fill(user);page.locator('[name=password]').fill('common-rules-test-only');page.locator('[data-login-form] button[type=submit]').click();page.wait_for_url(base+'/')

def row(page):return page.locator('table tbody tr').filter(has=page.get_by_text(NAME,exact=True))

def close_feedback(page):
    if page.locator('#approval-feedback').is_visible():page.locator('#approval-feedback-close').click()

with sync_playwright() as pw:
    browser=pw.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
    manager=browser.new_context(viewport={'width':1366,'height':900});m=manager.new_page();login(m,'accounting');m.goto(base+'/regulations/')
    if row(m).count():
        row(m).get_by_role('button',name='삭제',exact=True).click();m.locator('#confirmation-go').click();m.wait_for_url(base+'/regulations/')
    expect(m.locator('#id_kind')).to_have_value('all')
    m.locator('#id_name').fill(NAME);m.locator('input[name=authors][value="3"]').check()
    m.locator('#id_fixed_reviewer').select_option('4');m.locator('#id_fixed_approver').select_option('4')
    m.locator('#id_allow_skip_review').check();m.locator('#id_allow_self_approval').check();m.locator('#id_enabled').check()
    m.get_by_role('button',name='규정 저장',exact=True).click();m.wait_for_url(base+'/regulations/')
    expect(row(m)).to_contain_text('모든 문서');edit=row(m).get_by_role('link',name='수정',exact=True).get_attribute('href')
    fits(m);m.screenshot(path=str(args.output/'rules-1366.png'),full_page=True)
    for width in [320,390,768,1366]:
        c=browser.new_context(viewport={'width':width,'height':900},locale='ko-KR',is_mobile=width<600,has_touch=width<1080);page=c.new_page()
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('response',lambda r:bad.append(r.url) if '/static/' in r.url and r.status>=400 else None)
        login(page,'reviewer')
        for kind in ['leave','office','stock']:
            page.goto(base+'/compose/?kind='+kind)
            if kind=='office':page.locator('#id_unit_price').fill('100')
            expect(page.locator('#route-preview')).to_contain_text(NAME)
            assert page.locator('#id_approval_mode option').all_text_contents()==['규정 기본','검토 생략','본인 전결']
        expect(page.locator('#approver-field')).to_be_visible();expect(page.locator('#reviewer-field')).to_be_visible()
        page.locator('#id_product').fill(f'QA {width}px 공통 재고');page.locator('#id_quantity').fill('2')
        page.get_by_role('button',name='재고 요청 제출',exact=True).click()
        expect(page.locator('.approval-track.four-stage')).to_be_visible();expect(page.locator('[data-stage=approval]')).to_contain_text('최종 승인')
        expect(page.locator('.badge.large')).to_contain_text('검토대기');pending.append((width,page.url));fits(page)
        page.screenshot(path=str(args.output/f'stock-basic-{width}.png'),full_page=True)
        page.goto(base+'/compose/?kind=stock');expect(page.locator('#route-preview')).to_contain_text(NAME)
        page.locator('#id_approval_mode').select_option('skip');expect(page.locator('#reviewer-field')).to_be_hidden();expect(page.locator('#approver-field')).to_be_visible()
        page.locator('#id_approval_mode').select_option('self');expect(page.locator('#route-preview')).to_contain_text('본인 전결')
        expect(page.locator('#approver-field')).to_be_hidden();page.locator('#id_product').fill(f'QA {width}px 재고 전결')
        page.get_by_role('button',name='전결로 제출·완료',exact=True).click()
        expect(page.locator('.badge.large')).to_contain_text('발주대기');expect(page.locator('[data-stage=approval]')).to_contain_text('본인 전결');expect(page.locator('[data-stage=review]')).to_have_count(0)
        expect(page.locator('form[data-document-action=delete]')).to_have_count(0);fits(page)
        page.screenshot(path=str(args.output/f'stock-self-{width}.png'),full_page=True);c.close()
        results.append({'width':width,'common_rule_all_kinds':True,'stock_basic_skip_self':True,'fits':True})
    m.goto(base+'/regulations/')
    m.set_viewport_size({'width':390,'height':900});fits(m)
    row(m).get_by_role('button',name='삭제',exact=True).click();expect(m.locator('#confirmation')).to_be_visible();expect(m.locator('#confirmation-text')).to_contain_text('기존 문서')
    m.locator('#confirmation-go').click();m.wait_for_url(base+'/regulations/');expect(row(m)).to_have_count(0)
    assert manager.request.get(base+edit).status==404
    m.screenshot(path=str(args.output/'rule-deleted-390.png'),full_page=True)
    c=browser.new_context(viewport={'width':1366,'height':900});a=c.new_page();login(a,'approver');rejected=[]
    for index,(width,url) in enumerate(pending):
        a.goto(url);expect(a.locator('.inline-info').first).to_contain_text(NAME)
        if index%2:
            a.locator('form[data-document-action=review] button').click();close_feedback(a);expect(a.locator('.badge.large')).to_contain_text('최종승인대기')
        if index in [0,1]:
            f=a.locator('form[data-document-action=reject]');f.locator('[name=reason]').fill('QA 보완 요청');f.get_by_role('button').click();expect(a.locator('.badge.large')).to_contain_text('반려');rejected.append((width,url))
        else:
            if index%2==0:a.locator('form[data-document-action=review] button').click();close_feedback(a)
            a.locator('form[data-document-action=approve] button').click();close_feedback(a);expect(a.locator('.badge.large')).to_contain_text('발주대기')
    c.close()
    for width,url in rejected:
        c=browser.new_context(viewport={'width':width,'height':900});o=c.new_page();login(o,'reviewer');o.goto(url);fits(o)
        o.locator('form[data-document-action=delete] button').click();expect(o.locator('#confirmation-text')).to_contain_text('반려 이력')
        o.locator('#confirmation-go').click();o.wait_for_url(base+'/documents/');assert c.request.get(url).status==404;c.close()
    manager.close();browser.close()
assert not errors,errors
assert not bad,bad
(args.output/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
print(json.dumps({'passed':True,'viewports':len(results),'rule_create_delete':True,'pending_routes_survive_delete':True,'owner_rejected_delete':True,'js_errors':errors,'failed_assets':bad}))
