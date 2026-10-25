from django.db.models import Q

from .models import User


def available_signatories(branch_id=None):
    users = User.objects.filter(
        is_active=True,
        signature__isnull=False,
    ).exclude(signature="")
    if branch_id is not None:
        users = users.filter(
            Q(branch_id=branch_id) | Q(role=User.Role.CEO) | Q(is_superuser=True)
        )
    return users.order_by("first_name", "last_name", "email")


def selected_signatory(request, branch_id=None):
    signatories = available_signatories(branch_id)
    requested_id = request.GET.get("signatory", "")
    if not requested_id.isdigit():
        return signatories, None
    return signatories, signatories.filter(pk=int(requested_id)).first()
