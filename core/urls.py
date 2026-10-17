from django.contrib.auth import views as auth_views
from django.urls import path

from . import views
from .forms import LoginForm

urlpatterns = [
    path("", views.home, name="home"),
    path("register/", views.register, name="register"),
    path("login/", auth_views.LoginView.as_view(authentication_form=LoginForm), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("classes/", views.class_list, name="class_list"),
    path("classes/new/", views.class_create, name="class_create"),
    path("classes/<int:pk>/", views.class_detail, name="class_detail"),
    path("classes/join/", views.class_join, name="class_join"),
    # teacher
    path("exams/new/", views.exam_create, name="exam_create"),
    path("exams/<int:pk>/", views.exam_detail, name="exam_detail"),
    path("exams/<int:pk>/edit/", views.exam_edit, name="exam_edit"),
    path("exams/<int:pk>/delete/", views.exam_delete, name="exam_delete"),
    path("exams/<int:pk>/publish/", views.exam_toggle_publish, name="exam_toggle_publish"),
    path("exams/<int:pk>/questions/add/", views.question_add, name="question_add"),
    path("exams/<int:pk>/questions/<int:qid>/edit/", views.question_edit, name="question_edit"),
    path("exams/<int:pk>/questions/<int:qid>/delete/", views.question_delete, name="question_delete"),
    path("exams/<int:pk>/results/", views.exam_results, name="exam_results"),
    path("exams/<int:pk>/results.csv", views.exam_results_csv, name="exam_results_csv"),
    path("exams/<int:pk>/analytics/", views.exam_analytics_view, name="exam_analytics"),
    # student
    path("take/<int:pk>/", views.exam_start, name="exam_start"),
    path("attempt/<int:pk>/", views.attempt_take, name="attempt_take"),
    path("attempt/<int:pk>/save/", views.attempt_save, name="attempt_save"),
    path("attempt/<int:pk>/event/", views.attempt_event, name="attempt_event"),
    path("attempt/<int:pk>/submit/", views.attempt_submit, name="attempt_submit"),
    path("attempt/<int:pk>/result/", views.attempt_result, name="attempt_result"),
]
