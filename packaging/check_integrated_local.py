"""Browser acceptance test against a fictional, loopback-only integrated instance."""
import argparse,json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright,expect
p=argparse.ArgumentParser();p.add_argument('--base-url',default='http://127.0.0.1:18117');p.add_argument('--password-file',type=Path,required=True);p.add_argument('--ids-file',type=Path,required=True);p.add_argument('--output',type=Path,default=Path('test-results/integrated'));a=p.parse_args();base=a.base_url.rstrip('/');assert urlsplit(base).hostname in ['localhost','127.0.0.1'];ids=json.loads(a.ids_file.read_text());a.output.mkdir(parents=True,exist_ok=True)
def switch(page,role):
 page.locator('#integrated-role').select_option(str(ids['p_'+role]));page.locator('.integrated-test-tools button').click();page.wait_for_url(base+'/')
def doc(page,pk):page.goto(base+f'/purchases/requests/{pk}/')
def shot(page,name):page.screenshot(path=str(a.output/name),full_page=True)
def login(page,who):
 page.goto(base+'/login/');page.locator('[name=username]').fill('p_'+who);page.locator('[name=password]').fill(a.password_file.read_text().strip());page.get_by_role('button',name='로그인',exact=True).click();page.wait_for_url(base+'/')
def create(page,role,name,method='direct',quote=False):
 switch(page,role);page.goto(base+'/purchases/new/')
 if method=='direct':page.locator('[name=request_method][value=direct]').check()
 page.locator('#id_product').fill(name);page.locator('#id_vendor').fill('가상구매처');page.locator('#id_quantity').fill('10');page.locator('#id_unit_price').fill('50,000');page.locator('#id_reason').fill('기존 사내결재 화면에서 통합 경로를 확인하는 가상 요청입니다.');page.locator('#id_needed_by').fill('2026-11-04')
 expect(page.locator('[data-price]')).to_have_text('500,000원')
 if quote:page.locator('#id_files').set_input_files({'name':'가상견적서.pdf','mimeType':'application/pdf','buffer':b'%PDF fictional quote'})
 page.get_by_role('button',name='구매담당자에게 요청' if method=='direct' else '검토 요청',exact=True).click();page.wait_for_url('**/requests/*/');return int(urlsplit(page.url).path.rstrip('/').split('/')[-1])
def approve(page,role,pk,label):
 switch(page,role);page.goto(base+'/documents/?mode=pending');expect(page.locator('tbody')).to_contain_text('통합시험');doc(page,pk);page.get_by_role('button',name=label,exact=True).click();page.wait_for_load_state('networkidle')
