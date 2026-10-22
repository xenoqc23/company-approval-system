"""Create fictional purchase-only accounts on an empty isolated local database."""
from pathlib import Path
from getpass import getpass
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand,CommandError
from django.db import transaction
from workflow.models import Profile
from purchasing.models import DemoAccount,PurchasePolicy,PurchasePermission

ACCOUNTS=[
 ('p_admin','가상관리자','인사팀','이사','관리자 · 구매 규정 설정'),
 ('p_dev','가상개발직원','개발팀','대리','개발팀 직원 · 요청 작성'),
 ('p_dev_lead','가상개발팀장','개발팀','팀장','개발팀 팀장 · 중간 승인 테스트'),
 ('p_dev_director','가상개발이사','개발팀','이사','개발팀 이사 · 개발팀 최종승인'),
 ('p_quality','가상품질직원','품질팀','사원','품질팀 직원 · 검토·승인 경로'),
 ('p_quality_manager','가상품질과장','품질팀','과장','품질팀 과장 · 검토 / 이사에게 직접 요청'),
 ('p_quality_lead','가상품질팀장','품질팀','팀장','품질팀 팀장 · 중간 승인'),
 ('p_sales_manager','가상영업부장','영업팀','부장','영업팀 부장 · 생산팀 이사에게 직접 요청'),
 ('p_prod_director','가상생산이사','생산팀','이사','생산팀 이사 · 그 외 부서 최종승인'),
 ('p_finance','가상경리','인사팀','대리','경리 · 품목 선택·취합·구매 진행'),
 ('p_ceo','가상대표','대표이사실','대표','대표 · 품목별 구매승인'),
]


class Command(BaseCommand):
    def add_arguments(self,parser):parser.add_argument('--password-file',type=Path)
    @transaction.atomic
    def handle(self,*args,**options):
        if not settings.PURCHASE_LAB_ENABLED or settings.PRODUCTION or settings.DATA_DIR.name!='purchase-test':
            raise CommandError('별도 purchase-test 로컬 데이터에서만 실행할 수 있습니다.')
        if DemoAccount.objects.exists():
            self.stdout.write('기존 가상 직원·비밀번호·구매요청·규정을 유지합니다. 초기화하지 않았습니다.')
            return
        if get_user_model().objects.exists():raise CommandError('기존 직원이 있는 데이터베이스에는 가상 계정을 만들지 않습니다.')
        password=options['password_file'].read_text().rstrip('\r\n') if options['password_file'] else getpass('가상 계정의 공통 테스트 비밀번호를 정해 주세요 (4자 이상): ')
        if len(password)<4:raise CommandError('테스트 비밀번호를 4자 이상 입력해 주세요.')
        people={}
        for position,(username,name,dept,rank,label) in enumerate(ACCOUNTS):
            user=get_user_model().objects.create_user(username,first_name=name,password=password)
            Profile.objects.create(user=user,department=dept,rank=rank,approved=True,
                manage_system=username=='p_admin',representative_slot=1 if username=='p_ceo' else None,
                representative_can_approve=username=='p_ceo')
            DemoAccount.objects.create(user=user,label=label,position=position);people[username]=user
        p,_=PurchasePolicy.objects.get_or_create(pk=1)
        p.enabled=True;p.dev_director=people['p_dev_director'];p.production_director=people['p_prod_director'];p.representative=people['p_ceo'];p.save()
        p.finance.set([people['p_finance']])
        PurchasePermission.objects.get_or_create(user=people['p_prod_director'],defaults={'view_completed':True})
        (settings.DATA_DIR/'.purchase-lab').write_text('purchase-lab-v1')
        self.stdout.write('구매 전용 가상 계정을 만들었습니다. 실제 직원·문서·연차는 사용하지 않습니다.')
        for username,_,_,_,label in ACCOUNTS:self.stdout.write(f'{username}: {label}')
