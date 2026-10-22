"""Isolated local purchase workflow. No legacy documents or balances are converted."""
from decimal import Decimal
from uuid import uuid4
from django.conf import settings
from django.db import models
from django.utils import timezone

MODES = [('direct','이사님에게 바로 요청'),('approval','승인 → 이사님'),('review_approval','검토 → 승인 → 이사님')]


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
    version = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)


class PurchaseRequest(models.Model):
    STATES = [('draft','임시저장'),('review','검토 대기'),('approval','중간 승인 대기'),('director','담당 이사 최종승인 대기'),
              ('ready','부서 승인 완료 · 경리 취합 대기'),('ceo','대표 구매허가 심사 중'),('allowed','구매허가 완료 · 결제 대기'),
              ('denied','구매불허'),('hold','구매보류'),('paid','결제 완료 · 수령 대기'),('received','수령 완료'),
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
    private = models.BooleanField(default=False)
    status = models.CharField(max_length=12,choices=STATES,default='draft',db_index=True)
    request_key = models.UUIDField(default=uuid4,unique=True,editable=False)
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name='+')
    approver = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name='+')
    director = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name='+')
    route = models.JSONField(default=dict,blank=True)
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


class PurchaseReport(models.Model):
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='+')
    representative = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='+')
    title = models.CharField(max_length=180)
    note = models.CharField(max_length=1000)
    status = models.CharField(max_length=12,choices=[('pending','대표 심사 중'),('decided','품목별 결정 완료')],default='pending')
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
        if self.status!='decided':return '대표 심사 중'
        states=set(self.items.values_list('decision',flat=True))
        return '구매허가' if states=={'allow'} else '구매불허' if states=={'deny'} else '구매보류' if states=={'hold'} else '품목별 부분 결정'


class PurchaseReportItem(models.Model):
    DECISIONS=[('pending','미정'),('allow','구매허가'),('deny','구매불허'),('hold','보류')]
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
