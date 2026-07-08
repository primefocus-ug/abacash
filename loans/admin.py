from django.contrib import admin

from .models import Loan, LoanProduct, LoanSchedule
from .models import LoanScheduleExtension


@admin.register(LoanProduct)
class LoanProductAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "interest_rate_monthly",
        "interest_method",
        "default_repayment_frequency",
        "min_amount",
        "max_amount",
        "min_term_months",
        "max_term_months",
        "requires_guarantor",
        "is_active",
        "created_at",
    )
    list_filter = (
        "interest_method",
        "default_repayment_frequency",
        "requires_guarantor",
        "is_active",
    )
    search_fields = ("name", "description")
    ordering = ("name",)


@admin.register(Loan)
class LoanAdmin(admin.ModelAdmin):
    list_display = (
        "loan_number",
        "client",
        "product",
        "status",
        "principal_amount",
        "application_date",
        "approval_date",
        "disbursement_date",
    )
    list_filter = ("status", "product", "application_date")
    search_fields = ("loan_number", "client__first_name", "client__last_name")
    ordering = ("-application_date",)


@admin.register(LoanSchedule)
class LoanScheduleAdmin(admin.ModelAdmin):
    list_display = (
        "loan",
        "period_number",
        "due_date",
        "status",
        "total_payment",
        "amount_paid",
        "paid_date",
    )
    list_filter = ("status", "due_date")
    search_fields = ("loan__loan_number",)
    ordering = ("loan", "period_number")


@admin.register(LoanScheduleExtension)
class LoanScheduleExtensionAdmin(admin.ModelAdmin):
    list_display = (
        "schedule_entry",
        "old_due_date",
        "new_due_date",
        "extended_by",
        "extended_at",
    )
    search_fields = ("schedule_entry__loan__loan_number", "extended_by__username")
    ordering = ("-extended_at",)

