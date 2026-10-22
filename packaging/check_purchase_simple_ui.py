"""Check intuitive labels, visible next action, status colors and independent receipt status."""
import argparse,json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright,expect
p=argparse.ArgumentParser();p.add_argument('--base-url',default='http://127.0.0.1:18113');p.add_argument('--password-file',type=Path,required=True);p.add_argument('--ids-file',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args();base=args.base_url.rstrip('/');assert urlsplit(base).hostname in ['localhost','127.0.0.1'];ids=json.loads(args.ids_file.read_text());args.output.mkdir(parents=True,exist_ok=True)
def switch(page,role):
 page.locator('#demo-user').select_option(str(ids['p_'+role]));page.get_by_role('button',name='이 계정으로 전환',exact=True).click();page.wait_for_url(base+'/purchase-lab/')
def doc(page,pk):page.goto(base+f'/purchase-lab/requests/{pk}/')
def create(page,name):
 switch(page,'quality');page.goto(base+'/purchase-lab/new/');page.locator('#id_product').fill(name);page.locator('#id_vendor').fill('가상구매처');page.locator('#id_quantity').fill('2');page.locator('#id_unit_price').fill('50000');page.locator('#id_reason').fill('직관적인 화면을 확인하는 가상 요청입니다.');page.get_by_role('button',name='구매요청 제출',exact=True).click();page.wait_for_url('**/requests/*/');return int(urlsplit(page.url).path.rstrip('/').split('/')[-1])
def color(locator,expected):assert locator.evaluate('(e)=>getComputedStyle(e).backgroundColor')==expected
with sync_playwright() as tool:
 b=tool.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox']);context=b.new_context(viewport={'width':1440,'height':1000},locale='ko-KR');page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)));page.on('dialog',lambda d:d.accept());page.goto(base+'/purchase-lab/login/');page.locator('[name=username]').fill('p_quality');page.locator('[name=password]').fill(args.password_file.read_text());page.get_by_role('button',name='로그인',exact=True).click();page.wait_for_url(base+'/purchase-lab/')
 pk=create(page,'공용 업무용 키보드')
 switch(page,'quality_manager');expect(page.locator('.work-card')).to_have_count(1);doc(page,pk);expect(page.locator('[data-primary-task]')).to_have_attribute('data-primary-task','approve');expect(page.locator('[data-primary-task] .primary:visible')).to_have_count(1);expect(page.locator('[data-secondary-actions]')).not_to_have_attribute('open','');expect(page.get_by_role('button',name='반려',exact=True)).not_to_be_visible();color(page.locator('.heading .badge.large'),'rgb(255, 241, 217)');page.screenshot(path=str(args.output/'23-review-next-action.png'),full_page=True);page.get_by_role('button',name='검토 완료 · 승인자에게 전달',exact=True).click();page.wait_for_load_state('networkidle')
 switch(page,'quality_lead');doc(page,pk);page.get_by_role('button',name='내부 승인 완료',exact=True).click();page.wait_for_load_state('networkidle')
 switch(page,'prod_director');expect(page.locator('.work-card')).to_have_count(1);doc(page,pk);expect(page.locator('[data-primary-task]')).to_have_attribute('data-primary-task','confirm');expect(page.get_by_role('button',name='기안자에게 보완 요청',exact=True)).not_to_be_visible();page.screenshot(path=str(args.output/'24-confirm-next-action.png'),full_page=True)
 cancel=create(page,'취소 상태 색상 확인용');page.get_by_text('추가 작업',exact=True).click();form=page.locator('form:has(input[value=cancel])');form.locator('[name=reason]').fill('가상 테스트 요청 취소');form.get_by_role('button',name='요청 취소',exact=True).click();page.wait_for_load_state('networkidle');color(page.locator('.heading .badge.large'),'rgb(237, 240, 241)');expect(page.get_by_role('heading',name='요청 종료',exact=True)).to_be_visible()
 page.goto(base+'/purchase-lab/requests/?mode=mine');row=page.locator('tbody tr').filter(has_text='공용 업무용 키보드');expect(row).to_contain_text('구매 진행 중');color(row.locator('.tone-active'),'rgb(230, 239, 255)');approved=page.locator('tbody tr').filter(has_text='보완 시험 측정장치');expect(approved.locator('td').nth(3)).to_have_text('구매 승인완료');expect(approved.locator('td').nth(4)).to_have_text('수령 완료');color(approved.locator('td').nth(3).locator('.badge'),'rgb(222, 243, 229)');page.screenshot(path=str(args.output/'25-requester-status-colors.png'),full_page=True)
 switch(page,'finance');expect(page.get_by_role('link',name='구매 모아보기',exact=False).first).to_be_visible();expect(page.locator('.work-card')).to_have_count(1);page.screenshot(path=str(args.output/'26-finance-task-home.png'),full_page=True)
 switch(page,'ceo');expect(page.locator('.work-card')).to_have_count(1);expect(page.locator('.purchase-overview')).to_have_count(0);expect(page.locator('.purchase-quick')).to_have_count(0);page.screenshot(path=str(args.output/'27-representative-task-home.png'),full_page=True)
 for role in ['quality','quality_manager','prod_director','finance','ceo']:
  switch(page,role)
  routes=['/purchase-lab/']
  if role in ['quality','quality_manager','prod_director']:routes.append(f'/purchase-lab/requests/{pk}/')
  for route in routes:
   page.goto(base+route)
   for width in [320,390,768,1366,2560]:
    page.set_viewport_size({'width':width,'height':1000});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),(role,route,width)
 assert not errors,errors
 result=dict(passed=True,blue_purchase_progress=True,orange_review_wait=True,green_purchase_approval=True,gray_cancel=True,one_primary_task=True,secondary_actions_collapsed=True,role_homes=True,approval_and_receipt_separate=True,responsive=True,js_errors=errors)
 (args.output/'simple-ui-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False));b.close()
