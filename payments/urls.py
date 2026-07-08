from django.urls import path
from . import views

app_name = "payments"

urlpatterns = [
    path("",                         views.payment_list,   name="list"),
    path("record/",                  views.record_payment, name="record"),
    path("record/<uuid:loan_pk>/",   views.record_payment, name="record_for_loan"),
    path("receipt/<uuid:pk>/",       views.receipt_view,   name="receipt"),
    path("history/<uuid:loan_pk>/",  views.payment_history,name="history"),
    path("credit-refund/<uuid:client_pk>/", views.credit_refund, name="credit_refund"),
]