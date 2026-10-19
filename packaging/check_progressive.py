"""Actual browser checks on a fresh, fictional local progressive fixture only."""
import argparse,json,re
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright,expect
p=argparse.ArgumentParser();p.add_argument('--base-url',default='http://127.0.0.1:18092');p.add_argument('--password-file',type=Path,required=True);p.add_argument('--output',type=Path,default=Path('test-results/progressive-browser'));a=p.parse_args();base=a.base_url.rstrip('/');assert urlsplit(base).hostname in ['localhost','127.0.0.1']
pw=a.password_file.read_text();a.output.mkdir(parents=True,exist_ok=True);errors=[];assets=[]
def fits(page):assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1'),page.url
def login(browser,user,width=1366):
    context=browser.new_context(viewport={'width':width,'height':950},locale='ko-KR',timezone_id='Asia/Seoul',is_mobile=width<600,has_touch=width<1080)
    page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)));page.on('response',lambda r:assets.append(r.url) if '/static/' in r.url and r.status>=400 else None)
    page.goto(base+'/login/');page.locator('[name=username]').fill(user);page.locator('[name=password]').fill(pw);page.locator('[data-login-form] button[type=submit]').click();page.wait_for_url(base+'/');return context,page

def close_feedback(page):
    if page.locator('#approval-feedback').is_visible():page.locator('#approval-feedback-close').click()
