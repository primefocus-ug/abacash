from django.db import migrations, models
import django.core.validators
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0012_companysettings_loan_terms"),
    ]

    operations = [
        migrations.CreateModel(
            name="Investor",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=200)),
                ("investor_type", models.CharField(choices=[("INDIVIDUAL", "Individual"), ("COMPANY", "Company"), ("PARTNERSHIP", "Partnership")], default="INDIVIDUAL", max_length=20)),
                ("phone", models.CharField(blank=True, max_length=20)),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("national_id", models.CharField(blank=True, max_length=100)),
                ("address", models.CharField(blank=True, max_length=255)),
                ("committed_amount", models.DecimalField(decimal_places=2, default=0, max_digits=15, validators=[django.core.validators.MinValueValidator(0)])),
                ("investment_date", models.DateField(blank=True, null=True)),
                ("maturity_date", models.DateField(blank=True, null=True)),
                ("payment_method", models.CharField(choices=[("CASH", "Cash"), ("BANK", "Bank Transfer"), ("MOBILE_MONEY", "Mobile Money")], default="BANK", max_length=20)),
                ("status", models.CharField(choices=[("ACTIVE", "Active"), ("INACTIVE", "Inactive"), ("PROSPECT", "Prospect")], default="ACTIVE", max_length=10)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("branch", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="investors", to="accounts.branch")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_investors", to="accounts.user")),
            ],
            options={
                "verbose_name": "Investor",
                "verbose_name_plural": "Investors",
                "ordering": ["name"],
                "indexes": [
                    models.Index(fields=["name"], name="accounts_in_name_7d2c3a_idx"),
                    models.Index(fields=["status"], name="accounts_in_status_5f1c96_idx"),
                    models.Index(fields=["investment_date"], name="accounts_in_investm_46ad8c_idx"),
                ],
            },
        ),
        migrations.AlterModelOptions(
            name="user",
            options={
                "ordering": ["first_name", "last_name"],
                "permissions": [
                    ("can_view_admin_panel", "View the admin panel hub"),
                    ("can_manage_users", "Manage staff accounts"),
                    ("can_manage_branches", "Manage branches"),
                    ("can_manage_loan_products", "Manage loan products & fee types"),
                    ("can_manage_system_settings", "Manage the holiday calendar"),
                    ("can_manage_company_settings", "Manage company settings"),
                    ("can_manage_guarantors", "Manage guarantors"),
                    ("can_verify_guarantors", "Verify guarantors"),
                    ("can_view_audit_log", "View audit log"),
                    ("can_manage_permissions", "Manage roles & permissions"),
                    ("can_manage_expenses", "Record & manage expenses"),
                    ("can_manage_expense_categories", "Manage expense categories"),
                    ("can_manage_capital", "Manage capital injections"),
                    ("can_manage_investors", "Manage investors"),
                    ("can_manage_bank_accounts", "Manage bank accounts & transactions"),
                    ("can_view_financial_overview", "View company-wide financial overview"),
                    ("can_approve_loans", "Approve or renew loans"),
                    ("can_approve_unlimited_loans", "Approve loans above the standard manager limit"),
                    ("can_regenerate_schedule", "Regenerate a loan's repayment schedule"),
                    ("can_write_off_loans", "Write off loans"),
                    ("can_backdate_transactions", "Back-date disbursements/payments"),
                    ("can_edit_any_loan", "Edit or delete loans created by others"),
                    ("can_view_all_loan_products", "View inactive/all loan products"),
                    ("can_manage_clients", "Manage all clients, not just own branch"),
                    ("can_manage_payments", "Edit or reverse recorded payments"),
                    ("can_view_reports", "View reports"),
                    ("can_view_all_branches", "View/filter data across all branches"),
                ],
            },
        ),
    ]
