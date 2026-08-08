"""
Single source of truth for "who can see which branch's data".

Rule (per product decision): CEOs see every branch. Managers and Cashiers
are restricted to their own branch. A staff member with no branch assigned
sees nothing branch-scoped until an admin assigns one — we deliberately do
NOT fall back to "show everything" for an unassigned user, since that would
silently leak other branches' data.

Usage:
    from accounts.branch_scope import scope_to_branch
    loans = scope_to_branch(Loan.objects.all(), request.user)                 # field="branch" by default
    payments = scope_to_branch(Payment.objects.all(), request.user, "loan__branch")
"""


def scope_to_branch(queryset, user, field="branch"):
    """Restrict queryset to the user's branch unless they're a CEO.

    - CEO (or Django superuser): queryset returned unchanged.
    - Everyone else with a branch assigned: filtered to that branch.
    - Everyone else with NO branch assigned: filtered to nothing (empty
      queryset) rather than showing all branches by accident.
    """
    if getattr(user, "is_ceo", False) or getattr(user, "is_superuser", False):
        return queryset
    branch_id = getattr(user, "branch_id", None)
    if not branch_id:
        return queryset.none()
    return queryset.filter(**{f"{field}_id": branch_id})


def can_access_branch_object(user, obj, field="branch"):
    """True if the user is allowed to view/act on a single object.

    Mirrors scope_to_branch's rule for the single-object case (detail/edit
    views that fetch by pk before deciding whether to show it).
    """
    if getattr(user, "is_ceo", False) or getattr(user, "is_superuser", False):
        return True
    branch_id = getattr(user, "branch_id", None)
    if not branch_id:
        return False
    obj_branch_id = obj
    for part in field.split("__"):
        obj_branch_id = getattr(obj_branch_id, part, None)
        if obj_branch_id is None:
            return False
    obj_branch_id = getattr(obj_branch_id, "pk", obj_branch_id)
    return obj_branch_id == branch_id


SESSION_KEY = "ceo_branch_filter"


def effective_branch_id(request, param="branch"):
    """Resolve which branch a list/report page should be scoped to.

    - Non-CEO: always their own branch (branch_id, or -1 if unassigned).
      Ignores any ?branch= param and the session switcher entirely — a
      Manager/Cashier can't page-hack or switcher-hack into another branch.
    - CEO: the page's own ?branch= query param wins if present (including
      an explicit empty value, meaning "All branches" was chosen on this
      page). Otherwise falls back to the nav switcher's session default.
      Otherwise None (all branches).

    Returns an int branch id, -1 (deliberately-empty scope), or None (no
    restriction — only ever returned for a CEO).
    """
    user = request.user
    if not (getattr(user, "is_ceo", False) or getattr(user, "is_superuser", False)):
        return user.branch_id or -1

    raw = request.GET.get(param, None)
    if raw is not None:
        return int(raw) if raw.isdigit() else None

    session_val = request.session.get(SESSION_KEY)
    if session_val:
        return int(session_val) if str(session_val).isdigit() else None
    return None


def scope_to_branch_request(queryset, request, field="branch", param="branch"):
    """Like scope_to_branch, but CEO-aware of the nav switcher/page filter."""
    branch_id = effective_branch_id(request, param=param)
    if branch_id is None:
        return queryset
    return queryset.filter(**{f"{field}_id": branch_id})
