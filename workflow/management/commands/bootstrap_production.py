from pathlib import Path
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from workflow.models import AnnualPolicy, Profile
from workflow.policy_defaults import PRODUCTION_POLICY


class Command(BaseCommand):
    help = '빈 운영 DB에 관리자만 생성합니다. 기존 계정과 규정을 변경하지 않습니다.'

    def add_arguments(self, parser):
        parser.add_argument('--password-file', required=True)

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.PRODUCTION:
            raise CommandError('운영 모드에서만 실행할 수 있습니다.')
        User = get_user_model()
        if User.objects.exists():
            self.stdout.write('기존 계정이 있어 초기화를 생략했습니다.')
            return
        password = Path(options['password_file']).read_text().strip()
        if len(password) < 12:
            raise CommandError('초기 관리자 비밀번호는 12자 이상이어야 합니다.')
        admin = User.objects.create_user(username='admin', first_name='관리자', password=password)
        Profile.objects.create(user=admin, department='전략기획팀', rank='이사',
                               approved=True, manage_system=True, must_change_password=True)
        # No sample people, documents, balances, or dated demo policy prose.
        policy = AnnualPolicy.objects.first()
        if policy and not policy.text:
            policy.text = PRODUCTION_POLICY
            policy.save(update_fields=['text'])
        self.stdout.write('운영 관리자 생성 완료. 최초 로그인에서 비밀번호를 변경해 주세요.')
