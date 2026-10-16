from decimal import Decimal
from uuid import uuid4
from django.conf import settings
from django.db import models
from django.utils import timezone

DEPARTMENTS = ['생산팀', '품질팀', '개발팀', '영업팀', '전략기획팀', '인사팀']
RANKS = ['사원', '주임', '대리', '과장', '팀장', '부장', '이사']

class Profile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile')
    department = models.CharField(max_length=30, choices=[(x, x) for x in DEPARTMENTS])
    department_confirmed = models.BooleanField(default=True)
    rank = models.CharField(max_length=20, choices=[(x, x) for x in RANKS])
    approved = models.BooleanField(default=False)
    must_change_password = models.BooleanField(default=False)
    manage_leave = models.BooleanField(default=False)
    view_accounting = models.BooleanField(default=False)
    procure = models.BooleanField(default=False)
    manage_system = models.BooleanField(default=False)
    hire_date = models.DateField(null=True, blank=True)

class AnnualBalance(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='balances')
    year = models.PositiveIntegerField()
    total = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    used = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    grant_initialized = models.BooleanField(default=False)
    total_manual = models.BooleanField(default=False)
    grant_policy_year = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'year'], name='unique_user_year')]

    @property
    def remaining(self):
        return self.total - self.used

class Document(models.Model):
    KINDS = [('leave', '휴가원'), ('office', '사무·사내용품'), ('stock', '생산 재고 요청')]
    LEAVES = [('annual', '연차'), ('am', '오전반차'), ('pm', '오후반차'), ('outing', '외출')]
    STATES = [('draft', '임시저장'), ('review', '검토대기'), ('approve', '최종승인대기'),
              ('approved', '결재완료'), ('rejected', '반려'), ('cancelled', '취소'), ('deleted', '삭제')]
    SHIPMENTS = [('', '구매·발주 전'), ('shipping', '배송중'), ('ordered', '발주완료·입고대기'),
                 ('received', '수령완료')]
    number = models.CharField(max_length=40, unique=True, null=True, blank=True)
    title = models.CharField(max_length=220, blank=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='owned_documents')
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='review_documents', null=True, blank=True)
    approver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='approve_documents', null=True, blank=True)
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='receive_documents', null=True, blank=True)
    kind = models.CharField(max_length=12, choices=KINDS, default='leave')
    status = models.CharField(max_length=15, choices=STATES, default='draft')
    leave_type = models.CharField(max_length=12, choices=LEAVES, default='annual')
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    reason = models.TextField(blank=True)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    product = models.CharField(max_length=180, blank=True)
    url = models.URLField(max_length=1000, blank=True)
    urgency = models.CharField(max_length=10, choices=[('normal', '일반'), ('urgent', '긴급')], default='normal')
    needed_date = models.DateField(null=True, blank=True)
    shipment = models.CharField(max_length=16, choices=SHIPMENTS, blank=True, default='')
    route_snapshot = models.JSONField(default=dict, blank=True)
    allocations = models.JSONField(default=dict, blank=True)
    charged = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    created_at = models.DateTimeField(default=timezone.now)
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-pk']

    @property
    def review_required(self):
        return self.kind == 'stock' or not self.route_snapshot.get('skip_review', False)

    @property
    def total_price(self):
        return self.quantity * self.unit_price

    @property
    def type_label(self):
        return self.get_leave_type_display() if self.kind == 'leave' else self.get_kind_display()

    @property
    def shipment_label(self):
        if self.kind == 'stock' and not self.shipment:
            return '발주대기' if self.status == 'approved' else '검토 후 발주'
        if self.shipment == 'received':
            return '배송완료' if self.kind == 'office' else '입고완료'
        return self.get_shipment_display()

    @property
    def status_label(self):
        if self.kind == 'stock' and self.status == 'approved':
            return {'': '발주대기', 'ordered': '입고대기', 'received': '입고완료'}.get(self.shipment, '검토완료')
        return self.get_status_display()

class DocumentCounter(models.Model):
    day = models.DateField(unique=True)
    value = models.PositiveIntegerField(default=0)

class ManualLeaveUsage(models.Model):
    """Dated leave taken outside the approval flow; cancellation retains the record."""
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='manual_leaves')
    used_date = models.DateField()
    leave_type = models.CharField(max_length=12, choices=Document.LEAVES)
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    amount = models.DecimalField(max_digits=3, decimal_places=2)
    reason = models.CharField(max_length=1000)
    request_key = models.UUIDField(default=uuid4, unique=True, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='registered_manual_leaves')
    created_at = models.DateTimeField(default=timezone.now)
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='cancelled_manual_leaves')
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=1000, blank=True)

    class Meta:
        ordering = ['-used_date', '-created_at', '-pk']
        constraints = [models.CheckConstraint(condition=models.Q(amount__gt=0, amount__lte=1), name='manual_leave_positive_amount')]

class AccountingReadState(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    kind = models.CharField(max_length=20, choices=Document.KINDS)
    seen_until = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'kind'], name='unique_accounting_read_kind')]

class Audit(models.Model):
    document = models.ForeignKey(Document, null=True, blank=True, on_delete=models.PROTECT, related_name='audits')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)
    target = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='target_audits')
    event = models.CharField(max_length=80)
    detail = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at', '-pk']

class Notice(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    document = models.ForeignKey(Document, null=True, blank=True, on_delete=models.PROTECT)
    text = models.CharField(max_length=250)
    subject = models.CharField(max_length=250, blank=True)
    stage = models.CharField(max_length=40, blank=True)
    read = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at', '-pk']

    @property
    def display_text(self):
        return f'{self.subject} - {self.stage}' if self.subject and self.stage else self.text

    @property
    def reason_text(self):
        return self.text.partition('사유: ')[2] if self.subject and self.stage else ''

class Policy(models.Model):
    tenure = models.TextField()
    text = models.TextField()
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)


class Absence(models.Model):
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reason = models.CharField(max_length=100)
    start_date = models.DateField()
    end_date = models.DateField()
    all_day = models.BooleanField(default=True)
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)


class CompanyHoliday(models.Model):
    title = models.CharField(max_length=100)
    day = models.DateField()
    use_annual = models.BooleanField(default=False)
    description = models.CharField(max_length=300, blank=True)
    active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)


class CompanyHolidayLock(models.Model):
    """Singleton lock to serialize all company-wide leave operations."""
    pass


class CompanyLeaveCharge(models.Model):
    holiday = models.ForeignKey(CompanyHoliday, on_delete=models.PROTECT, related_name='charges')
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    year = models.PositiveIntegerField()
    amount = models.DecimalField(max_digits=8, decimal_places=2, default=1)
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['holiday', 'employee'], name='unique_company_leave_charge')]


class RegulationLock(models.Model):
    """Serialize regulation edits and submission snapshots."""
    pass


class ApprovalRule(models.Model):
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=12, choices=Document.KINDS[:2])
    amount_over = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    amount_to = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    author_ranks = models.JSONField(default=list, blank=True)
    reviewer_ranks = models.JSONField(default=list)
    approver_ranks = models.JSONField(default=list)
    skip_review = models.BooleanField(default=False)
    enabled = models.BooleanField(default=False)
    version = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['kind', 'amount_over', 'pk']


class AnnualPolicy(models.Model):
    effective_year = models.PositiveIntegerField(unique=True)
    bands = models.JSONField(default=list)
    text = models.TextField(blank=True)
    hire_year_monthly = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-effective_year']


class WelfarePolicy(models.Model):
    benefits = models.JSONField(default=list)
    awards = models.JSONField(default=list)
    version = models.PositiveIntegerField(default=1)
