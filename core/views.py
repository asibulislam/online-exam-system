import csv
import random
from datetime import timedelta
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db.models import Count, F, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import ClassRoomForm, ExamForm, JoinClassForm, QuestionForm, RegisterForm
from .models import Answer, Attempt, Choice, ClassRoom, Enrollment, Exam, Question
from .utils import csv_safe, exam_analytics


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def role_required(role):
    """Only let users with this role in; everybody else goes back to their dashboard."""

    def decorator(view):
        @login_required
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if request.user.role != role:
                messages.error(request, "You do not have access to that page.")
                return redirect("dashboard")
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


teacher_required = role_required("teacher")
student_required = role_required("student")


def grade_overdue(exam, now=None):
    """Grade attempts whose time ran out without a submit, so teachers never see them stuck."""
    now = now or timezone.now()
    for attempt in exam.attempts.filter(submitted_at__isnull=True, deadline__lt=now):
        attempt.finalize(now)


def save_answer(attempt, question_id, choice_id):
    """Store one answer. Returns False if the ids do not belong to this exam."""
    try:
        question_id, choice_id = int(question_id), int(choice_id)
    except (TypeError, ValueError):
        return False
    question = Question.objects.filter(pk=question_id, exam_id=attempt.exam_id).first()
    choice = Choice.objects.filter(pk=choice_id, question_id=question_id).first()
    if not question or not choice:
        return False
    Answer.objects.update_or_create(attempt=attempt, question=question, defaults={"choice": choice})
    return True


# --------------------------------------------------------------------------
# public pages and accounts
# --------------------------------------------------------------------------
def home(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    return render(request, "core/home.html")


def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, f"Welcome, {user.display_name}! Your account is ready.")
        return redirect("dashboard")
    return render(request, "core/register.html", {"form": form})


@login_required
def dashboard(request):
    if request.user.is_teacher:
        return teacher_dashboard(request)
    return student_dashboard(request)


# --------------------------------------------------------------------------
# teacher side
# --------------------------------------------------------------------------
@teacher_required
def teacher_dashboard(request):
    exams = (
        Exam.objects.filter(teacher=request.user)
        .annotate(
            q_count=Count("questions", distinct=True),
            done_count=Count("attempts", filter=Q(attempts__submitted_at__isnull=False), distinct=True),
        )
        .order_by("-start_time")
    )
    now = timezone.now()
    for exam in exams:
        exam.state = exam.status(now)
    return render(request, "core/teacher_dashboard.html", {"exams": exams})


@teacher_required
def class_list(request):
    classes = ClassRoom.objects.filter(teacher=request.user).annotate(
        student_count=Count("enrollments", distinct=True)
    )
    return render(request, "core/class_list.html", {"classes": classes})


@teacher_required
def class_create(request):
    form = ClassRoomForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        classroom = form.save(commit=False)
        classroom.teacher = request.user
        classroom.save()
        messages.success(request, f"Class created. Students join with the code {classroom.code}.")
        return redirect("class_detail", pk=classroom.pk)
    return render(request, "core/class_form.html", {"form": form})


@teacher_required
def class_detail(request, pk):
    classroom = get_object_or_404(ClassRoom, pk=pk, teacher=request.user)
    return render(
        request,
        "core/class_detail.html",
        {
            "classroom": classroom,
            "students": classroom.enrollments.select_related("student").order_by("student__first_name", "student__username"),
            "exams": classroom.exams.order_by("-start_time"),
        },
    )


@teacher_required
def exam_create(request):
    form = ExamForm(request.POST or None, teacher=request.user)
    if request.method == "POST" and form.is_valid():
        exam = form.save(commit=False)
        exam.teacher = request.user
        exam.save()
        messages.success(request, "Exam created. Now add some questions.")
        return redirect("exam_detail", pk=exam.pk)
    return render(request, "core/exam_form.html", {"form": form, "title": "Create exam"})


