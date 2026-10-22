"""Local browser journey: supplement, bulk exceptions, held items and amount reapproval."""
import argparse,json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright,expect
parser=argparse.ArgumentParser();parser.add_argument('--base-url',default='http://127.0.0.1:18111');parser.add_argument('--password-file',type=Path,required=True);parser.add_argument('--ids-file',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
base=args.base_url.rstrip('/');assert urlsplit(base).hostname in ['localhost','127.0.0.1'];ids=json.loads(args.ids_file.read_text());args.output.mkdir(parents=True,exist_ok=True)
def switch(page,role):
 page.locator('#demo-user').select_option(str(ids['p_'+role]));page.get_by_role('button',name='이 계정으로 전환',exact=True).click();page.wait_for_url(base+'/purchase-lab/')
def doc(page,pk):page.goto(base+f'/purchase-lab/requests/{pk}/')
def batch(page,pks):
 page.goto(base+'/purchase-lab/requests/?mode=finance')
 for pk in pks:page.locator(f'input[data-select-item][value="{pk}"]').check()
 page.get_by_role('button',name='선택 품목 요약·보고',exact=True).click();page.locator('[name=note]').fill('보완 내용을 확인한 가상 구매요청입니다.');page.get_by_role('button',name='대표님께 구매요청',exact=True).click();page.wait_for_url('**/reports/*/');return page.url
with sync_playwright() as tool:
 browser=tool.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox']);context=browser.new_context(viewport={'width':1440,'height':1000},locale='ko-KR');page=context.new_page();errors=[];dialogs=[];page.on('pageerror',lambda e:errors.append(str(e)))
 def accept(dialog):dialogs.append(dialog.message);dialog.accept()
 page.on('dialog',accept);page.goto(base+'/purchase-lab/login/');page.locator('[name=username]').fill('p_admin');page.locator('[name=password]').fill(args.password_file.read_text());page.get_by_role('button',name='로그인',exact=True).click();page.wait_for_url(base+'/purchase-lab/')
 docs=[]
 for product in ['보완 시험 측정장치','보류 시험 소모품']:
  switch(page,'quality');page.goto(base+'/purchase-lab/new/');page.locator('#id_product').fill(product);page.locator('#id_vendor').fill('가상구매상사');page.locator('#id_quantity').fill('2');page.locator('#id_unit_price').fill('50000');page.locator('#id_reason').fill('장비 교체용 가상 요청');page.get_by_role('button',name='구매요청 제출',exact=True).click();page.wait_for_url('**/requests/*/');pk=int(urlsplit(page.url).path.rstrip('/').split('/')[-1]);docs.append(pk)
  for role in ['quality_manager','quality_lead']:
   switch(page,role);doc(page,pk);page.locator('form:has(input[value=approve]) button').click();page.wait_for_load_state('networkidle')
 switch(page,'prod_director');doc(page,docs[0]);page.get_by_text('자료 보완 요청',exact=True).click();form=page.locator('form:has(input[value=request_supplement])');form.locator('[name=reason]').fill('보증기간 확인 자료를 추가해 주세요.');form.get_by_role('button',name='기안자에게 보완 요청',exact=True).click();page.wait_for_load_state('networkidle')
 switch(page,'quality');doc(page,docs[0]);page.get_by_role('link',name='보완 내용 작성',exact=True).click();page.locator('[name=reason]').fill('교체 장비는 보증기간 2년이 필요합니다.');page.locator('[name=response]').fill('보증기간과 구매 링크를 보완했습니다.');page.locator('[name=url]').fill('https://example.com/warranty');page.locator('[name=files]').set_input_files({'name':'가상보완자료.pdf','mimeType':'application/pdf','buffer':b'%PDF supplemental fictional document'});page.get_by_role('button',name='보완 내용 제출',exact=True).click();page.wait_for_load_state('networkidle');expect(page.locator('.approval-card.done')).to_have_count(3);expect(page.locator('body')).to_contain_text('보완 완료');page.screenshot(path=str(args.output/'16-supplement-completed.png'),full_page=True)
 switch(page,'prod_director')
 for pk in docs:doc(page,pk);page.get_by_role('button',name='구매 품목 확인',exact=True).click();page.wait_for_load_state('networkidle')
 page.goto(base+'/purchase-lab/requests/?mode=completed');expect(page.locator('.badge.allowed').filter(has_text='확인완료').first).to_be_visible();page.screenshot(path=str(args.output/'17-confirmed-badges.png'),full_page=True)
 switch(page,'finance');original=batch(page,docs)
 switch(page,'ceo');page.goto(original);page.get_by_role('button',name='전체 품목 승인으로 선택',exact=True).click();expect(page.locator('[data-item-decision]').first).to_have_value('allow');expect(page.locator('[data-item-decision]').last).to_have_value('allow');page.locator('[data-item-decision]').last.select_option('hold');page.locator('[data-item-reason]').last.fill('품번을 확인해 주세요.');expect(page.locator('[data-decision-summary]')).to_contain_text('승인 1건');expect(page.locator('[data-decision-summary]')).to_contain_text('보류 1건');page.screenshot(path=str(args.output/'18-bulk-approval-exception.png'),full_page=True);page.get_by_role('button',name='구매 검토 결과 확정',exact=True).click();page.wait_for_load_state('networkidle');assert any('승인 1건' in message and '보류 1건' in message for message in dialogs)
 switch(page,'quality');expect(page.locator('[data-live=own_completed]')).to_have_text('1');page.goto(base+'/purchase-lab/requests/?mode=mine&unread=1');expect(page.locator('tbody')).to_contain_text('보완 시험 측정장치');doc(page,docs[0]);expect(page.get_by_role('button',name='수령 확인',exact=True)).to_be_visible();assert context.request.get(base+'/purchase-lab/status/').json()['counts']['own_completed']==0;page.screenshot(path=str(args.output/'19-owner-approved-receipt-ready.png'),full_page=True)
 # Decreasing the approved amount keeps its decision and records the previous values.
 switch(page,'finance');doc(page,docs[0]);page.get_by_role('link',name='수량·금액 변경',exact=True).click();page.locator('[name=unit_price]').fill('49000');page.locator('[name=reason]').fill('가상 할인 적용');page.get_by_role('button',name='금액 변경 저장',exact=True).click();page.wait_for_load_state('networkidle');expect(page.locator('body')).to_contain_text('금액 감소 · 기존 승인 유지')
 page.get_by_role('link',name='수량·금액 변경',exact=True).click();page.locator('[name=unit_price]').fill('55000');page.locator('[name=reason]').fill('최종 견적 인상');page.get_by_role('button',name='금액 변경 저장',exact=True).click();page.wait_for_load_state('networkidle');expect(page.locator('.heading .badge.large')).to_contain_text('재승인 대기')
 switch(page,'quality');doc(page,docs[0]);expect(page.get_by_role('button',name='수령 확인',exact=True)).to_have_count(0);expect(page.locator('.heading .badge.large')).to_have_text('구매 진행 중');expect(page.locator('[data-purchase-progress]')).to_have_count(0)
 switch(page,'finance');second=batch(page,[docs[0]]);switch(page,'ceo');page.goto(second);expect(page.locator('body')).to_contain_text('금액 변경 재승인');page.screenshot(path=str(args.output/'20-amount-increase-reapproval.png'),full_page=True);page.get_by_role('button',name='전체 품목 승인으로 선택',exact=True).click();page.get_by_role('button',name='구매 검토 결과 확정',exact=True).click();page.wait_for_load_state('networkidle')
 switch(page,'quality');doc(page,docs[0]);page.get_by_role('button',name='수령 확인',exact=True).click();page.wait_for_load_state('networkidle');page.goto(base+'/purchase-lab/requests/?mode=mine');row=page.locator('tbody tr').filter(has_text='보완 시험 측정장치');expect(row).to_contain_text('수령 완료');expect(row).to_contain_text('처리 완료');page.screenshot(path=str(args.output/'21-owner-receipt-column.png'),full_page=True)
 switch(page,'finance');page.goto(base+'/purchase-lab/requests/?mode=hold');row=page.locator('tbody tr').filter(has_text='보류 시험 소모품');expect(row).to_contain_text('품번을 확인');expect(row.locator('[data-select-item]')).to_have_count(0);doc(page,docs[1]);page.locator('form:has(input[value=prepare_hold]) [name=reason]').fill('요청 부서에 품번 확인 완료');page.get_by_role('button',name='재보고 준비 완료',exact=True).click();page.wait_for_load_state('networkidle');page.goto(base+'/purchase-lab/requests/?mode=hold');page.screenshot(path=str(args.output/'22-hold-followup-box.png'),full_page=True);page.locator(f'input[data-select-item][value="{docs[1]}"]').check();page.get_by_role('button',name='선택 품목 요약·보고',exact=True).click();page.locator('[name=note]').fill('보류 품목 보완 후 재보고');page.get_by_role('button',name='대표님께 구매요청',exact=True).click();page.wait_for_url('**/reports/*/');held=page.url
 switch(page,'ceo');page.goto(held);expect(page.locator('body')).to_contain_text('보류 품목 재보고');page.locator('[data-item-decision]').select_option('deny');page.locator('[data-item-reason]').fill('다음 분기에 구매합니다.');page.get_by_role('button',name='구매 검토 결과 확정',exact=True).click();page.wait_for_load_state('networkidle');page.goto(original);expect(page.locator('.badge.hold')).to_have_text('구매보류');expect(page.locator('.badge.allow')).to_have_text('구매승인')
 for role in ['quality','finance','ceo']:
  switch(page,role)
  routes=['/purchase-lab/','/purchase-lab/requests/?mode=mine'] if role=='quality' else ['/purchase-lab/requests/?mode=hold'] if role=='finance' else [urlsplit(original).path]
  for route in routes:
   page.goto(base+route)
   for width in [320,390,768,1366,2560]:
    page.set_viewport_size({'width':width,'height':1000});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),(role,route,width)
 assert not errors,errors
 result=dict(passed=True,supplement_and_attachment=True,approval_history_preserved=True,confirmation_badges=True,bulk_approval_with_exceptions=True,final_confirmation_counts=True,completion_notice_unread_counter=True,receipt_without_finance_step=True,decrease_history=True,increase_blocks_receipt_until_reapproval=True,hold_box_followup_and_rereport=True,original_reports_immutable=True,responsive=True,js_errors=errors)
 (args.output/'followup-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False));browser.close()
