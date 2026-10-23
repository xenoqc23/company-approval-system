"""Isolated local purchase workflow. No legacy documents or balances are converted."""
from decimal import Decimal
from uuid import uuid4
from django.conf import settings
from django.db import models
from django.utils import timezone

MODES = [('direct','본인 전결'),('approval','기안 → 승인'),('review_approval','기안 → 검토 → 승인')]

def approval_modes():
    return other_modes()


def dev_modes():
    from workflow.models import RANKS
    return {rank:'direct' for rank in RANKS}


def other_modes():
    from workflow.models import RANKS
    return {rank:'review_approval' if rank in ['사원','주임','대리'] else 'direct' for rank in RANKS}


def direct_request_ranks():return ['과장','팀장','부장','이사']


class PurchasePolicy(models.Model):
    enabled = models.BooleanField(default=False)
    department_routing = models.BooleanField(default=True)
    direct_ranks = models.JSONField(default=direct_request_ranks)
    review_mode = models.CharField(max_length=20,default='review_approval')
    combine_confirmation = models.BooleanField(default=True)
    director_self_request = models.BooleanField(default=True)
    dev_director = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,related_name='+')
    production_director = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,related_name='+')
    representative = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,related_name='+')
    finance = models.ManyToManyField(settings.AUTH_USER_MODEL,related_name='+')
    review_final_users = models.ManyToManyField(settings.AUTH_USER_MODEL,blank=True,related_name='+')
    development_modes = models.JSONField(default=dev_modes)
    other_modes = models.JSONField(default=other_modes)
    approval_modes = models.JSONField(default=approval_modes)
    version = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)


class PurchaseRequest(models.Model):
    STATES = [('draft','임시저장'),('review','검토 대기'),('approval','승인 대기'),('director','담당 이사 최종승인 대기'),
              ('ready','승인완료'),('supplement','보완 요청'),('reapproval','금액 변경 · 재승인 대기'),('ceo','구매요청'),('allowed','승인완료 · 수령 대기'),
              ('denied','구매반려'),('hold','구매보류'),('paid','결제 완료 · 수령 대기'),('received','수령 완료'),
              ('rejected','내부 결재 반려'),('cancelled','요청 취소')]
    owner = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='purchase_requests')
    department = models.CharField(max_length=30)
    rank = models.CharField(max_length=20)
    product = models.CharField(max_length=180)
    vendor = models.CharField(max_length=150)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=14,decimal_places=2)
    url = models.URLField(max_length=1000,blank=True)
    reason = models.TextField()
    needed_by = models.DateField(null=True,blank=True)
    urgent = models.BooleanField(default=False)
    urgent_reason = models.CharField(max_length=500,blank=True)
    usage_department = models.CharField(max_length=30,blank=True)
    storage_location = models.CharField(max_length=150,blank=True)
    received_quantity = models.PositiveIntegerField(default=0)
    completion_unread = models.BooleanField(default=False)
    hold_ready = models.BooleanField(default=False)
    hold_note = models.CharField(max_length=1000,blank=True)
    private = models.BooleanField(default=False)
    status = models.CharField(max_length=12,choices=STATES,default='draft',db_index=True)
    request_key = models.UUIDField(default=uuid4,unique=True,editable=False)
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name='+')
    approver = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name='+')
    director = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name='+')
    route = models.JSONField(default=dict,blank=True)
    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name='+')
    purchase_checker = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name='+')
    confirmation_method = models.CharField(max_length=24,blank=True,choices=[('manual','확인완료'),('with_approval','승인 시 함께 확인'),('director_request','담당 이사 직접 요청')])
    confirmed_at = models.DateTimeField(null=True,blank=True)
    purchase_route = models.JSONField(default=dict,blank=True)
    current_report = models.ForeignKey('PurchaseReport',on_delete=models.PROTECT,null=True,blank=True,related_name='+')
    decision_reason = models.CharField(max_length=1000,blank=True)
    submitted_at = models.DateTimeField(null=True,blank=True)
    reviewed_at = models.DateTimeField(null=True,blank=True)
    intermediate_at = models.DateTimeField(null=True,blank=True)
    director_at = models.DateTimeField(null=True,blank=True)
    permitted_at = models.DateTimeField(null=True,blank=True)
    paid_at = models.DateTimeField(null=True,blank=True)
    received_at = models.DateTimeField(null=True,blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    revision = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-created_at','-pk']

    @property
    def number(self):return f'PUR-{timezone.localtime(self.created_at):%Y%m%d}-{self.pk:04d}' if self.pk else '임시저장'
    @property
    def total(self):return self.quantity*self.unit_price
    @property
    def remaining_quantity(self):return max(0,self.quantity-self.received_quantity)


class PurchaseReport(models.Model):
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='+')
    representative = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='+')
    title = models.CharField(max_length=180)
    note = models.CharField(max_length=1000)
    status = models.CharField(max_length=12,choices=[('pending','구매요청'),('decided','검토 완료')],default='pending')
    request_key = models.UUIDField(default=uuid4,unique=True)
    created_at = models.DateTimeField(default=timezone.now)
    decided_at = models.DateTimeField(null=True,blank=True)
    revision = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-created_at','-pk']

    @property
    def number(self):return f'BATCH-{timezone.localtime(self.created_at):%Y%m%d}-{self.pk:04d}'
    @property
    def result_label(self):
        if settings.INTEGRATED_PURCHASES:
            states=set(self.items.values_list('decision',flat=True))
            if self.status!='decided':return '대표 결재 대기'
            if 'hold' in states:return '일부 승인 · 보류' if 'allow' in states else '보류' if states=={'hold'} else '반려 · 보류'
            if states=={'allow'}:return '결재완료'
            if states=={'deny'}:return '반려'
            return '결재완료 · 일부 승인' if 'allow' in states else '결정 완료'
        if self.status!='decided':return '구매 승인 대기'
        states=set(self.items.values_list('decision',flat=True))
        labels={'allow':'구매 승인완료','deny':'구매반려','hold':'구매보류'}
        if len(states)==1:return labels.get(next(iter(states)),'결정 완료')
        return ' · '.join(label for key,label in [('allow','일부 승인'),('deny','반려'),('hold','보류')] if key in states)

    @property
    def result_tone(self):
        if self.status!='decided':return 'waiting'
        states=set(self.items.values_list('decision',flat=True))
        return 'positive' if states=={'allow'} else 'negative' if states=={'deny'} else 'waiting'


