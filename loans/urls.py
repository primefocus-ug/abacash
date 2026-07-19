from django.urls import path
from . import views

app_name = "loans"

urlpatterns = [
    path("",                         views.loan_list,       name="list"),
    path("apply/",                   views.loan_apply_step1,    name="apply"),
    path("apply/client-search/",      views.client_search_htmx,  name="client_search"),
    path("apply/<uuid:client_id>/",  views.loan_apply_step2,name="apply_step2"),
    path("apply/<uuid:client_id>/schedule-pdf/", views.schedule_preview_pdf, name="apply_schedule_pdf"),
    path("apply/<uuid:client_id>/step3/", views.loan_apply_step3, name="apply_step3"),
    path("apply/<uuid:client_id>/review/", views.loan_apply_review, name="apply_review"),
    path("<uuid:pk>/",               views.loan_detail,     name="detail"),
    path("<uuid:pk>/edit/",          views.loan_edit,       name="edit"),
    path("<uuid:pk>/approve/",       views.loan_approve,    name="approve"),
    path("<uuid:pk>/reject/",        views.loan_reject,     name="reject"),
    path("recall/<uuid:loan_id>/",   views.loan_recall,     name="recall"),
    path("<uuid:pk>/download/",      views.loan_schedule_download, name="schedule_download"),
    path("<uuid:pk>/print/",          views.loan_schedule_print,    name="schedule_print"),
    path("schedule-preview/",        views.schedule_preview,name="schedule_preview"),
    path("<uuid:pk>/reschedule/",     views.loan_reschedule, name="reschedule"),
    path("schedule/<int:pk>/extend/", views.schedule_extend, name="schedule_extend"),
    path("<uuid:pk>/renew/",          views.loan_renew,     name="renew"),
    path("<uuid:pk>/regenerate-schedule/", views.loan_regenerate_schedule, name="regenerate_schedule"),
    path("<uuid:pk>/delete-draft/",  views.loan_draft_delete, name="draft_delete"),
    path("search/",                  views.loan_search,    name="search"),
    # Loan products (CEO config)
    path("products/",                views.loan_product_list,   name="products"),
    path("products/new/",           views.loan_product_create, name="products_create"),
    path("products/<int:pk>/edit/", views.loan_product_edit,   name="products_edit"),
]