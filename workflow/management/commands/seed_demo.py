from datetime import date, timedelta, time
from decimal import Decimal
from getpass import getpass
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from workflow.models import AnnualBalance, Document, Policy, Profile, Absence
from workflow.annual_grants import entitlement
from workflow.services import act_on_document, save_document


from workflow.policy_defaults import TENURE, POLICY


class Command(BaseCommand):
    help = '비어 있는 시안 DB에 가상 직원과 예시 문서를 생성합니다. 기존 DB는 덮어쓰지 않습니다.'

    def add_arguments(self, parser):
        parser.add_argument('--initial-password', help='예시 계정의 초기 비밀번호. 생략하면 안전하게 입력받습니다.')

    @transaction.atomic
    def handle(self, *args, **options):
        if settings.PRODUCTION:
            raise CommandError('운영 DB에는 예시 데이터를 생성할 수 없습니다.')
        User = get_user_model()
        if User.objects.exists():
            self.stdout.write('기존 계정이 있어 예시 데이터를 추가하지 않았습니다.')
            return
        password = options['initial_password'] or getpass('시안 계정 초기 비밀번호: ')
        if not password:
            raise CommandError('초기 비밀번호를 입력해 주세요.')
        try:
            validate_password(password)
        except ValidationError as exc:
            raise CommandError(' '.join(exc.messages)) from exc
        people = {}
        specs = [
            ('admin', '관리자', '전략기획팀', '이사', {'manage_system': True, 'must_change_password': True}),
            ('employee', '이서연', '개발팀', '대리', {}),
            ('reviewer', '김민준', '개발팀', '팀장', {}),
            ('approver', '박지훈', '전략기획팀', '이사', {}),
            ('accounting', '정유진', '인사팀', '과장', {'manage_leave': True, 'view_accounting': True, 'procure': True}),
            ('quality', '최하린', '품질팀', '주임', {}),
            ('production', '한도윤', '생산팀', '대리', {}),
            ('sales', '윤지호', '영업팀', '과장', {}),
        ]
        year = timezone.localdate().year
        demo_tenure = {'employee': 3, 'reviewer': 5, 'approver': 20, 'accounting': 10,
                       'quality': 1, 'production': 2, 'sales': 7}
        for username, name, department, rank, flags in specs:
            user = User.objects.create_user(username=username, first_name=name, password=password)
            hire = date(year-demo_tenure[username], 10, 15) if username != 'admin' else None
            Profile.objects.create(user=user, department=department, rank=rank, approved=True, hire_date=hire, **flags)
            AnnualBalance.objects.create(user=user, year=year, total=entitlement(hire, year) if hire else 0,
                                         used=2 if username == 'employee' else 1, grant_initialized=True)
            people[username] = user
        Policy.objects.create(tenure=TENURE, text=POLICY, updated_by=people['accounting'])
        owner, reviewer, approver = [people[x] for x in ['employee', 'reviewer', 'approver']]
        today = timezone.localdate()
        monday = today + timedelta(days=(7 - today.weekday()) % 7 or 7)
        Absence.objects.create(employee=people['sales'], reason='외근 (예시)', start_date=monday, end_date=monday,
                               all_day=False, start_time=time(9), end_time=time(12))

        def make(stage='review', **fields):
            doc_owner = fields.pop('owner', owner)
            doc = Document(owner=doc_owner, reviewer=fields.pop('reviewer', reviewer),
                           approver=fields.pop('approver', approver), recipient=fields.pop('recipient', doc_owner), **fields)
            if doc.kind == 'office' and doc.total_price <= 100000:
                doc.approver = doc.reviewer or doc_owner
            save_document(doc, doc_owner, submit=stage != 'draft')
            if stage in ['approve', 'approved'] and doc.review_required:
                doc = act_on_document(doc.pk, doc.reviewer, 'review')
            if stage == 'approved' and doc.kind != 'stock':
                doc = act_on_document(doc.pk, doc.approver, 'approve')
            return doc

        leave = {'kind': 'leave', 'leave_type': 'annual', 'start_date': monday + timedelta(days=4),
                 'end_date': monday + timedelta(days=4), 'reason': '개인 일정으로 연차를 신청합니다.'}
        make(**leave)
        make(stage='approve', kind='office', product='A4 복사용지', quantity=10, unit_price=6500,
             url='https://example.com/office/a4', urgency='urgent', reason='개발팀 공용 용지 재고가 부족합니다.')
        stock = make(stage='approved', kind='stock', product='제품 사용자 매뉴얼', quantity=100, unit_price=2500,
                     recipient=people['production'], reason='다음 생산 일정에 필요한 부족 재고를 발주 요청합니다.')
        act_on_document(stock.pk, people['accounting'], 'place')
        make(stage='approved', kind='leave', leave_type='am', start_date=monday + timedelta(days=1),
             end_date=monday + timedelta(days=1), start_time=time(9), end_time=time(12, 30), reason='병원 방문')
        office = make(stage='approved', kind='office', product='화이트보드 마커', quantity=12, unit_price=2200,
                      url='https://example.com/office/marker', reason='회의실 비품 구매')
        act_on_document(office.pk, people['accounting'], 'place')
        rejected = make(kind='leave', leave_type='annual', start_date=monday + timedelta(days=3),
                        end_date=monday + timedelta(days=3), reason='개인 일정')
        act_on_document(rejected.pk, reviewer, 'reject', '팀 일정 확인 후 다시 신청해 주세요.')
        make(stage='draft', kind='office', product='문서 보관 파일', quantity=5, unit_price=3200,
             url='https://example.com/office/file')
        make(owner=people['quality'], reviewer=owner, kind='office', product='품질 점검 노트',
             quantity=3, unit_price=5000, url='https://example.com/office/notebook')
        make(stage='approve', owner=people['production'], approver=owner, kind='stock',
             product='제품 보관함', quantity=20, unit_price=12000)
        self.stdout.write(self.style.SUCCESS('가상 직원 8명과 예시 기안 9건을 생성했습니다. admin은 첫 로그인 시 비밀번호 변경이 필요합니다.'))
