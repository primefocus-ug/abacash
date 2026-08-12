def company(request):

    """

    Makes the current tenant and its branding settings available in all templates.

    """

    tenant = getattr(request, "tenant", None)

    settings_obj = None

    if tenant is not None and getattr(tenant, "schema_name", None) not in (None, "public"):

        try:

            from accounts.models import CompanySettings

            settings_obj = CompanySettings.get()

        except Exception:

            settings_obj = None

    return {

        "company": tenant,

        "company_settings": settings_obj,

    }


def active_branch_filter(request):
    """
    Makes the CEO's currently-selected branch (nav switcher) available in
    every template, so any page can show a "you're viewing Branch X" banner
    without each view having to look it up itself.

    Only ever non-None for a logged-in CEO with a branch chosen in the
    switcher — everyone else (including Managers/Cashiers, who aren't
    switch-able) gets None and templates simply won't render the banner.
    """
    user = getattr(request, "user", None)
    if not user or not getattr(user, "is_authenticated", False):
        return {"active_branch_filter": None}
    if not (getattr(user, "is_ceo", False) or getattr(user, "is_superuser", False)):
        return {"active_branch_filter": None}

    session_val = request.session.get("ceo_branch_filter")
    if not session_val:
        return {"active_branch_filter": None}

    try:
        from accounts.models import Branch
        branch = Branch.objects.filter(pk=session_val, is_active=True).first()
    except Exception:
        branch = None

    return {"active_branch_filter": branch}