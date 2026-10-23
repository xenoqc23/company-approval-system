"""Seed only a new, explicitly isolated integrated local database."""
from pathlib import Path
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand,CommandError
from django.db import transaction
from django.utils import timezone
from workflow.models import Profile,AnnualBalance,ApprovalRule,ApprovalFlowPolicy,CompanyHolidayLock
from purchasing.models import DemoAccount

class Command(BaseCommand):
    def add_arguments(self,parser):parser.add_argument('--password-file')
    @transaction.atomic
    def handle(self,*args,**options):
        if not settings.INTEGRATED_PURCHASES or settings.PRODUCTION or settings.DATA_DIR.name!='purchase-test':raise CommandError('통합 로컬 테스트에서만 실행할 수 있습니다.')
        marker=settings.DATA_DIR/'.integrated-lab'
        existing=DemoAccount.objects.exists()
        if existing and not marker.exists():raise CommandError('다른 테스트 데이터와 합치지 않습니다. 새 폴더에서 실행해 주세요.')
        call_command('seed_purchase_demo',**({'password_file':Path(options['password_file'])} if options['password_file'] else {}))
        if existing:return
        CompanyHolidayLock.objects.get_or_create(pk=1)
        for a in DemoAccount.objects.select_related('user','user__profile'):
            u=a.user
            if u.profile.is_representative:continue
            u.profile.manage_leave=u.username in ['p_admin','p_finance']
            u.profile.view_accounting=u.username=='p_finance'
            u.profile.procure=u.username=='p_finance'
            u.profile.save()
            AnnualBalance.objects.get_or_create(user=u,year=timezone.localdate().year,defaults=dict(total=16,used=0,grant_initialized=True,total_manual=True))
        p,_=ApprovalFlowPolicy.objects.get_or_create(pk=1);p.enabled=True;p.save()
        r=ApprovalRule.objects.create(name='휴가원 기본 규정',kind='leave',enabled=True,reviewer_ranks=['주임','대리','과장','팀장','부장','이사'],approver_ranks=['주임','대리','과장','팀장','부장','이사'],allow_skip_review=True,allow_self_approval=True,allow_review_final=True,allow_representative_direct=True)
        r.review_final_users.set(Profile.objects.filter(rank__in=['과장','팀장','부장','이사']).exclude(user__username='p_admin').values_list('user_id',flat=True))
        marker.write_text('integrated-local-fictional-v1')
        self.stdout.write('기존 사내결재 화면 + 새 구매요청 통합 준비 완료. 문서는 빈 상태이며 가상 연차만 부여했습니다.')
