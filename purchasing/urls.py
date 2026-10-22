from django.urls import path
from . import views
app_name='purchasing'
urlpatterns=[
 path('',views.home,name='home'),path('login/',views.login_view,name='login'),path('logout/',views.logout_view,name='logout'),
 path('switch/',views.switch,name='switch'),path('requests/',views.request_list,name='requests'),
 path('new/',views.compose,name='new'),path('draft/<int:pk>/',views.compose,name='edit'),
 path('requests/<int:pk>/',views.detail,name='detail'),path('requests/<int:pk>/action/',views.act,name='action'),
 path('reports/new/',views.report_new,name='report_new'),path('reports/',views.report_list,name='reports'),
 path('reports/<int:pk>/',views.report_detail,name='report_detail'),path('rules/',views.regulations,name='regulations'),
 path('staff/',views.staff_permissions,name='staff'),path('requests/<int:pk>/attachments/',views.upload_attachments,name='attachments'),path('attachments/<int:pk>/download/',views.download_attachment,name='attachment_download'),path('requests/<int:pk>/location/',views.update_location,name='location'),path('status/',views.status,name='status'),path('similar/',views.hints,name='hints')]
