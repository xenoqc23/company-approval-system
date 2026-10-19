from django.db.models import Q
from django.urls import reverse
from .models import Document, NotificationPreference
from .notifications import visible_notices


def waiting_documents(user):
    return Document.objects.filter(Q(status='review',reviewer=user)|Q(status='approve',approver=user)|
                                   Q(status='executive',representative=user))


def live_summary(user,after=None):
    from .accounting import accounting_tabs
    from .services import visible_documents
    notices=visible_notices(user)
    latest=notices.order_by('-pk').values_list('pk',flat=True).first() or 0
    incoming=[]
    if after is not None:
        rows=list(notices.filter(pk__gt=after,read=False).order_by('pk')[:21])
        accessible=set(visible_documents(user).filter(pk__in=[n.document_id for n in rows]).values_list('pk',flat=True))
        incoming=[dict(id=n.pk,text=n.display_text,url=reverse('detail',args=[n.document_id])
                       if n.document_id in accessible else reverse('notices')) for n in rows[:20]]
    tabs=accounting_tabs(user) if user.profile.view_accounting else []
    pref=NotificationPreference.objects.filter(user=user).first()
    return dict(user=user.pk,unread=notices.filter(read=False).count(),waiting=waiting_documents(user).count(),
                accounting_unread=tabs[0]['unread_count'] if tabs else 0,tabs=tabs,latest=latest,
                cursor=incoming[-1]['id'] if incoming else latest,events=incoming,
                preferences=dict(popup=pref.popup if pref else True,sound=pref.sound if pref else False))
