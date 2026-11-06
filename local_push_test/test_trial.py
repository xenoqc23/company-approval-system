import base64
import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import Mock,patch
from http.server import ThreadingHTTPServer
from server import Trial,handler,validate_subscription


def subscription(suffix='one'):
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    point=ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)
    enc=lambda b:base64.urlsafe_b64encode(b).rstrip(b'=').decode()
    return dict(endpoint='https://fcm.googleapis.com/fcm/send/local-trial-'+suffix,
                keys=dict(p256dh=enc(point),auth=enc(b'0123456789abcdef')))


class TrialTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.now=1000
        self.trial=Trial(Path(self.temp.name),clock=lambda:self.now)

    def test_valid_chrome_edge_providers_and_reject_private_network_or_invalid_keys(self):
        data=subscription()
        self.assertEqual(validate_subscription(data),data)
        data['endpoint']='https://wns2-test.notify.windows.com/w/?token=example'
        self.assertEqual(validate_subscription(data),data)
        for endpoint in ['http://fcm.googleapis.com/a','https://127.0.0.1/a','https://fcm.googleapis.com.evil.test/a',
                         'https://a.notify.windows.com.evil.test/a','https://fcm.googleapis.com:8443/a',
                         'https://user@fcm.googleapis.com/a','https://localhost/a']:
            with self.subTest(endpoint=endpoint),self.assertRaises(ValueError):
                validate_subscription({**data,'endpoint':endpoint})
        with self.assertRaises(ValueError):validate_subscription({**data,'keys':{'p256dh':'bad','auth':'bad'}})

    def test_delayed_delivery_is_device_scoped_rate_limited_and_only_once(self):
        first=self.trial.connect(subscription('chrome'));second=self.trial.connect(subscription('edge'))
        self.trial.schedule(first,'request')
        sender=Mock();self.assertEqual(self.trial.deliver_due(sender),0);sender.assert_not_called()
        with self.assertRaises(ValueError):self.trial.schedule(first,'completed')
        self.now+=30;self.assertEqual(self.trial.deliver_due(sender),1);sender.assert_called_once()
        self.assertEqual(json.loads(sender.call_args.kwargs['data'])['kind'],'request')
        self.assertEqual(self.trial.status(first)['last_delivery']['status'],'sent')
        self.assertIsNone(self.trial.status(second)['last_delivery'])
        self.assertEqual(self.trial.deliver_due(sender),0)
        self.trial.schedule(second,'completed');self.now+=30;self.trial.deliver_due(sender)
        self.assertEqual(json.loads(sender.call_args.kwargs['data'])['kind'],'completed')

    def test_disconnect_cancels_queued_test(self):
        device=self.trial.connect(subscription());self.trial.schedule(device,'request');self.trial.disconnect(device)
        self.now+=40;sender=Mock();self.trial.deliver_due(sender);sender.assert_not_called()
        self.assertFalse(self.trial.status(device)['connected'])
        self.assertEqual(self.trial.status(device)['last_delivery']['status'],'cancelled')

    def test_sender_failure_never_exposes_endpoints_or_claims_pc_received(self):
        device=self.trial.connect(subscription());self.trial.schedule(device,'request');self.now+=30
        self.trial.deliver_due(Mock(side_effect=RuntimeError('sensitive endpoint key details')))
        result=self.trial.status(device)
        self.assertEqual(result['last_delivery']['status'],'failed')
        self.assertNotIn('sensitive',json.dumps(result));self.assertNotIn('fcm.googleapis',json.dumps(result))

    def test_key_is_preserved_and_browser_reconnect_does_not_cancel_existing_job(self):
        another=Trial(self.temp.name);self.assertEqual(another.public_key,self.trial.public_key)
        device=self.trial.connect(subscription());self.trial.schedule(device,'completed')
        data=self.trial.devices[device]
        self.assertEqual(self.trial.connect(data),device)
        self.assertEqual(self.trial.status(device)['last_delivery']['status'],'pending')
        self.assertEqual(len(list(Path(self.temp.name).rglob('*'))),1)

    def test_actual_webpush_encrypts_payload_with_this_test_key(self):
        import http_ece
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization
        key=ec.generate_private_key(ec.SECP256R1());auth=b'0123456789abcdef'
        point=key.public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)
        enc=lambda b:base64.urlsafe_b64encode(b).rstrip(b'=').decode()
        data=subscription();data['keys']=dict(p256dh=enc(point),auth=enc(auth))
        device=self.trial.connect(data);self.trial.schedule(device,'request');self.now+=30
        with patch('requests.post',return_value=Mock(status_code=201)) as transport:
            self.trial.deliver_due()
        encrypted=transport.call_args.kwargs['data']
        decoded=json.loads(http_ece.decrypt(encrypted,private_key=key,auth_secret=auth,version='aes128gcm'))
        self.assertEqual(decoded['kind'],'request');self.assertIn('홍길동',decoded['body'])
        self.assertIn('vapid ',transport.call_args.kwargs['headers']['Authorization'])


class LocalHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.trial=Trial(self.temp.name)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),handler(self.trial))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.close)
        self.port=self.server.server_address[1]

    def close(self):
        self.server.shutdown();self.server.server_close();self.thread.join(timeout=3)

    def request(self,path,data=None,headers=None):
        conn=HTTPConnection('127.0.0.1',self.port,timeout=5)
        defaults={'Origin':f'http://127.0.0.1:{self.port}'}
        if data is not None:defaults.update({'Content-Type':'application/json','X-Local-Test-Token':self.trial.token})
        defaults.update(headers or {})
        conn.request('POST' if data is not None else 'GET',path,json.dumps(data) if data is not None else None,defaults)
        response=conn.getresponse();status=response.status;body=response.read();conn.close()
        return status,json.loads(body) if body.startswith(b'{') else body

    def test_browser_connect_queue_status_and_disconnect_without_application_data(self):
        status,config=self.request('/api/config');self.assertEqual(status,200)
        self.assertEqual(set(config),{'public_key','token','delay'})
        status,connected=self.request('/api/connect',{'subscription':subscription()});self.assertEqual(status,200)
        device=connected['device']
        self.assertEqual(self.request('/api/test',{'device':device,'kind':'completed'})[0],200)
        status,result=self.request('/api/status?device='+device)
        self.assertEqual(result['last_delivery']['status'],'pending')
        self.assertNotIn('endpoint',json.dumps(result))
        self.assertEqual(self.request('/api/disconnect',{'device':device})[0],200)
        self.assertEqual(self.request('/api/status?device='+device)[1]['last_delivery']['status'],'cancelled')

    def test_cross_site_wrong_host_and_missing_token_cannot_send(self):
        data={'subscription':subscription()}
        for headers in [{'Origin':'https://untrusted.example'}, {'Host':'untrusted.example'}, {'X-Local-Test-Token':''}]:
            self.assertEqual(self.request('/api/connect',data,headers)[0],403)
        self.assertEqual(self.request('/api/config',headers={'Host':'untrusted.example'})[0],403)
        self.assertEqual(self.request('/api/connect',{'subscription':None})[0],400)
        self.assertEqual(self.request('/../.local-test-data/local-test-vapid.pem')[0],404)

    def test_persistent_pending_routes_and_explicit_startup_controls(self):
        desktop=Mock();enabled={'value':False}
        desktop.status.side_effect=lambda:dict(supported=True,enabled=enabled['value'],message='테스트 상태')
        desktop.enable.side_effect=lambda:enabled.update(value=True)
        desktop.disable.side_effect=lambda:enabled.update(value=False)
        self.trial.desktop=desktop
        status,result=self.request('/api/pending/create',{})
        self.assertEqual(status,200);self.assertEqual(result['pending_count'],2)
        desktop.enable.assert_not_called();desktop.notify.assert_not_called()
        self.assertEqual(self.request('/api/startup/enable',{},headers={'X-Local-Test-Token':''})[0],403)
        desktop.enable.assert_not_called()
        status,result=self.request('/api/startup/enable',{})
        self.assertTrue(result['startup']['enabled']);desktop.enable.assert_called_once()
        status,result=self.request('/api/pending/remind',{})
        self.assertEqual(result['reminder_result']['result'],'requested');desktop.notify.assert_called_once()
        self.assertEqual(self.request('/api/pending/complete',{'document':'trial-leave'})[1]['pending_count'],1)
        from server import Trial
        reopened=Trial(self.temp.name)
        self.assertEqual(reopened.pending_store.status()['pending_count'],1)
        self.assertEqual(self.request('/api/startup/disable',{})[1]['startup']['enabled'],False)
        self.assertEqual(self.request('/api/pending/complete',{'document':'missing'})[0],400)


if __name__=='__main__':unittest.main()
