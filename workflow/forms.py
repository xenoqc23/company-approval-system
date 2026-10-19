from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordChangeForm, UserCreationForm
from .models import DEPARTMENTS, RANKS, Document, Absence, CompanyHoliday
from .people import approval_people, rank_order

User = get_user_model()

class ProfilePasswordForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['old_password'].label = '현재 비밀번호'
        for field in self.fields.values():
            field.help_text = ''


class AbsenceForm(forms.ModelForm):
    class Meta:
        model = Absence
        fields = ['reason', 'start_date', 'end_date', 'all_day', 'start_time', 'end_time']
        labels = {'reason': '부재 사유', 'start_date': '시작일', 'end_date': '종료일',
                  'all_day': '종일', 'start_time': '시작 시간', 'end_time': '종료 시간'}
        widgets = {**{k: forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d') for k in ['start_date', 'end_date']},
                   **{k: forms.TimeInput(attrs={'type': 'time'}) for k in ['start_time', 'end_time']}}

    def clean(self):
        data = super().clean()
        start, end = data.get('start_date'), data.get('end_date')
        if start and end and (end < start or not 2000 <= start.year <= end.year <= 2100):
            raise forms.ValidationError('시작·종료 날짜를 확인해 주세요.')
        if data.get('all_day'):
            data['start_time'] = data['end_time'] = None
        elif not data.get('start_time') or not data.get('end_time'):
            raise forms.ValidationError('시간을 입력하거나 종일을 선택해 주세요.')
        elif start == end and data['end_time'] <= data['start_time']:
            raise forms.ValidationError('종료 시간은 시작 시간 이후여야 합니다.')
        return data


class CompanyHolidayForm(forms.ModelForm):
    class Meta:
        model = CompanyHoliday
        fields = ['title', 'day', 'use_annual', 'description']
        labels = {'title': '휴무명', 'day': '휴무 날짜', 'use_annual': '공용연차 사용 (직원별 1일 차감)', 'description': '설명'}
        widgets = {'day': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')}

    def clean_day(self):
        day = self.cleaned_data['day']
        if not 2000 <= day.year <= 2100:
            raise forms.ValidationError('휴무 연도는 2000~2100년으로 입력해 주세요.')
        return day


class HireDateForm(forms.Form):
    hire_date = forms.DateField(label='입사일', widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'))


def birthday_fields(required=False):
    return {
        'birthday_calendar': forms.ChoiceField(label='생일 기준', choices=[('solar', '양력'), ('lunar', '음력')],
            initial='solar', widget=forms.Select(attrs={'data-birthday-calendar': ''})),
        'birthday_month': forms.TypedChoiceField(label='생일 월', required=required, coerce=int, empty_value=None,
            choices=[('', '월 선택')] + [(month, f'{month}월') for month in range(1,13)]),
        'birthday_day': forms.TypedChoiceField(label='생일 일', required=required, coerce=int, empty_value=None,
            choices=[('', '일 선택')] + [(day, f'{day}일') for day in range(1,32)]),
        'birthday_lunar_leap': forms.BooleanField(label='음력 윤달 생일', required=False,
            widget=forms.CheckboxInput(attrs={'data-birthday-leap': ''})),
    }


def clean_birthday(data):
    from .birthdays import birthday_values
    return birthday_values(data.get('birthday_month'), data.get('birthday_day'),
        data.get('birthday_calendar', 'solar'), data.get('birthday_lunar_leap', False))


class BirthdayForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields.update(birthday_fields())

    def clean(self):
        data = super().clean()
        if not self.errors:
            data.update(clean_birthday(data))
        return data

class ManualLeaveForm(forms.Form):
    used_date = forms.DateField(label='실제 사용 날짜', widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'))
    leave_type = forms.ChoiceField(label='휴가 종류 · 사용 일수', choices=[
        ('annual', '연차 · 1일'), ('am', '오전반차 · 0.5일'), ('pm', '오후반차 · 0.5일'), ('outing', '외출 · 0.25일')])
    start_time = forms.TimeField(label='시작 시간 (반차·외출)', required=False, widget=forms.TimeInput(attrs={'type': 'time'}))
    end_time = forms.TimeField(label='종료 시간 (반차·외출)', required=False, widget=forms.TimeInput(attrs={'type': 'time'}))
    reason = forms.CharField(label='등록 사유', max_length=1000, widget=forms.Textarea(attrs={
        'rows': 3, 'placeholder': '예: 종이 신청서로 접수한 연차'}))
    request_key = forms.UUIDField(widget=forms.HiddenInput)

    def clean(self):
        data = super().clean()
        if not self.errors:
            from .manual_leave import validate_values
            data.update(validate_values(data))
        return data

class SignupForm(UserCreationForm):
    first_name = forms.CharField(label='이름', max_length=80)
    department = forms.ChoiceField(label='부서', choices=[(x, x) for x in DEPARTMENTS])
    rank = forms.ChoiceField(label='직급', choices=[(x, x) for x in RANKS])

    class Meta:
        model = User
        fields = ['first_name', 'username', 'password1', 'password2', 'department', 'rank']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].label = '아이디'
        self.fields['password1'].label = '비밀번호'
        self.fields['password2'].label = '비밀번호 확인'
        for field in self.fields.values():
            field.help_text = ''
        self.fields.update(birthday_fields(required=True))

    def clean(self):
        data = super().clean()
        if not any(key.startswith('birthday_') for key in self.errors):
            data.update(clean_birthday(data))
        return data

class EmployeeChoice(forms.ModelChoiceField):
    def label_from_instance(self, user):
        return f'{user.first_name} · {user.profile.department} {user.profile.rank}'

class EmployeeMultipleChoice(forms.ModelMultipleChoiceField):
    def label_from_instance(self, user):
        return f'{user.first_name} · {user.profile.department} {user.profile.rank}'

class DepartmentEmployeeSelect(forms.Select):
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        if value:
            option['attrs']['data-department'] = value.instance.profile.department
            option['attrs']['data-rank'] = value.instance.profile.rank
        return option

def department_picker(person_field):
    return forms.ChoiceField(label='부서', required=False, choices=[('', '부서를 선택하세요')] + [(x, x) for x in DEPARTMENTS],
        widget=forms.Select(attrs={'data-department-picker': '', 'data-person-field': f'id_{person_field}'}))

class ApprovalAssignmentForm(forms.Form):
    new_person_department = department_picker('new_person')
    new_person = EmployeeChoice(label='새 담당자', queryset=User.objects.none(), widget=DepartmentEmployeeSelect())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['new_person'].queryset = approval_people()

class DocumentForm(forms.ModelForm):
    reviewer_department = department_picker('reviewer')
    approver_department = department_picker('approver')
    reviewer = EmployeeChoice(label='검토자', queryset=User.objects.none(), required=False, widget=DepartmentEmployeeSelect())
    approver = EmployeeChoice(label='최종 승인자', queryset=User.objects.none(), required=False, widget=DepartmentEmployeeSelect())
    recipient = EmployeeChoice(label='물품 수령자', queryset=User.objects.none(), required=False)

    class Meta:
        model = Document
        fields = ['approval_mode', 'kind', 'leave_type', 'start_date', 'end_date', 'start_time', 'end_time', 'reason',
                  'product', 'quantity', 'unit_price', 'url', 'urgency', 'needed_date', 'reviewer', 'approver', 'recipient']
        widgets = {x: forms.DateInput(attrs={'type': 'date'}) for x in ['start_date', 'end_date', 'needed_date']}
        widgets.update({x: forms.TimeInput(attrs={'type': 'time'}) for x in ['start_time', 'end_time']})
        widgets.update({'reason': forms.Textarea(attrs={'rows': 4, 'placeholder': '신청 내용을 입력해 주세요.'}),
                        'product': forms.TextInput(attrs={'placeholder': '예: A4 복사용지'}),
                        'url': forms.URLInput(attrs={'placeholder': 'https://'}),
                        'quantity': forms.NumberInput(attrs={'min': 1}),
                        'unit_price': forms.NumberInput(attrs={'min': 0, 'step': '0.01'})})
        labels = {'kind': '문서 종류', 'leave_type': '휴가 종류', 'start_date': '시작일', 'end_date': '종료일',
                  'start_time': '시작 시간', 'end_time': '종료 시간', 'reason': '신청 사유',
                  'product': '품목', 'quantity': '수량', 'unit_price': '개당 가격 (부가세 포함)',
                  'url': '구매 사이트 링크', 'urgency': '긴급도', 'needed_date': '구매 필요 날짜'}

    def __init__(self, *args, submit=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.submit = submit
        people = rank_order(User.objects.filter(is_active=True, profile__approved=True,
            profile__representative_slot__isnull=True).select_related('profile'))
        self.fields['recipient'].queryset = people
        for key in ['reviewer', 'approver']:
            self.fields[key].queryset = approval_people()
            self.fields[f'{key}_department'].widget.attrs['data-person-field'] = self[key].auto_id
            selected_id = self.data.get(self.add_prefix(key)) if self.is_bound else getattr(self.instance, f'{key}_id', None)
            selected = self.fields[key].queryset.filter(pk=selected_id).first() if str(selected_id or '').isdigit() else None
            if selected:
                self.initial[f'{key}_department'] = selected.profile.department
        for f in self.fields.values():
            f.required = False
        self.fields['kind'].required = True
        self.fields['quantity'].initial = 1
        from .delegation import simplified_eligible
        self.simplified_eligible = simplified_eligible(self.instance.owner) if self.instance.owner_id else False
        self.fields['approval_mode'].label = '결재방식'
        self.fields['approval_mode'].required = False
        self.fields['approval_mode'].initial = 'base'
        if not self.is_bound and self.instance.owner_id:
            from .delegation import resolve_route
            kind = self.initial.get('kind', self.instance.kind)
            try:
                route = resolve_route(kind, self.instance.owner.profile.rank, self.instance.total_price, owner=self.instance.owner)
            except forms.ValidationError:
                route = {'available_modes': ['base']}  # Preview and submission show the actionable rule error.
            self.fields['approval_mode'].choices = [(key, label) for key, label in self.fields['approval_mode'].choices if key in route['available_modes']]
            for stage in ['reviewer', 'approver']:
                fixed = route.get('fixed_' + stage + '_id')
                if fixed and not (route.get('progressive') and stage == 'approver'):
                    person = User.objects.select_related('profile').get(pk=fixed)
                    self.initial[stage] = person.pk
                    self.initial[stage + '_department'] = person.profile.department

        if not self.simplified_eligible:
            self.fields['approval_mode'].choices = [('base', '규정 기본')]
            self.fields['approval_mode'].widget = forms.HiddenInput()

    def clean(self):
        data = super().clean()
        data['approval_mode'] = data.get('approval_mode') or 'base'
        route = None
        if self.instance.owner_id and data.get('kind'):
            from .delegation import resolve_route
            try:
                route = resolve_route(data['kind'], self.instance.owner.profile.rank,
                    (data.get('quantity') or 1) * (data.get('unit_price') or 0),
                    owner=self.instance.owner, mode=data['approval_mode'])
                for stage in ['reviewer', 'approver']:
                    fixed = route.get('fixed_' + stage + '_id')
                    if fixed and not (route.get('progressive') and route['mode'] == 'base' and stage == 'approver'):
                        data[stage] = User.objects.select_related('profile').get(pk=fixed)
                        data[stage + '_department'] = data[stage].profile.department
                if route['skip_review']:
                    data['reviewer'] = None
            except forms.ValidationError as exc:
                self.add_error(None, exc)
        for key in ['reviewer', 'approver']:
            person, department = data.get(key), data.get(f'{key}_department')
            if person and department and person.profile.department != department:
                self.add_error(key, '선택한 부서에 속한 직원을 지정해 주세요.')
        if data.get('kind') == 'leave' and data.get('leave_type') != 'annual':
            data['end_date'] = data.get('start_date')
        if data.get('kind') == 'leave':
            data['quantity'], data['unit_price'] = 1, 0
            if data.get('leave_type') == 'annual':
                data['start_time'] = data['end_time'] = None
        else:
            data['leave_type'] = 'annual'
            data['start_date'] = data['end_date'] = data['start_time'] = data['end_time'] = None
            data['quantity'] = data.get('quantity') if data.get('quantity') is not None else 1
            data['unit_price'] = data.get('unit_price') or 0
            if data.get('kind') == 'stock':
                data['unit_price'], data['url'] = 0, ''
                if not route or not route.get('stock_final_approval'):
                    data['approver'] = None
        if route and route.get('progressive'):
            if route['mode'] == 'base':
                data['approver'] = None
            if route['mode'] == 'ceo':
                data['reviewer'] = data['approver'] = None
            if self.submit and data.get('kind'):
                from .progressive import prepare
                temp = Document(owner=self.instance.owner, **{k:data.get(k) for k in ['kind','leave_type','start_date','end_date','start_time','end_time','quantity','unit_price']})
                temp.approver = data.get('approver')
                try:
                    prepare(temp,route)
                except forms.ValidationError as exc:
                    self.add_error(None,exc)
        if self.submit:
            required = ['reviewer']
            if route and route['skip_review']:
                data['reviewer'] = None
                required = []
            if (data.get('kind') != 'stock' or (route and route.get('stock_final_approval'))) and not (route and route.get('progressive') and route['mode'] in ['base','ceo']):
                required += ['approver']
            if data.get('kind') == 'leave':
                required += ['leave_type', 'start_date', 'end_date', 'reason']
                if data.get('leave_type') != 'annual':
                    required += ['start_time', 'end_time']
            else:
                required += ['product']
                if data.get('kind') == 'office':
                    required += ['url']
            for key in required:
                if not data.get(key):
                    self.add_error(key, '이 항목을 입력해 주세요.')
        return data


class ApprovalRuleForm(forms.ModelForm):
    author_ranks = forms.MultipleChoiceField(label='기안자 직급 (미선택: 전체)', choices=[(x, x) for x in RANKS], required=False,
        widget=forms.CheckboxSelectMultiple)
    reviewer_ranks = forms.MultipleChoiceField(label='검토 가능 직급', choices=[(x, x) for x in RANKS[1:]], required=False,
        widget=forms.CheckboxSelectMultiple)
    approver_ranks = forms.MultipleChoiceField(label='승인 가능 직급', choices=[(x, x) for x in RANKS[1:]],
        widget=forms.CheckboxSelectMultiple)

    author_departments = forms.MultipleChoiceField(label='적용 부서 (미선택: 전체)', choices=[(x, x) for x in DEPARTMENTS], required=False, widget=forms.CheckboxSelectMultiple)
    authors = EmployeeMultipleChoice(label='특정 직원 (미선택: 공통 규정)', queryset=User.objects.none(), required=False, widget=forms.CheckboxSelectMultiple)
    fixed_reviewer = EmployeeChoice(label='검토자 고정 (빈칸: 기안 시 선택)', queryset=User.objects.none(), required=False)
    fixed_approver = EmployeeChoice(label='상위 승인자 고정 (빈칸: 검토자가 선택)', queryset=User.objects.none(), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['authors'].queryset = rank_order(User.objects.filter(is_active=True, profile__approved=True, profile__manage_system=False, profile__representative_slot__isnull=True).exclude(username__iexact='admin').select_related('profile'))
        for stage in ['fixed_reviewer', 'fixed_approver']:
            self.fields[stage].queryset = approval_people()

    class Meta:
        from .models import ApprovalRule
        model = ApprovalRule
        fields = ['name', 'kind', 'amount_over', 'amount_to', 'author_ranks', 'author_departments', 'authors', 'skip_review', 'allow_skip_review', 'allow_self_approval', 'allow_review_final', 'allow_representative_direct', 'reviewer_ranks', 'approver_ranks', 'fixed_reviewer', 'fixed_approver', 'approver_is_author', 'enabled']
        labels = {'name': '규정명', 'kind': '문서 종류', 'amount_over': '구매 총금액 하한 (초과)',
            'amount_to': '구매 총금액 상한 (이하, 빈칸: 제한 없음)', 'skip_review': '기존 고정 결재선에서 검토 생략', 'allow_skip_review': '과장급 이상에게 검토 생략 선택 허용', 'allow_self_approval': '과장급 이상에게 본인 전결 선택 허용', 'allow_review_final': '검토자 전결 허용 (기안자 본인 제외)', 'allow_representative_direct': '팀장급 이상에게 대표 직접 결재 요청 허용', 'approver_is_author': '기존 고정 결재선에서 승인자를 기안자 본인으로 지정', 'enabled': '규정 사용'}

    def clean(self):
        data = super().clean()
        if not data.get('skip_review') and not data.get('reviewer_ranks'):
            self.add_error('reviewer_ranks', '검토 가능 직급을 선택해 주세요.')
        if data.get('approver_is_author') and data.get('fixed_approver'):
            self.add_error('fixed_approver', '기안자 본인과 고정 승인자를 동시에 지정할 수 없습니다.')
        for stage in ['reviewer', 'approver']:
            person = data.get('fixed_' + stage)
            if person and person.profile.rank not in data.get(stage + '_ranks', []):
                self.add_error('fixed_' + stage, '해당 담당자의 직급을 허용 직급에 포함해 주세요.')
        low, high = data.get('amount_over'), data.get('amount_to')
        if low is not None and (low < 0 or (high is not None and high <= low)):
            self.add_error('amount_to', '상한은 하한보다 커야 합니다.')
        return data


class AnnualBandForm(forms.Form):
    years = forms.IntegerField(label='근속 시작 연수 (이상)', min_value=0, max_value=100)
    days = forms.IntegerField(label='연차일수', min_value=0, max_value=999)


class BenefitRuleForm(forms.Form):
    category = forms.CharField(label='구분', max_length=80)
    target = forms.CharField(label='대상·근속 조건', max_length=140)
    amount = forms.IntegerField(label='경조금 (원)', min_value=0, max_value=999999999)
    remark = forms.CharField(label='비고', max_length=100, required=False)


class AwardRuleForm(forms.Form):
    years = forms.IntegerField(label='포상 근속연수', min_value=1, max_value=100)
    reward = forms.CharField(label='포상 내용', max_length=120)


class ApprovalFlowPolicyForm(forms.ModelForm):
    class Meta:
        from .models import ApprovalFlowPolicy
        model = ApprovalFlowPolicy
        fields = ['enabled','leave_threshold','purchase_threshold']
        labels = {'enabled':'새 기안에 단계별 결재 적용','leave_threshold':'대표 결재 요청 선택 기준 · 연차 (일 이상)',
                  'purchase_threshold':'대표 결재 요청 선택 기준 · 구매 총금액 (원 이상, 부가세 포함)'}

    def clean(self):
        data=super().clean()
        for field in ['leave_threshold','purchase_threshold']:
            if data.get(field) is not None and data[field] <= 0:
                self.add_error(field,'0보다 큰 기준을 입력해 주세요.')
        return data
