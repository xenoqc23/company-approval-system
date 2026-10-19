"""Actual browser proof of upgraded reviewer grants, independent of the author."""
import argparse,json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright,expect
p=argparse.ArgumentParser();p.add_argument('--base-url',default='http://127.0.0.1:18094');p.add_argument('--fixture',type=Path,required=True);p.add_argument('--password-file',type=Path,required=True);p.add_argument('--output',type=Path,default=Path('test-results/reviewer-authority-browser'));a=p.parse_args();base=a.base_url.rstrip('/');assert urlsplit(base).hostname in ['localhost','127.0.0.1']
f=json.loads(a.fixture.read_text());pw=a.password_file.read_text();a.output.mkdir(parents=True,exist_ok=True);errors=[];assets=[]
def login(browser,user):
    c=browser.new_context(viewport={'width':1366,'height':950},locale='ko-KR',timezone_id='Asia/Seoul');page=c.new_page();page.on('pageerror',lambda e:errors.append(str(e)));page.on('response',lambda r:assets.append(r.url) if '/static/' in r.url and r.status>=400 else None)
    page.goto(base+'/login/');page.locator('[name=username]').fill(user);page.locator('[name=password]').fill(pw);page.locator('[data-login-form] button[type=submit]').click();page.wait_for_url(base+'/');return c,page

def fits(page):assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),page.url
with sync_playwright() as tool:
    b=tool.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
    ac,admin=login(b,'admin');ruleurl=base+f"/regulations/delegation/{f['rule']}/";docurl=base+f"/documents/{f['document']}/"
    admin.goto(ruleurl)
    expect(admin.locator(f'[name=authors][value="{f["reviewer"]}"]')).to_be_checked()
    expect(admin.locator(f'[name=review_final_users][value="{f["reviewer"]}"]')).to_be_checked()
    expect(admin.locator(f'[name=authors][value="{f["owner"]}"]')).not_to_be_checked()
    expect(admin.get_by_text('전결 가능한 검토자 (과장급 이상 · 체크한 직원만)',exact=True)).to_be_visible()
    admin.screenshot(path=str(a.output/'admin-reviewer-permissions.png'),full_page=True)
    rc,review=login(b,'reviewer');review.goto(docurl)
    expect(review.locator('.inline-info').first).to_contain_text('기본 결재규정')
    expect(review.get_by_role('button',name='검토자 전결',exact=True)).to_be_visible()
    for width in [320,390,768,1366]:
        review.set_viewport_size({'width':width,'height':950});fits(review)
        review.screenshot(path=str(a.output/f'reviewer-final-{width}.png'),full_page=True)
    # Existing pending document responds immediately to permission revocation and re-grant.
    admin.locator('[name=allow_review_final]').uncheck();admin.get_by_role('button',name='규정 저장',exact=True).click();admin.wait_for_url(base+'/regulations/')
    review.reload();expect(review.get_by_role('button',name='검토자 전결',exact=True)).to_have_count(0)
    admin.goto(ruleurl);admin.locator('[name=allow_review_final]').check();admin.get_by_role('button',name='규정 저장',exact=True).click();admin.wait_for_url(base+'/regulations/')
    review.reload();expect(review.get_by_role('button',name='검토자 전결',exact=True)).to_be_visible()
    form=review.locator('[data-document-action=review_final]');form.locator('[name=reason]').fill('체크된 검토자 권한으로 최종 승인');form.get_by_role('button',name='검토자 전결',exact=True).click();review.wait_for_load_state('networkidle')
    expect(review.locator('.page-heading .badge')).to_have_text('결재완료')
    review.screenshot(path=str(a.output/'review-final-complete.png'),full_page=True)
    oc,owner=login(b,'employee');expect(owner.locator('.personal-leave-values .remaining dd')).to_contain_text('12')
    # Only the reviewer list changes. Author-specific self/skip grants remain preserved.
    admin.goto(ruleurl);expect(admin.locator('[name=allow_self_approval]')).to_be_checked();expect(admin.locator('[name=allow_skip_review]')).to_be_checked();expect(admin.locator(f'[name=authors][value="{f["reviewer"]}"]')).to_be_checked()
    for c in [ac,rc,oc]:c.close()
    b.close()
assert not errors,errors
assert not assets,assets
result=dict(passed=True,preexisting_pending_document=True,selected_reviewers_migrated=True,author_not_required=True,live_revoke_regrant=True,final_charge_once=True,author_permissions_preserved=True,viewports=[320,390,768,1366],js_errors=errors,failed_assets=assets)
(a.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result))
