from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordChangeForm, UserCreationForm
from .models import DEPARTMENTS, RANKS, Document

User = get_user_model()

class ProfilePasswordForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['old_password'].label = '현재 비밀번호'
        for field in self.fields.values():
            field.help_text = ''

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

class EmployeeChoice(forms.ModelChoiceField):
    def label_from_instance(self, user):
        return f'{user.first_name} · {user.profile.department} {user.profile.rank}'

class DocumentForm(forms.ModelForm):
    reviewer = EmployeeChoice(label='검토자', queryset=User.objects.none(), required=False)
    approver = EmployeeChoice(label='최종 승인자', queryset=User.objects.none(), required=False)
    recipient = EmployeeChoice(label='물품 수령자', queryset=User.objects.none(), required=False)

    class Meta:
        model = Document
        fields = ['kind', 'leave_type', 'start_date', 'end_date', 'start_time', 'end_time', 'reason',
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
        people = User.objects.filter(is_active=True, profile__approved=True).select_related('profile').order_by('first_name')
        for key in ['reviewer', 'approver', 'recipient']:
            self.fields[key].queryset = people
        for f in self.fields.values():
            f.required = False
        self.fields['kind'].required = True
        self.fields['quantity'].initial = 1

    def clean(self):
        data = super().clean()
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
                data['unit_price'], data['approver'], data['url'] = 0, None, ''
        if self.submit:
            required = ['reviewer']
            if data.get('kind') != 'stock':
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
