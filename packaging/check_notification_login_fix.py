"""Reproduce account-alternating test, explicit test-button feedback and session mismatch."""
import argparse,json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright,expect
p=argparse.ArgumentParser();p.add_argument('--base-url',default='http://127.0.0.1:18095');p.add_argument('--password-file',type=Path,required=True);p.add_argument('--output',type=Path,default=Path('test-results/notification-login-fix'));a=p.parse_args()
base=a.base_url.rstrip('/');assert urlsplit(base).hostname in ['127.0.0.1','localhost'];pw=a.password_file.read_text();a.output.mkdir(parents=True,exist_ok=True);errors=[]
def login(page,name):
 page.goto(base+'/login/');page.locator('[name=username]').fill(name);page.locator('[name=password]').fill(pw);page.locator('[data-login-form] button[type=submit]').click();page.wait_for_url(base+'/')
def logout(page):page.locator('form[action="/logout/"] button').click();page.wait_for_url(base+'/login/')
def submit(page):
 page.goto(base+'/compose/?kind=office');page.locator('#id_product').fill('계정 교대 알림 재현');page.locator('#id_quantity').fill('1');page.locator('#id_unit_price').fill('10000');page.locator('#id_url').fill('https://example.com/item');page.locator('#id_reason').fill('가상 직원 테스트');page.locator('#id_reviewer_department').select_option(label='개발팀');page.locator('#id_reviewer').select_option(label='김민준 · 개발팀 팀장');page.get_by_role('button',name='기안 제출',exact=True).click();page.wait_for_url('**/documents/*/')
with sync_playwright() as tool:
 b=tool.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
 c=b.new_context(viewport={'width':2560,'height':1000},permissions=['notifications'],locale='ko-KR');page=c.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
 login(page,'employee');submit(page);logout(page);login(page,'reviewer')
 expect(page.locator('.notification-toast').first).to_contain_text('미결 문서')
 page.screenshot(path=str(a.output/'maximized-login-pending.png'))
 page.set_viewport_size({'width':1024,'height':1000});expect(page.locator('.notification-toast').first).to_be_visible()
 page.set_viewport_size({'width':2560,'height':1000})
 page.goto(base+'/account/')
 page.locator('.notification-toast button').evaluate_all('(nodes)=>nodes.forEach(n=>n.click())')
 # The test button gives guidance immediately; it no longer silently ignores the click.
 page.locator('[data-push-test]').click();expect(page.locator('[data-push-state]')).to_contain_text('먼저 웹 푸시를 켜')
 expect(page.locator('[data-push-test]')).to_be_enabled()
 page.locator('[data-screen-test]').click();expect(page.locator('.notification-toast')).to_contain_text('화면 팝업 테스트')
 page.locator('[data-push-diagnostics]').click();expect(page.locator('[data-push-diagnostic-result]')).to_contain_text('브라우저 알림: 허용')
 expect(page.locator('[data-push-diagnostic-result]')).to_contain_text('웹 푸시: 꺼짐')
 expect(page.locator('[data-push-state]')).to_contain_text('먼저 웹 푸시를 켜')
 page.locator('[data-os-test]').click();expect(page.locator('[data-push-state]')).to_contain_text('Windows에 표시를 요청했습니다')
 count=page.evaluate('''async()=>{const reg=await navigator.serviceWorker.ready;const rows=await reg.getNotifications({tag:'xenosys-local-display-test'});for(const n of rows)n.close();return rows.length}''');assert count==1
 page.screenshot(path=str(a.output/'test-feedback-desktop.png'),full_page=True)
 # A visible but unfocused tab must not consume another window's popup.
 page.locator('.notification-toast button').evaluate_all('(nodes)=>nodes.forEach(n=>n.click())')
 quiet=c.new_page();quiet.goto(base+'/');quiet.locator('.notification-toast button').evaluate_all('(nodes)=>nodes.forEach(n=>n.click())')
 quiet.evaluate("Object.defineProperty(document,'hasFocus',{configurable:true,value:()=>false})")
 owner_context=b.new_context(viewport={'width':1366,'height':950});owner=owner_context.new_page();login(owner,'employee');submit(owner)
 with quiet.expect_response(lambda r:'/notifications/status/' in r.url):
  quiet.evaluate("window.dispatchEvent(new Event('xenosys-refresh-notifications'))")
 quiet.wait_for_timeout(100);expect(quiet.locator('.notification-toast')).to_have_count(0)
 page.bring_to_front()
 page.evaluate("window.dispatchEvent(new Event('xenosys-refresh-notifications'))")
 expect(page.locator('.notification-toast')).to_contain_text('구매요청서')
 owner_context.close();quiet.close()
 # Another tab changes the shared cookie. The old tab must explain why its polling stops.
 other=c.new_page();other.goto(base+'/');logout(other);login(other,'employee')
 page.bring_to_front();page.evaluate("window.dispatchEvent(new Event('xenosys-refresh-notifications'))")
 expect(page.locator('#notification-connection')).to_be_visible();expect(page.locator('#notification-connection')).to_contain_text('다른 계정')
 page.screenshot(path=str(a.output/'account-change-warning.png'))
 result=dict(passed=True,alternating_account_login_reminder=True,desktop2560_and_narrow1024=True,test_before_optin_gives_feedback=True,local_screen_test=True,real_service_worker_display_request=True,diagnostics_device_scope=True,shared_account_change_explained=True,unfocused_window_does_not_consume_popup=True,external_provider_delivery_tested=False,js_errors=errors)
 assert not errors,errors
 (a.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False));b.close()
