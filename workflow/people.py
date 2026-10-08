from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from .models import DEPARTMENTS, RANKS


def approval_people():
    return get_user_model().objects.filter(
        is_active=True, is_superuser=False, profile__approved=True,
        profile__department_confirmed=True, profile__department__in=DEPARTMENTS,
        profile__rank__in=RANKS[1:], profile__manage_system=False,
    ).exclude(username__iexact='admin').select_related('profile').order_by('first_name', 'username')


def validate_approval_person(person):
    if person and not approval_people().filter(pk=person.pk).exists():
        raise ValidationError('검토자·승인자는 admin 계정을 제외한 주임 이상 직원만 지정할 수 있습니다.')
