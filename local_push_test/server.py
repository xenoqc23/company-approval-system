"""Loopback-only, standalone Web Push trial. No NAS/application imports or data."""
import argparse
import base64
import hashlib
import json
import os
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent
SAMPLES = {
    'request': ('[테스트] 결재 요청', '개발팀 홍길동 대리님이 휴가원을 올렸습니다. 검토해 주세요.'),
    'completed': ('[테스트] 결재 완료', '신청하신 구매요청서의 결재가 완료되었습니다.'),
}


def validate_subscription(value):
    try:
        endpoint = value['endpoint']
        if not isinstance(endpoint, str) or len(endpoint) > 2048:
            raise ValueError
        url = urlsplit(endpoint)
        host = (url.hostname or '').lower()
        allowed = host == 'fcm.googleapis.com' or host.endswith('.notify.windows.com')
        if (url.scheme != 'https' or not allowed or url.port not in (None, 443)
                or url.username or url.password or url.fragment):
            raise ValueError
        keys = value['keys']
        decode = lambda s: base64.b64decode(s + '=' * (-len(s) % 4), altchars=b'-_', validate=True)
        point, auth = decode(keys['p256dh']), decode(keys['auth'])
        if len(point) != 65 or point[0] != 4 or len(auth) != 16:
            raise ValueError
        from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePublicKey, SECP256R1
        EllipticCurvePublicKey.from_encoded_point(SECP256R1(), point)
        return {'endpoint': endpoint, 'keys': {'p256dh': keys['p256dh'], 'auth': keys['auth']}}
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ValueError('Chrome 또는 Edge의 올바른 알림 연결 정보가 필요합니다.') from None


class Trial:
    def __init__(self, data_dir, clock=time.time):
        self.clock = clock
        self.lock = threading.RLock()
        self.token = secrets.token_urlsafe(32)
        self.devices, self.jobs = {}, []
        self.data_dir = Path(data_dir)
        self._pending_store = None
        from desktop import WindowsDesktop
        self.desktop = WindowsDesktop(ROOT, self.data_dir)
        self.key_path = Path(data_dir) / 'local-test-vapid.pem'
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        if not self.key_path.exists():
            key = ec.generate_private_key(ec.SECP256R1())
            value = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
            try:
                with os.fdopen(os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as f:
                    f.write(value)
            except FileExistsError:
                pass
        key = serialization.load_pem_private_key(self.key_path.read_bytes(), password=None)
        self.public_key = base64.urlsafe_b64encode(key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)).rstrip(b'=').decode()

    @property
    def pending_store(self):
        from pending import PendingStore
        with self.lock:
            if self._pending_store is None:
                self._pending_store = PendingStore(self.data_dir / 'pending-trial.sqlite3', self.clock)
            return self._pending_store

    def pending_status(self):
        return {**self.pending_store.status(), 'startup': self.desktop.status()}

    def connect(self, value):
        sub = validate_subscription(value)
        device = hashlib.sha256(sub['endpoint'].encode()).hexdigest()
        with self.lock:
            if device not in self.devices and len(self.devices) >= 20:
                raise ValueError('테스트 연결이 많습니다. 실행 창을 다시 시작해 주세요.')
            self.devices[device] = sub
        return device

    def schedule(self, device, kind):
        with self.lock:
            if device not in self.devices:
                raise ValueError('먼저 이 브라우저의 알림을 허용하고 연결해 주세요.')
            if kind not in SAMPLES:
                raise ValueError('테스트 알림 종류를 확인해 주세요.')
            if any(j['device'] == device and self.clock() - j['created'] < 30 for j in self.jobs):
                raise ValueError('테스트 알림은 30초 간격으로 보낼 수 있습니다.')
            if len(self.jobs) >= 200:
                self.jobs = [j for j in self.jobs if j['status'] == 'pending']
            job = dict(id=secrets.token_hex(12), device=device, kind=kind,
                       created=self.clock(), due=self.clock() + 30, status='pending', message='30초 후 발송 대기')
            self.jobs.append(job)
            return job['id']

    def status(self, device):
        with self.lock:
            jobs = [j for j in self.jobs if j['device'] == device]
            last = jobs[-1] if jobs else None
            return dict(connected=device in self.devices, last_delivery=(
                dict(status=last['status'], message=last['message'], due=last['due']) if last else None))

    def disconnect(self, device):
        with self.lock:
            self.devices.pop(device, None)
            for job in self.jobs:
                if job['device'] == device and job['status'] == 'pending':
                    job.update(status='cancelled', message='알림 연결을 해제해 취소했습니다.')

    def deliver_due(self, sender=None):
        if sender is None:
            from pywebpush import webpush
            sender = webpush
        with self.lock:
            due = [j for j in self.jobs if j['status'] == 'pending' and j['due'] <= self.clock()]
            for job in due:
                job.update(status='sending', message='푸시 서비스에 전달 중')
        for job in due:
            with self.lock:
                sub = self.devices.get(job['device'])
            if not sub:
                job.update(status='cancelled', message='알림 연결이 해제되었습니다.')
                continue
            title, body = SAMPLES[job['kind']]
            payload = dict(title=title, body=body, kind=job['kind'], tag='local-trial-' + job['id'])
            try:
                sender(subscription_info=sub, data=json.dumps(payload, ensure_ascii=False),
                       vapid_private_key=str(self.key_path), vapid_claims={'sub': 'https://localhost'},
                       ttl=120, timeout=10, headers={'Urgency': 'high'})
                update = dict(status='sent', message='푸시 서비스에 전달했습니다. PC 팝업 표시는 직접 확인해 주세요.')
            except Exception as exc:
                code = getattr(getattr(exc, 'response', None), 'status_code', None)
                update = dict(status='failed', message=(
                    '알림 연결이 만료됐습니다. 연결을 해제하고 다시 허용해 주세요.' if code in (404, 410)
                    else f'푸시 발송 실패{f" (HTTP {code})" if code else ""}. PC 인터넷 연결과 보안 프로그램의 연결 제한을 확인해 주세요.'))
            with self.lock:
                job.update(update)
        return len(due)


