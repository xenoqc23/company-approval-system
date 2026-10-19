(() => {
  const runtime = document.getElementById('notification-runtime');
  const seedNode = document.getElementById('notification-seed');
  if (!runtime || !seedNode) return;
  const initial = JSON.parse(seedNode.textContent);
  let cursor = initial.latest, checking = false, settings = initial.preferences, registration = null;
  let stopped = false, audio = null;
  const storage = {
    get(key) { try { return localStorage.getItem(key); } catch { return null; } },
    set(key, value) { try { localStorage.setItem(key, value); } catch { /* Private browsing. */ } },
    remove(key) { try { localStorage.removeItem(key); } catch { /* Private browsing. */ } }
  };
  const ownerKey = 'xenosys-push-owner';
  const csrf = () => document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
  const post = async (url, data) => {
    const response = await fetch(url, {method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':csrf()},body:JSON.stringify(data),cache:'no-store'});
    if (response.redirected) throw new Error('로그인 상태를 확인해 주세요.');
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
    ['unread','waiting','accounting_unread'].forEach(key => document.querySelectorAll(`[data-live-count="${key}"]`).forEach(node => {
      node.textContent=summary[key];node.hidden=!summary[key] && !node.hasAttribute('data-keep-zero');
      node.setAttribute('aria-label',`${key==='accounting_unread'?'미확인':key==='waiting'?'미결':'안 읽은 알림'} ${summary[key]}건`);
    }));
    document.querySelectorAll('[data-accounting-kind]').forEach(link => {
      const tab=summary.tabs.find(t=>t.key===link.dataset.accountingKind);if(!tab)return;
      link.classList.toggle('has-new',tab.unread);link.querySelector('[data-tab-count]').textContent=tab.count;
      const badge=link.querySelector('[data-tab-unread]');badge.hidden=!tab.unread_count;badge.textContent=`미확인 ${tab.unread_count}건`;
      link.setAttribute('aria-label',`${tab.label} ${tab.count}건, 미확인 ${tab.unread_count}건`);
    });
    const pending=document.querySelector('.pending-approval-summary');if(pending)pending.classList.toggle('has-pending',summary.waiting>0);
  }
  async function poll() {
    if(stopped || checking || document.hidden)return;
    checking=true;
    try {
      const response=await fetch(`${runtime.dataset.status}?after=${cursor}`,{cache:'no-store'});
      if(response.redirected || response.status===401 || response.status===403){stopped=true;return;}
      if(!response.ok || !response.headers.get('content-type')?.includes('application/json'))return;
      const summary=await response.json();if(summary.user!==initial.user){stopped=true;return;}
      update(summary);cursor=summary.cursor;
      for(const event of summary.events){
        const key=`xenosys-event-${initial.user}-${event.id}`;
        const show=()=>{if(storage.get(key))return;storage.set(key,'1');if(settings.popup)toast(event.text,event.url);sound();};
        if(navigator.locks)await navigator.locks.request('xenosys-notice',show);else show();
      }
    } catch { /* Keep existing badges during temporary network failures. */ }
    finally {checking=false;}
  }
  update(initial);
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
  const state=document.querySelector('[data-push-state]'), enable=document.querySelector('[data-push-enable]'), disable=document.querySelector('[data-push-disable]'), test=document.querySelector('[data-push-test]');
  let configured=false, applicationKey='';
  function pushState(text,active=false){if(!state)return;state.textContent=text;enable.hidden=active;disable.hidden=!active;test.disabled=!active;}
  const bytes=value=>Uint8Array.from(atob(value.replace(/-/g,'+').replace(/_/g,'/')+'='.repeat((4-value.length%4)%4)),c=>c.charCodeAt(0));
  const ready=(async()=>{
    if(!window.isSecureContext || !('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)){
      pushState('이 브라우저에서는 웹 푸시를 지원하지 않습니다. HTTPS 또는 이 PC의 localhost에서 Chrome·Edge로 확인해 주세요.');if(enable)enable.disabled=true;return;
    }
    try{
      const response=await fetch(runtime.dataset.pushConfig,{cache:'no-store'});if(!response.ok || response.redirected)return;
      const config=await response.json();configured=config.configured;applicationKey=config.public_key;
      if(!configured){pushState('서버의 웹 푸시 초기 설정이 필요합니다. 기존 시스템 알림은 계속 사용할 수 있습니다.');if(enable)enable.disabled=true;return;}
      registration=await navigator.serviceWorker.register(runtime.dataset.worker,{scope:'/',updateViaCache:'none'});
      await navigator.serviceWorker.ready;
      let sub=await registration.pushManager.getSubscription();
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
    if(!configured || !registration)return;
    enable.disabled=true;
    try{
      const permission=await Notification.requestPermission();if(permission!=='granted'){pushState('알림이 허용되지 않았습니다. 사이트 설정에서 알림을 허용해 주세요.');return;}
      let sub=await registration.pushManager.getSubscription();sub ||= await registration.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:bytes(applicationKey)});
      await post(runtime.dataset.subscribe,sub.toJSON());storage.set(ownerKey,String(initial.user));pushState('이 브라우저의 웹 푸시가 켜져 있습니다.',true);
    }catch{pushState('웹 푸시를 켜지 못했습니다. 브라우저의 알림 권한과 인터넷 연결을 확인해 주세요.');}
    finally{enable.disabled=false;}
  };
  if(disable)disable.onclick=async()=>{
    disable.disabled=true;
    try{const sub=await registration?.pushManager.getSubscription();if(sub){await post(runtime.dataset.unsubscribe,{endpoint:sub.endpoint});await sub.unsubscribe();}storage.remove(ownerKey);pushState('이 브라우저의 웹 푸시를 껐습니다.');}
    catch(error){state.textContent=error.message;}finally{disable.disabled=false;}
  };
  if(test)test.onclick=async()=>{
    test.disabled=true;
    try{const sub=await registration?.pushManager.getSubscription();if(!sub)throw new Error('먼저 웹 푸시를 켜 주세요.');const result=await post(runtime.dataset.pushTestUrl,{endpoint:sub.endpoint});state.textContent=result.message;}
    catch(error){state.textContent=error.message;}finally{setTimeout(()=>{test.disabled=false;},30000);}
  };
  document.querySelectorAll('form[action="/logout/"]').forEach(form=>form.addEventListener('submit',async event=>{
    if(form.dataset.pushCleaned)return;
    event.preventDefault();stopped=true;
    try{
      await Promise.race([ready,new Promise(resolve=>setTimeout(resolve,2000))]);
      const sub=await registration?.pushManager.getSubscription();
      if(sub){const field=document.createElement('input');field.type='hidden';field.name='push_endpoint';field.value=sub.endpoint;form.append(field);await sub.unsubscribe();}
    }catch{/* The server still revokes the submitted endpoint when available. */}
    storage.remove(ownerKey);form.dataset.pushCleaned='1';form.submit();
  }));
})();
