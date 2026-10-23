"""Separated human-readable rules, only used by the isolated integrated preview."""
from decimal import Decimal
from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied,ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404,redirect
from django.urls import reverse
from workflow.models import ApprovalRule,ApprovalFlowPolicy,RegulationLock
from workflow.forms import ApprovalRuleForm
from workflow.regulations import save_rule
from workflow.views import page


class ScopedRuleForm(ApprovalRuleForm):
    def __init__(self,*args,kind,**kwargs):
        super().__init__(*args,**kwargs);self.kind=kind
        self.fields['kind'].choices=[(kind,'휴가원' if kind=='leave' else '생산 재고 요청')]
        self.fields['kind'].initial=kind;self.initial['kind']=kind
        self.fields['kind'].widget=forms.HiddenInput()
        for name in ['amount_over','amount_to']:
            self.fields[name].widget=forms.HiddenInput();self.fields[name].required=False
        self.initial['amount_over']=0
        if kind=='leave' and self.instance.pk:
            self.initial['allow_representative_direct']=bool(self.instance.allow_representative_direct or self.instance.allow_self_approval or self.instance.skip_review or self.instance.approver_is_author)
        self.fields['name'].label='규정 이름'
        self.fields['authors'].label='특정 기안자에게만 적용 · 선택사항'
        self.fields['allow_review_final'].label='지정한 검토자가 승인까지 완료할 수 있음'
        self.fields['allow_representative_direct'].label='과장·팀장·부장·이사에게 대표 결재 요청 허용'
    def clean(self):
        data=super().clean();data['amount_over']=Decimal('0');data['amount_to']=None
        if self.kind=='leave':data['skip_review']=False
        return data


class LeaveThresholdForm(forms.Form):
    leave_threshold=forms.DecimalField(label='승인자가 대표 결재도 선택할 수 있는 휴가 일수',min_value=Decimal('.25'),max_value=999,decimal_places=2)


def regulations(request,pk=None):
    if not (request.user.profile.manage_system or request.user.profile.manage_leave):raise PermissionDenied
    tab=request.GET.get('tab','')
    if not pk and not tab:return page(request,'integrated_rules_hub','규정 관리','regulations')
    if tab=='purchase':return redirect('purchasing:regulations')
    instance=get_object_or_404(ApprovalRule,pk=pk,deleted_at__isnull=True) if pk else None
    if instance and instance.kind not in ['leave','stock']:
        messages.info(request,'기존 공통·구매 규정은 보존됩니다. 새 휴가원·구매요청은 문서별 규정에서 설정해 주세요.');return redirect('regulations')
    kind=instance.kind if instance else 'stock' if tab=='stock' else 'leave'
    label='휴가원' if kind=='leave' else '생산 재고'
    form=ScopedRuleForm(request.POST if request.method=='POST' and request.POST.get('intent')!='threshold' else None,kind=kind,instance=instance,
        initial={} if instance else dict(kind=kind,reviewer_ranks=['주임','대리','과장','팀장','부장','이사'],approver_ranks=['주임','대리','과장','팀장','부장','이사']))
    p=ApprovalFlowPolicy.objects.filter(pk=1).first()
    threshold=LeaveThresholdForm(request.POST if request.method=='POST' and request.POST.get('intent')=='threshold' else None,initial=dict(leave_threshold=p.leave_threshold if p else 3))
    if request.method=='POST':
        try:
            if request.POST.get('intent')=='threshold':
                if kind!='leave' or not request.user.profile.manage_system:raise PermissionDenied
                if threshold.is_valid():
                    with transaction.atomic():
                        RegulationLock.objects.select_for_update().get_or_create(pk=1)
                        current,_=ApprovalFlowPolicy.objects.select_for_update().get_or_create(pk=1)
                        current.leave_threshold=threshold.cleaned_data['leave_threshold'];current.version+=1
                        current.save(update_fields=['leave_threshold','version'])
                        from workflow.services import audit
                        audit(request.user,'휴가원 대표 결재 선택 기준 수정',detail=f'{current.leave_threshold}일 이상 / 기존 제출 경로 유지')
                    messages.success(request,'휴가원 기준을 저장했습니다. 구매·생산 재고 규정은 바뀌지 않습니다.');return redirect(reverse('regulations')+'?tab=leave')
            elif form.is_valid():
                save_rule(request.user,form);messages.success(request,f'{label} 규정을 저장했습니다. 기존 제출 문서는 유지됩니다.');return redirect(reverse('regulations')+'?tab='+kind)
        except ValidationError as exc:form.add_error(None,exc)
    groups=[('1. 규정 이름과 사용 여부',['name','enabled']),('2. 결재 가능한 직급',['reviewer_ranks','approver_ranks']),('3. 과장급 이상의 요청 방식',['allow_representative_direct'])]
    return page(request,'integrated_rule_edit',f'{label} 결재 규정','regulations',kind=kind,rule_label=label,rule_form=form,threshold_form=threshold,
        field_groups=[(label,[form[name] for name in names]) for label,names in groups],review_final_fields=[form[name] for name in ['allow_review_final','review_final_users']],advanced_fields=[form[name] for name in ['author_ranks','author_departments','authors','fixed_reviewer','fixed_approver']+(['skip_review'] if kind=='stock' else [])],
        rules=ApprovalRule.objects.filter(kind=kind,deleted_at__isnull=True).prefetch_related('review_final_users'),common_rules=ApprovalRule.objects.filter(kind='all',deleted_at__isnull=True))
