(() => {
  const runtime = document.getElementById('notification-runtime');
  const seedNode = document.getElementById('notification-seed');
  if (!runtime || !seedNode) return;
  const initial = JSON.parse(seedNode.textContent);
  let purchaseCursor = initial.purchase_latest || 0;
  let cursor = initial.latest, checking = false, settings = initial.preferences, registration = null;
  let failures=0;
  let stopped = false, audio = null;
  const storage = {
    get(key) { try { return localStorage.getItem(key); } catch { return null; } },
    set(key, value) { try { localStorage.setItem(key, value); } catch { /* Private browsing. */ } },
    remove(key) { try { localStorage.removeItem(key); } catch { /* Private browsing. */ } }
  };
  const scope=initial.storage_scope?`${initial.storage_scope}-${location.port}-`:'';
  const cursorKey=`xenosys-notice-cursor-${scope}${initial.user}`;
  const savedCursor=Number(storage.get(cursorKey));
  if(storage.get(cursorKey)!==null && Number.isSafeInteger(savedCursor) && savedCursor>=0 && savedCursor<=initial.latest)cursor=savedCursor;
  else storage.set(cursorKey,String(cursor));
  const purchaseCursorKey=`xenosys-purchase-cursor-${location.port}-${initial.user}`;
  const savedPurchase=Number(storage.get(purchaseCursorKey));
  if(storage.get(purchaseCursorKey)!==null&&Number.isSafeInteger(savedPurchase)&&savedPurchase>=0&&savedPurchase<=purchaseCursor)purchaseCursor=savedPurchase;
  else storage.set(purchaseCursorKey,String(purchaseCursor));
  const reminderKey=`xenosys-work-reminder-${scope}${initial.user}`;
  const ownerKey = 'xenosys-push-owner';
  const bounded = (promise,ms=15000) => {
    let timer;
    return Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('알림 준비 시간이 초과되었습니다. 브라우저 알림 권한을 확인한 뒤 다시 시도해 주세요.')),ms);})]).finally(()=>clearTimeout(timer));
  };
  async function request(url,options={}) {
    const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),10000);
    try{return await fetch(url,{...options,signal:controller.signal});}catch(error){if(error.name==='AbortError')throw new Error('응답 시간이 초과되었습니다. 연결 상태를 확인한 뒤 다시 시도해 주세요.');throw error;}finally{clearTimeout(timer);}
  }
  const csrf = () => document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
  const post = async (url, data) => {
    const response = await request(url, {method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':csrf()},body:JSON.stringify(data),cache:'no-store'});
    if (response.redirected) throw new Error('로그인 상태를 확인해 주세요.');
    if(!response.headers.get('content-type')?.includes('application/json'))throw new Error('로그인 상태가 바뀌었거나 요청을 확인하지 못했습니다. 화면을 새로고침한 뒤 다시 시도해 주세요.');
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || '처리하지 못했습니다. 다시 시도해 주세요.');
    return result;
  };
  const sound = () => {
    if (!settings.sound || !audio || audio.state !== 'running') return;
    const osc = audio.createOscillator(), gain = audio.createGain();
    osc.connect(gain); gain.connect(audio.destination);osc.frequency.value=760;
    gain.gain.setValueAtTime(.06,audio.currentTime);gain.gain.exponentialRampToValueAtTime(.001,audio.currentTime+.2);
    osc.start();osc.stop(audio.currentTime+.2);
  };
  const unlockAudio = () => {
    if (!settings.sound) return;
    const Audio = window.AudioContext || window.webkitAudioContext;
    if (!Audio) return;
    audio ||= new Audio();audio.resume().catch(() => {});
  };
  document.addEventListener('pointerdown', unlockAudio);
  document.addEventListener('keydown', unlockAudio);
  function toast(text,url) {
    const list=document.getElementById('notification-toasts');
    while(list.children.length>=3)list.firstElementChild.remove();
    const box=document.createElement('div');box.className='notification-toast';
    const link=document.createElement('a');link.href=url;link.textContent=text;
    const hint=document.createElement('small');hint.textContent='눌러서 확인하기';link.append(hint);
    const close=document.createElement('button');close.type='button';close.textContent='×';close.setAttribute('aria-label','알림 닫기');close.onclick=()=>box.remove();
    box.append(link,close);list.append(box);setTimeout(()=>box.remove(),15000);
  }
  function update(summary) {
    settings=summary.preferences;
    if(summary.purchase_counts)document.querySelectorAll('[data-live-purchase]').forEach(node=>{const n=summary.purchase_counts[node.dataset.livePurchase]||0;node.textContent=n;});
    if(summary.purchase_counts)document.querySelectorAll('[data-live-purchase-region]').forEach(node=>{node.hidden=!(summary.purchase_counts[node.dataset.livePurchaseRegion]||0);});
    ['unread','waiting','accounting_unread','completed_unread'].forEach(key => document.querySelectorAll(`[data-live-count="${key}"]`).forEach(node => {
      node.textContent=summary[key];node.hidden=!summary[key] && !node.hasAttribute('data-keep-zero');
      node.setAttribute('aria-label',`${['accounting_unread','completed_unread'].includes(key)?'미확인':key==='waiting'?'미결':'안 읽은 알림'} ${summary[key]}건`);
    }));
    document.querySelectorAll('[data-accounting-kind]').forEach(link => {
      const tab=summary.tabs.find(t=>t.key===link.dataset.accountingKind);if(!tab)return;
      link.classList.toggle('has-new',tab.unread);link.querySelector('[data-tab-count]').textContent=tab.count;
      const badge=link.querySelector('[data-tab-unread]');badge.hidden=!tab.unread_count;badge.textContent=`미확인 ${tab.unread_count}건`;
      link.setAttribute('aria-label',`${tab.label} ${tab.count}건, 미확인 ${tab.unread_count}건`);
    });
    const completed=document.querySelector('.completion-summary');if(completed)completed.classList.toggle('has-pending',summary.completed_unread>0);
    const pending=document.querySelector('.pending-approval-summary');if(pending)pending.classList.toggle('has-pending',summary.waiting>0);
  }
  function connection(text='',url='') {
    const banner=document.getElementById('notification-connection');
    if(!banner)return;
    banner.hidden=!text;
    banner.querySelector('span').textContent=text;
    const link=banner.querySelector('a');link.hidden=!url;if(url)link.href=url;
  }
  function remindPending() {
    const counts=`${initial.waiting}:${initial.accounting_unread}:${initial.completed_unread}`;
    if(!settings.popup || (!initial.waiting && !initial.accounting_unread && !initial.completed_unread))return;
    let previous=null;try{previous=sessionStorage.getItem(reminderKey);}catch{}
    if(previous===counts)return;
    try{sessionStorage.setItem(reminderKey,counts);}catch{}
    if(initial.completed_unread)toast(`내 기안 중 ${initial.storage_scope?'승인완료':'결재완료'} 미확인 문서가 ${initial.completed_unread}건 있습니다.`, '/documents/?mode=completed&unread=1');
    if(initial.waiting)toast(`내가 처리할 미결 문서가 ${initial.waiting}건 있습니다.`, '/documents/?mode=pending');
    if(initial.accounting_unread)toast(`아직 확인하지 않은 최종 승인 문서가 ${initial.accounting_unread}건 있습니다.`, '/documents/?mode=accounting');
  }
  async function poll() {
    if(stopped || checking || document.hidden)return;
    checking=true;
    try {
      const response=await request(`${runtime.dataset.status}?after=${cursor}&after_purchase=${purchaseCursor}`,{cache:'no-store'});
      if(response.redirected || response.status===401 || response.status===403){stopped=true;connection('로그인 상태가 바뀌어 알림 갱신이 중지되었습니다.','/login/');return;}
      if(!response.ok || !response.headers.get('content-type')?.includes('application/json'))throw new Error('status');
      const summary=await response.json();if(summary.user!==initial.user){stopped=true;connection('다른 계정으로 로그인되어 이 화면의 알림 갱신이 중지되었습니다. 현재 계정으로 새로고침해 주세요.',location.pathname+location.search);return;}
      failures=0;connection();update(summary);
      // A visible window on another monitor must not consume the focused window's popup.
      if(!document.hasFocus())return;
      cursor=summary.cursor;storage.set(cursorKey,String(cursor));
      purchaseCursor=summary.purchase_cursor??purchaseCursor;storage.set(purchaseCursorKey,String(purchaseCursor));
      for(const event of [...summary.events,...(summary.purchase_events||[])]){
        const key=`xenosys-event-${scope}${initial.user}-${event.id}`;
        const show=()=>{if(storage.get(key))return;storage.set(key,'1');if(settings.popup)toast(event.text,event.url);sound();};
        if(navigator.locks)await navigator.locks.request('xenosys-notice',show);else show();
      }
    } catch { if(++failures>=2)connection('알림 연결을 다시 시도하고 있습니다. 계속되면 관리자에게 문의해 주세요.'); }
    finally {checking=false;}
  }
  update(initial);
  remindPending();
  poll();
  window.setInterval(poll,15000);
  document.addEventListener('visibilitychange',poll);window.addEventListener('focus',poll);
  // Tests can exercise the same public refresh path without shortening production polling.
  window.addEventListener('xenosys-refresh-notifications',poll);
  const message=document.querySelector('[data-notification-settings-message]');
  const popup=document.querySelector('[data-notification-popup]'), soundBox=document.querySelector('[data-notification-sound]');
  if(popup && soundBox){
    popup.checked=settings.popup;soundBox.checked=settings.sound;
    for(const box of [popup,soundBox])box.addEventListener('change',async()=>{
      const previous={...settings};settings={popup:popup.checked,sound:soundBox.checked};unlockAudio();
      try{await post(runtime.dataset.preferences,settings);message.textContent='알림 설정을 저장했습니다.';}
      catch(error){settings=previous;popup.checked=settings.popup;soundBox.checked=settings.sound;message.textContent=error.message;}
    });
  }
  const screenTest=document.querySelector('[data-screen-test]');
  if(screenTest)screenTest.onclick=()=>{toast('화면 팝업 테스트입니다. 창 크기와 관계없이 표시됩니다.','/notices/');sound();};
  document.querySelectorAll('form[action="/logout/"]').forEach(form=>form.addEventListener('submit',()=>{
    try{sessionStorage.removeItem(reminderKey);}catch{}
  }));
  if(!initial.webpush_enabled)return;
  const state=document.querySelector('[data-push-state]'), enable=document.querySelector('[data-push-enable]'), disable=document.querySelector('[data-push-disable]'), test=document.querySelector('[data-push-test]');
  let configured=false, applicationKey='';
  function pushState(text,active=false){if(!state)return;state.textContent=text;enable.hidden=active;disable.hidden=!active;}
  const bytes=value=>Uint8Array.from(atob(value.replace(/-/g,'+').replace(/_/g,'/')+'='.repeat((4-value.length%4)%4)),c=>c.charCodeAt(0));
  const ready=(async()=>{
    if(!window.isSecureContext || !('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)){
      pushState('이 브라우저에서는 웹 푸시를 지원하지 않습니다. HTTPS 또는 이 PC의 localhost에서 Chrome·Edge로 확인해 주세요.');if(enable)enable.disabled=true;return;
    }
    try{
      const response=await request(runtime.dataset.pushConfig,{cache:'no-store'});if(!response.ok || response.redirected)return;
      const config=await response.json();configured=config.configured;applicationKey=config.public_key;
      if(!configured){pushState('서버의 웹 푸시 초기 설정이 필요합니다. 기존 시스템 알림은 계속 사용할 수 있습니다.');if(enable)enable.disabled=true;return;}
      registration=await navigator.serviceWorker.register(runtime.dataset.worker,{scope:'/',updateViaCache:'none'});
      await bounded(navigator.serviceWorker.ready);
      let sub=await bounded(registration.pushManager.getSubscription());
      if(sub && storage.get(ownerKey)!==String(initial.user)){
        await post(runtime.dataset.unsubscribe,{endpoint:sub.endpoint});await sub.unsubscribe();sub=null;storage.remove(ownerKey);
      }
      if(sub && Notification.permission==='granted'){
        await post(runtime.dataset.subscribe,sub.toJSON());pushState('이 브라우저의 웹 푸시가 켜져 있습니다.',true);
      }else pushState(Notification.permission==='denied'?'알림이 차단되어 있습니다. 주소창의 사이트 설정에서 알림을 허용한 뒤 다시 눌러 주세요.':'웹 푸시가 꺼져 있습니다. 버튼을 눌러 알림을 허용해 주세요.');
    }catch{pushState('웹 푸시 상태를 확인하지 못했습니다. 네트워크 연결을 확인해 주세요.');}
  })();
  if(enable)enable.onclick=async()=>{
    // Permission request stays in the user's explicit click, never on page load.
    if(!configured || !registration){pushState('웹 푸시 준비 상태를 확인하고 있습니다. 잠시 후 다시 눌러 주세요.');return;}
    enable.disabled=true;
    try{
      const permission=await Notification.requestPermission();if(permission!=='granted'){pushState('알림이 허용되지 않았습니다. 사이트 설정에서 알림을 허용해 주세요.');return;}
      let sub=await bounded(registration.pushManager.getSubscription());sub ||= await bounded(registration.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:bytes(applicationKey)}));
      await post(runtime.dataset.subscribe,sub.toJSON());storage.set(ownerKey,String(initial.user));pushState('이 브라우저의 웹 푸시가 켜져 있습니다.',true);
    }catch{pushState('웹 푸시를 켜지 못했습니다. 브라우저의 알림 권한과 인터넷 연결을 확인해 주세요.');}
    finally{enable.disabled=false;}
  };
  if(disable)disable.onclick=async()=>{
    disable.disabled=true;
    try{const sub=await bounded(registration?.pushManager.getSubscription());if(sub){await post(runtime.dataset.unsubscribe,{endpoint:sub.endpoint});await sub.unsubscribe();}storage.remove(ownerKey);pushState('이 브라우저의 웹 푸시를 껐습니다.');}
    catch(error){state.textContent=error.message;}finally{disable.disabled=false;}
  };
  const osTest=document.querySelector('[data-os-test]');
  if(osTest)osTest.onclick=async()=>{
    osTest.disabled=true;
    try {
      if(!('Notification' in window))throw new Error('이 브라우저는 Windows 알림을 지원하지 않습니다.');
      const permission=await Notification.requestPermission();
      if(permission!=='granted')throw new Error('브라우저에서 알림을 허용해 주세요.');
      await ready;
      if(!registration)throw new Error('알림 준비가 끝나지 않았습니다. 잠시 후 다시 눌러 주세요.');
      await registration.showNotification('사내결재시스템',{body:'이 PC의 알림 표시 테스트입니다.',tag:'xenosys-local-display-test'});
      state.textContent='Windows에 표시를 요청했습니다. 알림 센터도 확인해 주세요. 표시되지 않으면 Windows 알림·방해 금지 설정을 확인해 주세요.';
    }catch(error){state.textContent=error.message;}finally{osTest.disabled=false;}
  };
  const diagnosticButton=document.querySelector('[data-push-diagnostics]');
  async function diagnose() {
    const target=document.querySelector('[data-push-diagnostic-result]');if(!target)return;
    try {
      const response=await request(runtime.dataset.pushStatus,{cache:'no-store'});
      if(!response.ok || response.redirected)throw new Error('로그인 상태와 연결 상태를 확인해 주세요.');
      const result=await response.json();
      const permission=('Notification' in window)?Notification.permission:'unsupported';
      const labels={granted:'허용',denied:'차단',default:'아직 허용하지 않음',unsupported:'지원하지 않음'};
      const lines=[`브라우저 알림: ${labels[permission]}`,`이 계정의 웹 푸시: ${result.subscribed?'켜짐':'꺼짐'}`,`푸시 발송 프로그램: ${result.worker_running?'실행 중':'중지 또는 응답 없음 (관리자에게 문의해 주세요)'}`];
      if(result.last_delivery)lines.push(`최근 발송: ${result.last_delivery.label}`);
      target.textContent=lines.join(' / ');
    }catch(error){target.textContent=error.message;}
  }
  if(diagnosticButton)diagnosticButton.onclick=diagnose;
  if(test)test.onclick=async()=>{
    let queued=false;test.disabled=true;
    state.textContent='웹 푸시 구독과 발송 상태를 확인하고 있습니다…';
    try{const sub=await bounded(registration?.pushManager.getSubscription());if(!sub)throw new Error('먼저 웹 푸시를 켜 주세요.');const result=await post(runtime.dataset.pushTestUrl,{endpoint:sub.endpoint});queued=true;state.textContent=result.message;diagnose();setTimeout(diagnose,13000);}
    catch(error){state.textContent=error.message;}finally{if(queued)setTimeout(()=>{test.disabled=false;},30000);else test.disabled=false;}
  };
  document.querySelectorAll('form[action="/logout/"]').forEach(form=>form.addEventListener('submit',async event=>{
    if(form.dataset.pushCleaned)return;
    event.preventDefault();stopped=true;
    try{
      await Promise.race([ready,new Promise(resolve=>setTimeout(resolve,2000))]);
      const sub=await bounded(registration?.pushManager.getSubscription());
      if(sub){const field=document.createElement('input');field.type='hidden';field.name='push_endpoint';field.value=sub.endpoint;form.append(field);await sub.unsubscribe();}
    }catch{/* The server still revokes the submitted endpoint when available. */}
    storage.remove(ownerKey);try{sessionStorage.removeItem(reminderKey);}catch{}form.dataset.pushCleaned='1';form.submit();
  }));
})();
