from django.urls import path
from . import views

app_name = "reports"

urlpatterns = [
    path("",                  views.report_index,          name="index"),

    path("loan-book/",        views.loan_book,             name="loan_book"),
    path("loan-book/download/", views.loan_book_download,  name="loan_book_download"),

    path("staff-performance/", views.staff_performance_report, name="staff_performance"),
    path("staff-performance/download/", views.staff_performance_download, name="staff_performance_download"),

    path("collections/",      views.collections_report,    name="collections"),
    path("collections/download/", views.collections_download, name="collections_download"),

    path("cash-flow/",        views.cash_flow_report,      name="cash_flow"),
    path("cash-flow/download/", views.cash_flow_download,  name="cash_flow_download"),

    path("overdue/",          views.overdue_report,        name="overdue"),
    path("overdue/download/", views.overdue_download,      name="overdue_download"),

    path("income/",           views.income_statement,      name="income"),
    path("income/download/",  views.income_download,       name="income_download"),

    path("disbursements/",    views.disbursements_report,  name="disbursements"),
    path("disbursements/download/", views.disbursements_download, name="disbursements_download"),

    path("repayments/",       views.repayments_report,     name="repayments"),
    path("repayments/download/", views.repayments_download, name="repayments_download"),

    path("defaulted/",        views.defaulted_loans_report,name="defaulted"),
    path("defaulted/download/", views.defaulted_download,  name="defaulted_download"),

    path("closed-loans/",     views.closed_loans_report,   name="closed_loans"),
    path("closed-loans/download/", views.closed_loans_download, name="closed_loans_download"),

    path("par/",              views.par_report,            name="par"),
    path("par/download/",     views.par_download,          name="par_download"),

    path("client-statement/", views.client_statement,      name="client_statement"),
    path("client-statement/download/", views.client_statement_download, name="client_statement_download"),
]