"""NAS and PC share the full application; fake identities never activate on NAS."""
import unittest,os,subprocess,sys,json
from pathlib import Path
from tempfile import TemporaryDirectory
from io import BytesIO
from zipfile import ZipFile
from unittest.mock import patch
from django.conf import settings
if not settings.INTEGRATED_PURCHASES:raise unittest.SkipTest('Full application only.')
from django.test import TestCase,SimpleTestCase,override_settings
from django.urls import reverse
from workflow.models import ApprovalRule,RANKS
from . import test_departments as fixtures
from .forms import RequestForm
from .services import request_action
from workflow.backup_files import add_files,verify_files,install_files

class FullApplicationTests(TestCase):
    @classmethod
    def setUpTestData(cls):fixtures.DepartmentPurchaseTests.setUpTestData.__func__(cls)
    user=fixtures.DepartmentPurchaseTests.user
    as_user=fixtures.DepartmentPurchaseTests.as_user
    create=fixtures.DepartmentPurchaseTests.create
    def test_original_departments_and_selectors_are_available_without_conflicting_notes(self):
        self.as_user('quality');r=self.client.get(reverse('purchasing:new'),follow=True)
        for label in ['검토자 부서','결재선 지정']:self.assertContains(r,label)
        self.assertNotContains(r,'이 직급은 규정에 따라 본인 전결로 내부 결재를 완료합니다.')
        self.assertContains(r,'data-department-picker');self.assertNotContains(r,'name="purchase-approver"')
    def test_cross_department_internal_approval_keeps_author_department_checker(self):
        d=self.create('quality','review',reviewer=self.user('dev_lead'),approver=self.user('prod_director'))
        self.assertEqual(d.purchase_checker,self.user('prod_director'))
        request_action(d.pk,self.user('dev_lead'),'forward',new_person=self.user('prod_director'));d=request_action(d.pk,self.user('prod_director'),'approve')
        self.assertEqual(d.confirmation_method,'with_approval')
    def test_development_request_with_other_department_approver_still_requires_dev_checker(self):
        d=self.create('dev_manager','review',reviewer=self.user('quality_lead'),approver=self.user('prod_director'))
        request_action(d.pk,self.user('quality_lead'),'forward',new_person=self.user('prod_director'));d=request_action(d.pk,self.user('prod_director'),'approve')
        self.assertEqual(d.purchase_checker,self.user('dev_director'));self.assertIsNone(d.confirmed_at)
    def test_original_common_rules_remain_editable_and_full_editor_is_kept(self):
        r=ApprovalRule.objects.create(name='기존 공통 규정',kind='all',enabled=False,reviewer_ranks=RANKS[1:],approver_ranks=RANKS[1:])
        self.as_user('admin');response=self.client.get(reverse('rule_edit',args=[r.pk]));self.assertEqual(response.status_code,200)
        self.assertContains(response,'기존 공통 규정');self.assertContains(response,'id="rule-simulator"')
        self.assertContains(self.client.get('/regulations/?tab=delegation'),'name="amount_over"')
    def test_all_original_management_pages_remain_accessible(self):
        u=self.user('admin');u.profile.manage_leave=True;u.profile.view_accounting=True;u.profile.procure=True;u.profile.save();self.as_user('admin')
        for url in ['/balances/','/company-holidays/','/backups/','/staff/','/calendar/','/welfare/','/regulations/?tab=annual','/regulations/?tab=benefits','/regulations/?tab=awards','/regulations/?tab=delegation','/documents/?mode=all']:
            self.assertEqual(self.client.get(url).status_code,200,url)
    def test_production_has_same_application_and_no_fake_switcher(self):
        with TemporaryDirectory() as folder:
            env={**os.environ,'APPROVAL_PRODUCTION':'1','DJANGO_DEBUG':'0','DJANGO_SECRET_KEY':'settings-parity-only-'+'x'*64,'DJANGO_ALLOWED_HOSTS':'localhost','DB_ENGINE':'mariadb','DB_NAME':'unconnected','DB_USER':'unconnected','DB_PASSWORD':'not-real','APPROVAL_DATA_DIR':folder,'APPROVAL_LOCAL_DEMO':'1','APPROVAL_PURCHASE_LAB':'1','APPROVAL_INTEGRATED_PURCHASES':'1'}
            code="import approval_site.settings as s; assert s.INTEGRATED_PURCHASES; assert 'purchasing' in s.INSTALLED_APPS; assert not s.LOCAL_DEMO_ENABLED; assert not s.PURCHASE_LAB_ENABLED; assert s.MIDDLEWARE[-1]=='workflow.middleware.AccountGateMiddleware'; assert s.SESSION_COOKIE_NAME=='xenosys_approval_sessionid'"
            r=subprocess.run([sys.executable,'-c',code],cwd=settings.BASE_DIR,env=env,capture_output=True,text=True);self.assertEqual(r.returncode,0,r.stderr)

class PrivateBackupTests(SimpleTestCase):
    def test_private_files_roundtrip_with_checksums(self):
        with TemporaryDirectory() as folder:
            root=Path(folder);data=root/'data';f=data/'purchase-attachments/1'/(32*'a'+'.pdf');f.parent.mkdir(parents=True);f.write_bytes(b'%PDF quote')
            archive=BytesIO()
            with override_settings(DATA_DIR=data):
                with ZipFile(archive,'w') as z:files=add_files(z)
                stage=root/'staging'
                with ZipFile(archive) as z:verify_files(z,dict(files=files),stage)
                f.unlink();install_files(stage);self.assertEqual(f.read_bytes(),b'%PDF quote')
    def test_tampering_and_traversal_are_rejected(self):
        for name,digest in [('../escape.pdf','x'),('1/valid.pdf','incorrect')]:
            archive=BytesIO()
            with ZipFile(archive,'w') as z:z.writestr('attachments/'+name,b'pdf')
            with TemporaryDirectory() as folder,ZipFile(archive) as z:
                with self.assertRaises(ValueError):verify_files(z,dict(files={name:dict(size=3,sha256=digest)}),Path(folder))
    def test_unlisted_extra_file_is_rejected(self):
        archive=BytesIO()
        with ZipFile(archive,'w') as z:z.writestr('attachments/1/extra.pdf',b'pdf')
        with TemporaryDirectory() as folder,ZipFile(archive) as z:
            with self.assertRaises(ValueError):verify_files(z,{},Path(folder))
