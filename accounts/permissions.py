"""
Central registry for the app's permission system.

Permissions are plain Django auth Permissions (Meta.permissions on User,
see accounts/models.py), so they use the normal has_perm() machinery and
show up in the standard auth_permission table — no new tables needed.

Roles (Cashier/Manager/CEO) are implemented as Django Groups, each
pre-loaded with the permissions listed below. A user's `role` field still
exists and still drives which Group they're placed in by default (see the
0007 data migration and accounts.signals), but actual access-control
decisions should go through `user.can(codename)` / `user.has_perm(...)`,
not through `is_ceo`/`is_manager`/`is_cashier` — those remain as
descriptive properties (e.g. "is this specific staff record a CEO"),
they're just no longer meant to gate what someone is allowed to do.

Per-user overrides: because this rides on PermissionsMixin, granting one
specific user an extra permission beyond their group's defaults is just
`user.user_permissions.add(permission)` — no code change required.
"""

# Group names — kept identical to the existing Role choices so the data
# migration can map role -> group 1:1.
GROUP_CASHIER = "Cashier"
GROUP_MANAGER = "Manager"
GROUP_CEO = "CEO"

ALL_GROUPS = [GROUP_CASHIER, GROUP_MANAGER, GROUP_CEO]

# (codename, human-readable name, [groups it's granted to by default])
# codename must be a valid Python identifier fragment (Django lowercases
# and validates these); keep them descriptive since they're what shows up
# in the Roles & Permissions admin UI.
PERMISSIONS = [
    # --- Admin panel / configuration -------------------------------------
    ("can_view_admin_panel",         "View the admin panel hub",                 [GROUP_CEO]),
    ("can_manage_users",             "Manage staff accounts",                    [GROUP_CEO]),
    ("can_manage_branches",          "Manage branches",                          [GROUP_CEO]),
    ("can_manage_loan_products",     "Manage loan products & fee types",         [GROUP_CEO]),
    ("can_manage_system_settings",   "Manage system settings (holidays, params)",[GROUP_CEO]),
    ("can_manage_company_settings",  "Manage company settings",                  [GROUP_CEO]),
    ("can_manage_guarantors",        "Manage guarantors",                        [GROUP_MANAGER, GROUP_CEO]),
    ("can_verify_guarantors",        "Verify guarantors",                        [GROUP_CEO]),
    ("can_view_audit_log",           "View audit log",                           [GROUP_CEO]),
    ("can_manage_permissions",       "Manage roles & permissions",               [GROUP_CEO]),

    # --- Finance ----------------------------------------------------------
    ("can_manage_expenses",          "Record & manage expenses",                 [GROUP_CEO]),
    ("can_manage_expense_categories","Manage expense categories",                [GROUP_CEO]),
    ("can_manage_capital",           "Manage capital injections",                [GROUP_CEO]),
    ("can_manage_bank_accounts",     "Manage bank accounts & transactions",      [GROUP_CEO]),
    ("can_view_financial_overview",  "View company-wide financial overview",     [GROUP_CEO]),

    # --- Loans --------------------------------------------------------------
    ("can_approve_loans",            "Approve or renew loans",                   [GROUP_MANAGER, GROUP_CEO]),
    ("can_approve_unlimited_loans",  "Approve loans above the standard manager limit", [GROUP_CEO]),
    ("can_regenerate_schedule",      "Regenerate a loan's repayment schedule",   [GROUP_MANAGER, GROUP_CEO]),
    ("can_write_off_loans",          "Write off loans",                          [GROUP_CEO]),
    ("can_backdate_transactions",    "Back-date disbursements/payments",         [GROUP_CEO]),
    ("can_edit_any_loan",            "Edit or delete loans created by others",   [GROUP_MANAGER, GROUP_CEO]),
    ("can_view_all_loan_products",   "View inactive/all loan products",          [GROUP_CEO]),

    # --- Clients & payments -------------------------------------------------
    ("can_manage_clients",           "Manage all clients, not just own branch",  [GROUP_MANAGER, GROUP_CEO]),
    ("can_manage_payments",          "Edit or reverse recorded payments",        [GROUP_MANAGER, GROUP_CEO]),

    # --- Reports & branch visibility ----------------------------------------
    ("can_view_reports",             "View reports",                             [GROUP_MANAGER, GROUP_CEO]),
    ("can_view_all_branches",        "View/filter data across all branches",     [GROUP_CEO]),
]

# codename -> description, for quick lookups (e.g. rendering the admin UI)
PERMISSION_LABELS = {codename: label for codename, label, _ in PERMISSIONS}
