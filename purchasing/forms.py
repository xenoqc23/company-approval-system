from decimal import Decimal
from uuid import uuid4
from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from workflow.models import RANKS
from workflow.forms import DepartmentEmployeeSelect,department_picker
from django.conf import settings
from .models import PurchaseRequest,PurchasePolicy,MODES,dev_modes,other_modes
from .access import is_admin
from .services import eligible_people,mode_for,validate_policy_people,event,actor_now,lock_policy,can_request_direct,department_checker,forward_people
from django.db import transaction


class PersonChoice(forms.ModelChoiceField):
    def label_from_instance(self,obj):return f'{obj.first_name} · {obj.profile.department} {obj.profile.rank}'


class PersonMultiple(forms.ModelMultipleChoiceField):
    def label_from_instance(self,obj):return f'{obj.first_name} · {obj.profile.department} {obj.profile.rank}'


class WonField(forms.DecimalField):
    def to_python(self, value):
        if isinstance(value, str):
            import re
            value=value.strip()
            if ',' in value:
                if not re.fullmatch(r'\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?',value):
                    raise ValidationError('금액을 50,000 또는 50000처럼 입력해 주세요.')
                value=value.replace(',','')
        return super().to_python(value)


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected=True


class MultipleFileField(forms.FileField):
    def clean(self,data,initial=None):
        from .attachments import validated_files
        if not data:
            if self.required:super().clean(data,initial)
            return []
        return validated_files([super(MultipleFileField,self).clean(f,initial) for f in (data if isinstance(data,(list,tuple)) else [data])])


class AttachmentForm(forms.Form):
    files=MultipleFileField(label='첨부파일',required=True,widget=MultipleFileInput(attrs={'accept':'.pdf,.png,.jpg,.jpeg,.gif,.webp,.xlsx,.xls,.docx,.doc,.hwp,.hwpx,.txt'}))


