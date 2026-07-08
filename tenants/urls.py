from django.urls import path
from . import views

app_name = "tenants"

urlpatterns = [
    path("",         views.landing,  name="landing"),
    path("register/",views.register, name="register"),
    path("success/", views.success,  name="success"),
]
