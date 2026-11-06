'use strict';
const $=id=>document.getElementById(id);
const browser=/Edg\//.test(navigator.userAgent)?'Microsoft Edge':/Chrome\//.test(navigator.userAgent)?'Chrome':'Chrome 또는 Edge 사용을 권장합니다';
$('browser-name').textContent=browser;
let config,registration,connected=false,device='',lastStatus=null,busy=false,cooldownUntil=0;
let pendingBusy=false,pendingStatus=null,documentFingerprint='';
let displayObservation='아직 확인하지 않음',windowsDiagnostic=null;
try{device=localStorage.getItem('xenosys-local-push-device')||'';}catch{}
const state=text=>$('connection').textContent=text;
const delivery=text=>$('delivery').textContent=text;
const bytes=value=>Uint8Array.from(atob(value.replace(/-/g,'+').replace(/_/g,'/')+'='.repeat((4-value.length%4)%4)),c=>c.charCodeAt(0));
const bounded=operation=>new Promise((resolve,reject)=>{
  const timer=setTimeout(()=>reject(new Error('브라우저 푸시 연결 시간이 초과됐습니다. 인터넷 연결을 확인한 뒤 다시 눌러 주세요.')),20000);
  Promise.resolve(operation).then(value=>{clearTimeout(timer);resolve(value);},error=>{clearTimeout(timer);reject(error);});
});
async function request(path,data){
  const response=await fetch(path,{method:data?'POST':'GET',cache:'no-store',headers:data?{'Content-Type':'application/json','X-Local-Test-Token':config.token}:{},body:data?JSON.stringify(data):undefined});
  const result=await response.json();if(!response.ok)throw new Error(result.error||'연결을 확인해 주세요.');return result;
}
function controls(){
  $('connect').disabled=!registration||busy;$('connect').hidden=connected;$('disconnect').hidden=!connected;
  $('display').disabled=!registration||busy;
  document.querySelectorAll('.send').forEach(button=>button.disabled=!connected||busy||Date.now()<cooldownUntil);
}
function diagnostic(){
  const permission=('Notification' in window)?Notification.permission:'지원하지 않음';
  const labels={granted:'허용',denied:'차단',default:'아직 허용하지 않음'};
  const lines=[`브라우저: ${browser}`,`브라우저 알림: ${labels[permission]||permission}`,`로컬 연결: ${connected?'켜짐':'꺼짐'}`];
  lines.push(`표시 시험: ${displayObservation}`);
  if(registration)lines.push(`서비스 워커: ${registration.active?.state||'준비 중'}`);
  if(lastStatus?.last_delivery)lines.push(`최근 발송: ${lastStatus.last_delivery.message}`);
  if(pendingStatus?.last_reminder)lines.push(`PC 로그인 알림 최근 요청: ${pendingStatus.last_reminder.message}`);
  if(windowsDiagnostic)lines.push(windowsDiagnostic);
  return lines.join('\n');
}
async function refresh(){
  try{
    lastStatus=await request('/api/status?device='+encodeURIComponent(device));connected=lastStatus.connected;
    if(lastStatus.last_delivery){
      const job=lastStatus.last_delivery;
      if(job.status==='pending'){
        const seconds=Math.max(0,Math.ceil(job.due-Date.now()/1000));
        delivery(`${seconds}초 후 발송 예정입니다. 브라우저 창을 닫아도 검은 실행 창은 켜 두세요.`);
        cooldownUntil=Math.max(cooldownUntil,job.due*1000);
      }else delivery(job.message);
    }
    $('diagnostic').textContent=diagnostic();controls();
  }catch{state('로컬 실행 창이 켜져 있는지 확인해 주세요. 실행 창을 다시 시작했다면 화면을 새로고침해 주세요.');}
}
function pendingControls(){
  const windows=!!pendingStatus?.startup.supported;
  $('pending-create').disabled=!config||pendingBusy;
  $('pending-remind').disabled=!config||pendingBusy||!windows||!pendingStatus?.pending_count;
  $('startup-enable').disabled=!config||pendingBusy||!windows;
  $('startup-disable').disabled=!config||pendingBusy||!windows;
  document.querySelectorAll('[data-complete-document]').forEach(button=>button.disabled=pendingBusy);
}
function renderPending(result){
  pendingStatus=result;
  const fingerprint=JSON.stringify(result.documents);
  if(fingerprint!==documentFingerprint){
    documentFingerprint=fingerprint;
    const rows=result.documents.map(doc=>{
      const row=document.createElement('div');row.className='pending-document';
      const info=document.createElement('div'),title=document.createElement('strong'),who=document.createElement('small');
      title.textContent=`${doc.kind} · ${doc.completed===null?'검토 대기':'처리완료'}`;
      who.textContent=`${doc.department} ${doc.author} ${doc.rank}`;
      info.append(title,who);row.append(info);
      if(doc.completed===null){
        const button=document.createElement('button');button.type='button';button.textContent='처리완료';button.dataset.completeDocument=doc.id;
        button.onclick=()=>pendingAction('/api/pending/complete',{document:doc.id});row.append(button);
      }
      return row;
    });
    $('pending-documents').replaceChildren(...rows);
  }
  let text=`저장된 가상 미결 문서 ${result.pending_count}건`;
  if(result.last_reminder){const last=result.last_reminder;text+=`\n최근 확인: ${new Date(last.created*1000).toLocaleString()} · ${last.reason==='windows_login'?'Windows 로그인':'PC 켜기 상황 재현'}\n${last.message}`;}
  $('pending-state').textContent=text;
  $('startup-state').textContent=result.startup.message;
  pendingControls();
}
async function refreshPending(){
  if(pendingBusy||!config)return;
  try{renderPending(await request('/api/pending'));}
  catch{$('pending-state').textContent='미결 문서 확인에 실패했습니다. 로컬 실행 창을 확인해 주세요.';}
}
async function pendingAction(path,data={}){
  pendingBusy=true;pendingControls();
  if(path==='/api/pending/remind')$('pending-state').textContent='저장된 미결 문서의 Windows 알림 표시를 요청하고 있습니다…';
  try{renderPending(await request(path,data));}
  catch(error){$('pending-state').textContent=error.message;}
  finally{pendingBusy=false;pendingControls();}
}
async function registerExisting(sub){
  const result=await request('/api/connect',{subscription:sub.toJSON()});device=result.device;connected=true;
  try{localStorage.setItem('xenosys-local-push-device',device);}catch{}
  state('이 브라우저에 알림이 연결됐습니다. 아래에서 테스트해 주세요.');delivery('원하는 테스트 알림을 선택해 주세요.');
}
const ready=(async()=>{
  try{config=await request('/api/config');$('windows-diagnostics').disabled=false;await refreshPending();}
  catch{state('로컬 실행 창을 켜고 화면을 새로고침해 주세요.');return;}
  if(!window.isSecureContext||!('serviceWorker' in navigator)||!('PushManager' in window)||!('Notification' in window)){
    state('Chrome 또는 Edge에서 검은 실행 창에 나온 http://127.0.0.1 주소로 접속해 주세요. HTML 파일을 직접 열면 테스트할 수 없습니다.');return;
  }
  try{
    registration=await navigator.serviceWorker.register('/sw.js',{scope:'/',updateViaCache:'none'});
    await navigator.serviceWorker.ready;
    const sub=await registration.pushManager.getSubscription();
    if(sub&&Notification.permission==='granted')await registerExisting(sub);
    else state(Notification.permission==='denied'?'알림이 차단됐습니다. 주소창 왼쪽 사이트 설정에서 알림을 허용해 주세요.':'준비됐습니다. 알림 허용하고 연결을 눌러 주세요.');
    controls();await refresh();
  }catch{state('로컬 알림 준비에 실패했습니다. 실행 창을 켜고 페이지를 새로고침해 주세요.');}
})();
$('connect').onclick=async()=>{
  busy=true;controls();
  try{
    const permission=await Notification.requestPermission();
    if(permission!=='granted')throw new Error('알림이 허용되지 않았습니다. 주소창 왼쪽 사이트 설정에서 알림을 허용해 주세요.');
    await ready;
    let sub=await registration.pushManager.getSubscription();
    sub ||= await bounded(registration.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:bytes(config.public_key)}));
    await registerExisting(sub);await refresh();
  }catch(error){state(error.name==='NotAllowedError'?'알림을 허용해 주세요. 브라우저가 계속 차단하면 주소창의 사이트 설정을 확인해 주세요.':`알림 연결 실패: ${error.message}\n인터넷 연결과 브라우저의 푸시 서비스 연결을 확인해 주세요.`);}
  finally{busy=false;controls();}
};
$('display').onclick=async()=>{
  busy=true;controls();
  try{
    const permission=await Notification.requestPermission();
    if(permission!=='granted')throw new Error('브라우저 알림을 허용해 주세요.');
    const tag='local-display-test-'+Date.now();
    await registration.showNotification('[테스트] 윈도우 표시 확인',{body:'이 PC의 알림 표시 테스트입니다. 실제 결재 문서는 없습니다.',tag,data:{localTrial:true}});
    let found=false;
    for(let i=0;i<8;i++){
      if((await registration.getNotifications({tag})).length){found=true;break;}
      await new Promise(resolve=>setTimeout(resolve,250));
    }
    displayObservation=found?'브라우저 알림 목록에서 확인됨 · 실제 PC 표시는 별도 확인':'브라우저가 표시 요청을 받았지만 알림 목록에서는 찾지 못함';
    state(found?'브라우저 알림 목록에는 등록됐습니다. 실제 팝업과 알림 센터에 없다면 아래 ‘Windows 알림 상태 확인’을 눌러 주세요.':'표시 요청은 끝났지만 브라우저 알림 목록에서도 확인되지 않았습니다. 아래 ‘Windows 알림 상태 확인’을 눌러 주세요.');
    $('diagnostic').textContent=diagnostic();
  }catch(error){state(error.message);}finally{busy=false;controls();}
};
$('disconnect').onclick=async()=>{
  busy=true;controls();
  try{
    await request('/api/disconnect',{device});const sub=await registration.pushManager.getSubscription();if(sub)await sub.unsubscribe();
    connected=false;device='';lastStatus=null;cooldownUntil=0;
    try{localStorage.removeItem('xenosys-local-push-device');}catch{}
    state('이 브라우저의 연결을 해제했습니다. 대기 중인 테스트도 취소했습니다.');delivery('다시 시험하려면 알림 허용하고 연결을 눌러 주세요.');
    $('diagnostic').textContent=diagnostic();
  }catch(error){state(error.message);}finally{busy=false;controls();}
};
document.querySelectorAll('.send').forEach(button=>button.onclick=async()=>{
  busy=true;controls();
  try{
    const result=await request('/api/test',{device,kind:button.dataset.kind});cooldownUntil=Date.now()+result.delay*1000;
    delivery('30초 후 발송을 예약했습니다. 브라우저의 모든 창을 닫고 기다려 주세요. 검은 실행 창은 켜 두세요.');
    await refresh();
  }catch(error){delivery(error.message);}finally{busy=false;controls();}
});
document.querySelectorAll('[data-copy]').forEach(button=>button.onclick=async()=>{
  try{await navigator.clipboard.writeText(button.dataset.copy);button.textContent='복사됨';setTimeout(()=>button.textContent='주소 복사',1600);}
  catch{state('위 주소를 직접 선택해 복사한 뒤 주소창에 붙여넣어 주세요.');}
});
$('refresh').onclick=refresh;
$('pending-create').onclick=()=>pendingAction('/api/pending/create');
$('pending-remind').onclick=()=>pendingAction('/api/pending/remind');
$('startup-enable').onclick=()=>pendingAction('/api/startup/enable');
$('startup-disable').onclick=()=>pendingAction('/api/startup/disable');
$('windows-diagnostics').onclick=async()=>{
  const button=$('windows-diagnostics');button.disabled=true;
  $('windows-diagnostic').textContent='Windows 알림 상태를 확인하고 있습니다…';
  try{
    const value=await request('/api/windows/diagnose',{});
    if(!value.supported)windowsDiagnostic=value.message;
    else{
      const setting=v=>v===0?'꺼짐':v===1?'켜짐':'기본값 · Windows 설정에서 확인 필요';
      const policy=v=>v===1?'알림 차단 정책 확인됨':'차단 값 확인되지 않음';
      const native=value.native||{};
      const lines=[`Windows 버전: ${value.windows||'확인 불가'}`,`Windows 전체 알림: ${setting(value.global_toasts)}`,
        `테스트 앱 등록 정보: ${value.app_registered?'있음':'없음'}`,`테스트 앱 알림: ${setting(value.app_toasts)}`,
        `사용자 정책: ${policy(value.user_policy)}`,`PC 정책: ${policy(value.machine_policy)}`,
        `Windows 알림 API: ${native.ok?'응답 확인':'실패'}`,`확인 단계: ${native.stage||'unknown'}`,
        `API 알림 설정: ${native.setting||'unknown'}`];
      if(native.hresult||native.error_type)lines.push(`오류: ${native.hresult||native.error_type}`);
      if(native.details)lines.push(`상세: ${native.details}`);
      windowsDiagnostic=lines.join('\n');
    }
    $('windows-diagnostic').textContent=windowsDiagnostic+'\n이 결과는 표시 여부를 확인하는 진단이며, 알림·보안 설정은 변경하지 않습니다.';
    $('diagnostic').textContent=diagnostic();
  }catch(error){$('windows-diagnostic').textContent=error.message;}
  finally{button.disabled=false;}
};
$('copy-result').onclick=async()=>{
  await refresh();try{await navigator.clipboard.writeText(diagnostic());$('copy-result').textContent='복사됨';}
  catch{$('diagnostic').textContent=diagnostic()+'\n위 내용을 직접 복사해 주세요.';}
};
setInterval(()=>{controls();if(!document.hidden){refresh();refreshPending();}},2000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden){refresh();refreshPending();}});
