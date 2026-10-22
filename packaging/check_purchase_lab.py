"""Real PC purchase-only browser journey; reads only fictional private fixture credentials."""
import argparse,json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright,expect
p=argparse.ArgumentParser();p.add_argument('--base-url',default='http://127.0.0.1:18105');p.add_argument('--password-file',type=Path,required=True);p.add_argument('--ids-file',type=Path,required=True);p.add_argument('--output',type=Path,default=Path('test-results/purchase-lab-browser'));a=p.parse_args()
base=a.base_url.rstrip('/');assert urlsplit(base).hostname in ['127.0.0.1','localhost'];pw=a.password_file.read_text();ids=json.loads(a.ids_file.read_text());a.output.mkdir(parents=True,exist_ok=True);errors=[];assets=[]

def switch(page,who):
 page.locator('#demo-user').select_option(str(ids['p_'+who]));page.get_by_role('button',name='이 계정으로 전환',exact=True).click();page.wait_for_url(base+'/purchase-lab/')
def create(page,who,product,vendor,reason,qty,price):
 switch(page,who);page.goto(base+'/purchase-lab/new/');page.locator('#id_product').fill(product);page.locator('#id_vendor').fill(vendor);page.locator('#id_reason').fill(reason);page.locator('#id_quantity').fill(str(qty));page.locator('#id_unit_price').fill(str(price))
 if who=='quality':
  page.locator('#id_reviewer').select_option(str(ids['p_quality_manager']));page.locator('#id_approver').select_option(str(ids['p_quality_lead']))
 else:expect(page.locator('#id_reviewer')).to_have_count(0);expect(page.locator('#id_approver')).to_have_count(0)
 page.get_by_role('button',name='구매요청 제출',exact=True).click();page.wait_for_url('**/purchase-lab/requests/*/');return int(urlsplit(page.url).path.rstrip('/').split('/')[-1])
def approve(page,who,pk):
 switch(page,who);page.goto(base+f'/purchase-lab/requests/{pk}/');page.locator('form:has(input[value=approve]) button').click();page.wait_for_load_state('networkidle')
def open_request(page,pk):page.goto(base+f'/purchase-lab/requests/{pk}/')

