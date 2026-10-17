from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Answer, Attempt, Choice, ClassRoom, Enrollment, Exam, Question, User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Role", {"fields": ("role",)}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("Role", {"fields": ("role",)}),)
    list_display = ("username", "email", "role", "is_staff")
    list_filter = UserAdmin.list_filter + ("role",)


class ChoiceInline(admin.TabularInline):
    model = Choice
    extra = 0


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("text", "exam", "topic", "marks")
    list_filter = ("exam", "topic")
    inlines = [ChoiceInline]


@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = ("title", "teacher", "start_time", "end_time", "is_published")
    list_filter = ("is_published",)


@admin.register(ClassRoom)
class ClassRoomAdmin(admin.ModelAdmin):
    list_display = ("name", "teacher", "code")


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ("student", "classroom", "joined_at")


@admin.register(Attempt)
class AttemptAdmin(admin.ModelAdmin):
    list_display = ("student", "exam", "score", "total", "tab_switches", "submitted_at")
    list_filter = ("exam",)


admin.site.register(Answer)