with sync_playwright() as tool:
 browser=tool.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox']);context=browser.new_context(viewport={'width':1440,'height':1000},locale='ko-KR',timezone_id='Asia/Seoul');page=context.new_page();errors=[];assets=[];page.on('pageerror',lambda e:errors.append(str(e)));page.on('response',lambda r:assets.append(r.url) if '/static/' in r.url and r.status>=400 else None);page.on('dialog',lambda d:d.accept());login(page,'admin')
 expect(page.locator('#integrated-role option')).to_have_count(10);expect(page.locator('body')).to_contain_text('나의 연차 현황');shot(page,'01-original-home.png')
 page.goto(base+'/regulations/');expect(page.get_by_text('휴가원 결재 규정 →',exact=True)).to_be_visible();expect(page.get_by_text('구매요청 규정 →',exact=True)).to_be_visible();shot(page,'02-rules-separated.png')
 page.goto(base+'/purchases/rules/');expect(page.locator('#id_dev_director')).to_have_count(0);expect(page.locator('[data-route-preview]')).to_contain_text('가상생산이사');page.locator('[data-preview-department]').select_option('dev');expect(page.locator('[data-route-preview]')).to_contain_text('가상개발이사');shot(page,'03-purchase-rules.png')
 page.goto(base+'/staff/');page.get_by_text('담당자·권한 설정 열기',exact=True).click();expect(page.locator('#id_dev_director')).to_have_value(str(ids['p_dev_director']));shot(page,'04-shared-permissions.png')
 # An independently logged-in reviewer must get the existing on-screen popup.
 watcher=browser.new_context(viewport={'width':1440,'height':1000},locale='ko-KR');w=watcher.new_page();login(w,'quality_manager');w.goto(base+'/documents/?mode=pending')
 normal=create(page,'quality','통합시험 현장용 모니터','review',quote=True)
 w.bring_to_front();w.evaluate("window.dispatchEvent(new Event('xenosys-refresh-notifications'))");expect(w.locator('#notification-toasts')).to_contain_text('통합시험 현장용 모니터',timeout=20000);shot(w,'05-shared-arrival-popup.png');watcher.close();page.bring_to_front()
 approve(page,'quality_manager',normal,'검토 완료 · 승인자에게 전달');approve(page,'quality_lead',normal,'내부 승인 완료')
 switch(page,'finance');assert context.request.get(base+f'/purchases/requests/{normal}/').status==404
 switch(page,'prod_director');doc(page,normal);page.get_by_role('button',name='구매 내용 확인',exact=True).click();page.wait_for_load_state('networkidle')
 dev=create(page,'dev_manager','통합시험 개발용 키보드');switch(page,'prod_director');assert context.request.get(base+f'/purchases/requests/{dev}/').status==404
 switch(page,'dev_director');doc(page,dev);page.get_by_role('button',name='구매 내용 확인',exact=True).click();page.wait_for_load_state('networkidle')
 other=create(page,'quality_manager','통합시험 추가 장치');switch(page,'prod_director');doc(page,other);page.get_by_role('button',name='구매 내용 확인',exact=True).click();page.wait_for_load_state('networkidle')
 combined=create(page,'dev_manager','통합시험 호환 연결장치','review');approve(page,'dev_lead',combined,'검토 완료 · 승인자에게 전달');switch(page,'dev_director');doc(page,combined);page.get_by_role('button',name='승인하고 구매담당자에게 전달',exact=True).click();page.wait_for_load_state('networkidle');expect(page.locator('[data-purchase-progress]')).to_contain_text('승인 시 함께 확인')
 own_dev=create(page,'dev_director','통합시험 개발 이사 요청');own_prod=create(page,'prod_director','통합시험 생산 이사 요청')
 switch(page,'finance');page.goto(base+'/purchases/reports/');expect(page.locator('[data-select-item]')).to_have_count(6);expect(page.locator('#workspace-navigation')).not_to_contain_text('구매 모아보기');expect(page.locator('#workspace-navigation')).not_to_contain_text('구매보류함');expect(page.locator('.queue-cards')).to_have_count(0);shot(page,'06-single-purchase-inbox.png')
 doc(page,normal);page.get_by_text('자료 추가',exact=True).click();upload=page.locator('form:has(button:text-is("첨부파일 등록"))');upload.locator('input[type=file]').set_input_files({'name':'가상구매증빙.pdf','mimeType':'application/pdf','buffer':b'%PDF private evidence'});upload.get_by_role('button',name='첨부파일 등록',exact=True).click();page.wait_for_load_state('networkidle');evidence=page.get_by_role('link',name='가상구매증빙.pdf').get_attribute('href')
 page.goto(base+'/purchases/reports/');page.locator('[data-select-all]').check();page.get_by_role('button',name='선택 품목으로 구매요청',exact=True).click();page.locator('[name=note]').fill('여섯 품목의 부서별 구매 필요성을 확인했습니다.');page.get_by_role('button',name='대표님께 구매요청',exact=True).click();page.wait_for_url('**/reports/*/');report=page.url
 switch(page,'quality');doc(page,normal);expect(page.locator('[data-purchase-progress]')).to_have_count(0);assert context.request.get(base+evidence).status==404;assert context.request.get(report).status==404
 switch(page,'ceo');page.goto(report);page.get_by_role('button',name='전체 품목 승인으로 선택',exact=True).click()
 for name,choice,reason in [('통합시험 추가 장치','deny','보유 물품을 먼저 사용합니다.'),('통합시험 호환 연결장치','hold','호환 여부를 확인합니다.')]:
  item=page.locator('[data-report-item]').filter(has=page.get_by_role('heading',name=name,exact=True));item.locator('[data-item-decision]').select_option(choice);item.locator('[data-item-reason]').fill(reason)
 page.get_by_role('button',name='선택한 결과 확정',exact=True).click();page.wait_for_load_state('networkidle');expect(page.locator('[data-report-fulfillment]')).to_contain_text('승인 4건 · 반려 1건 · 보류 1건');shot(page,'07-item-decisions.png')
 switch(page,'quality');expect(page.locator('[data-live-count=completed_unread]').first).to_contain_text('1');page.goto(base+'/documents/?mode=completed&unread=1');expect(page.locator('tbody')).to_contain_text('통합시험 현장용 모니터');doc(page,normal);expect(page.locator('.heading .badge.large')).to_have_text('구매 승인완료');expect(page.locator('[data-purchase-progress]')).to_have_count(0);page.locator('[data-receipt-form] [name=quantity]').fill('6');page.get_by_role('button',name='받은 수량 등록',exact=True).click();page.wait_for_load_state('networkidle');shot(page,'08-requester-partial-receipt.png')
 switch(page,'finance');page.goto(base+'/purchases/reports/?tab=sent');row=page.locator('tbody tr').filter(has_text=urlsplit(report).path.split('/')[-2]) if False else page.locator('tbody tr').first;expect(row).to_contain_text('일부 수령 1개');shot(page,'09-finance-partial-receipt.png');page.goto(report);expect(page.locator('[data-report-fulfillment]')).to_contain_text('일부 수령 1개 품목')
 switch(page,'quality');doc(page,normal);page.locator('[data-receipt-form] [name=quantity]').fill('4');page.get_by_role('button',name='받은 수량 등록',exact=True).click();page.wait_for_load_state('networkidle')
 switch(page,'dev_manager');doc(page,dev);page.locator('[data-receipt-form] [name=quantity]').fill('10');page.get_by_role('button',name='받은 수량 등록',exact=True).click();page.wait_for_load_state('networkidle')
 switch(page,'finance');page.goto(report);expect(page.locator('[data-report-fulfillment]')).to_contain_text('승인된 4개 품목 중 2개 수령 완료');shot(page,'10-finance-receipt-complete.png')
 with page.expect_download() as download:page.get_by_role('button',name='엑셀 다운로드',exact=True).click()
 assert download.value.suggested_filename.endswith('.xlsx')
 page.goto(base+'/purchases/reports/');expect(page.locator('[data-select-item]')).to_have_count(0);page.get_by_role('link',name='보류 1',exact=True).click();expect(page.locator('tbody')).to_contain_text('호환 여부');shot(page,'11-hold-in-same-inbox.png')
 # Saved rule changes affect the form and server, without changing the leave rule.
 switch(page,'admin');page.goto(base+'/purchases/rules/');page.locator('[name=direct_ranks][value="과장"]').uncheck();page.locator('[name=reason]').fill('통합 규정 경계 테스트');page.get_by_role('button',name='구매 규정 저장',exact=True).click();page.wait_for_load_state('networkidle');switch(page,'dev_manager');page.goto(base+'/purchases/new/');expect(page.locator('[name=request_method][value=direct]')).to_have_count(0)
 switch(page,'admin');page.goto(base+'/purchases/rules/');page.locator('[name=direct_ranks][value="과장"]').check();page.locator('[name=reason]').fill('기본 테스트 규정으로 복원');page.get_by_role('button',name='구매 규정 저장',exact=True).click();page.wait_for_load_state('networkidle')
 for role,routes in [('admin',['/','/regulations/','/regulations/?tab=leave','/staff/','/purchases/rules/']),('finance',['/purchases/reports/','/purchases/reports/?tab=sent',urlsplit(report).path]),('quality',['/compose/?kind=leave','/compose/?kind=stock',f'/purchases/requests/{normal}/']),('dev_manager',['/purchases/new/'])]:
  switch(page,role)
  for route in routes:
   page.goto(base+route)
   for width in [320,390,768,1366,2560]:
    page.set_viewport_size({'width':width,'height':1000});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),(role,route,width)
   page.set_viewport_size({'width':1440,'height':1000})
 assert not errors,errors;assert not assets,assets
 result=dict(passed=True,shared_shell=True,shared_inbox=True,arrival_popup=True,department_routing=True,combined_approval=True,director_self_request=True,unified_finance_menu=True,per_item_approval=True,completion_unread=True,partial_receipts=True,finance_receipt_summary=True,private_purchase_details=True,private_files=True,excel_download=True,separated_rule_ui=True,shared_permission_ui=True,responsive=True,js_errors=errors,failed_assets=assets)
 (a.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False));browser.close()