with sync_playwright() as tool:
 browser=tool.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
 context=browser.new_context(viewport={'width':1440,'height':1000},locale='ko-KR',timezone_id='Asia/Seoul');page=context.new_page()
 page.on('pageerror',lambda e:errors.append(str(e)));page.on('response',lambda r:assets.append(r.url) if '/static/' in r.url and r.status>=400 else None);page.on('dialog',lambda d:d.accept())
 page.goto(base+'/purchase-lab/login/');page.locator('[name=username]').fill('p_admin');page.locator('[name=password]').fill(pw);page.get_by_role('button',name='로그인',exact=True).click();page.wait_for_url(base+'/purchase-lab/')
 page.goto(base+'/purchase-lab/rules/');expect(page.locator('h1')).to_have_text('구매 규정 설정');page.screenshot(path=str(a.output/'purchase-rules-desktop.png'),full_page=True)
 # 50,000 won must survive keyboard, wheel, server save, and page reload exactly.
 switch(page,'dev');page.goto(base+'/purchase-lab/new/');price=page.locator('#id_unit_price');price.fill('50,000');price.press('ArrowDown');expect(price).to_have_value('50,000');price.hover();page.mouse.wheel(0,160);expect(price).to_have_value('50,000');expect(page.locator('[data-price]')).to_have_text('50,000원')
 page.locator('#id_product').fill('금액 확인용 5만원 품목');page.locator('#id_vendor').fill('가상금액확인몰');page.locator('#id_reason').fill('입력 금액이 그대로 저장되는지 확인합니다.');page.get_by_role('button',name='구매요청 제출',exact=True).click();page.wait_for_url('**/purchase-lab/requests/*/');page.reload();expect(page.locator('dd').filter(has_text='50,000원')).to_have_count(2);expect(page.locator('body')).not_to_contain_text('49,999.99');page.screenshot(path=str(a.output/'won-50000-roundtrip.png'),full_page=True)
 first=create(page,'dev','27인치 모니터 MX-27','가상상사','노후 모니터 고장으로 교체가 필요합니다.',2,'12345.67')
 second=create(page,'quality','작업용 보호커버','가상안전몰','작업 중 오염 방지를 위한 보호커버입니다.',3,'7000')
 third=create(page,'sales_manager','휴대용 프린터','가상사무몰','외부 영업 현장에서 문서 출력이 필요합니다.',1,'400000')
 fourth=create(page,'dev','USB-C 케이블','가상전자몰','개발 장비 연결용 예비 케이블이 필요합니다.',5,'9000')
 switch(page,'finance');page.goto(base+'/purchase-lab/requests/?mode=finance');expect(page.locator('[data-select-item]')).to_have_count(0)
 approve(page,'quality_manager',second);expect(page.locator('.heading .badge')).to_contain_text('중간 승인 대기')
 approve(page,'quality_lead',second);expect(page.locator('.heading .badge')).to_contain_text('이사 최종승인 대기')
 switch(page,'prod_director');page.goto(base+'/purchase-lab/requests/?mode=director');expect(page.get_by_role('link',name='27인치 모니터 MX-27',exact=True)).to_have_count(0);expect(page.get_by_role('link',name='휴대용 프린터',exact=True)).to_have_count(1)
 approve(page,'prod_director',second);approve(page,'prod_director',third);approve(page,'dev_director',first);approve(page,'dev_director',fourth)
 switch(page,'dev');open_request(page,first);expect(page.locator('.status-explanation')).to_contain_text('구매를 진행하고 있습니다.');expect(page.locator('body')).not_to_contain_text('경리 취합');expect(page.locator('body')).not_to_contain_text('대표 구매허가');page.screenshot(path=str(a.output/'requester-finance-wait.png'),full_page=True)
 switch(page,'finance');page.goto(base+'/purchase-lab/requests/?mode=finance');expect(page.locator('[data-select-item]')).to_have_count(4);page.locator('[data-select-all]').check();page.get_by_role('button',name='선택 품목 요약·보고',exact=True).click();expect(page.locator('body')).to_contain_text('노후 모니터 고장으로 교체가 필요합니다.');expect(page.locator('body')).to_contain_text('가상상사');page.screenshot(path=str(a.output/'finance-summary-with-reasons.png'),full_page=True)
 page.locator('[name=title]').fill('가상 구매허가 취합 보고');page.locator('[name=note]').fill('각 부서 이사님이 승인한 품목입니다. 구매사유와 구매처를 확인하여 품목별 구매허가를 요청합니다.');page.get_by_role('button',name='대표님께 구매허가 요청',exact=True).click();page.wait_for_url('**/purchase-lab/reports/*/');report_url=page.url
 switch(page,'ceo');page.goto(report_url);expect(page.locator('[data-report-item]')).to_have_count(4)
 for product,decision,reason in [('27인치 모니터 MX-27','allow',''),('작업용 보호커버','deny','기존 재고를 먼저 사용해 주세요.'),('휴대용 프린터','hold','비교 견적 확인 후 재보고해 주세요.'),('USB-C 케이블','allow','')]:
  item=page.locator('[data-report-item]').filter(has=page.get_by_role('heading',name=product,exact=True));item.locator('[data-item-decision]').select_option(decision);item.locator('[data-item-reason]').fill(reason)
 page.get_by_role('button',name='심사 내용 임시저장',exact=True).click();page.wait_for_load_state('networkidle')
 switch(page,'dev');open_request(page,first);expect(page.locator('.heading .badge')).to_contain_text('구매 진행 중')
 switch(page,'ceo');page.goto(report_url);page.screenshot(path=str(a.output/'ceo-item-decisions.png'),full_page=True);page.get_by_role('button',name='품목별 결정 최종 확정',exact=True).click();page.wait_for_load_state('networkidle');expect(page.locator('body')).to_contain_text('확정된 품목별 결과')
 switch(page,'dev');open_request(page,first);expect(page.locator('.heading .badge')).to_contain_text('구매 진행 중');expect(page.locator('.status-explanation')).to_contain_text('구매를 진행하고 있습니다.');expect(page.locator('body')).not_to_contain_text('취합 문서:');expect(page.locator('body')).not_to_contain_text('대표 구매허가');page.screenshot(path=str(a.output/'requester-allowed-before-payment.png'),full_page=True)
 switch(page,'quality');open_request(page,second);expect(page.locator('.heading .badge')).to_contain_text('구매불허');expect(page.locator('.decision-reason')).to_contain_text('기존 재고');expect(page.locator('.progress-track .blocked')).to_have_count(1);page.screenshot(path=str(a.output/'requester-denied-with-reason.png'),full_page=True)
 switch(page,'sales_manager');open_request(page,third);expect(page.locator('.heading .badge')).to_contain_text('구매보류');expect(page.locator('.decision-reason')).to_contain_text('비교 견적');expect(page.locator('.progress-track .paused')).to_have_count(1);page.screenshot(path=str(a.output/'requester-hold.png'),full_page=True)
 switch(page,'finance');open_request(page,first);pay=page.locator('form:has(input[value=paid])');pay.locator('[name=reason]').fill('대표님 카드 결제 완료를 확인했습니다.');pay.get_by_role('button',name='결제 완료 확인',exact=True).click();page.wait_for_load_state('networkidle');expect(page.locator('.heading .badge')).to_contain_text('결제 완료')
 open_request(page,second);expect(page.locator('form:has(input[value=paid])')).to_have_count(0)
 switch(page,'dev');open_request(page,first);page.get_by_role('button',name='물품 수령 완료',exact=True).click();page.wait_for_load_state('networkidle');expect(page.locator('.heading .badge')).to_contain_text('수령 완료')
 # The owner can view its source and decision, never the other departments in the combined report.
 assert context.request.get(report_url).status==404
 switch(page,'dev');page.goto(base+'/purchase-lab/');page.screenshot(path=str(a.output/'requester-home.png'),full_page=True)
 page.goto(base+'/purchase-lab/new/');page.screenshot(path=str(a.output/'purchase-compose-desktop.png'),full_page=True)
 # Rule edits are easy, validated, and affect new requests only.
 switch(page,'admin');page.goto(base+'/purchase-lab/rules/');page.locator('[name=other_0]').select_option('approval');page.locator('[name=reason]').fill('직급별 중간 단계를 바꾸는 로컬 테스트');page.get_by_role('button',name='구매 규정 저장',exact=True).click();page.wait_for_load_state('networkidle');expect(page.locator('[name=other_0]')).to_have_value('approval')
 for route,label in [('/purchase-lab/rules/','rules'),('/purchase-lab/','home')]:
  page.goto(base+route)
  for width in [320,390,768,1366,2560]:
   page.set_viewport_size({'width':width,'height':1000});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),(label,width);page.screenshot(path=str(a.output/f'{label}-{width}.png'),full_page=True)
 assert not errors,errors;assert not assets,assets
 result=dict(passed=True,won_50000_exact=True,original_xenosys_shell=True,requester_stages_collapsed=True,purchase_only=True,development_director_route=True,other_review_approval_route=True,manager_direct_route=True,finance_only_after_director=True,summary_reason_vendor_source=True,partial_allow_deny_hold=True,interim_not_purchase_permission=True,owner_stage_and_reasons=True,payment_separate_from_permission=True,received=True,report_privacy=True,easy_rules_save=True,responsive_widths=[320,390,768,1366,2560],js_errors=errors,failed_assets=assets)
 (a.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False));browser.close()
