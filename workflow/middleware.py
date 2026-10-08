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
        return self.get_response(request)
