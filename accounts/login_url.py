from accounts.views import login_view
from django.urls import path


urlpatterns = [
    path("", login_view, name="login"),
]