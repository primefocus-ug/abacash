

# ------------------------------------------------------------------ #
# Expense Management                                                   #
# ------------------------------------------------------------------ #

@_ceo_required
def expense_list(request):
    qs = Expense.objects.select_related("created_by").order_by("-expense_date")

    category = request.GET.get("category", "")
    if category:
        qs = qs.filter(category=category)

    date_from = request.GET.get("date_from", "")
    if date_from:
        qs = qs.filter(expense_date__gte=date_from)

    date_to = request.GET.get("date_to", "")
    if date_to:
        qs = qs.filter(expense_date__lte=date_to)

    # Pagination
    paginator = Paginator(qs, 25)
    page = request.GET.get("page", 1)
    expenses = paginator.get_page(page)

    total_amount = sum(e.amount for e in qs)

    return render(request, "accounts/expense_list.html", {
        "expenses": expenses,
        "category_filter": category,
        "date_from": date_from,
        "date_to": date_to,
        "total_amount": total_amount,
        "category_choices": Expense.Category.choices,
    })


@_ceo_required
def expense_create(request):
    if request.method == "POST":
        d = request.POST
        try:
            expense = Expense.objects.create(
                category=d["category"],
                amount=d["amount"],
                expense_date=d["expense_date"],
                description=d.get("description", "").strip(),
                created_by=request.user,
            )
            messages.success(request, f"Expense recorded: {expense.get_category_display()} - UGX {expense.amount:,.0f}")
            return redirect("accounts:expense_list")
        except Exception as e:
            messages.error(request, f"Could not create expense: {e}")

    return render(request, "accounts/expense_form.html", {
        "title": "Record Expense",
        "action": "create",
        "category_choices": Expense.Category.choices,
    })


@_ceo_required
def expense_edit(request, pk):
    expense = get_object_or_404(Expense, pk=pk)

    if request.method == "POST":
        d = request.POST
        try:
            expense.category = d["category"]
            expense.amount = d["amount"]
            expense.expense_date = d["expense_date"]
            expense.description = d.get("description", "").strip()
            expense.save()
            messages.success(request, f"Expense updated.")
            return redirect("accounts:expense_list")
        except Exception as e:
            messages.error(request, f"Could not update expense: {e}")

    return render(request, "accounts/expense_form.html", {
        "title": f"Edit Expense — {expense.get_category_display()}",
        "action": "edit",
        "expense": expense,
        "category_choices": Expense.Category.choices,
    })


@_ceo_required
def expense_delete(request, pk):
    expense = get_object_or_404(Expense, pk=pk)
    if request.method == "POST":
        expense.delete()
        messages.success(request, "Expense deleted.")
        return redirect("accounts:expense_list")
    return render(request, "accounts/expense_confirm_delete.html", {"expense": expense})


# ------------------------------------------------------------------ #
# Capital Injection Management                                        #
# ------------------------------------------------------------------ #

@_ceo_required
def capital_injection_list(request):
    qs = CapitalInjection.objects.select_related("created_by").order_by("-injected_date")

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(source__icontains=q) | Q(investor__icontains=q))

    date_from = request.GET.get("date_from", "")
    if date_from:
        qs = qs.filter(injected_date__gte=date_from)

    date_to = request.GET.get("date_to", "")
    if date_to:
        qs = qs.filter(injected_date__lte=date_to)

    # Pagination
    paginator = Paginator(qs, 25)
    page = request.GET.get("page", 1)
    injections = paginator.get_page(page)

    total_amount = sum(i.amount for i in qs)

    return render(request, "accounts/capital_injection_list.html", {
        "injections": injections,
        "q": q,
        "date_from": date_from,
        "date_to": date_to,
        "total_amount": total_amount,
    })


@_ceo_required
def capital_injection_create(request):
    if request.method == "POST":
        d = request.POST
        try:
            amount_value = d.get("amount", "")
            injection = CapitalInjection.objects.create(
                source=d["source"].strip(),
                amount=amount_value,
                injected_date=d["injected_date"],
                investor=d.get("investor", "").strip(),
                notes=d.get("notes", "").strip(),
                created_by=request.user,
            )
            amount_display = f"{injection.amount:,.2f}".rstrip("0").rstrip(".") if hasattr(injection.amount, "quantize") else str(injection.amount)
            messages.success(request, f"Capital injection recorded: UGX {amount_display} from {injection.source}")
            return redirect("accounts:capital_injection_list")
        except Exception as e:
            messages.error(request, f"Could not create capital injection: {e}")

    return render(request, "accounts/capital_injection_form.html", {
        "title": "Record Capital Injection",
        "action": "create",
    })


@_ceo_required
def capital_injection_edit(request, pk):
    injection = get_object_or_404(CapitalInjection, pk=pk)

    if request.method == "POST":
        d = request.POST
        try:
            injection.source = d["source"].strip()
            injection.amount = d["amount"]
            injection.injected_date = d["injected_date"]
            injection.investor = d.get("investor", "").strip()
            injection.notes = d.get("notes", "").strip()
            injection.save()
            messages.success(request, f"Capital injection updated.")
            return redirect("accounts:capital_injection_list")
        except Exception as e:
            messages.error(request, f"Could not update capital injection: {e}")

    return render(request, "accounts/capital_injection_form.html", {
        "title": f"Edit Capital Injection — {injection.source}",
        "action": "edit",
        "injection": injection,
    })


@_ceo_required
def capital_injection_delete(request, pk):
    injection = get_object_or_404(CapitalInjection, pk=pk)
    if request.method == "POST":
        injection.delete()
        messages.success(request, "Capital injection deleted.")
        return redirect("accounts:capital_injection_list")
    return render(request, "accounts/capital_injection_confirm_delete.html", {"injection": injection})
