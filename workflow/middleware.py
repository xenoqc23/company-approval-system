from django.shortcuts import redirect
from django.http import HttpResponseForbidden

class AccountGateMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and not request.path.startswith('/static/'):
            allowed = {'/login/', '/login/csrf/', '/logout/', '/signup/', '/password/', '/pending/', '/health/'}
            profile = request.user.profile
            if not profile.approved and request.path not in allowed:
                return redirect('pending')
            if profile.must_change_password and request.path not in allowed:
                return redirect('password')
            if profile.is_representative:
                own_account = request.path in {'/account/', '/password/', '/logout/', '/login/', '/login/csrf/', '/notices/'}
                representative_action = (profile.representative_can_approve and request.path.startswith('/documents/')
                    and request.path.endswith('/action/') and request.POST.get('action') in ['approve','reject','cancel_approval'])
                notice_open = request.path.startswith('/notices/') and request.path.endswith('/open/')
                if ((request.method not in {'GET','HEAD','OPTIONS'} and not (own_account or notice_open or representative_action or request.path.startswith('/notifications/')))
                        or request.path.startswith(('/compose/', '/calendar/absence/', '/regulations/', '/balances/recalculate/'))):
                    return HttpResponseForbidden('회사 대표 계정은 현재 조회 전용입니다.')
            if profile.approved and request.path not in allowed:
                from .annual_grants import sync_annual_grants
                sync_annual_grants()
        return self.get_response(request)