class PurchaseReportItem(models.Model):
    DECISIONS=[('pending','검토 전'),('allow','구매승인'),('deny','구매반려'),('hold','구매보류')]
    report = models.ForeignKey(PurchaseReport,on_delete=models.PROTECT,related_name='items')
    request = models.ForeignKey(PurchaseRequest,on_delete=models.PROTECT,related_name='report_items')
    snapshot = models.JSONField()
    decision = models.CharField(max_length=10,choices=DECISIONS,default='pending')
    reason = models.CharField(max_length=1000,blank=True)

    class Meta:
        ordering=['pk']
        constraints=[models.UniqueConstraint(fields=['report','request'],name='purchase_report_unique_request')]

    @property
    def total(self):return Decimal(self.snapshot['unit_price'])*self.snapshot['quantity']


class PurchaseSupplement(models.Model):
    request = models.ForeignKey(PurchaseRequest,on_delete=models.PROTECT,related_name='supplements')
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='+')
    reason = models.CharField(max_length=1000)
    before = models.JSONField()
    after = models.JSONField(null=True,blank=True)
    response = models.CharField(max_length=1000,blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    resolved_at = models.DateTimeField(null=True,blank=True)

    class Meta:ordering=['-created_at','-pk']


class PurchaseAmendment(models.Model):
    request = models.ForeignKey(PurchaseRequest,on_delete=models.PROTECT,related_name='amendments')
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='+')
    previous_report = models.ForeignKey(PurchaseReport,on_delete=models.PROTECT)
    before = models.JSONField()
    after = models.JSONField()
    reason = models.CharField(max_length=1000)
    requires_reapproval = models.BooleanField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:ordering=['-created_at','-pk']


class PurchaseEvent(models.Model):
    request = models.ForeignKey(PurchaseRequest,on_delete=models.PROTECT,null=True,related_name='events')
    report = models.ForeignKey(PurchaseReport,on_delete=models.PROTECT,null=True,related_name='events')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='+')
    event = models.CharField(max_length=100)
    detail = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:ordering=['-created_at','-pk']


class PurchaseNotice(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE)
    request = models.ForeignKey(PurchaseRequest,on_delete=models.PROTECT,null=True)
    report = models.ForeignKey(PurchaseReport,on_delete=models.PROTECT,null=True)
    text = models.CharField(max_length=250)
    read = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:ordering=['-pk']


class DemoAccount(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL,on_delete=models.CASCADE)
    label = models.CharField(max_length=100)
    position = models.PositiveIntegerField(default=0)

    class Meta:ordering=['position','pk']


class PurchasePermission(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name='purchase_permission')
    view_completed = models.BooleanField(default=False,verbose_name='구매요청승인완료함')


from .attachments import private_storage,attachment_path

class PurchaseAttachment(models.Model):
    request = models.ForeignKey(PurchaseRequest,on_delete=models.PROTECT,related_name='attachments')
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='+')
    kind = models.CharField(max_length=10,choices=[('request','기안 첨부'),('purchase','구매 증빙')])
    original_name = models.CharField(max_length=200)
    file = models.FileField(storage=private_storage,upload_to=attachment_path,max_length=300)
    size = models.PositiveIntegerField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:ordering=['created_at','pk']


class PurchaseReceipt(models.Model):
    request = models.ForeignKey(PurchaseRequest,on_delete=models.PROTECT,related_name='receipts')
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='+')
    quantity = models.PositiveIntegerField()
    location = models.CharField(max_length=150,blank=True)
    note = models.CharField(max_length=1000,blank=True)
    key = models.UUIDField(default=uuid4,unique=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:ordering=['created_at','pk']
