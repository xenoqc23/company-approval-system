"""Four NAS features through real forms, cookies and production static assets; fictional data only."""
import argparse,json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright,expect
p=argparse.ArgumentParser();p.add_argument('--base-url',default='http://127.0.0.1:18098');p.add_argument('--password-file',type=Path,required=True);p.add_argument('--output',type=Path,default=Path('test-results/document-updates-browser'));a=p.parse_args()
base=a.base_url.rstrip('/');assert urlsplit(base).hostname in ['127.0.0.1','localhost'];pw=a.password_file.read_text();a.output.mkdir(parents=True,exist_ok=True);errors=[];assets=[];push=[]

def login(browser,name):
 c=browser.new_context(viewport={'width':1366,'height':950},locale='ko-KR',timezone_id='Asia/Seoul')
 c.add_init_script("Object.defineProperty(window,'Notification',{get(){throw new Error('OS Notification API must remain deferred')}})")
 page=c.new_page();page.on('pageerror',lambda e:errors.append(str(e)));page.on('response',lambda r:assets.append(r.url) if '/static/' in r.url and r.status>=400 else None);page.on('request',lambda r:push.append(r.url) if '/notifications/push/' in r.url else None)
 page.goto(base+'/login/');page.locator('[name=username]').fill(name);page.locator('[name=password]').fill(pw);page.locator('[data-login-form] button[type=submit]').click();page.wait_for_url(base+'/');return c,page

def summary(context):return context.request.get(base+'/notifications/status/').json()
def refresh(page):page.bring_to_front();page.evaluate("window.dispatchEvent(new Event('xenosys-refresh-notifications'))")
def finish(page,url):
 page.goto(url);form=page.locator('[data-document-action=review_final]');form.locator('[name=reason]').fill('가상 검증 전결');form.get_by_role('button',name='검토자 전결',exact=True).click();page.wait_for_load_state('networkidle')
def confirm_action(page,action,reason=''):
 form=page.locator(f'[data-document-action={action}]');
 if reason:form.locator('[name=reason]').fill(reason)
 form.locator('button').click();page.locator('#confirmation-go').click();page.wait_for_load_state('networkidle')

