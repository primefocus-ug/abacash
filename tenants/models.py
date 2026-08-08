from django.contrib.auth.hashers import check_password, make_password
from django.db import models
from django_tenants.models import TenantMixin, DomainMixin


class Plan(models.TextChoices):
    STARTER = "STARTER", "Starter — up to 500 clients"
    PROFESSIONAL = "PROFESSIONAL", "Professional — up to 2,000 clients"
    ENTERPRISE = "ENTERPRISE", "Enterprise — unlimited"


class Company(TenantMixin):
    class ProvisioningStatus(models.TextChoices):
        PENDING = "PENDING", "Pending"
        RUNNING = "RUNNING", "Provisioning"
        READY   = "READY",   "Ready"
        FAILED  = "FAILED",  "Failed"

    name = models.CharField(max_length=200)
    plan = models.CharField(max_length=20, choices=Plan.choices, default=Plan.STARTER)
    created_on = models.DateField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    provisioning_status = models.CharField(
        max_length=10, choices=ProvisioningStatus.choices, default=ProvisioningStatus.PENDING,
        help_text="Tracks background schema creation + seeding via Celery. "
                   "A company is not safe to log into until this reaches READY.",
    )
    provisioning_error = models.TextField(blank=True)
    provisioning_started_at = models.DateTimeField(null=True, blank=True)
    provisioning_completed_at = models.DateTimeField(null=True, blank=True)

    # Schema creation is driven explicitly by tenants.provisioning.provision_tenant()
    # (called from a Celery task), NOT automatically on save(). This is what makes
    # background provisioning possible — with auto_create_schema=True, django-tenants
    # creates and migrates the schema synchronously inside save() itself, which would
    # block the request no matter what we do around it.
    auto_create_schema = False

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Company"
        verbose_name_plural = "Companies"
        ordering = ["name"]


class Domain(DomainMixin):
    pass


class PlatformAdmin(models.Model):
    """
    System-admin account for the /public-admin/ control panel.

    Deliberately separate from django.contrib.auth.models.User: AUTH_USER_MODEL
    is already set to the tenant-scoped accounts.User, and Django only supports
    one swappable user model per project. This model reimplements just enough
    of the auth surface (hashed password storage/verification) to be driven by
    tenants.auth, which handles authentication and session management by hand.
    """

    class Role(models.TextChoices):
        SUPERADMIN = "SUPERADMIN", "Super Admin"
        OPERATOR = "OPERATOR", "Operator"

    username = models.CharField(max_length=150, unique=True)
    email = models.EmailField(max_length=254, unique=True)
    password = models.CharField(max_length=128)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    role = models.CharField(max_length=12, choices=Role.choices, default=Role.OPERATOR)
    is_active = models.BooleanField(default=True)
    last_login = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Platform Admin"
        verbose_name_plural = "Platform Admins"
        ordering = ["username"]

    def __str__(self):
        return self.username

    def set_password(self, raw_password):
        self.password = make_password(raw_password)

    def check_password(self, raw_password):
        return check_password(raw_password, self.password)

    def get_full_name(self):
        full_name = f"{self.first_name} {self.last_name}".strip()
        return full_name or self.username

    @property
    def is_superadmin(self):
        return self.role == self.Role.SUPERADMIN


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
