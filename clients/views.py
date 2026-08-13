"""clients/views.py — Client registration, list, detail, and edit."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from .models import Client, NextOfKin
from accounts.audit import log_action
from accounts.models import AuditLog, Branch
from accounts.branch_scope import scope_to_branch, can_access_branch_object, scope_to_branch_request
from django.http import JsonResponse
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger

# Fields required to save a Client, used to validate POST data explicitly
# instead of relying on KeyError from raw dict access.
REQUIRED_CLIENT_FIELDS = [
    "first_name", "last_name", "gender", "date_of_birth", "marital_status",
    "nin", "phone_primary", "physical_address", "employment_status",
]


@login_required
def client_search(request):
    """Return JSON suitable for Select2 AJAX searches.

    Query param: `q` — search term
    Response: {"results":[{"id": "<uuid>", "text": "Display text"}, ...]}
    """
    q = request.GET.get("q", "").strip()
    results = []
    if q:
        qs = Client.objects.filter(
            Q(first_name__icontains=q) |
            Q(last_name__icontains=q)  |
            Q(client_number__icontains=q) |
            Q(nin__icontains=q) |
            Q(phone_primary__icontains=q)
        )
        qs = scope_to_branch(qs, request.user)
        # Exclude blacklisted/inactive clients by default so they can't be
        # picked up accidentally by pickers (e.g. new loan application).
        # Pass include_inactive=1 to bypass (e.g. for an admin lookup screen).
        if request.GET.get("include_inactive") != "1":
            qs = qs.filter(is_active=True, is_blacklisted=False)
        qs = qs.order_by("last_name")[:50]
        for c in qs:
            text = f"{c.client_number} — {c.full_name} ({c.phone_primary})"
            results.append({"id": str(c.pk), "text": text})
    return JsonResponse({"results": results})


@login_required
def client_list(request):
    qs = Client.objects.select_related("registered_by", "branch").order_by("-created_at")
    qs = scope_to_branch_request(qs, request)
    search = request.GET.get("q", "").strip()
    if search:
        qs = qs.filter(
            Q(first_name__icontains=search) |
            Q(last_name__icontains=search)  |
            Q(client_number__icontains=search) |
            Q(nin__icontains=search) |
            Q(phone_primary__icontains=search)
        )
    status = request.GET.get("status", "")
    if status == "active":
        qs = qs.filter(is_active=True, is_blacklisted=False)
    elif status == "blacklisted":
        qs = qs.filter(is_blacklisted=True)
    # Pagination
    per_page = request.GET.get("per_page") or request.GET.get("show") or 10
    try:
        per_page = int(per_page)
    except Exception:
        per_page = 10

    paginator = Paginator(qs, per_page)
    page = request.GET.get("page")
    try:
        page_obj = paginator.page(page)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    # Build querystring for pagination links (preserve filters/search but not page)
    params = request.GET.copy()
    if "page" in params:
        params.pop("page")
    querystring = params.urlencode()

    return render(request, "clients/client_list.html", {
        "clients": page_obj.object_list,
        "page_obj": page_obj,
        "paginator": paginator,
        "querystring": querystring,
        "total_count": paginator.count,
        "search": search,
        "status": status,
        "per_page": per_page,
        "branches": Branch.objects.filter(is_active=True).order_by("name") if request.user.can("can_view_all_branches") else None,
        "selected_branch": request.GET.get("branch", ""),
    })


@login_required
def client_detail(request, pk):
    client = get_object_or_404(Client, pk=pk)
    if not can_access_branch_object(request.user, client):
        messages.error(request, "That client belongs to a different branch.")
        return redirect("clients:list")
    loans  = client.loans.select_related("product").order_by("-application_date")
    kin    = client.next_of_kin.all()
    docs   = client.documents.all()
    return render(request, "clients/client_detail.html", {
        "client": client,
        "loans":  loans,
        "kin":    kin,
        "docs":   docs,
    })


@login_required
def client_create(request):
    duplicates = []
    client_data = {}

    if request.method == "POST":
        d = request.POST
        client_data = {
            "first_name":        d.get("first_name", "").strip(),
            "last_name":         d.get("last_name", "").strip(),
            "other_names":       d.get("other_names", "").strip(),
            "gender":            d.get("gender", ""),
            "date_of_birth":     d.get("date_of_birth", ""),
            "marital_status":    d.get("marital_status", ""),
            "nin":               d.get("nin", "").strip().upper(),
            "phone_primary":     d.get("phone_primary", "").strip(),
            "phone_secondary":   d.get("phone_secondary", "").strip(),
            "email":             d.get("email", "").strip(),
            "physical_address":  d.get("physical_address", "").strip(),
            "district":          d.get("district", "Kampala").strip(),
            "employment_status": d.get("employment_status", ""),
            "employer_name":     d.get("employer_name", "").strip(),
            "employer_address":  d.get("employer_address", "").strip(),
            "job_title":         d.get("job_title", "").strip(),
            "monthly_income":    d.get("monthly_income") or 0,
            "notes":             d.get("notes", "").strip(),
        }

        client_branch = None
        branch_error = None
        if request.user.can("can_view_all_branches"):
            branch_id = d.get("branch", "").strip()
            client_branch = Branch.objects.filter(pk=branch_id, is_active=True).first() if branch_id else None
            if not client_branch:
                branch_error = "Please select which branch this client belongs to."
        else:
            client_branch = request.user.branch

        duplicate_filter = Q(nin__iexact=client_data["nin"])
        if client_data["phone_primary"]:
            duplicate_filter |= Q(phone_primary=client_data["phone_primary"])

        duplicates = list(Client.objects.filter(duplicate_filter))
        if duplicates:
            messages.warning(
                request,
                "A client with the same National ID or primary phone already exists. "
                "Please edit the existing record or cancel registration."
            )
        elif branch_error:
            messages.error(request, branch_error)
        elif not all(client_data.get(f) for f in
                     ("first_name", "last_name", "gender", "date_of_birth",
                      "marital_status", "nin", "phone_primary", "physical_address",
                      "employment_status")):
            messages.error(request, "Please fill in all required fields.")
        elif not request.FILES.get("passport_photo"):
            messages.error(request, "A passport photo is required to register a client.")
        else:
            try:
                with transaction.atomic():
                    client = Client.objects.create(
                        first_name        = client_data["first_name"],
                        last_name         = client_data["last_name"],
                        other_names       = client_data["other_names"],
                        gender            = client_data["gender"],
                        date_of_birth     = client_data["date_of_birth"],
                        marital_status    = client_data["marital_status"],
                        nin               = client_data["nin"],
                        phone_primary     = client_data["phone_primary"],
                        phone_secondary   = client_data["phone_secondary"],
                        email             = client_data["email"],
                        physical_address  = client_data["physical_address"],
                        district          = client_data["district"],
                        employment_status = client_data["employment_status"],
                        employer_name     = client_data["employer_name"],
                        employer_address  = client_data["employer_address"],
                        job_title         = client_data["job_title"],
                        monthly_income    = client_data["monthly_income"],
                        notes             = client_data["notes"],
                        registered_by     = request.user,
                        branch            = client_branch,
                    )
                    if request.FILES.get("passport_photo"):
                        client.passport_photo = request.FILES["passport_photo"]
                        client.save()
                    # Optional next of kin
                    kin_name  = d.get("kin_name", "").strip()
                    kin_phone = d.get("kin_phone", "").strip()
                    if kin_name and kin_phone:
                        NextOfKin.objects.create(
                            client           = client,
                            full_name        = kin_name,
                            relationship     = d.get("kin_relationship", "").strip(),
                            phone_primary    = kin_phone,
                            phone_secondary  = d.get("kin_phone2", "").strip(),
                            physical_address = d.get("kin_address", "").strip(),
                            is_guarantor     = d.get("kin_is_guarantor") == "on",
                        )
                    log_action(request.user, AuditLog.Action.CREATE, client, request=request,
                               changes={"client_number": client.client_number, "name": client.full_name},
                               remarks=f"Client {client.full_name} registered")
                messages.success(
                    request,
                    f"Client {client.full_name} registered. Reference: {client.client_number}"
                )
                return redirect("clients:detail", pk=client.pk)
            except IntegrityError:
                # Most likely a concurrent registration grabbed the same NIN,
                # phone, or client_number between our duplicate check and the
                # insert. Nothing was partially saved (atomic rolled it back).
                messages.error(
                    request,
                    "Could not save this client — a matching record was created "
                    "at the same time. Please search again before retrying."
                )
            except Exception as e:
                messages.error(request, f"Error saving client: {e}")

    return render(request, "clients/client_form.html", {
        "title":              "Register New Client",
        "action":             "create",
        "gender_choices":     Client.Gender.choices,
        "marital_choices":    Client.MaritalStatus.choices,
        "employment_choices": Client.EmploymentStatus.choices,
        "client":             client_data,
        "duplicates":        duplicates,
        "branches":          Branch.objects.filter(is_active=True).order_by("name"),
    })


@login_required
def client_edit(request, pk):
    client = get_object_or_404(Client, pk=pk)

    if not request.user.can("can_manage_clients"):
        messages.error(request, "You do not have permission to edit client records.")
        return redirect("clients:detail", pk=pk)

    if not can_access_branch_object(request.user, client):
        messages.error(request, "That client belongs to a different branch.")
        return redirect("clients:list")

    if request.method == "POST":
        d = request.POST

        missing = [f for f in REQUIRED_CLIENT_FIELDS if not d.get(f, "").strip()]
        if missing:
            messages.error(request, "Please fill in all required fields: " + ", ".join(missing))
            return render(request, "clients/client_form.html", {
                "title":              f"Edit — {client.full_name}",
                "action":             "edit",
                "client":             client,
                "gender_choices":     Client.Gender.choices,
                "marital_choices":    Client.MaritalStatus.choices,
                "employment_choices": Client.EmploymentStatus.choices,
                "branches":           Branch.objects.filter(is_active=True).order_by("name"),
            })

        new_nin   = d["nin"].strip().upper()
        new_phone = d["phone_primary"].strip()
        duplicate_filter = Q(nin__iexact=new_nin)
        if new_phone:
            duplicate_filter |= Q(phone_primary=new_phone)
        duplicates = list(Client.objects.filter(duplicate_filter).exclude(pk=client.pk))
        if duplicates:
            messages.error(
                request,
                "Another client already has this National ID or primary phone. "
                f"Check {', '.join(dup.client_number for dup in duplicates)} before saving."
            )
            return render(request, "clients/client_form.html", {
                "title":              f"Edit — {client.full_name}",
                "action":             "edit",
                "client":             client,
                "gender_choices":     Client.Gender.choices,
                "marital_choices":    Client.MaritalStatus.choices,
                "employment_choices": Client.EmploymentStatus.choices,
                "branches":           Branch.objects.filter(is_active=True).order_by("name"),
            })

        try:
            with transaction.atomic():
                client.first_name        = d["first_name"].strip()
                client.last_name         = d["last_name"].strip()
                client.other_names       = d.get("other_names", "").strip()
                client.gender            = d["gender"]
                client.date_of_birth     = d["date_of_birth"]
                client.marital_status    = d["marital_status"]
                client.nin               = new_nin
                client.phone_primary     = new_phone
                client.phone_secondary   = d.get("phone_secondary", "").strip()
                client.email             = d.get("email", "").strip()
                client.physical_address  = d["physical_address"].strip()
                client.district          = d.get("district", "Kampala").strip()
                client.employment_status = d["employment_status"]
                client.employer_name     = d.get("employer_name", "").strip()
                client.employer_address  = d.get("employer_address", "").strip()
                client.job_title         = d.get("job_title", "").strip()
                client.monthly_income    = d.get("monthly_income") or 0
                client.notes             = d.get("notes", "").strip()
                if request.FILES.get("passport_photo"):
                    client.passport_photo = request.FILES["passport_photo"]
                # Users who can see across branches can also toggle blacklist and reassign branch
                if request.user.can("can_view_all_branches"):
                    client.is_blacklisted    = d.get("is_blacklisted") == "on"
                    client.blacklist_reason  = d.get("blacklist_reason", "").strip()
                    client.is_active         = d.get("is_active") == "on"
                    new_branch_id = d.get("branch", "").strip()
                    if new_branch_id:
                        client.branch = Branch.objects.filter(pk=new_branch_id, is_active=True).first() or client.branch
                client.save()
                log_action(request.user, AuditLog.Action.UPDATE, client, request=request,
                           changes={"name": client.full_name},
                           remarks=f"Client {client.full_name} updated")
            messages.success(request, f"Client {client.full_name} updated.")
            return redirect("clients:detail", pk=pk)
        except IntegrityError:
            messages.error(
                request,
                "Could not save — this National ID or phone number was just taken "
                "by another record. Please refresh and try again."
            )
        except Exception as e:
            messages.error(request, f"Error updating client: {e}")

    return render(request, "clients/client_form.html", {
        "title":              f"Edit — {client.full_name}",
        "action":             "edit",
        "client":             client,
        "gender_choices":     Client.Gender.choices,
        "marital_choices":    Client.MaritalStatus.choices,
        "employment_choices": Client.EmploymentStatus.choices,
        "branches":           Branch.objects.filter(is_active=True).order_by("name"),
    })
