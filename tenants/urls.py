from django.urls import path
from . import views

app_name = "tenants"

urlpatterns = [
    path("",          views.landing,  name="landing"),
    path("features/", views.features, name="features"),
    path("pricing/",  views.pricing,  name="pricing"),
    path("pages/",    views.pages,    name="pages"),
    path("public-admin/", views.public_admin, name="public_admin"),
    path("public-admin/login/", views.public_admin_login, name="public_admin_login"),
    path("public-admin/logout/", views.public_admin_logout, name="public_admin_logout"),
    path("register/", views.register, name="public_register"),
    path("login/",    views.public_login, name="public_login"),
    path("support/",  views.support,      name="support"),
    path("success/",  views.success,      name="success"),
]
