from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand,CommandError
from workflow.models import ApprovalRule,ApprovalFlowPolicy

class Command(BaseCommand):
    help='Enable reviewer final approval only for the isolated PC notification demo.'
    def handle(self,*args,**options):
        if settings.PRODUCTION or settings.DATA_DIR.name!='notification-test' or settings.DATABASES['default']['ENGINE']!='django.db.backends.sqlite3':
            raise CommandError('알림 전용 로컬 테스트 DB에서만 사용할 수 있습니다.')
        person=get_user_model().objects.filter(username='reviewer',first_name='김민준').first()
        if not person:raise CommandError('가상 직원 seed_demo를 먼저 실행해 주세요.')
        ApprovalFlowPolicy.objects.update_or_create(pk=1,defaults={'enabled':True})
        rule,_=ApprovalRule.objects.get_or_create(name='로컬 알림 테스트 전결',defaults=dict(kind='all',enabled=True,allow_review_final=True,
            reviewer_ranks=['팀장','부장','이사'],approver_ranks=['팀장','부장','이사']))
        rule.review_final_users.add(person)
        self.stdout.write('가상 검토자 전결 테스트 준비 완료.')