@teacher_required
def exam_edit(request, pk):
    exam = get_object_or_404(Exam, pk=pk, teacher=request.user)
    form = ExamForm(request.POST or None, instance=exam, teacher=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Exam updated. Students who already started keep their original deadline.")
        return redirect("exam_detail", pk=exam.pk)
    return render(request, "core/exam_form.html", {"form": form, "title": "Edit exam", "exam": exam})


@teacher_required
@require_POST
def exam_delete(request, pk):
    exam = get_object_or_404(Exam, pk=pk, teacher=request.user)
    exam.delete()
    messages.success(request, "Exam deleted.")
    return redirect("dashboard")


@teacher_required
def exam_detail(request, pk):
    exam = get_object_or_404(Exam, pk=pk, teacher=request.user)
    questions = exam.questions.prefetch_related("choices")
    has_attempts = exam.attempts.exists()
    return render(
        request,
        "core/exam_detail.html",
        {
            "exam": exam,
            "questions": questions,
            "total_marks": exam.total_marks(),
            "has_attempts": has_attempts,
            "state": exam.status(),
        },
    )


@teacher_required
@require_POST
def exam_toggle_publish(request, pk):
    exam = get_object_or_404(Exam, pk=pk, teacher=request.user)
    if not exam.is_published and not exam.questions.exists():
        messages.error(request, "Add at least one question before publishing.")
    else:
        exam.is_published = not exam.is_published
        exam.save(update_fields=["is_published"])
        messages.success(request, "Exam published." if exam.is_published else "Exam unpublished.")
    return redirect("exam_detail", pk=exam.pk)


def _locked(request, exam):
    """Questions cannot change once a student has started: it would change their grades."""
    if exam.attempts.exists():
        messages.error(request, "Questions are locked because students have already started this exam.")
        return True
    return False


@teacher_required
def question_add(request, pk):
    exam = get_object_or_404(Exam, pk=pk, teacher=request.user)
    if _locked(request, exam):
        return redirect("exam_detail", pk=exam.pk)
    form = QuestionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save(exam)
        messages.success(request, "Question added.")
        if "save_add" in request.POST:
            return redirect("question_add", pk=exam.pk)
        return redirect("exam_detail", pk=exam.pk)
    return render(request, "core/question_form.html", {"form": form, "exam": exam, "title": "Add question"})


@teacher_required
def question_edit(request, pk, qid):
    exam = get_object_or_404(Exam, pk=pk, teacher=request.user)
    question = get_object_or_404(Question, pk=qid, exam=exam)
    if _locked(request, exam):
        return redirect("exam_detail", pk=exam.pk)
    if request.method == "POST":
        form = QuestionForm(request.POST, question=question)
    else:
        form = QuestionForm(question=question)
    if request.method == "POST" and form.is_valid():
        form.save(exam)
        messages.success(request, "Question updated.")
        return redirect("exam_detail", pk=exam.pk)
    return render(request, "core/question_form.html", {"form": form, "exam": exam, "title": "Edit question"})


@teacher_required
@require_POST
def question_delete(request, pk, qid):
    exam = get_object_or_404(Exam, pk=pk, teacher=request.user)
    question = get_object_or_404(Question, pk=qid, exam=exam)
    if not _locked(request, exam):
        question.delete()
        messages.success(request, "Question deleted.")
    return redirect("exam_detail", pk=exam.pk)


@teacher_required
def exam_results(request, pk):
    exam = get_object_or_404(Exam, pk=pk, teacher=request.user)
    grade_overdue(exam)
    attempts = exam.attempts.filter(submitted_at__isnull=False).select_related("student")
    ranked = sorted(attempts, key=lambda a: (-a.percent, a.minutes_taken))
    in_progress = exam.attempts.filter(submitted_at__isnull=True).count()
    return render(
        request,
        "core/exam_results.html",
        {"exam": exam, "attempts": ranked, "in_progress": in_progress},
    )


@teacher_required
def exam_results_csv(request, pk):
    exam = get_object_or_404(Exam, pk=pk, teacher=request.user)
    grade_overdue(exam)
    attempts = exam.attempts.filter(submitted_at__isnull=False).select_related("student")
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="exam-{exam.pk}-results.csv"'
    writer = csv.writer(response)
    writer.writerow(["Rank", "Username", "Name", "Score", "Total", "Percent", "Result", "Minutes taken", "Tab switches", "Submitted at"])
    ranked = sorted(attempts, key=lambda a: (-a.percent, a.minutes_taken))
    for rank, a in enumerate(ranked, start=1):
        writer.writerow(
            [
                rank,
                csv_safe(a.student.username),
                csv_safe(a.student.display_name),
                a.score,
                a.total,
                a.percent,
                "Pass" if a.passed else "Fail",
                a.minutes_taken,
                a.tab_switches,
                timezone.localtime(a.submitted_at).strftime("%Y-%m-%d %H:%M"),
            ]
        )
    return response


@teacher_required
def exam_analytics_view(request, pk):
    exam = get_object_or_404(Exam, pk=pk, teacher=request.user)
    grade_overdue(exam)
    data = exam_analytics(exam)
    chart = {
        "distribution": {
            "labels": [f"{i * 10}-{i * 10 + 10}%" for i in range(10)],
            "values": data["distribution"],
        },
        "questions": {
            "labels": [f"Q{i}" for i in range(1, len(data["questions"]) + 1)],
            "values": [q["pct"] for q in data["questions"]],
        },
        "topics": {
            "labels": [t["topic"] for t in data["topics"]],
            "values": [t["pct"] for t in data["topics"]],
        },
        "pass_mark": exam.pass_percent,
    }
    return render(request, "core/exam_analytics.html", {"exam": exam, "a": data, "chart": chart})


# --------------------------------------------------------------------------
# student side
# --------------------------------------------------------------------------
def visible_exams(user):
    """Published exams this student may see: their classes' exams plus exams with no class."""
    joined = Enrollment.objects.filter(student=user).values("classroom_id")
    return Exam.objects.filter(is_published=True).filter(Q(classroom__isnull=True) | Q(classroom_id__in=joined))


@student_required
@require_POST
def class_join(request):
    form = JoinClassForm(request.POST)
    if form.is_valid():
        Enrollment.objects.get_or_create(classroom=form.classroom, student=request.user)
        messages.success(request, f"You joined {form.classroom.name}.")
    else:
        for error in form.errors.get("code", []):
            messages.error(request, error)
    return redirect("dashboard")


@student_required
def student_dashboard(request):
    now = timezone.now()
    my_attempts = {a.exam_id: a for a in Attempt.objects.filter(student=request.user).select_related("exam")}

    # An attempt whose time ran out while the student was away is graded now.
    for attempt in my_attempts.values():
        if not attempt.is_submitted and now > attempt.deadline:
            attempt.finalize(now)

    buckets = {"available": [], "upcoming": [], "missed": [], "completed": []}
    for exam in visible_exams(request.user).select_related("teacher", "classroom").order_by("start_time"):
        attempt = my_attempts.get(exam.pk)
        exam.attempt = attempt
        state = exam.status(now)
        if attempt and attempt.is_submitted:
            buckets["completed"].append(exam)
        elif state == "open":
            buckets["available"].append(exam)
        elif state == "upcoming":
            buckets["upcoming"].append(exam)
        else:
            buckets["missed"].append(exam)

    done = [e.attempt for e in buckets["completed"]]
    summary = {
        "count": len(done),
        "avg": round(sum(a.percent for a in done) / len(done), 1) if done else None,
        "passed": sum(1 for a in done if a.passed),
    }
    joined_classes = ClassRoom.objects.filter(enrollments__student=request.user).order_by("name")
    join_form = JoinClassForm()
    return render(
        request,
        "core/student_dashboard.html",
        {**buckets, "summary": summary, "joined_classes": joined_classes, "join_form": join_form},
    )


@student_required
def exam_start(request, pk):
    """GET shows the rules. POST starts the clock."""
    exam = get_object_or_404(visible_exams(request.user), pk=pk)
    now = timezone.now()
    existing = Attempt.objects.filter(exam=exam, student=request.user).first()
    if existing:
        if existing.is_submitted:
            return redirect("attempt_result", pk=existing.pk)
        return redirect("attempt_take", pk=existing.pk)
    if exam.status(now) != "open":
        messages.error(request, "This exam is not open right now.")
        return redirect("dashboard")
    if request.method == "POST":
        deadline = min(now + timedelta(minutes=exam.duration_minutes), exam.end_time)
        attempt, _ = Attempt.objects.get_or_create(exam=exam, student=request.user, defaults={"deadline": deadline})
        return redirect("attempt_take", pk=attempt.pk)
    return render(
        request,
        "core/exam_instructions.html",
        {
            "exam": exam,
            "question_count": exam.questions.count(),
            "total_marks": exam.total_marks(),
            "minutes": min(exam.duration_minutes, max(1, int((exam.end_time - now).total_seconds() // 60))),
        },
    )


@student_required
def attempt_take(request, pk):
    attempt = get_object_or_404(Attempt.objects.select_related("exam"), pk=pk, student=request.user)
    now = timezone.now()
    if attempt.is_submitted:
        return redirect("attempt_result", pk=attempt.pk)
    if now > attempt.deadline:
        attempt.finalize(now)
        messages.info(request, "Time was up, so your exam was submitted automatically.")
        return redirect("attempt_result", pk=attempt.pk)

    exam = attempt.exam
    questions = list(exam.questions.prefetch_related("choices"))
    if exam.shuffle:
        random.Random(attempt.pk).shuffle(questions)
    for q in questions:
        q.options = list(q.choices.all())
        if exam.shuffle:
            random.Random(attempt.pk * 100003 + q.pk).shuffle(q.options)

    saved = {a.question_id: a.choice_id for a in attempt.answers.all()}
    for q in questions:
        q.selected = saved.get(q.pk)

    return render(
        request,
        "core/exam_take.html",
        {
            "attempt": attempt,
            "exam": exam,
            "questions": questions,
            "remaining": max(0, int((attempt.deadline - now).total_seconds())),
            "answered": len(saved),
            "tab_switches": attempt.tab_switches,
        },
    )


@student_required
@require_POST
def attempt_save(request, pk):
    """Called by the browser every time a student picks an option (auto-save)."""
    attempt = get_object_or_404(Attempt, pk=pk, student=request.user)
    now = timezone.now()
    if attempt.is_submitted or now > attempt.deadline:
        return JsonResponse({"ok": False, "expired": True}, status=403)
    if not save_answer(attempt, request.POST.get("question"), request.POST.get("choice")):
        return JsonResponse({"ok": False}, status=400)
    return JsonResponse({"ok": True, "remaining": int((attempt.deadline - now).total_seconds())})


@student_required
@require_POST
def attempt_event(request, pk):
    """Called by the browser when the exam tab is hidden. Recorded for the teacher, not used for grading."""
    attempt = get_object_or_404(Attempt, pk=pk, student=request.user)
    if attempt.is_submitted or timezone.now() > attempt.deadline:
        return JsonResponse({"ok": False}, status=403)
    if request.POST.get("type") == "tab_hidden":
        Attempt.objects.filter(pk=attempt.pk).update(tab_switches=F("tab_switches") + 1)
    return JsonResponse({"ok": True})


@student_required
@require_POST
def attempt_submit(request, pk):
    attempt = get_object_or_404(Attempt, pk=pk, student=request.user)
    now = timezone.now()
    grace = timedelta(seconds=settings.SUBMIT_GRACE_SECONDS)
    if not attempt.is_submitted and now <= attempt.deadline + grace:
        # The form carries every selected option, so even if an auto-save was
        # missed the last answers still get stored.
        for key, value in request.POST.items():
            if key.startswith("q_"):
                save_answer(attempt, key[2:], value)
    attempt.finalize(now)
    return redirect("attempt_result", pk=attempt.pk)


@student_required
def attempt_result(request, pk):
    attempt = get_object_or_404(Attempt.objects.select_related("exam"), pk=pk, student=request.user)
    if not attempt.is_submitted:
        if timezone.now() > attempt.deadline:
            attempt.finalize()
        else:
            return redirect("attempt_take", pk=attempt.pk)
    chosen = {a.question_id: a.choice_id for a in attempt.answers.all()}
    review = []
    for q in attempt.exam.questions.prefetch_related("choices"):
        picked = chosen.get(q.pk)
        options = list(q.choices.all())
        correct = next((c for c in options if c.is_correct), None)
        review.append(
            {
                "question": q,
                "options": options,
                "picked": picked,
                "correct_id": correct.pk if correct else None,
                "is_correct": picked is not None and correct is not None and picked == correct.pk,
            }
        )
    return render(request, "core/exam_result.html", {"attempt": attempt, "exam": attempt.exam, "review": review})
