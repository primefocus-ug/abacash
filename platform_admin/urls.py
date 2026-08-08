from django.urls import path

from . import views

app_name = "platform_admin"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("companies/", views.company_list, name="company_list"),
    path("companies/<str:schema_name>/", views.company_detail, name="company_detail"),
    path("companies/<str:schema_name>/toggle-active/", views.company_toggle_active, name="company_toggle_active"),
    path("companies/<str:schema_name>/update-plan/", views.company_update_plan, name="company_update_plan"),
    path("companies/<str:schema_name>/retry-provisioning/", views.company_retry_provisioning, name="company_retry_provisioning"),
]
