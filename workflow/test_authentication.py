"""Authentication regressions with real CSRF checks and NAS HTTPS headers."""
import re

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings

from .models import Profile


ORIGIN = 'https://xenonas.synology.me:18443'
HEADERS = {
    'HTTP_HOST': 'xenonas.synology.me:18443',
    'HTTP_X_FORWARDED_PROTO': 'https',
    'HTTP_ORIGIN': ORIGIN,
    'HTTP_REFERER': ORIGIN + '/login/',
}


@override_settings(
    ALLOWED_HOSTS=['xenonas.synology.me'],
    CSRF_TRUSTED_ORIGINS=[ORIGIN],
    SESSION_COOKIE_SECURE=True,
    CSRF_COOKIE_SECURE=True,
    SECURE_SSL_REDIRECT=True,
    SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO', 'https'),
)
class AuthenticationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            'auth-check', password='auth-regression-only', first_name='시험 직원')
        Profile.objects.create(user=cls.user, department='개발팀', rank='대리', approved=True)

    def setUp(self):
        self.browser = Client(enforce_csrf_checks=True)

    def get(self, path):
        return self.browser.get(path, **HEADERS)

    def token(self, response):
        match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', response.content.decode())
        self.assertIsNotNone(match)
        return match.group(1)

    def login(self, token):
        return self.browser.post('/login/', {
            'username': 'auth-check', 'password': 'auth-regression-only',
            'csrfmiddlewaretoken': token,
        }, **HEADERS)

    def assert_not_stored(self, response):
        cache = response.headers.get('Cache-Control', '')
        self.assertIn('no-store', cache)
        self.assertIn('private', cache)

    def test_repeated_https_login_logout_and_login(self):
        for _ in range(4):
            response = self.login(self.token(self.get('/login/')))
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response['Location'], '/')
            home = self.get('/')
            self.assertEqual(home.status_code, 200)
            self.assertTrue(self.browser.cookies[settings.SESSION_COOKIE_NAME]['secure'])
            logout = self.browser.post('/logout/', {
                'csrfmiddlewaretoken': self.token(home),
            }, **HEADERS)
            self.assertEqual(logout.status_code, 302)
            self.assertEqual(logout['Location'], '/login/')

    def test_login_redirect_logout_and_form_pages_are_not_cached(self):
        login_page = self.get('/login/')
        self.assert_not_stored(login_page)
        self.assert_not_stored(self.login(self.token(login_page)))
        home = self.get('/')
        self.assert_not_stored(home)
        self.assert_not_stored(self.get('/compose/'))
        self.assert_not_stored(self.browser.post('/logout/', {
            'csrfmiddlewaretoken': self.token(home),
        }, **HEADERS))

    def test_another_django_apps_default_cookies_do_not_break_this_login(self):
        token = self.token(self.get('/login/'))
        # Cookies are shared across ports on a host. Another app may set these.
        self.browser.cookies['csrftoken'] = 'F' * 32
        self.browser.cookies['sessionid'] = 'other-app-session'
        self.assertEqual(self.login(token).status_code, 302)
        self.browser.cookies['sessionid'] = 'other-app-session-after-login'
        self.assertEqual(self.get('/').status_code, 200)

    def test_old_login_token_is_rejected_and_can_be_refreshed_safely(self):
        original = self.token(self.get('/login/'))
        self.assertEqual(self.login(original).status_code, 302)
        home = self.get('/')
        self.assertEqual(self.browser.post('/logout/', {
            'csrfmiddlewaretoken': self.token(home),
        }, **HEADERS).status_code, 302)
        # The first login rotated the secret. A saved login form is now stale.
        self.assertEqual(self.login(original).status_code, 403)
        self.assertNotIn('_auth_user_id', self.browser.session)
        fresh = self.get('/login/csrf/')
        self.assertEqual(fresh.status_code, 200)
        self.assert_not_stored(fresh)
        self.assertEqual(self.login(fresh.json()['token']).status_code, 302)

    def test_invalid_origin_is_still_rejected_with_a_fresh_token(self):
        token = self.token(self.get('/login/'))
        headers = dict(HEADERS, HTTP_ORIGIN='https://untrusted.example')
        response = self.browser.post('/login/', {
            'username': 'auth-check', 'password': 'auth-regression-only',
            'csrfmiddlewaretoken': token,
        }, **headers)
        self.assertEqual(response.status_code, 403)
        self.assertNotIn('_auth_user_id', self.browser.session)

    def test_missing_token_is_still_rejected(self):
        self.get('/login/')
        response = self.browser.post('/login/', {
            'username': 'auth-check', 'password': 'auth-regression-only',
        }, **HEADERS)
        self.assertEqual(response.status_code, 403)
        self.assertNotIn('_auth_user_id', self.browser.session)

    def test_refresh_is_read_only_and_returns_no_account_or_session_data(self):
        response = self.get('/login/csrf/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json()), {'token'})
        self.assertEqual(len(response.json()['token']), 64)
        self.assertNotIn('Access-Control-Allow-Origin', response.headers)
        self.assertTrue(response.cookies[settings.CSRF_COOKIE_NAME]['secure'])
        self.assertEqual(response.cookies[settings.CSRF_COOKIE_NAME]['samesite'], 'Lax')
        post = self.browser.post('/login/csrf/', {
            'csrfmiddlewaretoken': response.json()['token'],
        }, **HEADERS)
        self.assertEqual(post.status_code, 405)
        self.assertNotIn('_auth_user_id', self.browser.session)

    def test_wrong_password_does_not_log_in_after_token_refresh(self):
        token = self.get('/login/csrf/').json()['token']
        response = self.browser.post('/login/', {
            'username': 'auth-check', 'password': 'wrong-password',
            'csrfmiddlewaretoken': token,
        }, **HEADERS)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '아이디 또는 비밀번호를 확인해 주세요.')
        self.assertNotIn('_auth_user_id', self.browser.session)
        self.assert_not_stored(response)

    def test_token_refresh_does_not_bypass_account_approval_or_password_gate(self):
        self.browser.force_login(self.user)
        for values, destination in [
            ({'approved': False, 'must_change_password': False}, '/pending/'),
            ({'approved': True, 'must_change_password': True}, '/password/'),
        ]:
            Profile.objects.filter(user=self.user).update(**values)
            self.assertEqual(self.get('/login/csrf/').status_code, 200)
            home = self.get('/')
            self.assertEqual(home.status_code, 302)
            self.assertEqual(home['Location'], destination)