def handler(trial):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Never print subscriptions, keys or request bodies.

        def send(self, status, value, content_type='application/json; charset=utf-8'):
            value = json.dumps(value, ensure_ascii=False).encode() if isinstance(value, dict) else value
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(value)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(value)

        def allowed_host(self):
            port = self.server.server_address[1]
            hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
            origin = self.headers.get('Origin')
            return self.headers.get('Host') in hosts and (origin is None or origin in {'http://' + h for h in hosts})

        def do_GET(self):
            if not self.allowed_host():
                return self.send(403, {'error': '이 PC의 로컬 주소에서만 이용할 수 있습니다.'})
            url = urlsplit(self.path)
            if url.path == '/api/config':
                return self.send(200, dict(public_key=trial.public_key, token=trial.token, delay=30))
            if url.path == '/api/status':
                return self.send(200, trial.status(parse_qs(url.query).get('device', [''])[0]))
            if url.path == '/api/pending':
                return self.send(200, trial.pending_status())
            files = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'application/javascript'),
                     '/sw.js': ('sw.js', 'application/javascript'), '/style.css': ('style.css', 'text/css; charset=utf-8')}
            if url.path not in files:
                return self.send(404, {'error': '없는 페이지입니다.'})
            name, kind = files[url.path]
            self.send(200, (ROOT / name).read_bytes(), kind)

        def do_POST(self):
            if not self.allowed_host() or not secrets.compare_digest(self.headers.get('X-Local-Test-Token', ''), trial.token):
                return self.send(403, {'error': '테스트 화면을 새로고침한 뒤 다시 시도해 주세요.'})
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 8192 or self.headers.get_content_type() != 'application/json':
                    raise ValueError('올바른 테스트 요청이 필요합니다.')
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict):
                    raise ValueError('올바른 테스트 요청이 필요합니다.')
                if self.path == '/api/connect':
                    return self.send(200, dict(device=trial.connect(data.get('subscription'))))
                if self.path == '/api/pending/create':
                    trial.pending_store.create_samples()
                    return self.send(200, trial.pending_status())
                if self.path == '/api/pending/complete':
                    if not isinstance(data.get('document'), str):
                        raise ValueError('가상 문서를 선택해 주세요.')
                    trial.pending_store.complete(data['document'])
                    return self.send(200, trial.pending_status())
                if self.path == '/api/pending/remind':
                    from pending import remind_once
                    result = remind_once(trial.pending_store, trial.desktop)
                    return self.send(200, {**trial.pending_status(), 'reminder_result': result})
                if self.path == '/api/startup/enable':
                    trial.desktop.enable()
                    return self.send(200, trial.pending_status())
                if self.path == '/api/startup/disable':
                    trial.desktop.disable()
                    return self.send(200, trial.pending_status())
                if self.path == '/api/windows/diagnose':
                    return self.send(200, trial.desktop.diagnose())
                if not isinstance(data.get('device'), str):
                    raise ValueError('이 브라우저를 먼저 연결해 주세요.')
                if self.path == '/api/test':
                    return self.send(200, dict(job=trial.schedule(data['device'], data.get('kind')), delay=30))
                if self.path == '/api/disconnect':
                    trial.disconnect(data['device'])
                    return self.send(200, {'ok': True})
                self.send(404, {'error': '없는 페이지입니다.'})
            except (ValueError, TypeError, UnicodeError, RuntimeError, OSError) as exc:
                message = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else '요청을 처리하지 못했습니다. 설정과 실행 상태를 확인해 주세요.'
                self.send(400, {'error': message})

    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=18110)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--data-dir', type=Path, default=ROOT / '.local-test-data')
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('1024~65535 포트를 사용해 주세요.')
    trial = Trial(args.data_dir)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler(trial))
    server.daemon_threads = True
    stop = threading.Event()

    def work():
        while not stop.wait(.5):
            trial.deliver_due()

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    print(f'\n로컬 PC 알림 테스트: http://127.0.0.1:{args.port}\n'
          'NAS에는 연결하지 않습니다. 가상 알림만 발송합니다.\n'
          '브라우저를 닫아도 이 실행 창은 켜 두세요. 종료: Ctrl+C\n', flush=True)
    if not args.no_browser:
        webbrowser.open(f'http://127.0.0.1:{args.port}/')
    try:
        server.serve_forever(poll_interval=.5)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()
        worker.join(timeout=12)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ImportError) as exc:
        print('테스트를 실행하지 못했습니다. 설치 상태와 포트 사용 여부를 확인해 주세요.\n' + str(exc))
        raise SystemExit(1)
