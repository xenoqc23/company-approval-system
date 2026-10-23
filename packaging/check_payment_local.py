"""Acceptance check only for a fresh seed_full_demo instance on loopback."""
import argparse,json,re,sys
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright,expect
parser=argparse.ArgumentParser();parser.add_argument('--base-url',default='http://127.0.0.1:18151');parser.add_argument('--password-file',type=Path,required=True);parser.add_argument('--output',type=Path,default=Path('test-results/payment'));args=parser.parse_args();base=args.base_url.rstrip('/')
assert urlsplit(base).hostname in ['127.0.0.1','localhost']
out=args.output;out.mkdir(parents=True,exist_ok=True)
pw=args.password_file.read_text().strip()
errors=[];checks=[]
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
 pages={}
 def role(who):
  if who not in pages:
   context=browser.new_context(viewport={'width':1440,'height':1000},locale='ko-KR',timezone_id='Asia/Seoul')
   page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)));page.on('dialog',lambda d:d.accept())
   page.goto(base+'/login/');page.locator('[name=username]').fill('admin' if who=='admin' else 'p_'+who);page.locator('[name=password]').fill(pw)
   page.get_by_role('button',name='로그인',exact=True).click();page.wait_for_url(base+'/');expect(page.locator('#integrated-role')).to_be_visible();pages[who]=page
  return pages[who]
 def shot(page,name):page.screenshot(path=str(out/name),full_page=True)
 def create(who,name,direct=False):
  page=role(who);page.goto(base+'/purchases/new/');expect(page.locator('#id_url')).to_be_visible();assert page.locator('#id_url').get_attribute('required') is not None
  if direct:page.locator('[name=request_method][value=direct]').check()
  for key,value in dict(product=name,vendor='가상구매처',quantity='2',unit_price='50,000',reason='업무용 장비 교체',url='https://example.com/test-product').items():page.locator('#id_'+key).fill(value)
  expect(page.locator('[data-price]')).to_have_text('100,000원');shot(page,'01-compose.png')
  page.get_by_role('button',name='구매담당자에게 요청' if direct else '검토 요청',exact=True).click();page.wait_for_url('**/requests/*/')
  return int(urlsplit(page.url).path.rstrip('/').split('/')[-1])
 def doc(who,pk):
  page=role(who);page.goto(base+f'/purchases/requests/{pk}/');return page
 def click(page,label):page.get_by_role('button',name=label,exact=True).click();page.wait_for_load_state('networkidle')
 def pay(page,item,action,reason=''):
  page.locator(f'[name=items][value="{item}"]').first.check()
  if reason:page.locator('#payment-reason').fill(reason)
  click(page,{'paid':'선택 품목 결제 완료','deny':'선택 품목 반려','hold':'선택 품목 보류'}[action]);expect(page.get_by_role('heading',name={'paid':'결제 완료 확인','deny':'반려 확인','hold':'보류 확인'}[action])).to_be_visible()
  expect(page.get_by_text('선택 품목 합계',exact=True)).to_be_visible();shot(page,'05-payment-confirm.png');click(page,{'paid':'결제 완료 확정','deny':'반려 확정','hold':'보류 확정'}[action])
 first=create('quality','결제시험 모니터')
 reviewer=doc('quality_manager',first);expect(reviewer.locator('#id_new_person_department')).to_be_visible();expect(reviewer.locator('#id_new_person')).to_be_visible()
 expect(reviewer.locator('[value=review_final]')).to_have_count(1);assert 'primary' not in reviewer.get_by_role('button',name='승인완료',exact=True).get_attribute('class')
 expect(reviewer.locator('[data-secondary-actions]')).to_be_visible();shot(reviewer,'02-reviewer.png')
 reviewer.locator('#id_new_person_department').select_option(label='품질팀')
 options=reviewer.locator('#id_new_person option').evaluate_all('(options)=>options.map(o=>({value:o.value,label:o.textContent}))')
 approver=next(o['value'] for o in options if '가상품질팀장' in o['label'])
 reviewer.locator('#id_new_person').select_option(approver);click(reviewer,'승인 요청');expect(reviewer.locator('[data-primary-task]')).to_have_attribute('data-primary-task','waiting')
 lead=doc('quality_lead',first);click(lead,'승인완료')
 checker=doc('prod_director',first);click(checker,'구매 내용 확인')
 second=create('dev_manager','결제시험 개발 장비',True);checker2=doc('dev_director',second);click(checker2,'구매 내용 확인')
 third=create('quality','결제시험 보류 장비');reviewer=doc('quality_manager',third);click(reviewer,'승인완료');checker=doc('prod_director',third);click(checker,'구매 내용 확인')
 finance=role('finance');finance.goto(base+'/purchases/reports/')
 for pk in [first,second,third]:finance.locator(f'[name=requests][value="{pk}"]').check()
 click(finance,'선택 품목으로 결제 요청');expect(finance.get_by_role('heading',name='대표님께 결제 요청')).to_be_visible()
 finance.locator('[name=title]').fill('가상 장비 결제 요청');finance.locator('[name=note]').fill('확인된 업무용 장비입니다.');click(finance,'대표님께 결제 요청');finance.wait_for_url('**/reports/*/')
 report_path=urlsplit(finance.url).path;shot(finance,'03-finance-request.png');assert finance.locator('tbody tr').count()==3
 item_ids=finance.locator('[name=items]').evaluate_all('(els)=>els.map(e=>e.value)');assert len(item_ids)==3
 ceo=role('ceo');ceo.goto(base+report_path);expect(ceo.get_by_role('heading',name='구매 진행현황')).to_be_visible()
 expect(ceo.locator('thead th')).to_have_text(['품목','기안자','구매처','수량','가격','용도','진행상황'])
 assert ceo.locator('[name=items]').count()==0;assert ceo.locator('[data-payment-form]').count()==0;expect(ceo.locator('.purchase-content')).not_to_contain_text('수령')
 assert ceo.request.get(base+'/notifications/status/').json()['waiting']==0;shot(ceo,'04-ceo-readonly.png')
 # Forged representative POST is refused even though this role can approve other document types.
 csrf=ceo.locator('[name=csrfmiddlewaretoken]').first.input_value()
 forged=ceo.request.post(base+report_path,form={'csrfmiddlewaretoken':csrf,'revision':'0','action':'paid','items':item_ids[0],'intent':'confirm'});assert forged.status==403
 finance.goto(base+report_path);pay(finance,item_ids[0],'paid');expect(finance.locator('tbody tr').nth(0)).to_contain_text('결제 완료');expect(finance.locator('tbody tr').nth(1)).to_contain_text('결제 대기')
 pay(finance,item_ids[1],'deny','대체품 사용');pay(finance,item_ids[2],'hold','규격 재확인');shot(finance,'06-finance-result.png')
 owner=doc('quality',first);expect(owner.locator('.heading')).to_contain_text('결재완료');expect(owner.get_by_role('button',name='수령 완료',exact=True)).to_be_visible()
 owner.goto(base+'/notices/');expect(owner.locator('main')).to_contain_text('최종결재가 완료되었습니다.');expect(owner.locator('main')).not_to_contain_text('결제 완료, 물품')
 owner=doc('quality',first);click(owner,'수령 완료');expect(owner.locator('.heading')).to_contain_text('수령 완료')
 finance.goto(base+'/purchases/reports/?tab=completed');expect(finance.locator('tbody')).to_contain_text('결제시험 모니터');shot(finance,'07-received.png')
 ceo.goto(base+report_path);expect(ceo.locator('.purchase-content')).not_to_contain_text('수령');shot(ceo,'08-ceo-result.png')
 # Changed amounts keep old snapshots; a mistaken payment can be corrected before receipt.
 changed=create('dev_manager','결제시험 금액 변경 장비',True);changed_checker=doc('dev_director',changed);click(changed_checker,'구매 내용 확인')
 finance.goto(base+'/purchases/reports/?tab=items');finance.locator(f'[name=requests][value="{changed}"]').check();click(finance,'선택 품목으로 결제 요청')
 finance.locator('[name=title]').fill('금액 변경 전 결제 요청');finance.locator('[name=note]').fill('변경 전 금액 보존 시험');click(finance,'대표님께 결제 요청');old_path=urlsplit(finance.url).path
 finance=doc('finance',changed);finance.get_by_role('link',name='수량·금액 변경',exact=True).click();finance.locator('[name=quantity]').fill('3');finance.locator('[name=reason]').fill('견적 수량 변경');click(finance,'금액 변경 저장')
 finance.goto(base+old_path);expect(finance.locator('tbody tr')).to_contain_text('100,000원');expect(finance.locator('tbody tr')).to_contain_text('보류')
 finance.goto(base+'/purchases/reports/?tab=items');finance.locator(f'[name=requests][value="{changed}"]').check();click(finance,'선택 품목으로 결제 요청')
 finance.locator('[name=title]').fill('금액 변경 후 결제 요청');finance.locator('[name=note]').fill('변경 금액 재요청');click(finance,'대표님께 결제 요청')
 expect(finance.locator('tbody tr')).to_contain_text('150,000원');changed_item=finance.locator('[name=items]').first.get_attribute('value');pay(finance,changed_item,'paid')
 finance.locator('.payment-correction [name=items]').check();finance.locator('.payment-correction [name=reason]').fill('가상 등록 정정 확인');click(finance,'선택 품목 등록 취소 확인');click(finance,'결제 완료 등록 취소 확정')
 expect(finance.locator('tbody tr')).to_contain_text('결제 대기');pay(finance,changed_item,'paid')
 # Original staff/rule/menu pages remain reachable. No horizontal page overflow.
 admin=role('admin')
 targets=[(ceo,report_path),(finance,report_path),(reviewer,f'/purchases/requests/{third}/'),(owner,f'/purchases/requests/{first}/'),(admin,'/staff/?purchase_settings=1'),(admin,'/regulations/?tab=leave')]
 for page,path in targets:
  for width in [320,390,768,1440,2560]:
   page.set_viewport_size({'width':width,'height':1000});response=page.goto(base+path);assert response.status==200,(path,response.status)
   assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'),(path,width,page.evaluate('document.documentElement.scrollWidth'))
 checks=['visible required link','reviewer visible approver picker','review completion secondary','review and internal finish paths','department checkers','finance batch','CEO read-only + forged POST denied','partial payment','item rejection and hold','owner final-only completion notice','receipt and completed tab','amount change preserves old snapshot and resubmits','payment correction and re-registration','original menus','320–2560px no overflow']
 assert not errors,errors
 (out/'result.json').write_text(json.dumps(dict(checks=checks,documents=[first,second,third],report=report_path,js_errors=errors),ensure_ascii=False,indent=2))
 print(json.dumps(dict(checks=checks,documents=[first,second,third],report=report_path,js_errors=errors),ensure_ascii=False))
 browser.close()
