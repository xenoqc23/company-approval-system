// No application pages, credentials or private document data are cached here.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));
self.addEventListener('push', event => {
  let payload = {};
  try { payload = event.data ? event.data.json() : {}; } catch { /* Show a generic alert. */ }
  event.waitUntil(self.registration.showNotification('사내결재시스템', {
    body: payload.body === '웹 푸시 테스트 알림입니다.' ? payload.body : '새 결재 알림이 도착했습니다. 알림함에서 확인해 주세요.',
    tag: typeof payload.tag === 'string' ? payload.tag : 'approval-notice',
    data: {url: '/notices/'},
    icon: '/static/workflow/images/xenosys-logo-refined.png'
  }));
});
self.addEventListener('notificationclick', event => {
  event.notification.close();
  event.waitUntil((async () => {
    const target = new URL('/notices/', self.location.origin).href;
    const windows = await self.clients.matchAll({type: 'window', includeUncontrolled: true});
    const existing = windows.find(client => new URL(client.url).origin === self.location.origin);
    if (existing) { await existing.navigate(target); return existing.focus(); }
    return self.clients.openWindow(target);
  })());
});