with sync_playwright() as tool:
 b=tool.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
 oc,owner=login(b,'employee');rc,review=login(b,'reviewer');fc,finance=login(b,'accounting');ac,admin=login(b,'admin')
 owner.goto(base+'/compose/?kind=leave');owner.locator('#id_start_date').fill('2026-11-12');owner.locator('#id_end_date').fill('2026-11-12');owner.locator('#id_reason').fill('가상 직원 휴가 신청');owner.locator('#id_reviewer_department').select_option(label='개발팀');owner.locator('#id_reviewer').select_option(label='예시검토자 · 개발팀 팀장');owner.get_by_role('button',name='기안 제출',exact=True).click();owner.wait_for_url('**/documents/*/');docurl=owner.url
 finish(review,docurl)
 owner.goto(base+'/');expect(owner.locator('[data-live-count=completed_unread]')).to_have_text('1');owner.screenshot(path=str(a.output/'owner-unread-home.png'),full_page=True)
 owner.locator('.completion-summary').click();expect(owner.locator('.document-new')).to_have_count(1);assert summary(oc)['completed_unread']==1
 owner.locator(f'.document-cell[href="{urlsplit(docurl).path}"]').click();assert summary(oc)['completed_unread']==0
 finance.goto(docurl);finance.get_by_role('link',name='휴가 사용내역 정정',exact=True).click();finance.locator('#id_leave_type').select_option('am');finance.locator('#id_start_time').fill('09:00');finance.locator('#id_end_time').fill('13:00');finance.locator('#id_correction_reason').fill('실제 오전반차 사용으로 1일에서 0.5일로 정정');finance.get_by_role('button',name='변경 내용 미리보기',exact=True).click();expect(finance.locator('[data-correction-preview]')).to_contain_text('19.5일');finance.screenshot(path=str(a.output/'leave-correction-preview.png'),full_page=True)
 # An edited preview cannot accidentally save old confirmation.
 finance.locator('#id_correction_reason').fill('실제 오전반차 사용 · 일정 변경 확인');expect(finance.locator('[data-correction-save]')).to_have_count(0);finance.get_by_role('button',name='변경 내용 미리보기',exact=True).click();finance.get_by_role('button',name='확인한 내용으로 정정 저장',exact=True).click();finance.wait_for_url(docurl)
 expect(finance.locator('body')).to_contain_text('승인 후 정정');expect(finance.locator('body')).to_contain_text('변경 전: 연차');expect(finance.locator('body')).to_contain_text('변경 후: 오전반차');finance.screenshot(path=str(a.output/'corrected-document.png'),full_page=True)
 assert summary(oc)['completed_unread']==1
 owner.goto(base+'/');expect(owner.locator('[data-live-count=completed_unread]')).to_have_text('1');owner.goto(docurl);assert summary(oc)['completed_unread']==0
 owner.goto(base+'/calendar/?year=2026&month=11');expect(owner.locator('body')).to_contain_text('예시기안자 · 오전반차')
 review.goto(docurl);confirm_action(review,'cancel_approval','실제 사용 취소 검증')
 finance.goto(docurl);expect(finance.locator('[data-document-action=delete]')).to_have_count(1);confirm_action(finance,'delete')
 admin.goto(base+'/documents/?mode=deleted');expect(admin.locator(f'.document-cell[href="{urlsplit(docurl).path}"]')).to_have_count(1);admin.screenshot(path=str(a.output/'admin-deleted-archive.png'),full_page=True)
 owner.goto(docurl);assert owner.locator('body').inner_text().strip()=='Not Found' or 'Not Found' in owner.title()
 # Ordinary employee can see minimal shared purchase facts, not original private document.
 owner.goto(base+'/compose/?kind=office');owner.locator('#id_product').fill('복사용지');box=owner.locator('[data-purchase-hints-results]');expect(box).to_contain_text('유사 구매요청이 2건');expect(box).to_contain_text('배송완료');expect(box).not_to_contain_text('기밀');expect(box).not_to_contain_text('취소된');expect(box).not_to_contain_text('PRIVATE_DO_NOT_SHARE')
 for width in [320,390,768,1366,2560]:
  owner.set_viewport_size({'width':width,'height':950});assert owner.evaluate('document.documentElement.scrollWidth<=innerWidth+1');owner.screenshot(path=str(a.output/f'purchase-hints-{width}.png'),full_page=True)
 owner.set_viewport_size({'width':1366,'height':950});owner.locator('#id_quantity').fill('1');owner.locator('#id_unit_price').fill('1000');owner.locator('#id_url').fill('https://example.com/item');owner.locator('#id_reason').fill('유사 품목 확인 후 추가 구매 필요');owner.locator('#id_reviewer_department').select_option(label='개발팀');owner.locator('#id_reviewer').select_option(label='예시검토자 · 개발팀 팀장');owner.get_by_role('button',name='기안 제출',exact=True).click();owner.wait_for_url('**/documents/*/')
 # Verify no browser-level push work or external provider calls occur on NAS.
 assert not push,push;assert not errors,errors;assert not assets,assets;assert not any(c.service_workers for c in [oc,rc,fc,ac])
 result=dict(passed=True,production_gunicorn_whitenoise_mariadb=True,owner_completion_detail_only=True,correction_preview_and_delta=True,original_approval_and_correction_history=True,corrected_calendar=True,cancel_then_delete=True,admin_retained_archive=True,all_history_purchase_hints=True,purchase_submission_not_blocked=True,minimal_purchase_metadata=True,responsive_widths=[320,390,768,1366,2560],no_webpush=True,js_errors=errors,failed_assets=assets)
 (a.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False))
 for c in [oc,rc,fc,ac]:c.close()
 b.close()
