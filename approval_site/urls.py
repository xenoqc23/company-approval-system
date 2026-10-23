from django.urls import include, path

urlpatterns = [path('', include('workflow.urls'))]

from django.conf import settings
if settings.PURCHASE_LAB_ENABLED:
    urlpatterns.insert(0,path('purchases/' if settings.INTEGRATED_PURCHASES else 'purchase-lab/', include('purchasing.urls')))
