def company(request):
    """
    Makes the current tenant available in all templates.
    """
    return {
        "company": getattr(request, "tenant", None)
    }