from datetime import timedelta, time
from decimal import Decimal
from getpass import getpass
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from workflow.models import AnnualBalance, Document, Policy, Profile
from workflow.services import act_on_document, save_document


TENURE = '''0~1년|11
1년~2년|15
3년~4년|16
5년~6년|17
7년~8년|18
9년~10년|19
11년~12년|20
13년~14년|21
15년~16년|22
17년~18년|23
19년~20년|24
21년~22년|25'''

POLICY = '''★ 잔여연차 보유자는 2026년 12월 31일까지 모두 사용하여 소진할 것.
★ 잔여연차 외 휴가사용은 모두 무급휴가로서 대표이사의 사전허가를 받을 것.
★ 사전허가가 없는 결근은 무단결근으로서 주차와 연차, 인사상의 불이익이 따름.
★ 예외규정: 잔여연차 상관없이 유급휴가로 인정받는 경우
1. 본인의 결혼: 5일
2. 배우자의 출산: 20일
3. 부모(배우자 포함) 또는 배우자의 사망: 5일
4. 본인의 조부모 또는 외조부모의 사망: 3일
5. 배우자의 조부모 또는 외조부모의 사망: 1일
6. 자녀 또는 그 자녀의 배우자의 사망: 3일
7. 형제, 자매 사망(배우자 포함): 3일
8. 사전에 대표이사가 연차를 허락한 경우
9. 기타 국가에서 정한 임시공휴일(선거일 등)'''


class Command(BaseCommand):
    help = '비어 있는 시안 DB에 가상 직원과 예시 문서를 생성합니다. 기존 DB는 덮어쓰지 않습니다.'

    def add_arguments(self, parser):
        parser.add_argument('--initial-password', help='예시 계정의 초기 비밀번호. 생략하면 안전하게 입력받습니다.')

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        if User.objects.exists():
            self.stdout.write('기존 계정이 있어 예시 데이터를 추가하지 않았습니다.')
            return
        password = options['initial_password'] or getpass('시안 계정 초기 비밀번호: ')
        if not password:
            raise CommandError('초기 비밀번호를 입력해 주세요.')
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
        for username, name, department, rank, flags in specs:
            user = User.objects.create_user(username=username, first_name=name, password=password)
            Profile.objects.create(user=user, department=department, rank=rank, approved=True, **flags)
            AnnualBalance.objects.create(user=user, year=year, total=15 if rank in ['주임', '대리'] else 20,
                                         used=2 if username == 'employee' else 1)
            people[username] = user
        Policy.objects.create(tenure=TENURE, text=POLICY, updated_by=people['accounting'])
        owner, reviewer, approver = [people[x] for x in ['employee', 'reviewer', 'approver']]
        today = timezone.localdate()
        monday = today + timedelta(days=(7 - today.weekday()) % 7 or 7)

        def make(stage='review', **fields):
            doc_owner = fields.pop('owner', owner)
            doc = Document(owner=doc_owner, reviewer=fields.pop('reviewer', reviewer),
                           approver=fields.pop('approver', approver), recipient=fields.pop('recipient', doc_owner), **fields)
            save_document(doc, doc_owner, submit=stage != 'draft')
            if stage in ['approve', 'approved']:
                doc = act_on_document(doc.pk, doc.reviewer, 'review')
            if stage == 'approved':
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
