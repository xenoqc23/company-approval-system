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


class PurchasePolicy(models.Model):
    enabled = models.BooleanField(default=False)
    dev_director = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,related_name='+')
    production_director = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,related_name='+')
    representative = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,related_name='+')
    finance = models.ManyToManyField(settings.AUTH_USER_MODEL,related_name='+')
    development_modes = models.JSONField(default=dev_modes)
    other_modes = models.JSONField(default=other_modes)
    approval_modes = models.JSONField(default=approval_modes)
    version = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)


class PurchaseRequest(models.Model):
    STATES = [('draft','임시저장'),('review','검토 대기'),('approval','승인 대기'),('director','담당 이사 최종승인 대기'),
              ('ready','승인완료'),('ceo','구매요청'),('allowed','구매승인'),
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
    private = models.BooleanField(default=False)
    status = models.CharField(max_length=12,choices=STATES,default='draft',db_index=True)
    request_key = models.UUIDField(default=uuid4,unique=True,editable=False)
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name='+')
    approver = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name='+')
    director = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name='+')
    route = models.JSONField(default=dict,blank=True)
    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name='+')
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
        if self.status!='decided':return '구매요청'
        states=set(self.items.values_list('decision',flat=True))
        return '구매승인' if states=={'allow'} else '구매반려' if states=={'deny'} else '구매보류' if states=={'hold'} else '일부 승인 · 일부 반려/보류'


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
