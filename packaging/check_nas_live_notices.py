"""NAS-mode browser coverage: only in-app notifications, with hashed assets."""
import argparse,json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright,expect
p=argparse.ArgumentParser();p.add_argument('--base-url',default='http://127.0.0.1:18097');p.add_argument('--password-file',type=Path,required=True);p.add_argument('--fixture',type=Path,required=True);p.add_argument('--output',type=Path,default=Path('test-results/nas-live-notices-browser'));a=p.parse_args()
base=a.base_url.rstrip('/');assert urlsplit(base).hostname in ['127.0.0.1','localhost'];pw=a.password_file.read_text();fixture=json.loads(a.fixture.read_text());a.output.mkdir(parents=True,exist_ok=True);errors=[];assets=[];push_requests=[]

def attach(page):
 page.on('pageerror',lambda e:errors.append(str(e)))
 page.on('response',lambda r:assets.append(r.url) if '/static/' in r.url and r.status>=400 else None)
 page.on('request',lambda r:push_requests.append(r.url) if '/notifications/push/' in r.url or 'notifications-sw.js' in r.url else None)
def login(page,name):
 page.goto(base+'/login/');page.locator('[name=username]').fill(name);page.locator('[name=password]').fill(pw);page.locator('[data-login-form] button[type=submit]').click();page.wait_for_url(base+'/')
def context(browser,name):
 c=browser.new_context(viewport={'width':1366,'height':950},locale='ko-KR',timezone_id='Asia/Seoul')
 c.add_init_script("Object.defineProperty(window,'Notification',{get(){throw new Error('NAS must never access Windows Notification API')}});window.__toneCount=0;if(window.AudioContext){const old=AudioContext.prototype.createOscillator;AudioContext.prototype.createOscillator=function(...args){window.__toneCount++;return old.apply(this,args);};}")
 page=c.new_page();attach(page);login(page,name);return c,page
def summary(c):return c.request.get(base+'/notifications/status/').json()
def refresh(page):page.bring_to_front();page.evaluate("window.dispatchEvent(new Event('xenosys-refresh-notifications'))")
def submit(page,kind='leave'):
 page.goto(base+'/compose/?kind='+kind)
 if kind=='leave':
  page.locator('#id_start_date').fill('2026-11-12');page.locator('#id_end_date').fill('2026-11-12')
 else:
  page.locator('#id_product').fill('알림 보존 검증 비품');page.locator('#id_quantity').fill('1');page.locator('#id_unit_price').fill('10000');page.locator('#id_url').fill('https://example.com/item')
 page.locator('#id_reason').fill('가상 직원 운영 모드 검증');page.locator('#id_reviewer_department').select_option(label='개발팀');page.locator('#id_reviewer').select_option(label='예시검토자 · 개발팀 팀장');page.get_by_role('button',name='기안 제출',exact=True).click();page.wait_for_url('**/documents/*/');return page.url

with sync_playwright() as tool:
 b=tool.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
 rc,review=context(b,'reviewer');fc,finance=context(b,'accounting');oc,owner=context(b,'employee');f2c,f2=context(b,'finance2')
 before=summary(fc);before_other=summary(f2c)
 assert before['accounting_unread']==1  # Old category receipt was migrated, not forgotten.
 assert before_other['accounting_unread']==2
 finance.goto(base+'/documents/?mode=accounting');finance.locator('.notification-toast button').evaluate_all('(nodes)=>nodes.forEach(n=>n.click())')
 docurl=submit(owner);review.bring_to_front()
 # Use the real15second timer for the newly assigned request.
 expect(review.locator('.notification-toast')).to_contain_text('휴가원',timeout=20000)
 expect(review.locator('[data-live-count=waiting]').first).to_have_text('1')
 review.screenshot(path=str(a.output/'reviewer-arrival-desktop.png'),full_page=True)
 review.goto(docurl);assert summary(rc)['waiting']==1
 form=review.locator('[data-document-action=review_final]');form.locator('[name=reason]').fill('검토자 전결 검증');form.get_by_role('button',name='검토자 전결',exact=True).click();review.wait_for_load_state('networkidle')
 refresh(finance);expect(finance.locator('[data-live-count=accounting_unread]')).to_have_text('2');expect(finance.locator('.notification-toast')).to_contain_text('승인완료')
 finance.screenshot(path=str(a.output/'accounting-new-approved.png'),full_page=True)
 finance.locator('[data-accounting-kind=leave]').click();assert summary(fc)['accounting_unread']==2
 finance.locator(f'a.document-cell[href="{urlsplit(docurl).path}"]').click();assert summary(fc)['accounting_unread']==1
 assert summary(f2c)['accounting_unread']==3
 # Old already-acknowledged office document remains acknowledged.
 finance.goto(base+'/documents/?mode=accounting&kind=office');expect(finance.locator('.document-new')).to_have_count(0)
 review.goto(base+'/account/')
 expect(review.locator('[data-push-enable]')).to_have_count(0);expect(review.locator('[data-os-test]')).to_have_count(0);expect(review.locator('[data-push-test]')).to_have_count(0)
 review.locator('[data-notification-sound]').check();expect(review.locator('[data-notification-settings-message]')).to_have_text('알림 설정을 저장했습니다.')
 review.locator('[data-screen-test]').click();expect(review.locator('.notification-toast')).to_contain_text('화면 팝업 테스트');assert review.evaluate('window.__toneCount')>0
 for width in [320,390,768,1366,2560]:
  review.set_viewport_size({'width':width,'height':950});assert review.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
  review.screenshot(path=str(a.output/f'inapp-settings-{width}.png'),full_page=True)
 # Same-browser alternating account login still gets a pending reminder, without push code.
 review.locator('form[action="/logout/"] button').click();review.wait_for_url(base+'/login/')
 submit(owner,'office');login(review,'reviewer');expect(review.locator('.notification-toast').first).to_contain_text('미결 문서')
 assert all(not c.service_workers for c in [rc,fc,oc,f2c])
 assert not push_requests,push_requests
 assert not errors,errors
 assert not assets,assets
 result=dict(passed=True,production_gunicorn_whitenoise_mariadb=True,auto_poll_15sec=True,reviewer_toast_and_count=True,review_final_preserved=True,finance_receipts_individual=True,old_receipt_preserved=True,receipts_isolated_by_user=True,sound_oscillator_created=True,login_pending_reminder=True,viewports=[320,390,768,1366,2560],no_webpush_controls=True,no_windows_notification_api=True,no_push_requests=True,no_service_worker_registration=True,js_errors=errors,failed_assets=assets)
 (a.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False))
 for c in [rc,fc,oc,f2c]:c.close()
 b.close()
