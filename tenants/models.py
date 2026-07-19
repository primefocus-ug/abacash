from django.db import models
from django_tenants.models import TenantMixin, DomainMixin


class Plan(models.TextChoices):
    STARTER = "STARTER", "Starter — up to 500 clients"
    PROFESSIONAL = "PROFESSIONAL", "Professional — up to 2,000 clients"
    ENTERPRISE = "ENTERPRISE", "Enterprise — unlimited"


class Company(TenantMixin):
    name = models.CharField(max_length=200)
    plan = models.CharField(max_length=20, choices=Plan.choices, default=Plan.STARTER)
    created_on = models.DateField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    auto_create_schema = True

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Company"
        verbose_name_plural = "Companies"
        ordering = ["name"]


class Domain(DomainMixin):
    pass


class CompanyRegistration(models.Model):
    """
    Stores interest/registration requests submitted via the public landing page.
    Lives in the public schema — no tenant context needed.
    """

    Plan = Plan

    class Status(models.TextChoices):
        PENDING    = "PENDING",    "Pending Review"
        CONTACTED  = "CONTACTED",  "Contacted"
        ONBOARDED  = "ONBOARDED",  "Onboarded"
        REJECTED   = "REJECTED",   "Rejected"

    company_name   = models.CharField(max_length=200)
    contact_name   = models.CharField(max_length=200)
    email          = models.EmailField()
    phone          = models.CharField(max_length=30)
    country        = models.CharField(max_length=100, default="Uganda")
    city           = models.CharField(max_length=100, blank=True)
    plan           = models.CharField(max_length=20, choices=Plan.choices, default=Plan.STARTER)
    message        = models.TextField(blank=True, help_text="Anything else you'd like us to know")
    status         = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    submitted_at   = models.DateTimeField(auto_now_add=True)
    notes          = models.TextField(blank=True, help_text="Internal notes")

    def __str__(self):
        return f"{self.company_name} — {self.contact_name} ({self.get_status_display()})"

    class Meta:
        ordering = ["-submitted_at"]
        verbose_name = "Company Registration"
        verbose_name_plural = "Company Registrations"
