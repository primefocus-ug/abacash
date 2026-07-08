"""clients/views.py — Client registration, list, detail, and edit."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from .models import Client, NextOfKin
from accounts.audit import log_action
from accounts.models import AuditLog
from django.http import JsonResponse
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger


@login_required
def client_search(request):
    """Return JSON suitable for Select2 AJAX searches.

    Query param: `q` — search term
    Response: {"results":[{"id": "<uuid>", "text": "Display text"}, ...]}
    """
    q = request.GET.get("q", "").strip()
    results = []
    if q:
        from django.db.models import Q
        qs = Client.objects.filter(
            Q(first_name__icontains=q) |
            Q(last_name__icontains=q)  |
            Q(client_number__icontains=q) |
            Q(nin__icontains=q) |
            Q(phone_primary__icontains=q)
        ).order_by("last_name")[:50]
        for c in qs:
            text = f"{c.client_number} — {c.full_name} ({c.phone_primary})"
            results.append({"id": str(c.pk), "text": text})
    return JsonResponse({"results": results})


@login_required
def client_list(request):
    qs = Client.objects.select_related("registered_by").order_by("-created_at")
    search = request.GET.get("q", "").strip()
    if search:
        from django.db.models import Q
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
        "total_count": qs.count(),
        "search": search,
        "status": status,
        "per_page": per_page,
    })


@login_required
def client_detail(request, pk):
    client = get_object_or_404(Client, pk=pk)
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
        else:
            try:
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
    })


@login_required
def client_edit(request, pk):
    client = get_object_or_404(Client, pk=pk)

    if not (request.user.is_manager or request.user.is_ceo):
        messages.error(request, "Only Managers and the CEO can edit client records.")
        return redirect("clients:detail", pk=pk)

    if request.method == "POST":
        d = request.POST
        try:
            client.first_name        = d["first_name"].strip()
            client.last_name         = d["last_name"].strip()
            client.other_names       = d.get("other_names", "").strip()
            client.gender            = d["gender"]
            client.date_of_birth     = d["date_of_birth"]
            client.marital_status    = d["marital_status"]
            client.nin               = d["nin"].strip().upper()
            client.phone_primary     = d["phone_primary"].strip()
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
            # CEO can toggle blacklist
            if request.user.is_ceo:
                client.is_blacklisted    = d.get("is_blacklisted") == "on"
                client.blacklist_reason  = d.get("blacklist_reason", "").strip()
                client.is_active         = d.get("is_active") == "on"
            client.save()
            log_action(request.user, AuditLog.Action.UPDATE, client, request=request,
                       changes={"name": client.full_name},
                       remarks=f"Client {client.full_name} updated")
            messages.success(request, f"Client {client.full_name} updated.")
            return redirect("clients:detail", pk=pk)
        except Exception as e:
            messages.error(request, f"Error updating client: {e}")

    return render(request, "clients/client_form.html", {
        "title":              f"Edit — {client.full_name}",
        "action":             "edit",
        "client":             client,
        "gender_choices":     Client.Gender.choices,
        "marital_choices":    Client.MaritalStatus.choices,
        "employment_choices": Client.EmploymentStatus.choices,
    })
