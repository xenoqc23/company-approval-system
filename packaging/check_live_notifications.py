"""Local-only browser evidence. Provider delivery is deliberately simulated, never sent."""
import argparse,json,sys,re
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright,expect
p=argparse.ArgumentParser();p.add_argument('--base-url',default='http://127.0.0.1:18095');p.add_argument('--password-file',type=Path,required=True);p.add_argument('--output',type=Path,default=Path('test-results/live-notifications-browser'));a=p.parse_args()
base=a.base_url.rstrip('/');assert urlsplit(base).hostname in ['127.0.0.1','localhost']
pw=a.password_file.read_text();a.output.mkdir(parents=True,exist_ok=True);errors=[];assets=[]

def login(browser,name):
    context=browser.new_context(viewport={'width':1366,'height':950},locale='ko-KR',timezone_id='Asia/Seoul',permissions=['notifications'])
    page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)));page.on('response',lambda r:assets.append(r.url) if '/static/' in r.url and r.status>=400 else None)
    page.goto(base+'/login/');page.locator('[name=username]').fill(name);page.locator('[name=password]').fill(pw);page.locator('[data-login-form] button[type=submit]').click();page.wait_for_url(base+'/');return context,page

def summary(context):return context.request.get(base+'/notifications/status/').json()
def refresh(page):page.evaluate("window.dispatchEvent(new Event('xenosys-refresh-notifications'))")
with sync_playwright() as tool:
    browser=tool.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
    rc,review=login(browser,'reviewer');fc,finance=login(browser,'accounting');oc,owner=login(browser,'employee')
    reviewbase=summary(rc);financebase=summary(fc)
    finance.goto(base+'/documents/?mode=accounting')
    owner.goto(base+'/compose/?kind=office');owner.locator('#id_product').fill('로컬 알림 테스트 키보드');owner.locator('#id_quantity').fill('1');owner.locator('#id_unit_price').fill('50000');owner.locator('#id_url').fill('https://example.com/keyboard');owner.locator('#id_reason').fill('가상 직원 알림 동작 확인')
    owner.locator('#id_reviewer_department').select_option(label='개발팀');owner.locator('#id_reviewer').select_option(label='김민준 · 개발팀 팀장')
    owner.get_by_role('button',name='기안 제출',exact=True).click();owner.wait_for_url('**/documents/*/')
    docurl=owner.url
    refresh(review)
    expect(review.locator('[data-live-count=waiting]').first).to_have_text(str(reviewbase['waiting']+1))
    expect(review.locator('.notification-toast')).to_have_count(1);expect(review.locator('.notification-toast')).to_contain_text('구매요청서')
    review.screenshot(path=str(a.output/'reviewer-new-request.png'),full_page=True)
    # Reading the document clears unread notice, never the pending action count.
    review.goto(docurl);assert summary(rc)['waiting']==reviewbase['waiting']+1
    form=review.locator('[data-document-action=review_final]');form.locator('[name=reason]').fill('알림 테스트 전결');form.get_by_role('button',name='검토자 전결',exact=True).click();review.wait_for_load_state('networkidle')
    refresh(finance)
    expect(finance.locator('[data-live-count=accounting_unread]')).to_have_text(str(financebase['accounting_unread']+1))
    expect(finance.locator('.notification-toast')).to_contain_text('승인완료')
    expect(finance.locator('[data-accounting-kind=office]')).to_have_class(re.compile(r'\bhas-new\b'))
    finance.screenshot(path=str(a.output/'finance-final-approved.png'),full_page=True)
    finance.locator('[data-accounting-kind=office]').click();assert summary(fc)['accounting_unread']==financebase['accounting_unread']+1
    expect(finance.locator('.documents-table .document-new')).to_have_count(next(t['unread_count'] for t in financebase['tabs'] if t['key']=='office')+1)
    finance.locator(f'a.document-cell[href="{urlsplit(docurl).path}"]').click()
    assert summary(fc)['accounting_unread']==financebase['accounting_unread']
    finance.goto(base+'/account/')
    expect(finance.get_by_role('heading',name='알림 설정',exact=True)).to_be_visible()
    finance.locator('[data-notification-popup]').uncheck();expect(finance.locator('[data-notification-settings-message]')).to_have_text('알림 설정을 저장했습니다.')
    assert summary(fc)['preferences']['popup'] is False
    finance.locator('[data-notification-popup]').check();expect(finance.locator('[data-notification-settings-message]')).to_have_text('알림 설정을 저장했습니다.')
    for width in [320,390,768,1366]:
        finance.set_viewport_size({'width':width,'height':950});assert finance.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
        finance.screenshot(path=str(a.output/f'settings-{width}.png'),full_page=True)
    # Real Chromium service worker handles a CDP-injected push even with every page closed.
    # This validates worker lifecycle/rendering, not a Google/Mozilla/Apple delivery service.
    registration=finance.evaluate('''async()=>{await navigator.serviceWorker.ready;return (await navigator.serviceWorker.getRegistration('/')).active.scriptURL}''')
    assert registration.endswith('/notifications-sw.js')
    cdp=fc.new_cdp_session(finance);registrations=[]
    cdp.on('ServiceWorker.workerRegistrationUpdated',lambda event:registrations.extend(event['registrations']))
    cdp.send('ServiceWorker.enable');finance.wait_for_timeout(200)
    reg=next(r for r in registrations if r['scopeURL']==base+'/')
    keeper=fc.new_page();keeper.goto('about:blank');cdp2=fc.new_cdp_session(keeper);cdp2.send('ServiceWorker.enable')
    finance.close()
    cdp2.send('ServiceWorker.deliverPushMessage',dict(origin=base,registrationId=reg['registrationId'],data=json.dumps({'body':'웹 푸시 테스트 알림입니다.','tag':'local-worker-proof'})))
    check=fc.new_page();check.goto(base+'/account/')
    count=check.evaluate('''async()=>{const reg=await navigator.serviceWorker.ready;for(let i=0;i<30;i++){const rows=await reg.getNotifications({tag:'local-worker-proof'});if(rows.length){for(const n of rows)n.close();return rows.length;}await new Promise(r=>setTimeout(r,100));}return 0;}''')
    assert count==1,count
    # Exercise opt-in/test/opt-out/logout UI using a fake browser subscription only.
    # Keys are real P-256; no real endpoint is contacted by this test.
    import base64
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    point=ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)
    enc=lambda b:base64.urlsafe_b64encode(b).rstrip(b'=').decode()
    fake=dict(endpoint='https://fcm.googleapis.com/fcm/send/local-ui-fixture',keys=dict(p256dh=enc(point),auth=enc(b'0123456789abcdef')))
    pc=browser.new_context(viewport={'width':1366,'height':950},permissions=['notifications'])
    pc.add_init_script("""(()=>{let current=null;const data=FAKE;const sub=()=>({endpoint:data.endpoint,toJSON:()=>data,unsubscribe:async()=>{current=null;return true;}});PushManager.prototype.getSubscription=async()=>current;PushManager.prototype.subscribe=async()=>{current=sub();return current;};})();""".replace('FAKE',json.dumps(fake)))
    pp=pc.new_page();pp.goto(base+'/login/');pp.locator('[name=username]').fill('reviewer');pp.locator('[name=password]').fill(pw);pp.locator('[data-login-form] button[type=submit]').click();pp.wait_for_url(base+'/');pp.goto(base+'/account/')
    expect(pp.locator('[data-push-state]')).to_contain_text('꺼져')
    pp.locator('[data-push-enable]').click();expect(pp.locator('[data-push-state]')).to_contain_text('켜져')
    pp.locator('[data-push-test]').click();expect(pp.locator('[data-push-state]')).to_contain_text('10초 후 발송')
    pp.locator('[data-push-disable]').click();expect(pp.locator('[data-push-state]')).to_contain_text('껐습니다')
    pp.locator('[data-push-enable]').click();expect(pp.locator('[data-push-state]')).to_contain_text('켜져')
    pp.locator('form[action="/logout/"] button').click();pp.wait_for_url(base+'/login/');pc.close()
    result=dict(passed=True,push_optin_test_optout_logout_ui_simulated_subscription=True,real_ui_request_and_final=True,live_badges_and_popups=True,per_document_receipts=True,read_keeps_pending=True,settings_saved=True,viewports=[320,390,768,1366],service_worker_injected_push_after_app_page_closed=True,external_provider_delivery_tested=False,js_errors=errors,failed_assets=assets)
    (a.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    for context in [rc,fc,oc]:context.close()
    browser.close()
assert not errors,errors
assert not assets,assets
print(json.dumps(result,ensure_ascii=False))
