from django.contrib import admin
from .models import Company, Domain, CompanyRegistration


class DomainInline(admin.TabularInline):
    model = Domain
    extra = 1


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("name", "schema_name", "is_active", "created_on")
    inlines = [DomainInline]


@admin.register(CompanyRegistration)
class CompanyRegistrationAdmin(admin.ModelAdmin):
    list_display  = ("company_name", "contact_name", "email", "phone", "plan", "status", "submitted_at")
    list_filter   = ("status", "plan", "country")
    search_fields = ("company_name", "contact_name", "email", "phone")
    list_editable = ("status",)
    readonly_fields = ("submitted_at",)
    ordering = ("-submitted_at",)
