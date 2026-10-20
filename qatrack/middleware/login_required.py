# taken from from django.http import HttpResponseRedirect
from re import compile
from urllib.parse import quote, urlsplit

from django.conf import settings
from django.http import HttpResponse, HttpResponseRedirect

EXEMPT_URLS = [compile(settings.LOGIN_URL.lstrip('/'))]
if hasattr(settings, 'LOGIN_EXEMPT_URLS'):
    EXEMPT_URLS += [compile(expr) for expr in settings.LOGIN_EXEMPT_URLS]


class LoginRequiredMiddleware:
    """
    Middleware that requires a user to be authenticated to view any page other
    than LOGIN_URL. Exemptions to this requirement can optionally be specified
    in settings via a list of regular expressions in LOGIN_EXEMPT_URLS (which
    you can copy from your urls.py).

    Requires authentication middleware and template context processors to be
    loaded. You'll get an error if they aren't.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):

        if not request.user.is_authenticated:
            path = request.path_info.lstrip('/')
            if not any(m.match(path) for m in EXEMPT_URLS):
                if request.headers.get("HX-Request") == "true":
                    return htmx_login_redirect(request)
                login_url = "%s?next=%s" % (settings.LOGIN_URL, quote(request.get_full_path()))
                return HttpResponseRedirect(login_url)
        return self.get_response(request)


def htmx_login_redirect(request):
    """Send the whole browser to the login page when an htmx request arrives
    after the session has expired.

    A normal redirect would be followed by htmx itself, and the login page
    would be swapped into whatever part of the page made the request. After
    logging in, the user comes back to the page they were on, not to the
    fragment URL the request was for.
    """
    current = urlsplit(request.headers.get("HX-Current-URL", ""))
    # Only the path and query are used, so the login page can't be pointed
    # at another site.
    next_url = current.path + ("?%s" % current.query if current.query else "")
    login_url = "%s?next=%s" % (settings.LOGIN_URL, quote(next_url or "/"))
    response = HttpResponse(status=204)
    response["HX-Redirect"] = login_url
    return response
