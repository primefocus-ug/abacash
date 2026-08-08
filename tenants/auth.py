"""
Authentication for PlatformAdmin — the system-admin account used to log
into /public-admin/.

Deliberately separate from django.contrib.auth: AUTH_USER_MODEL is already
set to the tenant-scoped accounts.User, and Django only supports one
swappable user model per project, so PlatformAdmin can't be authenticated
with authenticate()/login(). This module does the same job by hand:
Django's own password hashers for storage/verification, and a normal
server-side session (django.contrib.sessions must be in SHARED_APPS so the
django_session table exists in the public schema — see settings.py) to
track the logged-in state instead of re-checking credentials every request.
"""
from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect
from django.utils import timezone

from .models import PlatformAdmin

SESSION_KEY = "platform_admin_id"


def authenticate_platform_admin(username_or_email, password):
    """Look up a PlatformAdmin by username or email and verify the password.
    Returns the PlatformAdmin instance on success, or None on any failure.
    Deliberately vague on which part (user vs. password) was wrong."""
    username_or_email = (username_or_email or "").strip()
    if not username_or_email or not password:
        return None

    admin = PlatformAdmin.objects.filter(username__iexact=username_or_email).first()
    if admin is None:
        admin = PlatformAdmin.objects.filter(email__iexact=username_or_email).first()
    if admin is None:
        return None
    if not admin.is_active:
        return None
    if not admin.check_password(password):
        return None
    return admin


def login_platform_admin(request, admin):
    """Start a session for this platform admin. Rotates the session key so a
    pre-login session id can't be reused post-login (session fixation)."""
    request.session.cycle_key()
    request.session[SESSION_KEY] = admin.pk
    admin.last_login = timezone.now()
    admin.save(update_fields=["last_login"])


def logout_platform_admin(request):
    request.session.flush()


def get_platform_admin(request):
    """Return the logged-in PlatformAdmin for this request, or None."""
    admin_id = request.session.get(SESSION_KEY)
    if not admin_id:
        return None
    return PlatformAdmin.objects.filter(pk=admin_id, is_active=True).first()


def platform_admin_required(view_func):
    """Require a logged-in PlatformAdmin. Attaches request.platform_admin."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        admin = get_platform_admin(request)
        if admin is None:
            return redirect("tenants:public_admin_login")
        request.platform_admin = admin
        return view_func(request, *args, **kwargs)
    return wrapper


def superadmin_required(view_func):
    """Require a logged-in PlatformAdmin with the SUPERADMIN role."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        admin = get_platform_admin(request)
        if admin is None:
            return redirect("tenants:public_admin_login")
        request.platform_admin = admin
        if not admin.is_superadmin:
            messages.error(request, "Only super admins can do that.")
            return redirect("tenants:public_admin")
        return view_func(request, *args, **kwargs)
    return wrapper