class RequestForm(forms.ModelForm):
    reviewer_department=department_picker('reviewer')
    approver_department=department_picker('approver')
    request_method=forms.ChoiceField(label='요청 방식',choices=[('review','검토 요청'),('direct','구매담당자에게 요청')],initial='review',widget=forms.RadioSelect)
    files=MultipleFileField(label='첨부파일 · 선택',required=False,widget=MultipleFileInput(attrs={'accept':'.pdf,.png,.jpg,.jpeg,.gif,.webp,.xlsx,.xls,.docx,.doc,.hwp,.hwpx,.txt'}))
    unit_price=WonField(label='개당 금액 · 부가세 포함',max_digits=14,decimal_places=2,min_value=Decimal('0.01'),max_value=Decimal('999999999.99'),widget=forms.TextInput(attrs={'inputmode':'decimal','placeholder':'예: 50,000','autocomplete':'off'}))
    key=forms.UUIDField(widget=forms.HiddenInput,initial=uuid4)
    reviewer=PersonChoice(label='검토자',queryset=get_user_model().objects.none(),required=False)
    approver=PersonChoice(label='승인자',queryset=get_user_model().objects.none(),required=False)
    class Meta:
        model=PurchaseRequest
        fields=['product','vendor','quantity','unit_price','url','reason','private','needed_by','urgent','urgent_reason','usage_department','storage_location']
        labels=dict(product='구매 품목·모델명·규격',vendor='구매처',quantity='수량',unit_price='개당 금액 · 부가세 포함',url='구매 링크 · 선택',reason='구매 사유',private='유사 구매 안내에서 제외 · 기밀 구매')
        widgets=dict(needed_by=forms.DateInput(attrs={'type':'date'}),urgent_reason=forms.TextInput(attrs={'placeholder':'긴급하게 필요한 이유'}),reason=forms.Textarea(attrs={'rows':4}),quantity=forms.NumberInput(attrs={'min':1,'max':999999}),
                     unit_price=forms.NumberInput(attrs={'min':'.01','max':'999999999.99','step':'.01'}),
                     product=forms.TextInput(attrs={'placeholder':'예: 27인치 모니터 / 모델명'}),vendor=forms.TextInput(attrs={'placeholder':'업체명 또는 쇼핑몰명'}))
    def __init__(self,*args,user,policy,**kwargs):
        super().__init__(*args,**kwargs)
        if not self.instance.pk:self.initial['usage_department']=user.profile.department
        self.department_routing=bool(policy and policy.department_routing)
        self.can_direct=can_request_direct(policy,user) if self.department_routing else False
        self.checker=department_checker(policy,user) if policy else None
        if self.department_routing and self.checker and self.checker.pk==user.pk and not policy.director_self_request:self.checker=policy.production_director if user.profile.department=='개발팀' else policy.dev_director
        if not self.department_routing:self.fields.pop('request_method')
        else:
            if not self.can_direct:self.fields['request_method'].choices=[('review','검토 요청')]
            self.initial['request_method']=self.instance.route.get('request_method','review') if self.instance.pk else 'review'
        method=self.data.get('request_method','review') if self.is_bound else self.initial.get('request_method','review')
        self.mode='direct' if self.department_routing and method=='direct' else mode_for(policy,user) if policy else 'direct'
        self.review_mode=mode_for(policy,user) if self.department_routing else self.mode
        director=policy.dev_director if policy and user.profile.department=='개발팀' else policy.production_director if policy else None
        qs=eligible_people(user)
        minimum=RANKS.index(user.profile.rank) if user.profile.rank in RANKS else len(RANKS)
        qs=qs.filter(profile__rank__in=RANKS[minimum:])
        self.fields['reviewer'].queryset=qs
        self.fields['approver'].queryset=qs
        if settings.INTEGRATED_PURCHASES:
            for key in ['reviewer','approver']:
                self.fields[key].widget=DepartmentEmployeeSelect()
                self.fields[key].widget.choices=self.fields[key].choices
                self.initial[key+'_department']=user.profile.department
                person_id=self.data.get(key) if self.is_bound else self.initial.get(key) or getattr(self.instance,key+'_id',None)
                person=qs.filter(pk=person_id).first() if str(person_id or '').isascii() and str(person_id or '').isdigit() and len(str(person_id))<=18 else None
                if person:self.initial[key+'_department']=person.profile.department
        else:
            self.fields.pop('reviewer_department');self.fields.pop('approver_department')
        self.fields['reviewer'].required=self.mode=='review_approval'
        self.fields['approver'].required=self.mode in ['approval','review_approval']
        if self.instance.pk:self.initial['key']=self.instance.request_key
        elif user.username=='p_quality':
            self.initial['reviewer']=qs.filter(username='p_quality_manager').values_list('pk',flat=True).first()
            self.initial['approver']=qs.filter(username='p_quality_lead').values_list('pk',flat=True).first()
        elif user.username=='p_dev_manager':
            self.initial['reviewer']=qs.filter(username='p_dev_lead').values_list('pk',flat=True).first()
            self.initial['approver']=qs.filter(username='p_dev_director').values_list('pk',flat=True).first()
        if settings.INTEGRATED_PURCHASES:
            self.fields.pop('approver',None);self.fields.pop('approver_department',None)
            self.mode='direct' if method=='direct' else 'review_approval';self.review_mode='review_approval'
            self.fields['reviewer'].required=self.mode=='review_approval' and self.data.get('intent')!='draft'

    def clean(self):
        data=super().clean()
        if data.get('urgent') and not (data.get('urgent_reason') or '').strip():self.add_error('urgent_reason','긴급 요청 사유를 입력해 주세요.')
        return data


