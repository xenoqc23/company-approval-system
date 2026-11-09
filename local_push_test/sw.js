'use strict';
const messages={
  request:{title:'[테스트] 결재 요청',body:'개발팀 홍길동 대리님이 휴가원을 올렸습니다. 검토해 주세요.'},
  completed:{title:'[테스트] 결재 완료',body:'신청하신 구매요청서의 결재가 완료되었습니다.'}
};
self.addEventListener('install',()=>self.skipWaiting());
self.addEventListener('activate',event=>event.waitUntil(self.clients.claim()));
self.addEventListener('push',event=>{
  let payload={};try{payload=event.data?event.data.json():{};}catch{}
  const message=messages[payload.kind]||{title:'[테스트] PC 알림',body:'로컬 PC 알림 테스트입니다.'};
  event.waitUntil(self.registration.showNotification(message.title,{body:message.body,
    tag:typeof payload.tag==='string'?payload.tag:'local-push-test',requireInteraction:true,
    actions:[{action:'acknowledge',title:'확인'}],data:{localTrial:true}}));
});
self.addEventListener('notificationclick',event=>{
  event.notification.close();
  if(event.action==='acknowledge')return;
  event.waitUntil((async()=>{
    const target=self.location.origin+'/';
    const windows=await self.clients.matchAll({type:'window',includeUncontrolled:true});
    const existing=windows.find(client=>new URL(client.url).origin===self.location.origin);
    if(existing){await existing.navigate(target);return existing.focus();}
    return self.clients.openWindow(target);
  })());
});
