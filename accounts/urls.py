from django.urls import path, reverse_lazy
from django.contrib.auth import views as auth_views
from . import views

app_name = "accounts"


class TenantPasswordResetView(auth_views.PasswordResetView):
    """
    Same as Django's stock PasswordResetView, except the reset email is
    built using the *actual request host* (e.g. acme.abacash.loan) rather
    than django.contrib.sites. Sites has no concept of django-tenants
    schemas/domains, so get_current_site() falls back to whatever generic
    row exists in django_site (usually "example.com"), which is why the
    emailed link was pointing at the wrong domain.
    """
    template_name = "accounts/password_reset_form.html"
    email_template_name = "accounts/password_reset_email.txt"
    html_email_template_name = "accounts/password_reset_email.html"
    subject_template_name = "accounts/password_reset_subject.txt"
    success_url = reverse_lazy("accounts:password_reset_done")

    def form_valid(self, form):
        opts = {
            "use_https": self.request.is_secure(),
            "token_generator": self.token_generator,
            "from_email": self._tenant_from_email(),
            "email_template_name": self.email_template_name,
            "subject_template_name": self.subject_template_name,
            "request": self.request,
            "html_email_template_name": self.html_email_template_name,
            # The emailed link already uses the real tenant host (domain_override,
            # below) — this adds the tenant's own name/logo/support contact to the
            # email itself, so a user juggling several tenants (or support staff
            # looking at a forwarded email) can tell at a glance which company
            # account it's for, instead of every reset email just saying "Abacash".
            "extra_email_context": {**(self.extra_email_context or {}), **self._tenant_branding_context()},
            # The key fix: use the tenant's real host instead of Sites.
            "domain_override": self.request.get_host(),
        }
        form.save(**opts)
        # Skip PasswordResetView.form_valid (it recomputes opts using Sites)
        # and go straight to FormView.form_valid, which just redirects.
        return super(auth_views.PasswordResetView, self).form_valid(form)

    def _tenant_branding_context(self):
        """Tenant name/logo/support-contact for the reset email templates.

        Falls back to generic Abacash branding if, for whatever reason,
        CompanySettings can't be loaded (e.g. mid-provisioning) — the email
        still goes out, it just won't be tenant-branded in that edge case.
        """
        tenant_name = "Abacash"
        logo_url = None
        support_email = "abauganda21@gmail.com"
        try:
            from accounts.models import CompanySettings
            settings_obj = CompanySettings.get()
            tenant_name = settings_obj.company_name or tenant_name
            support_email = settings_obj.company_email or support_email
            if settings_obj.company_logo:
                logo_url = self.request.build_absolute_uri(settings_obj.company_logo.url)
        except Exception:
            pass
        return {
            "tenant_name": tenant_name,
            "tenant_logo_url": logo_url,
            "tenant_support_email": support_email,
        }

    def _tenant_from_email(self):
        """Keep the technical From address as configured (so SPF/DKIM and
        deliverability aren't affected) but put the tenant's name in the
        display name, e.g. 'Acme Finance via Abacash <noreply@abacash.loan>',
        so the email's sender line also identifies the tenant."""
        from email.utils import formataddr

        base_from = self.from_email or None
        try:
            from accounts.models import CompanySettings
            tenant_name = CompanySettings.get().company_name
        except Exception:
            tenant_name = None

        if not base_from:
            from django.conf import settings
            base_from = getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@abacash.loan")

        if not tenant_name:
            return base_from

        # base_from may already be "Name <addr>" or a bare address.
        addr = base_from
        if "<" in base_from and ">" in base_from:
            addr = base_from.split("<", 1)[1].rstrip(">").strip()
        return formataddr((f"{tenant_name} via Abacash", addr))


class TenantPasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("accounts:password_reset_complete")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        reset_user = getattr(self, "user", None)
        context["reset_username"] = reset_user.username if reset_user else ""
        return context

