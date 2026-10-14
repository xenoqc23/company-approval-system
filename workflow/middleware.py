from django.shortcuts import redirect

class AccountGateMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and not request.path.startswith('/static/'):
            allowed = {'/login/', '/logout/', '/signup/', '/password/', '/pending/', '/health/'}
            profile = request.user.profile
            if not profile.approved and request.path not in allowed:
                return redirect('pending')
            if profile.must_change_password and request.path not in allowed:
                return redirect('password')
            if profile.approved and request.path not in allowed:
                from .annual_grants import sync_annual_grants
                sync_annual_grants()
        return self.get_response(request)
