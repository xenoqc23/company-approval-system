(() => {
  const correction=document.querySelector('[data-correction-form]');
  if(correction)correction.addEventListener('input',()=>{
    const preview=correction.querySelector('[data-correction-preview]');if(preview)preview.remove();
  });
  const form=document.querySelector('[data-purchase-hints]');
  if(!form)return;
  const product=form.querySelector('[name=product]'),kind=form.querySelector('[name=kind]'),box=form.querySelector('[data-purchase-hints-results]');
  if(!product || !box || !kind)return;
  let timer,controller,version=0;
  async function search(){
    const current=++version;controller?.abort();box.replaceChildren();box.hidden=true;
    const q=product.value.trim();if(kind.value==='leave' || q.replace(/\s/g,'').length<2)return;
    controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),10000);
    box.hidden=false;box.textContent='유사 구매내역을 찾고 있습니다…';
    try{
      const url=new URL(form.dataset.purchaseHints,location.origin);url.searchParams.set('q',q);url.searchParams.set('exclude',form.dataset.documentId);
      const response=await fetch(url,{signal:controller.signal,cache:'no-store'});
      if(response.redirected || !response.ok || !response.headers.get('content-type')?.includes('application/json'))throw new Error('response');
      const data=await response.json();if(version!==current)return;
      box.replaceChildren();const title=document.createElement('strong');title.textContent=data.count?`유사 구매요청이 ${data.count}건 있습니다.`:'유사 구매요청이 없습니다.';box.append(title);
      for(const row of data.results){const item=document.createElement('div');item.className='purchase-hint-item';
        const name=document.createElement('strong');name.textContent=row.product;
        const detail=document.createElement('small');detail.textContent=`${row.department} · ${row.quantity}개 · ${row.requested} 요청 · ${row.status}`;
        item.append(name,detail);box.append(item);
      }
      const note=document.createElement('p');note.textContent=(data.count>8?'진행 중인 요청을 먼저, 완료 내역은 최신순으로 최대 8건 표시합니다. ':'')+'배송·입고완료된 과거 내역도 포함합니다. 현재 재고를 뜻하지 않으며 필요한 경우 구매를 계속할 수 있습니다.';box.append(note);
    }catch(error){if(version===current){box.hidden=false;box.textContent='유사 구매내역을 확인하지 못했습니다. 다시 입력해 주세요. 구매요청은 계속 작성할 수 있습니다.';}}
    finally{clearTimeout(timeout);}
  }
  product.addEventListener('input',()=>{version++;controller?.abort();clearTimeout(timer);box.hidden=true;timer=setTimeout(search,400);});
  kind.addEventListener('change',search);search();
})();
