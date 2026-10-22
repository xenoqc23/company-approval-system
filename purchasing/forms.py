from uuid import uuid4
from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from workflow.models import RANKS
from .models import PurchaseRequest,PurchasePolicy,MODES,dev_modes,other_modes
from .access import is_admin
from .services import eligible_people,mode_for,validate_policy_people,event,actor_now,lock_policy
from django.db import transaction


class PersonChoice(forms.ModelChoiceField):
    def label_from_instance(self,obj):return f'{obj.first_name} · {obj.profile.department} {obj.profile.rank}'


class PersonMultiple(forms.ModelMultipleChoiceField):
    def label_from_instance(self,obj):return f'{obj.first_name} · {obj.profile.department} {obj.profile.rank}'


class RequestForm(forms.ModelForm):
    key=forms.UUIDField(widget=forms.HiddenInput,initial=uuid4)
    reviewer=PersonChoice(label='검토자',queryset=get_user_model().objects.none(),required=False)
    approver=PersonChoice(label='중간 승인자',queryset=get_user_model().objects.none(),required=False)
    class Meta:
        model=PurchaseRequest
        fields=['product','vendor','quantity','unit_price','url','reason','private']
        labels=dict(product='구매 품목·모델명·규격',vendor='구매처',quantity='수량',unit_price='개당 금액 · 부가세 포함',url='구매 링크 · 선택',reason='구매 사유',private='유사 구매 안내에서 제외 · 기밀 구매')
        widgets=dict(reason=forms.Textarea(attrs={'rows':4}),quantity=forms.NumberInput(attrs={'min':1,'max':999999}),
                     unit_price=forms.NumberInput(attrs={'min':'.01','max':'999999999.99','step':'.01'}),
                     product=forms.TextInput(attrs={'placeholder':'예: 27인치 모니터 / 모델명'}),vendor=forms.TextInput(attrs={'placeholder':'업체명 또는 쇼핑몰명'}))
    def __init__(self,*args,user,policy,**kwargs):
        super().__init__(*args,**kwargs)
        self.mode=mode_for(policy,user) if policy else 'direct'
        director=policy.dev_director if policy and user.profile.department=='개발팀' else policy.production_director if policy else None
        qs=eligible_people(user)
        if director:qs=qs.exclude(pk=director.pk)
        minimum=RANKS.index(user.profile.rank) if user.profile.rank in RANKS else len(RANKS)
        qs=qs.filter(profile__rank__in=RANKS[minimum:])
        self.fields['reviewer'].queryset=qs
        self.fields['approver'].queryset=qs
        self.fields['reviewer'].required=self.mode=='review_approval'
        self.fields['approver'].required=self.mode in ['approval','review_approval']
        if self.instance.pk:self.initial['key']=self.instance.request_key


class PolicyForm(forms.Form):
    enabled=forms.BooleanField(label='이 구매 규정 사용',required=False)
    dev_director=PersonChoice(label='개발팀 최종승인 이사',queryset=get_user_model().objects.none())
    production_director=PersonChoice(label='그 외 부서 최종승인 이사',queryset=get_user_model().objects.none())
    representative=PersonChoice(label='품목별 구매허가 대표',queryset=get_user_model().objects.none())
    finance=PersonMultiple(label='경리 취합 담당자',queryset=get_user_model().objects.none(),widget=forms.CheckboxSelectMultiple)
    revision=forms.IntegerField(widget=forms.HiddenInput)
    reason=forms.CharField(label='변경 사유',max_length=1000,widget=forms.Textarea(attrs={'rows':2}))
    def __init__(self,*args,instance,**kwargs):
        super().__init__(*args,**kwargs);self.instance=instance
        users=get_user_model().objects.filter(is_active=True,profile__approved=True).select_related('profile').order_by('first_name','pk')
        for key,dept in [('dev_director','개발팀'),('production_director','생산팀')]:
            self.fields[key].queryset=users.filter(profile__department=dept,profile__rank='이사',profile__representative_slot__isnull=True,profile__department_confirmed=True).exclude(username='admin')
        self.fields['representative'].queryset=users.filter(profile__representative_slot=1)
        self.fields['finance'].queryset=users.filter(profile__representative_slot__isnull=True).exclude(username='admin')
        for prefix,default in [('dev',dev_modes()),('other',other_modes())]:
            modes=getattr(instance,'development_modes' if prefix=='dev' else 'other_modes',None) or default
            for i,rank in enumerate(RANKS):
                key=f'{prefix}_{i}';self.fields[key]=forms.ChoiceField(label=rank,choices=MODES,initial=modes.get(rank,default[rank]))
        if instance:
            self.initial.update(enabled=instance.enabled,dev_director=instance.dev_director_id,
                production_director=instance.production_director_id,representative=instance.representative_id,
                finance=list(instance.finance.values_list('pk',flat=True)),revision=instance.version)
    @transaction.atomic
    def save(self,actor):
        p=lock_policy();actor=actor_now(actor)
        if not is_admin(actor):raise forms.ValidationError('관리자만 규정을 바꿀 수 있습니다.')
        data=self.cleaned_data
        if data['revision']!=p.version:raise forms.ValidationError('다른 창에서 규정이 바뀌었습니다. 새로고침해 주세요.')
        p.enabled=data['enabled'];p.dev_director=data['dev_director'];p.production_director=data['production_director'];p.representative=data['representative']
        p.development_modes={rank:data[f'dev_{i}'] for i,rank in enumerate(RANKS)}
        p.other_modes={rank:data[f'other_{i}'] for i,rank in enumerate(RANKS)}
        p.version+=1;p.save();p.finance.set(data['finance'])
        if p.enabled:validate_policy_people(p)
        event(actor,'구매 규정 변경',detail=f'버전 {p.version} / 개발팀: {p.development_modes} / 그 외: {p.other_modes}\n사유: {data["reason"]}')
        return p