class PolicyForm(forms.Form):
    enabled=forms.BooleanField(label='이 구매 규정 사용',required=False)
    representative=PersonChoice(label='품목별 구매승인 대표',queryset=get_user_model().objects.none())
    finance=PersonMultiple(label='구매 담당자',queryset=get_user_model().objects.none(),widget=forms.CheckboxSelectMultiple)
    dev_director=PersonChoice(label='개발팀 구매 확인 담당자',queryset=get_user_model().objects.none(),required=False)
    production_director=PersonChoice(label='그 외 부서 구매 확인 담당자',queryset=get_user_model().objects.none(),required=False)
    direct_ranks=forms.MultipleChoiceField(label='구매담당자에게 요청할 수 있는 직급',choices=[(r,r) for r in RANKS[3:]],required=False,widget=forms.CheckboxSelectMultiple)
    review_mode=forms.ChoiceField(label='검토 요청 경로',choices=[('review_approval','검토자 → 승인자'),('approval','승인자만 지정')])
    combine_confirmation=forms.BooleanField(label='담당 이사가 최종 승인하면 구매 확인까지 함께 처리',required=False)
    director_self_request=forms.BooleanField(label='담당 이사의 직접 요청은 구매담당자에게 바로 전달',required=False)
    revision=forms.IntegerField(widget=forms.HiddenInput)
    reason=forms.CharField(label='변경 사유',max_length=1000,widget=forms.Textarea(attrs={'rows':2}))
    def __init__(self,*args,instance,**kwargs):
        super().__init__(*args,**kwargs);self.instance=instance
        users=get_user_model().objects.filter(is_active=True,profile__approved=True).select_related('profile').order_by('first_name','pk')
        self.fields['representative'].queryset=users.filter(profile__representative_slot=1)
        self.fields['finance'].queryset=users.filter(profile__representative_slot__isnull=True).exclude(username='admin')
        self.legacy=bool(instance and not instance.department_routing)
        for key,department in [('dev_director','개발팀'),('production_director','생산팀')]:
            self.fields[key].queryset=users.filter(profile__department=department,profile__rank='이사',profile__department_confirmed=True,profile__representative_slot__isnull=True)
            self.fields[key].required=not self.legacy
        self.fields['review_mode'].required=not self.legacy
        if instance:self.initial.update(dev_director=instance.dev_director_id,production_director=instance.production_director_id,direct_ranks=instance.direct_ranks,review_mode=instance.review_mode,combine_confirmation=instance.combine_confirmation,director_self_request=instance.director_self_request)
        from .models import approval_modes
        modes=instance.approval_modes if instance else approval_modes()
        for i,rank in enumerate(RANKS if self.legacy else []):
            choices=MODES if i>=RANKS.index('과장') else [(key,label) for key,label in MODES if key!='direct']
            self.fields[f'rank_{i}']=forms.ChoiceField(label=rank,choices=choices,initial=modes.get(rank,'review_approval'))
        if instance:self.initial.update(enabled=instance.enabled,representative=instance.representative_id,finance=list(instance.finance.values_list('pk',flat=True)),revision=instance.version)
    @transaction.atomic
    def save(self,actor):
        p=lock_policy();actor=actor_now(actor)
        if not is_admin(actor):raise forms.ValidationError('관리자만 규정을 바꿀 수 있습니다.')
        data=self.cleaned_data
        if data['revision']!=p.version:raise forms.ValidationError('다른 창에서 규정이 바뀌었습니다. 새로고침해 주세요.')
        p.enabled=data['enabled'];p.representative=data['representative']
        if p.department_routing:
            p.dev_director=data['dev_director'];p.production_director=data['production_director'];p.direct_ranks=data['direct_ranks'];p.review_mode=data['review_mode']
            p.combine_confirmation=data['combine_confirmation'];p.director_self_request=data['director_self_request']
            from .models import PurchasePermission
            for person in [p.dev_director,p.production_director]:PurchasePermission.objects.update_or_create(user=person,defaults={'view_completed':True})
        else:p.approval_modes={rank:data[f'rank_{i}'] for i,rank in enumerate(RANKS)}
        p.version+=1;p.save();p.finance.set(data['finance'])
        if p.enabled:validate_policy_people(p)
        event(actor,'구매 규정 변경',detail=f'버전 {p.version} / 검토 경로: {p.review_mode} / 직접 요청 직급: {p.direct_ranks} / 개발팀 담당 {p.dev_director_id} / 그 외 담당 {p.production_director_id} / 승인 시 함께 확인 {p.combine_confirmation} / 이사 직접 요청 {p.director_self_request}\n사유: {data["reason"]}')
        return p


class SupplementForm(forms.Form):
    revision=forms.IntegerField(widget=forms.HiddenInput)
    reason=forms.CharField(label='구매 사유 보완',widget=forms.Textarea(attrs={'rows':4}),max_length=10000)
    url=forms.URLField(label='구매 링크 · 선택',required=False,max_length=1000)
    response=forms.CharField(label='보완한 내용',max_length=1000,widget=forms.Textarea(attrs={'rows':3}))
    files=MultipleFileField(label='보완 자료 · 선택',required=False,widget=MultipleFileInput())


class AmountChangeForm(forms.Form):
    revision=forms.IntegerField(widget=forms.HiddenInput)
    quantity=forms.IntegerField(label='변경 수량',min_value=1,max_value=999999)
    unit_price=WonField(label='변경 단가 · 부가세 포함',max_digits=14,decimal_places=2,min_value=Decimal('0.01'),max_value=Decimal('999999999.99'))
    reason=forms.CharField(label='변경 사유',max_length=1000,widget=forms.Textarea(attrs={'rows':3}))


class IntegratedPolicyForm(PolicyForm):
    """Routes only; personnel are exclusively managed on the shared staff page."""
    review_final_users=PersonMultiple(label='승인완료 가능한 검토자 · 과장급 이상',queryset=get_user_model().objects.none(),required=False,widget=forms.CheckboxSelectMultiple)
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        for name in ['dev_director','production_director','finance','representative']:self.fields.pop(name)
        self.fields.pop('review_mode',None)
        from workflow.people import review_final_people
        self.fields['review_final_users'].queryset=review_final_people()
        self.initial['review_final_users']=list(self.instance.review_final_users.values_list('pk',flat=True))
    def clean(self):
        data=super().clean()
        p=self.instance
        data.update(dev_director=p.dev_director,production_director=p.production_director,finance=list(p.finance.all()),representative=p.representative,review_mode='review_approval')
        return data
    @transaction.atomic
    def save(self,actor):
        p=super().save(actor)
        before=list(p.review_final_users.values_list('pk',flat=True));people=self.cleaned_data['review_final_users']
        p.review_final_users.set(people)
        event(actor,'구매 검토 승인완료 권한 변경',detail=f'{before} → {[u.pk for u in people]} / {self.cleaned_data["reason"]}')
        return p