with sync_playwright() as tool:
    browser=tool.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
    contexts=[]
    for width in [320,390,768,1366]:
        ctx,pg=login(browser,'employee',width);contexts.append(ctx);fits(pg)
        sizes=pg.locator('.personal-leave-values dd').evaluate_all('(els)=>els.map(el=>parseFloat(getComputedStyle(el).fontSize))');assert sizes[2]>sizes[0] and sizes[2]>sizes[1],sizes
        pg.locator('.mint-balance').screenshot(path=str(a.output/f'leave-emphasis-{width}.png'))
        pg.goto(base+'/compose/?kind=leave');expect(pg.locator('#compose-form')).to_have_attribute('data-progressive','true')
        expect(pg.locator('#reviewer-field')).to_be_visible();expect(pg.locator('#approver-field')).to_be_hidden();fits(pg)
        pg.screenshot(path=str(a.output/f'compose-{width}.png'),full_page=True);ctx.close()
    ownerctx,owner=login(browser,'employee');contexts.append(ownerctx)
    owner.goto(base+'/compose/?kind=leave');expect(owner.locator('#compose-form')).to_have_attribute('data-progressive','true')
    owner.locator('[name=start_date]').fill('2026-11-09');owner.locator('[name=end_date]').fill('2026-11-11');owner.locator('[name=reason]').fill('가상 직원의 3일 휴가 신청 예시')
    owner.locator('[name=reviewer_department]').select_option('개발팀');owner.locator('[name=reviewer]').select_option(label='김민준 · 개발팀 팀장')
    owner.get_by_role('button',name='기안 제출',exact=True).click();owner.wait_for_url(re.compile(re.escape(base)+r'/documents/\d+/'));docurl=owner.url
    expect(owner.locator('.progressive-track')).to_contain_text('검토 후 결정')
    rc,review=login(browser,'reviewer');contexts.append(rc);review.goto(docurl)
    expect(review.get_by_role('button',name='검토자 전결',exact=True)).to_be_visible()
    forward=review.locator('form[data-document-action=forward]');forward.locator('[name=new_person_department]').select_option('전략기획팀');forward.locator('[name=new_person]').select_option(label='박지훈 · 전략기획팀 이사');forward.locator('[name=reason]').fill('3일 휴가로 승인자 판단 요청')
    review.screenshot(path=str(a.output/'reviewer-forward-desktop.png'),full_page=True)
    for width in [320,390,768,1366]:
        review.set_viewport_size({'width':width,'height':950});fits(review)
    forward.get_by_role('button',name='상위 결재 요청',exact=True).click();review.wait_for_load_state('networkidle')
    ac,approver=login(browser,'approver');contexts.append(ac);approver.goto(docurl);expect(approver.get_by_role('button',name='대표 결재 요청',exact=True)).to_be_visible()
    approver.screenshot(path=str(a.output/'approver-options-desktop.png'),full_page=True)
    for width in [320,390,768,1366]:
        approver.set_viewport_size({'width':width,'height':950});fits(approver)
    form=approver.locator('form[data-document-action=escalate]');form.locator('[name=reason]').fill('부서 업무 공백 확인을 위해 대표 판단 요청');form.get_by_role('button',name='대표 결재 요청',exact=True).click();approver.wait_for_load_state('networkidle')
    expect(approver.locator('.page-heading .badge')).to_have_text('대표결재대기')
    owner.goto(base+'/');expect(owner.locator('.personal-leave-values .remaining dd')).to_contain_text('0.25')
    cc,ceo=login(browser,'representative',390);contexts.append(cc);expect(ceo.locator('.main')).to_contain_text('대표 결재함');ceo.goto(docurl);fits(ceo)
    ceo.screenshot(path=str(a.output/'representative-pending-390.png'),full_page=True)
    ceo.get_by_role('button',name='대표 최종 승인',exact=True).click();ceo.wait_for_load_state('networkidle');close_feedback(ceo);expect(ceo.locator('.page-heading .badge')).to_have_text('결재완료')
    owner.goto(base+'/');expect(owner.locator('.personal-leave-values .remaining dd')).to_contain_text('-2.75')
    # Explicitly granted senior modes and threshold changes in the actual form.
    review.goto(base+'/compose/?kind=office');expect(review.locator('#compose-form')).to_have_attribute('data-progressive','true')
    review.locator('[name=quantity]').fill('1');review.locator('[name=unit_price]').fill('1000000');review.locator('[name=unit_price]').dispatch_event('change')
    expect(review.locator('[name=approval_mode] option[value=self]')).to_have_count(1)
    expect(review.locator('[name=approval_mode] option[value=ceo]')).to_have_count(1)
    review.locator('[name=approval_mode]').select_option('ceo');expect(review.locator('#representative-mode-note')).to_be_visible();expect(review.locator('#reviewer-field')).to_be_hidden();expect(review.locator('#approver-field')).to_be_hidden()
    review.screenshot(path=str(a.output/'senior-direct-representative.png'),full_page=True)
    # Small request permits the explicitly granted reviewer final action.
    owner.goto(base+'/compose/?kind=leave');expect(owner.locator('#compose-form')).to_have_attribute('data-progressive','true')
    owner.locator('[name=start_date]').fill('2026-11-12');owner.locator('[name=end_date]').fill('2026-11-12');owner.locator('[name=reason]').fill('하루 휴가 예시');owner.locator('[name=reviewer_department]').select_option('개발팀');owner.locator('[name=reviewer]').select_option(label='김민준 · 개발팀 팀장')
    owner.get_by_role('button',name='기안 제출',exact=True).click();owner.wait_for_url(re.compile(re.escape(base)+r'/documents/\d+/'));review.goto(owner.url)
    expect(review.get_by_role('button',name='검토자 전결',exact=True)).to_be_visible()
    form=review.locator('form[data-document-action=review_final]');form.locator('[name=reason]').fill('부서 내 일정 확인 완료');form.get_by_role('button',name='검토자 전결',exact=True).click();review.wait_for_load_state('networkidle');expect(review.locator('.page-heading .badge')).to_have_text('결재완료')
    # Root admin settings are visible; no data change is needed here.
    adctx,admin=login(browser,'admin');contexts.append(adctx);admin.goto(base+'/regulations/');expect(admin.locator('.flow-settings')).to_contain_text('단계별 결재 기준');fits(admin)
    admin.screenshot(path=str(a.output/'flow-settings-desktop.png'),full_page=True)
    for ctx in contexts:
        try:ctx.close()
        except Exception:pass
    browser.close()
assert not errors,errors
assert not assets,assets
result={'passed':True,'viewports':[320,390,768,1366],'remaining_emphasis':True,'reviewer_only_compose':True,'reviewer_forward':True,'reviewer_final':True,'threshold_executive_choice':True,'final_only_charge':True,'representative_approval':True,'senior_direct_mode':True,'js_errors':errors,'failed_assets':assets}
(a.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result))
