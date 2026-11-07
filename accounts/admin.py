from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import BankTransaction, CapitalInjection, Expense, Investor, InvestorDrawing, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "email", "role", "is_staff", "is_active")
    list_filter = ("role", "is_staff", "is_active")
    search_fields = ("username", "email", "first_name", "last_name")
    ordering = ("username",)

    fieldsets = BaseUserAdmin.fieldsets + (
        ("ABA Uganda", {"fields": ("role", "phone")}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ("ABA Uganda", {"fields": ("role", "phone")}),
    )



@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("expense_date", "category", "amount", "created_by")
    list_filter = ("category", "expense_date")
    search_fields = ("description", "created_by__username", "created_by__first_name", "created_by__last_name")


@admin.register(BankTransaction)
class BankTransactionAdmin(admin.ModelAdmin):
    list_display = ("transaction_date", "bank_account", "transaction_type", "amount", "branch")
    list_filter = ("transaction_type", "branch", "transaction_date")
    search_fields = ("category", "reference_number", "bank_account__account_name", "bank_account__bank_name")


@admin.register(CapitalInjection)
class CapitalInjectionAdmin(admin.ModelAdmin):
    list_display = ("injected_date", "source", "amount", "payment_method", "branch", "investor", "attracts_interest")
    list_filter = ("injected_date", "payment_method", "branch")
    search_fields = ("source", "investor", "notes")


@admin.register(Investor)
class InvestorAdmin(admin.ModelAdmin):
    list_display = ("name", "investor_type", "committed_amount", "status", "branch", "phone")
    list_filter = ("investor_type", "status", "payment_method", "branch")
    search_fields = ("name", "phone", "email", "national_id")


@admin.register(InvestorDrawing)
class InvestorDrawingAdmin(admin.ModelAdmin):
    list_display = ("drawing_date", "investor", "amount", "payment_method", "purpose")
    list_filter = ("drawing_date", "payment_method")
    search_fields = ("investor__name", "purpose", "notes")
