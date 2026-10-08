from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'), path('health/', views.health, name='health'),
    path('login/', views.login_view, name='login'), path('logout/', views.logout_view, name='logout'),
    path('signup/', views.signup, name='signup'), path('pending/', views.pending, name='pending'),
    path('password/', views.password, name='password'), path('documents/', views.documents, name='documents'),
    path('account/', views.account, name='account'),
    path('documents/export/purchases/', views.export_purchases, name='export_purchases'),
    path('documents/accounting/status/', views.accounting_tab_status, name='accounting_tab_status'),
    path('compose/', views.compose, name='compose'), path('compose/<int:pk>/', views.compose, name='edit'),
    path('documents/<int:pk>/', views.detail, name='detail'), path('documents/<int:pk>/action/', views.action, name='action'),
    path('documents/<int:pk>/copy/', views.copy_document, name='copy'), path('balances/', views.balances, name='balances'),
    path('policy/', views.policy, name='policy'), path('notices/', views.notices, name='notices'),
    path('notices/<int:pk>/open/', views.open_notice, name='open_notice'), path('staff/', views.staff, name='staff'),
    path('backups/', views.backups, name='backups'),
]
