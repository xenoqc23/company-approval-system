from decimal import Decimal
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

class AnnualBalance(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='balances')
    year = models.PositiveIntegerField()
    total = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    used = models.DecimalField(max_digits=8, decimal_places=2, default=0)

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