class PurchaseForwardForm(forms.Form):
    new_person_department=department_picker('new_person')
    new_person=PersonChoice(label='승인자',queryset=get_user_model().objects.none(),widget=DepartmentEmployeeSelect())
    def __init__(self,*args,document,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['new_person'].queryset=forward_people(document)
        if document.reviewer_id:self.initial['new_person_department']=document.reviewer.profile.department
    def clean(self):
        data=super().clean();person=data.get('new_person');department=data.get('new_person_department')
        if person and department and person.profile.department!=department:self.add_error('new_person','선택한 부서에 속한 승인자를 지정해 주세요.')
        return data


class PurchaseAssignmentsForm(forms.Form):
    dev_director=PersonChoice(label='개발팀 구매 내용 확인',queryset=get_user_model().objects.none())
    production_director=PersonChoice(label='그 외 부서 구매 내용 확인',queryset=get_user_model().objects.none())
    finance=PersonMultiple(label='구매 담당자 · 품목 선택 및 대표에게 요청',queryset=get_user_model().objects.none(),widget=forms.CheckboxSelectMultiple)
    representative=PersonChoice(label='구매승인 대표',queryset=get_user_model().objects.none())
    revision=forms.IntegerField(widget=forms.HiddenInput)
    reason=forms.CharField(label='변경 사유',max_length=1000,widget=forms.Textarea(attrs={'rows':2}))
    def __init__(self,*args,**kwargs):
        from .access import policy
        super().__init__(*args,**kwargs);self.instance=policy()
        people=get_user_model().objects.filter(is_active=True,profile__approved=True,profile__department_confirmed=True).select_related('profile')
        for name,dept in [('dev_director','개발팀'),('production_director','생산팀')]:self.fields[name].queryset=people.filter(profile__representative_slot__isnull=True,profile__rank='이사',profile__department=dept)
        self.fields['representative'].queryset=people.filter(profile__representative_slot=1,profile__representative_can_approve=True)
        self.fields['finance'].queryset=people.filter(profile__representative_slot__isnull=True)
        p=self.instance
        if p:self.initial.update(revision=p.version,dev_director=p.dev_director_id,production_director=p.production_director_id,finance=list(p.finance.values_list('pk',flat=True)),representative=p.representative_id)
    @transaction.atomic
    def save(self,actor):
        from .models import PurchasePermission,PurchaseReport
        p=lock_policy();actor=actor_now(actor)
        if not is_admin(actor):raise ValidationError('직원 권한관리 권한이 필요합니다.')
        data=self.cleaned_data
        if data['revision']!=p.version:raise ValidationError('설정이 변경됐습니다. 새로고침 후 다시 저장해 주세요.')
        selected={u.pk for u in data['finance']};removed=set(p.finance.values_list('pk',flat=True))-selected
        if removed:
            for d in PurchaseRequest.objects.filter(status__in=['ready','supplement','reapproval','ceo','allowed','paid','hold']).exclude(confirmed_at=None).only('purchase_route'):
                if removed.intersection(d.purchase_route.get('collector_ids',[])):raise ValidationError('진행·수령 대기 문서가 있는 구매 담당자는 처리가 끝난 뒤 권한을 해제해 주세요.')
        if p.representative_id!=data['representative'].pk and PurchaseReport.objects.filter(status='pending',representative_id=p.representative_id).exists():raise ValidationError('현재 대표의 구매승인 대기 문서를 먼저 처리해 주세요.')
        before=f'개발 {p.dev_director_id}, 그 외 {p.production_director_id}, 구매 {list(p.finance.values_list("pk",flat=True))}, 대표 {p.representative_id}'
        for name in ['dev_director','production_director','representative']:setattr(p,name,data[name])
        p.finance.set(data['finance'])
        for u in [p.dev_director,p.production_director]:PurchasePermission.objects.update_or_create(user=u,defaults={'view_completed':True})
        if p.enabled:validate_policy_people(p)
        p.version+=1;p.save()
        event(actor,'구매 업무 담당자·권한 변경',detail=f'이전 {before}\n변경 사유: {data["reason"]}')
        return p
