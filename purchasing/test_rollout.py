import unittest
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from django.conf import settings
if not settings.INTEGRATED_PURCHASES:raise unittest.SkipTest('Integrated purchases only.')
from django.test import TestCase,override_settings
from django.core.management import call_command,CommandError
from django.contrib.auth import get_user_model
from workflow.models import Document,AnnualBalance,Profile
from workflow import rollout
from . import test_integrated as fixtures
from .models import PurchasePolicy


class RolloutTests(TestCase):
    setUpTestData=classmethod(fixtures.IntegratedTests.setUpTestData.__func__)
    user=fixtures.IntegratedTests.user
    create=fixtures.IntegratedTests.create

    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.override=override_settings(DATA_DIR=Path(self.temp.name),PURCHASE_LAB_ENABLED=False)
        self.override.enable();self.addCleanup(self.override.disable)
        self.options=dict(development_checker='username:p_dev_director',other_checker='username:p_prod_director',
            purchaser='username:p_finance',representative='username:p_ceo',operator='p_admin')
        self.path=Path(self.temp.name)/'nas-purchase-update-plan.json'

    def run_step(self, mode, **kwargs):
        call_command('prepare_purchase_update',**{mode:True},stdout=StringIO(),**kwargs)

    def prepare(self):
        self.run_step('check',**self.options);self.run_step('capture')

    def test_readonly_preflight_preserves_accounts_and_apply_only_named_roles(self):
        AnnualBalance.objects.create(user=self.user('quality'),year=2026,total=16,used=3)
        before=list(get_user_model().objects.values());profiles=list(Profile.objects.values())
        self.prepare();self.run_step('verify');self.run_step('apply')
        self.assertEqual(list(get_user_model().objects.values()),before);self.assertEqual(list(Profile.objects.values()),profiles)
        p=PurchasePolicy.objects.get(pk=1);self.assertTrue(p.enabled);self.assertTrue(p.combine_confirmation)
        self.assertEqual(p.dev_director,self.user('dev_director'));self.assertEqual(list(p.finance.all()),[self.user('finance')])
        self.assertEqual(AnnualBalance.objects.get().used,3)
        self.assertEqual(self.path.stat().st_mode & 0o777,0o600)
        with self.assertRaises(CommandError):self.run_step('apply')

    def test_missing_ambiguous_wrong_department_or_unregistered_rep_never_create_accounts(self):
        count=get_user_model().objects.count()
        for changed in [{'purchaser':'없는직원'},{'development_checker':'username:p_prod_director'},
                        {'representative':'username:p_finance'}]:
            with self.assertRaises(CommandError):self.run_step('check',**{**self.options,**changed})
        duplicate=get_user_model().objects.create_user('duplicate',first_name=self.user('dev_director').first_name)
        with self.assertRaises(CommandError):self.run_step('check',**{**self.options,'development_checker':duplicate.first_name})
        self.assertEqual(get_user_model().objects.count(),count+1)

    def test_pending_self_approval_blocks_before_db_changes(self):
        d=Document.objects.create(owner=self.user('quality'),reviewer=self.user('quality'),status='review')
        with self.assertRaisesMessage(CommandError,'본인이 검토'):self.run_step('check',**self.options)
        d.refresh_from_db();self.assertEqual(d.status,'review');self.assertFalse(self.path.exists())

    def test_data_attachment_and_staff_changes_stop_rollout(self):
        self.prepare()
        get_user_model().objects.filter(pk=self.user('quality').pk).update(first_name='변경된 이름')
        with self.assertRaisesMessage(CommandError,'보존 비교 실패'):self.run_step('verify')
        self.run_step('check',**self.options);self.run_step('capture')
        folder=Path(self.temp.name)/'purchase-attachments';folder.mkdir();(folder/'new.txt').write_text('changed')
        with self.assertRaisesMessage(CommandError,'첨부파일'):self.run_step('apply')
        self.run_step('check',**self.options);self.run_step('capture')
        Profile.objects.filter(user=self.user('finance')).update(rank='과장')
        with self.assertRaisesMessage(CommandError,'직원 정보'):self.run_step('verify')

    def test_existing_purchase_handover_is_blocked_before_shutdown(self):
        fixtures.IntegratedTests.confirmed(self)
        with self.assertRaisesMessage(CommandError,'인계'):
            self.run_step('check',**{**self.options,'purchaser':'username:p_quality_manager'})
        self.assertFalse(self.path.exists())

    def test_policy_change_stops_and_current_roles_can_be_retained(self):
        self.prepare();PurchasePolicy.objects.filter(pk=1).update(version=8)
        with self.assertRaisesMessage(CommandError,'규정이 변경'):self.run_step('apply')
        self.run_step('check',operator='p_admin')
        self.assertEqual(rollout.read_plan(self.path)['ids']['purchaser'],self.user('finance').pk)
