from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import BankTransaction, CapitalInjection, Expense, User


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
    list_display = ("injected_date", "source", "amount", "investor")
    list_filter = ("injected_date",)
    search_fields = ("source", "investor", "notes")
