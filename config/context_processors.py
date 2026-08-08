
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

