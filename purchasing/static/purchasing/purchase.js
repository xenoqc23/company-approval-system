(() => {
 const menu=document.querySelector('.purchase-menu-toggle');
 menu?.addEventListener('click',()=>{const open=document.body.classList.toggle('purchase-menu-open');menu.setAttribute('aria-expanded',String(open));});
 // Compute cents as integers, without floating point money arithmetic.
 const formatCents=cents=>{const whole=cents/100n,frac=String(cents%100n).padStart(2,'0').replace(/0+$/,'');return whole.toLocaleString('ko-KR')+(frac?'.'+frac:'')+'원';};
 document.querySelectorAll('button[data-confirm]').forEach(button=>button.addEventListener('click',event=>{if(!confirm(button.dataset.confirm))event.preventDefault();}));
 const select=document.querySelector('[data-batch-select]');
 if(select){const boxes=[...select.querySelectorAll('[data-select-item]')],all=select.querySelector('[data-select-all]');
  const update=()=>{const n=boxes.filter(b=>b.checked).length;select.querySelector('[data-selected-count]').textContent=`${n}건 선택`;select.querySelector('[data-batch-button]').disabled=n===0;all.checked=boxes.length>0 && n===boxes.length;all.indeterminate=n>0 && n<boxes.length;};
  boxes.forEach(b=>b.addEventListener('change',update));all.addEventListener('change',()=>{boxes.forEach(b=>b.checked=all.checked);update();});update();
 }
 const decisionFor=item=>item.querySelector('[data-item-decision]:checked')?.value||item.querySelector('select[data-item-decision]')?.value||'pending';
 document.querySelectorAll('[data-report-item]').forEach(item=>{const choices=item.querySelectorAll('[data-item-decision]'),reason=item.querySelector('[data-item-reason]');if(!choices.length)return;const sync=()=>{const value=decisionFor(item),needs=['deny','hold'].includes(value);if(reason){reason.required=needs;reason.disabled=!needs;if(!needs)reason.value='';}const panel=item.querySelector('[data-reason-field]');if(panel)panel.hidden=!needs;const label=item.querySelector('[data-reason-label]');if(label)label.textContent=value==='hold'?'보류 사유':'반려 사유';const pending=item.querySelector('[data-decision-needed]');if(pending)pending.hidden=value!=='pending';};choices.forEach(choice=>choice.addEventListener('change',sync));sync();});
 const reportForm=document.querySelector('[data-report-review]');
 if(reportForm){
  const items=[...reportForm.querySelectorAll('[data-report-item]')];
  const summary=()=>{const counts={pending:0,allow:0,deny:0,hold:0},totals={pending:0n,allow:0n,deny:0n,hold:0n};
   items.forEach(item=>{const choice=decisionFor(item);counts[choice]++;const [whole,frac='']=item.dataset.total.split('.');totals[choice]+=BigInt(whole)*100n+BigInt(frac.padEnd(2,'0'));});
   return [['allow','승인'],['deny','반려'],['hold','보류'],['pending','선택 필요']].map(([key,label])=>`${label} ${counts[key]}건 · ${formatCents(totals[key])}`).join(' / ');};
  const refresh=()=>{const target=reportForm.querySelector('[data-decision-summary]');if(target)target.textContent=summary();};
  reportForm.querySelector('[data-approve-all]')?.addEventListener('click',()=>{items.forEach(item=>{const radio=item.querySelector('[data-item-decision][value=allow]'),select=item.querySelector('select[data-item-decision]');if(radio){radio.checked=true;radio.dispatchEvent(new Event('change',{bubbles:true}));}else if(select){select.value='allow';select.dispatchEvent(new Event('change',{bubbles:true}));}});refresh();});
  reportForm.addEventListener('change',refresh);refresh();
  reportForm.querySelector('[data-final-decisions]')?.addEventListener('click',event=>{const pending=items.find(item=>decisionFor(item)==='pending');if(pending){event.preventDefault();pending.tabIndex=-1;pending.focus();pending.querySelector('[data-decision-needed]').hidden=false;reportForm.querySelector('[data-decision-summary]').textContent='선택이 필요한 품목이 있습니다. 각 품목의 승인·반려·보류를 선택해 주세요.';return;}if(!confirm(summary()+'\n이 결과를 확정할까요? 승인된 품목은 기안자에게 결재완료로 전달됩니다.'))event.preventDefault();});
 }
 const urgent=document.querySelector('[name=urgent]'),urgentReason=document.querySelector('[name=urgent_reason]');if(urgent&&urgentReason){const sync=()=>{urgentReason.required=urgent.checked;const box=document.querySelector('[data-urgent-reason]');if(box)box.hidden=!urgent.checked;};urgent.addEventListener('change',sync);sync();}
 const form=document.querySelector('[data-request-form]');
 if(form){const qty=form.querySelector('[name=quantity]'),price=form.querySelector('[name=unit_price]');const sum=()=>{let amount=price.value.trim();const valid=/^\d+(?:\.\d{0,2})?$/.test(amount)||/^\d{1,3}(?:,\d{3})+(?:\.\d{0,2})?$/.test(amount);const parts=amount.replaceAll(',','').split('.');const cents=valid?(BigInt(parts[0])*100n+BigInt((parts[1]||'').padEnd(2,'0'))):0n;const count=/^\d{1,6}$/.test(qty.value)?BigInt(qty.value):0n;form.querySelector('[data-price]').textContent=formatCents(cents*count);};qty.addEventListener('input',sum);price.addEventListener('input',sum);sum();
  const field=form.querySelector('[name=product]'),box=form.querySelector('[data-hints-results]');let timer,controller,cursor=0;
  field.addEventListener('input',()=>{clearTimeout(timer);controller?.abort();box.hidden=true;const version=++cursor;
   if(field.value.trim().length<2)return;
   timer=setTimeout(async()=>{controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),10000);try{
    const response=await fetch(form.dataset.hints+'?q='+encodeURIComponent(field.value),{signal:controller.signal,cache:'no-store'});
    if(!response.ok||response.redirected)throw Error();const data=await response.json();if(cursor!==version)return;box.replaceChildren();box.hidden=false;
    const title=document.createElement('strong');title.textContent=`유사 구매요청 ${data.count}건`;box.append(title);
    data.results.forEach(r=>{const p=document.createElement('p');p.textContent=`${r.product} · ${r.department} · ${r.quantity}개 · ${r.status}${r.usage_department?' · 사용 '+r.usage_department:''}${r.location?' · 보관 '+r.location:''}`;box.append(p);});
    const note=document.createElement('small');note.textContent='과거 수령 내역도 포함합니다. 현재 재고를 뜻하지 않으며 추가 구매를 계속 요청할 수 있습니다.';box.append(note);
   }catch{if(cursor===version){box.hidden=false;box.textContent='유사 구매내역을 확인하지 못했습니다. 요청은 계속 작성할 수 있습니다.';}}finally{clearTimeout(timeout);}},400);
  });
 }
 document.querySelectorAll('[data-receipt-complete]').forEach(form=>form.addEventListener('submit',event=>{if(!confirm('요청한 물품을 모두 받으셨나요? 수령 완료로 표시합니다.'))event.preventDefault();}));
 document.querySelectorAll('[data-receipt-form]').forEach(form=>form.addEventListener('submit',event=>{
  const quantity=Number(form.querySelector('[name=quantity]').value),remaining=Number(form.dataset.remaining);
  if(!Number.isSafeInteger(quantity)||quantity<1||quantity>remaining){event.preventDefault();return;}
  const after=remaining-quantity;
  if(!confirm(`이번에 받은 수량 ${quantity}개를 등록할까요?\n${after===0?'모든 수량을 받아 수령 완료로 표시됩니다.':`등록 후 남은 수량은 ${after}개입니다.`}`))event.preventDefault();
 }));
 document.querySelectorAll('.purchase-content form, body.purchase-workspace form').forEach(form=>form.addEventListener('submit',event=>{
   if(event.defaultPrevented)return;
   if(form.dataset.sending){event.preventDefault();return;}
   form.dataset.sending='1';
 }));
 const requestForm=document.querySelector('[data-request-form]');
 if(requestForm&&requestForm.querySelector('[name=request_method]')){
  const syncMethod=()=>{const direct=requestForm.querySelector('[name=request_method]:checked')?.value==='direct';const fields=requestForm.querySelector('[data-review-fields]');if(!fields)return;fields.hidden=direct;
   fields.querySelectorAll('select').forEach(field=>{field.disabled=direct;field.required=!direct&&((field.name==='approver')||(field.name==='reviewer'&&requestForm.dataset.reviewMode==='review_approval'));});
   requestForm.querySelector('[data-direct-note]').hidden=!direct;requestForm.querySelector('[data-submit-label]').textContent=direct?'구매담당자에게 요청':'검토 요청';requestForm.querySelector('[data-method-summary]').textContent=direct?requestForm.querySelector('[data-direct-note]').textContent.trim():'검토자가 다음 승인자를 지정해 승인 요청합니다.';
  };requestForm.querySelectorAll('[name=request_method]').forEach(input=>input.addEventListener('change',syncMethod));syncMethod();
 }
 const policyForm=document.querySelector('[data-policy-form]');
 if(policyForm&&policyForm.querySelector('[data-route-preview]')){
  const preview=()=>{const rank=policyForm.querySelector('[data-preview-rank]').value,method=policyForm.querySelector('[data-preview-method]').value,dev=policyForm.querySelector('[data-preview-department]').value==='dev';
   const allowed=[...policyForm.querySelectorAll('[name=direct_ranks]:checked')].map(e=>e.value).includes(rank),who=policyForm.querySelector(dev?'#id_dev_director':'#id_production_director')?.selectedOptions[0]?.textContent||policyForm.querySelector(dev?'[data-preview-checker-dev]':'[data-preview-checker-other]')?.textContent||'담당자 미지정';
   const text=method==='direct'&&!allowed?'이 직급은 검토 요청만 사용할 수 있습니다.':'기안자 → '+(method==='review'?(policyForm.querySelector('[name=review_mode]')?(policyForm.querySelector('[name=review_mode]').value==='review_approval'?'검토자 → 승인자 → ':'승인자 → '):'검토자 판단 → '):'')+who+' 구매 확인 → 구매담당자 결제 요청 → 대표님 결제 → 구매 담당자 결제 완료 등록';policyForm.querySelector('[data-route-preview]').textContent=text;
  };policyForm.addEventListener('change',preview);preview();
 }
 const simpleRule=document.querySelector('[data-simple-leave-rule]');
 if(simpleRule){const update=()=>{const option=simpleRule.querySelector('[name=allow_representative_direct]');simpleRule.querySelector('[data-rule-ceo-preview]').hidden=!option?.checked;};simpleRule.addEventListener('change',update);update();}
 const runtime=document.querySelector('[data-purchase-status]');
 if(runtime){let busy=false,stopped=false;const poll=async()=>{if(busy||stopped||document.hidden)return;busy=true;try{const r=await fetch(runtime.dataset.purchaseStatus,{cache:'no-store'});if(r.redirected||!r.ok)return;const data=await r.json();if(String(data.user)!==runtime.dataset.currentUser){stopped=true;return;}document.querySelectorAll('[data-live]').forEach(node=>node.textContent=data.counts[node.dataset.live]||0);}catch{}finally{busy=false;}};setInterval(poll,15000);window.addEventListener('focus',poll);}

 const summaryForm=document.querySelector('[data-purchase-summary]');
 if(summaryForm){
  const team=summaryForm.querySelector('[name=department]');
  const people=[...summaryForm.querySelectorAll('[data-summary-person]')];
  const filterPeople=()=>people.forEach(person=>{const input=person.querySelector('input');const visible=!team.value||JSON.parse(person.dataset.departments).includes(team.value);person.hidden=!visible;input.disabled=!visible;if(!visible)input.checked=false;});
  team.addEventListener('change',filterPeople);filterPeople();
  summaryForm.querySelector('[data-summary-all]').addEventListener('click',()=>people.forEach(person=>{person.querySelector('input').checked=false;}));
  summaryForm.querySelectorAll('[data-summary-period]').forEach(button=>button.addEventListener('click',()=>{summaryForm.querySelector('[name=start]').value=button.dataset.start;summaryForm.querySelector('[name=end]').value=button.dataset.end;}));
 }
})();
