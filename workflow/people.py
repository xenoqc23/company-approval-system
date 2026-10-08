from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Case, IntegerField, Value, When
from .models import DEPARTMENTS, RANKS


def rank_order(queryset, person_prefix=''):
    """Highest rank first, then name; keep document dates within each employee."""
    rank_field = f'{person_prefix}profile__rank'
    ordering = [f'{person_prefix}first_name', f'{person_prefix}username']
    if person_prefix:
        ordering += ['-created_at', '-pk']
    return queryset.annotate(_rank_order=Case(
        *[When(**{rank_field: rank}, then=Value(index))
          for index, rank in enumerate(reversed(RANKS))],
        default=Value(len(RANKS)), output_field=IntegerField(),
    )).order_by('_rank_order', *ordering)


def approval_people():
    return rank_order(get_user_model().objects.filter(
        is_active=True, is_superuser=False, profile__approved=True,
        profile__department_confirmed=True, profile__department__in=DEPARTMENTS,
        profile__rank__in=RANKS[1:], profile__manage_system=False,
    ).exclude(username__iexact='admin').select_related('profile'))


def validate_approval_person(person):
    if person and not approval_people().filter(pk=person.pk).exists():
        raise ValidationError('검토자·승인자는 admin 계정을 제외한 주임 이상 직원만 지정할 수 있습니다.')
