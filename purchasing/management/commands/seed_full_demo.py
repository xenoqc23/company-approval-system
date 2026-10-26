"""Only seed the separately marked PC test; production uses normal bootstrap."""
from pathlib import Path
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand,CommandError
from django.db import transaction
from django.contrib.auth import get_user_model
from purchasing.models import DemoAccount

class Command(BaseCommand):
    def add_arguments(self,parser):parser.add_argument('--password-file')
    @transaction.atomic
    def handle(self,*args,**options):
        if settings.PRODUCTION or not settings.LOCAL_DEMO_ENABLED or settings.DATA_DIR.name!='purchase-test' or settings.DATA_DIR.parent.name not in ['full-nas-test','full-nas-test-v2','full-nas-test-v3','full-nas-test-v4','full-nas-test-v5','full-nas-test-v6']:raise CommandError('별도 full-nas-test 로컬 데이터에서만 가상 직원을 만듭니다.')
        marker=settings.DATA_DIR/'.full-local'
        if DemoAccount.objects.exists():
            if not marker.exists():raise CommandError('기존 데이터는 사용하지 않습니다. 새 폴더에서 실행해 주세요.')
            self.stdout.write('기존 가상 직원과 테스트 데이터를 유지합니다.');return
        call_command('seed_integrated_demo',**({'password_file':options['password_file']} if options['password_file'] else {}))
        root=get_user_model().objects.get(username='p_admin');root.username='admin';root.save(update_fields=['username'])
        root.profile.view_accounting=True;root.profile.procure=True;root.profile.save(update_fields=['view_accounting','procure'])
        marker.write_text('full-local-fictional-v1')
        self.stdout.write('전체 기능 로컬 테스트 준비 완료. admin / 직접 정한 공통 비밀번호로 로그인하세요.')
