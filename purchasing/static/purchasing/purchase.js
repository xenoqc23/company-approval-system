(() => {
 const menu=document.querySelector('.purchase-menu-toggle');
 menu?.addEventListener('click',()=>{const open=document.body.classList.toggle('purchase-menu-open');menu.setAttribute('aria-expanded',String(open));});
 // Compute cents as integers, without floating point money arithmetic.
 const formatCents=cents=>{const whole=cents/100n,frac=String(cents%100n).padStart(2,'0').replace(/0+$/,'');return whole.toLocaleString('ko-KR')+(frac?'.'+frac:'')+'원';};
 document.querySelectorAll('[data-confirm]').forEach(button=>button.addEventListener('click',event=>{if(!confirm(button.dataset.confirm))event.preventDefault();}));
 document.querySelectorAll('form').forEach(form=>form.addEventListener('submit',event=>{
   if(event.defaultPrevented)return;
   if(form.dataset.sending){event.preventDefault();return;}
   form.dataset.sending='1';
 }));
 const select=document.querySelector('[data-batch-select]');
 if(select){const boxes=[...select.querySelectorAll('[data-select-item]')],all=select.querySelector('[data-select-all]');
  const update=()=>{const n=boxes.filter(b=>b.checked).length;select.querySelector('[data-selected-count]').textContent=`${n}건 선택`;select.querySelector('[data-batch-button]').disabled=n===0;all.checked=boxes.length>0 && n===boxes.length;all.indeterminate=n>0 && n<boxes.length;};
  boxes.forEach(b=>b.addEventListener('change',update));all.addEventListener('change',()=>{boxes.forEach(b=>b.checked=all.checked);update();});update();
 }
 document.querySelectorAll('[data-report-item]').forEach(item=>{const decision=item.querySelector('[data-item-decision]'),reason=item.querySelector('[data-item-reason]');if(!decision)return;const sync=()=>reason.required=['deny','hold'].includes(decision.value);decision.addEventListener('change',sync);sync();});
 document.querySelectorAll('[data-policy-form] select[name^=dev_], [data-policy-form] select[name^=other_]').forEach(input=>{const note=input.parentElement.querySelector('[data-rule-preview]');if(!note)return;const sync=()=>{note.textContent={direct:'요청 → 담당 이사 → 경리',approval:'요청 → 중간 승인 → 담당 이사 → 경리',review_approval:'요청 → 검토 → 중간 승인 → 담당 이사 → 경리'}[input.value]||'';};input.addEventListener('change',sync);sync();});
 const form=document.querySelector('[data-request-form]');
 if(form){const qty=form.querySelector('[name=quantity]'),price=form.querySelector('[name=unit_price]');const sum=()=>{let amount=price.value.trim();const valid=/^\d+(?:\.\d{0,2})?$/.test(amount)||/^\d{1,3}(?:,\d{3})+(?:\.\d{0,2})?$/.test(amount);const parts=amount.replaceAll(',','').split('.');const cents=valid?(BigInt(parts[0])*100n+BigInt((parts[1]||'').padEnd(2,'0'))):0n;const count=/^\d{1,6}$/.test(qty.value)?BigInt(qty.value):0n;form.querySelector('[data-price]').textContent=formatCents(cents*count);};qty.addEventListener('input',sum);price.addEventListener('input',sum);sum();
  const field=form.querySelector('[name=product]'),box=form.querySelector('[data-hints-results]');let timer,controller,cursor=0;
  field.addEventListener('input',()=>{clearTimeout(timer);controller?.abort();box.hidden=true;const version=++cursor;
   if(field.value.trim().length<2)return;
   timer=setTimeout(async()=>{controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),10000);try{
    const response=await fetch(form.dataset.hints+'?q='+encodeURIComponent(field.value),{signal:controller.signal,cache:'no-store'});
    if(!response.ok||response.redirected)throw Error();const data=await response.json();if(cursor!==version)return;box.replaceChildren();box.hidden=false;
    const title=document.createElement('strong');title.textContent=`유사 구매요청 ${data.count}건`;box.append(title);
    data.results.forEach(r=>{const p=document.createElement('p');p.textContent=`${r.product} · ${r.department} · ${r.quantity}개 · ${r.status}`;box.append(p);});
    const note=document.createElement('small');note.textContent='과거 수령 내역도 포함합니다. 현재 재고를 뜻하지 않으며 추가 구매를 계속 요청할 수 있습니다.';box.append(note);
   }catch{if(cursor===version){box.hidden=false;box.textContent='유사 구매내역을 확인하지 못했습니다. 요청은 계속 작성할 수 있습니다.';}}finally{clearTimeout(timeout);}},400);
  });
 }
 const runtime=document.querySelector('[data-purchase-status]');
 if(runtime){let busy=false,stopped=false;const poll=async()=>{if(busy||stopped||document.hidden)return;busy=true;try{const r=await fetch(runtime.dataset.purchaseStatus,{cache:'no-store'});if(r.redirected||!r.ok)return;const data=await r.json();if(String(data.user)!==runtime.dataset.currentUser){stopped=true;return;}document.querySelectorAll('[data-live]').forEach(node=>node.textContent=data.counts[node.dataset.live]||0);}catch{}finally{busy=false;}};setInterval(poll,15000);window.addEventListener('focus',poll);}
})();
