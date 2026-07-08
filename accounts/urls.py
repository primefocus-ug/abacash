from django.urls import path
from . import views

app_name = "accounts"

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

    # Bank Account Management
    path("admin-panel/bank-accounts/",              views.bank_account_list,   name="bank_account_list"),
    path("admin-panel/bank-accounts/new/",           views.bank_account_create, name="bank_account_create"),
    path("admin-panel/bank-accounts/<int:pk>/edit/", views.bank_account_edit,   name="bank_account_edit"),

    # Bank Transactions
    path("admin-panel/bank-transactions/",              views.bank_transaction_list,   name="bank_transaction_list"),
    path("admin-panel/bank-transactions/new/",          views.bank_transaction_create, name="bank_transaction_create"),
    path("admin-panel/bank-transactions/<int:pk>/edit/", views.bank_transaction_edit,   name="bank_transaction_edit"),

    # System Parameters
    path("admin-panel/parameters/",         views.system_parameters,    name="system_parameters"),
    path("admin-panel/parameters/<int:pk>/delete/", views.system_parameter_delete, name="system_parameter_delete"),
]