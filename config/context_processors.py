
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
    Makes the currently-selected branch (nav switcher) available in
    every template, so any page can show a "you're viewing Branch X" banner
    without each view having to look it up itself.

    Only ever non-None for a logged-in user with the can_view_all_branches
    permission (CEOs by default, but grantable to anyone) who has also
    chosen a branch in the switcher — everyone else gets None and templates
    simply won't render the banner.
    """
    user = getattr(request, "user", None)
    if not user or not getattr(user, "is_authenticated", False):
        return {"active_branch_filter": None}
    if not (getattr(user, "is_superuser", False) or (hasattr(user, "can") and user.can("can_view_all_branches"))):
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


def navigation(request):
    """Build compact, reusable breadcrumbs for authenticated app pages."""
    user = getattr(request, "user", None)
    if not user or not getattr(user, "is_authenticated", False):
        return {"breadcrumbs": []}

    match = getattr(request, "resolver_match", None)
    namespace = getattr(match, "namespace", None) if match else None
    url_name = getattr(match, "url_name", None) if match else None

    from django.urls import NoReverseMatch, reverse

    def link(label, url_name, namespace=None):
        name = f"{namespace}:{url_name}" if namespace else url_name
        try:
            return {"label": label, "url": reverse(name)}
        except NoReverseMatch:
            return None

    def dashboard():
        return link("Dashboard", "dashboard", "accounts")

    breadcrumbs = []
    root = dashboard()
    if root:
        breadcrumbs.append(root)

    section_map = {
        "loans": ("Loans", "loans:list"),
        "clients": ("Clients", "clients:list"),
        "payments": ("Payments", "payments:list"),
        "reports": ("Reports", "reports:index"),
        "accounts": ("Administration", "accounts:admin_dashboard"),
    }

    if namespace in section_map:
        section_label, section_name = section_map[namespace]
        section_namespace, section_url_name = section_name.split(":", 1)

        if namespace == "accounts" and url_name in {
            "dashboard", "home", "login", "logout",
        }:
            section_namespace = None
            section_url_name = None
        else:
            section = link(section_label, section_url_name, section_namespace)
            if section:
                if namespace == "accounts" and url_name not in {
                    "admin_dashboard", "user_list", "user_create", "user_edit",
                    "user_toggle",
                    "branch_list", "branch_create", "branch_edit", "branch_detail",
                    "fee_type_list", "fee_type_create", "fee_type_edit",
                    "holiday_list", "holiday_create", "holiday_edit",
                    "company_settings", "financial_overview", "audit_log",
                    "permissions_manage", "guarantor_list", "guarantor_detail",
                    "guarantor_create", "guarantor_edit", "guarantor_create_ajax",
                    "bank_account_list", "bank_account_form", "bank_transaction_list",
                    "bank_transaction_form", "expense_types_list", "expense_list",
                    "expense_create", "expense_edit", "expense_delete",
                    "capital_injection_list", "capital_injection_create",
                    "capital_injection_edit", "capital_injection_delete",
                    "investor_list", "investor_detail", "investor_form",
                    "investor_create", "investor_edit", "investor_drawing",
                    "investor_confirm_delete", "investor_drawing_form",
                }:
                    section = None
                if section:
                    breadcrumbs.append(section)

    if url_name and namespace:
        page_labels = {
            ("loans", "list"): "All Loans",
            ("loans", "apply"): "New Application",
            ("loans", "apply_step2"): "Application Details",
            ("loans", "apply_step3"): "Fees & Schedule",
            ("loans", "apply_review"): "Review Application",
            ("loans", "detail"): "Loan Details",
            ("loans", "edit"): "Edit Loan",
            ("loans", "renew"): "Renew Loan",
            ("loans", "schedule_print"): "Print Schedule",
            ("loans", "products"): "Loan Products",
            ("loans", "products_create"): "New Loan Product",
            ("loans", "products_edit"): "Edit Loan Product",
            ("clients", "list"): "All Clients",
            ("clients", "create"): "Register Client",
            ("clients", "detail"): "Client Details",
            ("clients", "edit"): "Edit Client",
            ("payments", "list"): "Payments",
            ("payments", "record"): "Record Payment",
            ("payments", "record_for_loan"): "Record Payment",
            ("payments", "receipt"): "Payment Receipt",
            ("payments", "combined_receipt"): "Combined Receipt",
            ("payments", "history"): "Payment History",
            ("payments", "credit_refund"): "Credit or Refund",
            ("reports", "index"): "Reports",
            ("reports", "company_ledger"): "Company Ledger",
            ("reports", "collateral_ledger"): "Collateral Ledger",
            ("reports", "loan_book"): "Loan Book",
            ("reports", "staff_performance"): "Staff Performance",
            ("reports", "collections"): "Collections",
            ("reports", "cash_flow"): "Cash Flow",
            ("reports", "fund_movement"): "Fund Movement",
            ("reports", "overdue"): "Overdue",
            ("reports", "income"): "Income Statement",
            ("reports", "disbursements"): "Disbursements",
            ("reports", "repayments"): "Repayments",
            ("reports", "defaulted"): "Defaulted Loans",
            ("reports", "closed_loans"): "Closed Loans",
            ("reports", "par"): "Portfolio at Risk",
            ("reports", "client_statement"): "Client Statement",
        }
        page_label = page_labels.get((namespace, url_name))

        if namespace == "accounts":
            account_labels = {
                "admin_dashboard": "Admin Dashboard",
                "user_list": "Users",
                "user_create": "New User",
                "user_edit": "Edit User",
                "branch_list": "Branches",
                "branch_create": "New Branch",
                "branch_edit": "Edit Branch",
                "branch_detail": "Branch Details",
                "fee_type_list": "Fee Types",
                "fee_type_create": "New Fee Type",
                "fee_type_edit": "Edit Fee Type",
                "holiday_list": "Holidays",
                "holiday_create": "New Holiday",
                "holiday_edit": "Edit Holiday",
                "company_settings": "Company Settings",
                "financial_overview": "Financial Overview",
                "audit_log": "Audit Log",
                "permissions_manage": "Permissions",
                "expense_types_list": "Expense Types",
                "expense_list": "Expenses",
                "expense_create": "New Expense",
                "expense_edit": "Edit Expense",
                "expense_delete": "Delete Expense",
                "capital_injection_list": "Capital Injections",
                "capital_injection_create": "New Capital Injection",
                "capital_injection_edit": "Edit Capital Injection",
                "capital_injection_delete": "Delete Capital Injection",
                "investor_list": "Investors",
                "investor_detail": "Investor Details",
                "investor_form": "Investor",
            }
            page_label = account_labels.get(url_name)

        if page_label:
            current_url = getattr(request, "path", None)
            current = {"label": page_label, "url": current_url}

            section_list_page = namespace in {"loans", "clients", "payments", "reports"}
            section_list_url_name = {
                "loans": "list",
                "clients": "list",
                "payments": "list",
                "reports": "index",
            }.get(namespace)
            if section_list_page and url_name == section_list_url_name:
                breadcrumbs.append(current)
            else:
                breadcrumbs.append(current)

    return {"breadcrumbs": breadcrumbs}

