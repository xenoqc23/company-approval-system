from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from .models import Profile


@override_settings(SECURE_SSL_REDIRECT=False, SESSION_COOKIE_SECURE=True)
class RememberUsernameTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user=get_user_model().objects.create_user('saved-user',password='private-test-password')
        Profile.objects.create(user=user,approved=True,department='품질팀',rank='사원')

    def login(self,**extra):
        return self.client.post('/login/',{'username':'saved-user','password':'private-test-password',**extra})

    def test_cookie_stores_only_signed_username_and_native_password_autofill(self):
        response=self.login(remember_username='on')
        cookie=response.cookies['xenosys_saved_username']
        self.assertTrue(cookie['httponly']);self.assertTrue(cookie['secure']);self.assertEqual(cookie['samesite'],'Lax')
        self.assertNotIn('private-test-password',cookie.value)
        self.client.post('/logout/')
        response=self.client.get('/login/')
        self.assertContains(response,'value="saved-user"');self.assertContains(response,'autocomplete="current-password"')
        self.assertNotContains(response,'private-test-password')
        self.assertEqual(response.context['remember_username'],True)

    def test_unchecked_login_or_failed_attempt_clears_previous_cookie(self):
        self.login(remember_username='on');self.client.post('/logout/')
        response=self.login(password='bad')
        self.assertEqual(response.cookies['xenosys_saved_username']['max-age'],0)
        self.assertNotIn('_auth_user_id',self.client.session)
        response=self.login()
        self.assertEqual(response.cookies['xenosys_saved_username']['max-age'],0)

    def test_tampered_cookie_ignored_and_failed_login_never_saves_password(self):
        self.client.cookies['xenosys_saved_username']='forged'
        response=self.client.get('/login/');self.assertEqual(response.context['saved_username'],'')
        response=self.login(password='bad',remember_username='on')
        self.assertNotIn('xenosys_saved_username',response.cookies)
        self.assertNotContains(response,'value="bad"')
