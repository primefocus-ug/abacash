"""
This app lives in the public schema (see README.md) and deliberately does
NOT introduce a second login system. It reuses the same session-based
PlatformAdmin authentication that tenants.views.public_admin_login already
sets up (see tenants/auth.py), so an operator who's logged into the tenants
app's public admin panel is automatically authenticated here too, and vice
versa.

`require_public_admin` is kept as the public name of this decorator (rather
than renaming every call site to `platform_admin_required`) since it mirrors
the existing `tenants:public_admin` login flow this app's views redirect to.
"""
from tenants.auth import platform_admin_required as require_public_admin

__all__ = ["require_public_admin"]
