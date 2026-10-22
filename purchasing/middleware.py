from django.shortcuts import redirect
from django.http import HttpResponseForbidden


class PurchaseLabGateMiddleware:
    """Selected only by a non-production flag, with different browser cookies and DB."""
    def __init__(self,get_response):self.get_response=get_response
    def __call__(self,request):
        if request.path.startswith('/static/') or request.path=='/health/':return self.get_response(request)
        if not request.path.startswith('/purchase-lab/'):
            return redirect('purchasing:home')
        if request.user.is_authenticated:
            if not request.user.is_active or not request.user.profile.approved:
                return HttpResponseForbidden('사용할 수 없는 계정입니다.')
        return self.get_response(request)