urlpatterns = [
    # Authentication
    path("login/",              views.login_view,          name="login"),
    path("contact-chatbot/",   views.contact_chatbot,     name="contact_chatbot"),
    path("logout/",             views.logout_view,         name="logout"),
    path("dashboard/",          views.dashboard,           name="dashboard"),
    path("",                    views.dashboard,           name="home"),

    # Admin Panel
    path("admin-panel/",                    views.admin_dashboard,      name="admin_dashboard"),

    # User Management
    path("admin-panel/users/",              views.user_list,            name="user_list"),
    path("admin-panel/users/new/",          views.user_create,          name="user_create"),
    path("admin-panel/users/<int:pk>/edit/",views.user_edit,            name="user_edit"),
    path("admin-panel/users/<int:pk>/toggle/", views.user_toggle_active, name="user_toggle"),

    # Branch Management
    path("admin-panel/branches/",           views.branch_list,          name="branch_list"),
    path("admin-panel/branches/new/",       views.branch_create,        name="branch_create"),
    path("admin-panel/branches/<int:pk>/edit/", views.branch_edit,      name="branch_edit"),
    path("admin-panel/branches/<int:pk>/", views.branch_detail,        name="branch_detail"),

    path("branch-filter/",                  views.set_branch_filter,   name="set_branch_filter"),

    # Fee Type Management
    path("admin-panel/fee-types/",          views.fee_type_list,        name="fee_type_list"),
    path("admin-panel/fee-types/new/",      views.fee_type_create,      name="fee_type_create"),
    path("admin-panel/fee-types/<int:pk>/edit/", views.fee_type_edit,   name="fee_type_edit"),

    # Holiday Management
    path("admin-panel/holidays/",           views.holiday_list,         name="holiday_list"),
    path("admin-panel/holidays/new/",       views.holiday_create,       name="holiday_create"),
    path("admin-panel/holidays/<int:pk>/edit/", views.holiday_edit,     name="holiday_edit"),

    # Company Settings
    path("admin-panel/settings/",           views.company_settings,     name="company_settings"),
    # Financial overview
    path("admin-panel/financials/",         views.financial_overview,   name="financial_overview"),

    # Guarantor Management
    path("guarantors/",                     views.guarantor_list,       name="guarantor_list"),
    path("guarantors/<int:pk>/",            views.guarantor_detail,     name="guarantor_detail"),
    path("guarantors/new/",                 views.guarantor_create,     name="guarantor_create"),
    path("guarantors/ajax-create/",          views.guarantor_create_ajax, name="guarantor_create_ajax"),
    path("guarantors/<int:pk>/edit/",       views.guarantor_edit,       name="guarantor_edit"),

    # Audit Log
    path("admin-panel/audit-log/",          views.audit_log,            name="audit_log"),
    path("admin-panel/permissions/",        views.permissions_manage,   name="permissions_manage"),

    # Transaction Categories & Expense Types
    path("admin-panel/expense-types/",                      views.expense_types_list,                name="expense_types_list"),
    path("admin-panel/transaction-categories/ajax-create/", views.transaction_category_create_ajax,  name="transaction_category_create_ajax"),
    path("admin-panel/expense-types/ajax-create/",          views.expense_type_create_ajax,          name="expense_type_create_ajax"),
    path("admin-panel/expense-types/for-category/",         views.expense_types_for_category,        name="expense_types_for_category"),

    # Expense Management
    path("admin-panel/expenses/",           views.expense_list,         name="expense_list"),
    path("admin-panel/expenses/create/",    views.expense_create,       name="expense_create"),
    path("admin-panel/expenses/<int:pk>/edit/", views.expense_edit,     name="expense_edit"),
    path("admin-panel/expenses/<int:pk>/delete/", views.expense_delete, name="expense_delete"),

    # Capital Injection Management
    path("admin-panel/capital-injections/", views.capital_injection_list, name="capital_injection_list"),
    path("admin-panel/capital-injections/create/", views.capital_injection_create, name="capital_injection_create"),
    path("admin-panel/capital-injections/<int:pk>/edit/", views.capital_injection_edit, name="capital_injection_edit"),
    path("admin-panel/capital-injections/<int:pk>/delete/", views.capital_injection_delete, name="capital_injection_delete"),

    # Investor Management
    path("admin-panel/investors/", views.investor_list, name="investor_list"),
    path("admin-panel/investors/new/", views.investor_create, name="investor_create"),
    path("admin-panel/investors/<int:pk>/", views.investor_detail, name="investor_detail"),
    path("admin-panel/investors/<int:pk>/drawings/new/", views.investor_drawing_create, name="investor_drawing_create"),
    path("admin-panel/investors/<int:pk>/edit/", views.investor_edit, name="investor_edit"),
    path("admin-panel/investors/<int:pk>/delete/", views.investor_delete, name="investor_delete"),

    # Bank Account Management
    path("admin-panel/bank-accounts/",              views.bank_account_list,   name="bank_account_list"),
    path("admin-panel/bank-accounts/new/",           views.bank_account_create, name="bank_account_create"),
    path("admin-panel/bank-accounts/<int:pk>/edit/", views.bank_account_edit,   name="bank_account_edit"),

    # Bank Transactions
    path("admin-panel/bank-transactions/",              views.bank_transaction_list,   name="bank_transaction_list"),
    path("admin-panel/bank-transactions/new/",          views.bank_transaction_create, name="bank_transaction_create"),
    path("admin-panel/bank-transactions/<int:pk>/edit/", views.bank_transaction_edit,   name="bank_transaction_edit"),

    # Password reset helper views for tenant and registration onboarding flow
    path(
        "password_reset/",
        TenantPasswordResetView.as_view(),
        name="password_reset",
    ),
    path("password_reset/done/", auth_views.PasswordResetDoneView.as_view(
        template_name="accounts/password_reset_done.html"), name="password_reset_done"),
    path("reset/<uidb64>/<token>/", TenantPasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("reset/done/", auth_views.PasswordResetCompleteView.as_view(
        template_name="accounts/password_reset_complete.html"), name="password_reset_complete"),
]
