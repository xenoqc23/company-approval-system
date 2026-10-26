"""One compose screen; leave/stock and purchase keep their own validators and records."""
from django.urls import reverse
from django.utils import timezone
from workflow.models import Document
from workflow.forms import DocumentForm
from .forms import RequestForm
from .access import policy


def workflow_form(user):
    form=DocumentForm(instance=Document(owner=user),initial=dict(kind='leave',recipient=user.pk,
        quantity=1,urgency='normal',start_date=timezone.localdate(),end_date=timezone.localdate()))
    form.fields['kind'].choices=[(key,label) for key,label in Document.KINDS if key!='office']
    return form


def render_compose(request,*,document_form=None,purchase_form=None,kind='leave',existing_files=(),purchase_pk=None):
    from workflow.views import page
    p=policy()
    document_form=document_form or workflow_form(request.user)
    purchase_form=purchase_form or RequestForm(user=request.user,policy=p,prefix='purchase')
    return page(request,'unified_compose','임시저장 이어쓰기' if purchase_pk else '기안 작성','compose',
        form=document_form,purchase_form=purchase_form,compose_kind=kind,kind_locked=bool(purchase_pk),
        unified_compose=True,existing_files=existing_files,
        purchase_action=reverse('purchasing:edit',args=[purchase_pk]) if purchase_pk else reverse('compose'),
        purchase_configured=bool(p and p.enabled and p.dev_director_id and p.production_director_id and p.representative_id and p.finance.exists()))
