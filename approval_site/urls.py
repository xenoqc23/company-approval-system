from django.urls import include, path

urlpatterns = [path('', include('workflow.urls'))]

from django.conf import settings
if settings.PURCHASE_LAB_ENABLED:
    urlpatterns.insert(0,path('purchase-lab/', include('purchasing.urls')))
