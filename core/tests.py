from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Answer, Attempt, Choice, ClassRoom, Enrollment, Exam, Question, User
from .utils import csv_safe, exam_analytics


def make_exam(teacher, minutes=30, start_offset=-10, end_offset=120, published=True):
    now = timezone.now()
    exam = Exam.objects.create(
        teacher=teacher,
        title="Test exam",
        subject="Testing",
        duration_minutes=minutes,
        start_time=now + timedelta(minutes=start_offset),
        end_time=now + timedelta(minutes=end_offset),
        pass_percent=50,
        is_published=published,
        shuffle=False,
    )
    # Q1 (2 marks, topic A), Q2 (1 mark, topic B); correct option is always the first one.
    for text, topic, marks in [("Q1?", "A", 2), ("Q2?", "B", 1)]:
        q = Question.objects.create(exam=exam, text=text, topic=topic, marks=marks)
        Choice.objects.create(question=q, text="right", is_correct=True)
        Choice.objects.create(question=q, text="wrong", is_correct=False)
    return exam


class BaseCase(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user("teach", password="pw12345!", role="teacher")
        self.other_teacher = User.objects.create_user("teach2", password="pw12345!", role="teacher")
        self.student = User.objects.create_user("stud", password="pw12345!", role="student")
        self.exam = make_exam(self.teacher)

    def pick(self, attempt, right_for):
        """Answer the questions listed in right_for correctly and the rest wrongly."""
        for q in self.exam.questions.all():
            choice = q.choices.get(is_correct=(q.text in right_for))
            Answer.objects.create(attempt=attempt, question=q, choice=choice)


class GradingTests(BaseCase):
    def test_score_uses_question_marks(self):
        attempt = Attempt.objects.create(exam=self.exam, student=self.student, deadline=timezone.now() + timedelta(minutes=5))
        self.pick(attempt, right_for=["Q1?"])
        attempt.finalize()
        self.assertEqual(attempt.score, 2)
        self.assertEqual(attempt.total, 3)
        self.assertEqual(attempt.percent, 66.7)
        self.assertTrue(attempt.passed)

    def test_skipped_question_scores_zero(self):
        attempt = Attempt.objects.create(exam=self.exam, student=self.student, deadline=timezone.now() + timedelta(minutes=5))
        attempt.finalize()
        self.assertEqual(attempt.score, 0)
        self.assertFalse(attempt.passed)

    def test_finalize_twice_does_not_change_result(self):
        attempt = Attempt.objects.create(exam=self.exam, student=self.student, deadline=timezone.now() + timedelta(minutes=5))
        self.pick(attempt, right_for=["Q1?", "Q2?"])
        attempt.finalize()
        first = attempt.submitted_at
        attempt.finalize(timezone.now() + timedelta(hours=1))
        self.assertEqual(attempt.submitted_at, first)
        self.assertEqual(attempt.score, 3)


class StudentFlowTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.client.login(username="stud", password="pw12345!")

    def start(self):
        self.client.post(reverse("exam_start", args=[self.exam.pk]))
        return Attempt.objects.get(exam=self.exam, student=self.student)

    def test_deadline_is_duration_after_start(self):
        attempt = self.start()
        delta = attempt.deadline - attempt.started_at
        self.assertAlmostEqual(delta.total_seconds(), 30 * 60, delta=5)

    def test_deadline_never_passes_exam_end(self):
        exam = make_exam(self.teacher, minutes=60, end_offset=10)
        self.client.post(reverse("exam_start", args=[exam.pk]))
        attempt = Attempt.objects.get(exam=exam, student=self.student)
        self.assertEqual(attempt.deadline, exam.end_time)

    def test_cannot_start_unpublished_closed_or_upcoming(self):
        draft = make_exam(self.teacher, published=False)
        closed = make_exam(self.teacher, start_offset=-200, end_offset=-100)
        upcoming = make_exam(self.teacher, start_offset=60, end_offset=200)
        self.assertEqual(self.client.post(reverse("exam_start", args=[draft.pk])).status_code, 404)
        for exam in (closed, upcoming):
            self.client.post(reverse("exam_start", args=[exam.pk]))
            self.assertFalse(Attempt.objects.filter(exam=exam).exists())

    def test_only_one_attempt_per_student(self):
        first = self.start()
        self.client.post(reverse("exam_start", args=[self.exam.pk]))
        self.assertEqual(Attempt.objects.filter(exam=self.exam, student=self.student).count(), 1)
        self.assertEqual(Attempt.objects.get(exam=self.exam).pk, first.pk)

    def test_autosave_stores_and_replaces_answer(self):
        attempt = self.start()
        q = self.exam.questions.first()
        right, wrong = q.choices.get(is_correct=True), q.choices.get(is_correct=False)
        url = reverse("attempt_save", args=[attempt.pk])
        self.assertEqual(self.client.post(url, {"question": q.pk, "choice": wrong.pk}).status_code, 200)
        self.assertEqual(self.client.post(url, {"question": q.pk, "choice": right.pk}).status_code, 200)
        answers = Answer.objects.filter(attempt=attempt)
        self.assertEqual(answers.count(), 1)
        self.assertEqual(answers.first().choice, right)

    def test_autosave_rejects_choice_from_another_question(self):
        attempt = self.start()
        q1, q2 = self.exam.questions.all()
        stray = q2.choices.first()
        res = self.client.post(reverse("attempt_save", args=[attempt.pk]), {"question": q1.pk, "choice": stray.pk})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(Answer.objects.count(), 0)

    def test_autosave_rejected_after_deadline(self):
        attempt = self.start()
        Attempt.objects.filter(pk=attempt.pk).update(deadline=timezone.now() - timedelta(seconds=1))
        q = self.exam.questions.first()
        res = self.client.post(reverse("attempt_save", args=[attempt.pk]), {"question": q.pk, "choice": q.choices.first().pk})
        self.assertEqual(res.status_code, 403)
        self.assertEqual(Answer.objects.count(), 0)

    def test_submit_after_grace_ignores_new_answers_but_still_grades(self):
        attempt = self.start()
        Attempt.objects.filter(pk=attempt.pk).update(deadline=timezone.now() - timedelta(minutes=5))
        q = self.exam.questions.first()
        self.client.post(reverse("attempt_submit", args=[attempt.pk]), {f"q_{q.pk}": q.choices.get(is_correct=True).pk})
        attempt.refresh_from_db()
        self.assertTrue(attempt.is_submitted)
        self.assertEqual(attempt.score, 0)

    def test_submit_within_time_grades_posted_answers(self):
        attempt = self.start()
        data = {f"q_{q.pk}": q.choices.get(is_correct=True).pk for q in self.exam.questions.all()}
        res = self.client.post(reverse("attempt_submit", args=[attempt.pk]), data)
        self.assertRedirects(res, reverse("attempt_result", args=[attempt.pk]))
        attempt.refresh_from_db()
        self.assertEqual((attempt.score, attempt.total), (3, 3))

    def test_expired_attempt_is_auto_submitted_when_opened(self):
        attempt = self.start()
        Attempt.objects.filter(pk=attempt.pk).update(deadline=timezone.now() - timedelta(seconds=1))
        res = self.client.get(reverse("attempt_take", args=[attempt.pk]))
        self.assertRedirects(res, reverse("attempt_result", args=[attempt.pk]))
        attempt.refresh_from_db()
        self.assertTrue(attempt.is_submitted)

    def test_take_page_does_not_leak_correct_answers(self):
        attempt = self.start()
        html = self.client.get(reverse("attempt_take", args=[attempt.pk])).content.decode()
        self.assertIn("Q1?", html)
        self.assertNotIn("is_correct", html)

    def test_student_cannot_open_another_students_attempt(self):
        attempt = self.start()
        User.objects.create_user("stud2", password="pw12345!", role="student")
        self.client.login(username="stud2", password="pw12345!")
        self.assertEqual(self.client.get(reverse("attempt_take", args=[attempt.pk])).status_code, 404)

    def test_student_dashboard_buckets(self):
        make_exam(self.teacher, start_offset=60, end_offset=200)  # upcoming
        res = self.client.get(reverse("dashboard"))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.context["available"]), 1)
        self.assertEqual(len(res.context["upcoming"]), 1)


class PermissionTests(BaseCase):
    def test_student_blocked_from_teacher_pages(self):
        self.client.login(username="stud", password="pw12345!")
        for name, args in [("exam_create", []), ("exam_detail", [self.exam.pk]), ("exam_analytics", [self.exam.pk])]:
            res = self.client.get(reverse(name, args=args))
            self.assertRedirects(res, reverse("dashboard"), fetch_redirect_response=False)

    def test_teacher_cannot_see_other_teachers_exam(self):
        self.client.login(username="teach2", password="pw12345!")
        self.assertEqual(self.client.get(reverse("exam_detail", args=[self.exam.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("exam_results_csv", args=[self.exam.pk])).status_code, 404)

    def test_anonymous_redirected_to_login(self):
        res = self.client.get(reverse("dashboard"))
        self.assertEqual(res.status_code, 302)
        self.assertIn(reverse("login"), res.url)

    def test_teacher_cannot_start_exam_as_student(self):
        self.client.login(username="teach", password="pw12345!")
        self.client.post(reverse("exam_start", args=[self.exam.pk]))
        self.assertFalse(Attempt.objects.exists())

    def test_questions_locked_after_first_attempt(self):
        Attempt.objects.create(exam=self.exam, student=self.student, deadline=timezone.now() + timedelta(minutes=5))
        self.client.login(username="teach", password="pw12345!")
        q = self.exam.questions.first()
        self.client.post(reverse("question_delete", args=[self.exam.pk, q.pk]))
        self.assertTrue(Question.objects.filter(pk=q.pk).exists())


class TeacherFlowTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.client.login(username="teach", password="pw12345!")

    def test_add_question_creates_choices_with_one_correct(self):
        exam = make_exam(self.teacher)
        exam.attempts.all().delete()
        data = {"text": "New?", "topic": "T", "marks": 2, "choice1": "a", "choice2": "b", "choice3": "c", "choice4": "", "correct": "2"}
        self.client.post(reverse("question_add", args=[exam.pk]), data)
        q = Question.objects.get(text="New?")
        self.assertEqual(q.choices.count(), 3)
        self.assertEqual(q.choices.get(is_correct=True).text, "b")

    def test_correct_option_cannot_be_blank(self):
        data = {"text": "Bad?", "topic": "T", "marks": 1, "choice1": "a", "choice2": "b", "choice3": "", "choice4": "", "correct": "3"}
        res = self.client.post(reverse("question_add", args=[self.exam.pk]), data)
        self.assertEqual(res.status_code, 200)
        self.assertFalse(Question.objects.filter(text="Bad?").exists())

    def test_cannot_publish_without_questions(self):
        empty = Exam.objects.create(
            teacher=self.teacher, title="Empty", subject="x", duration_minutes=5,
            start_time=timezone.now(), end_time=timezone.now() + timedelta(hours=1),
        )
        self.client.post(reverse("exam_toggle_publish", args=[empty.pk]))
        empty.refresh_from_db()
        self.assertFalse(empty.is_published)

    def test_end_time_must_be_after_start(self):
        now = timezone.now()
        data = {
            "title": "x", "subject": "y", "duration_minutes": 10, "pass_percent": 40,
            "start_time": (now + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M"),
            "end_time": (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"),
        }
        res = self.client.post(reverse("exam_create"), data)
        self.assertEqual(res.status_code, 200)
        self.assertFalse(Exam.objects.filter(title="x").exists())

    def test_pages_render(self):
        for name in ["dashboard", "exam_create"]:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)
        for name in ["exam_detail", "exam_edit", "question_add", "exam_results", "exam_analytics"]:
            self.assertEqual(self.client.get(reverse(name, args=[self.exam.pk])).status_code, 200)
        q = self.exam.questions.first()
        self.assertEqual(self.client.get(reverse("question_edit", args=[self.exam.pk, q.pk])).status_code, 200)


class AnalyticsTests(BaseCase):
    def make_attempt(self, username, right_for):
        user = User.objects.create_user(username, password="pw12345!", role="student")
        attempt = Attempt.objects.create(exam=self.exam, student=user, deadline=timezone.now() + timedelta(minutes=30))
        self.pick(attempt, right_for)
        attempt.finalize()
        return attempt

    def test_empty_exam_has_zero_stats(self):
        data = exam_analytics(self.exam)
        self.assertEqual(data["n"], 0)
        self.assertEqual(data["questions"], [])

    def test_numbers(self):
        self.make_attempt("a", ["Q1?", "Q2?"])  # 3/3 = 100%
        self.make_attempt("b", ["Q1?"])          # 2/3 = 66.7%
        self.make_attempt("c", [])               # 0/3 = 0%
        data = exam_analytics(self.exam)
        self.assertEqual(data["n"], 3)
        self.assertEqual(data["highest"], 100)
        self.assertEqual(data["lowest"], 0)
        self.assertEqual(data["avg"], 55.6)
        self.assertEqual(data["pass_count"], 2)
        self.assertEqual(data["pass_rate"], 66.7)
        self.assertEqual(sum(data["distribution"]), 3)
        self.assertEqual(data["distribution"][9], 1)
        self.assertEqual(data["distribution"][6], 1)
        self.assertEqual(data["distribution"][0], 1)

    def test_question_difficulty_and_topics(self):
        self.make_attempt("a", ["Q1?", "Q2?"])
        self.make_attempt("b", ["Q1?"])
        self.make_attempt("c", [])
        data = exam_analytics(self.exam)
        q1, q2 = data["questions"]
        self.assertEqual((q1["correct"], q1["pct"]), (2, 66.7))
        self.assertEqual((q2["correct"], q2["pct"]), (1, 33.3))
        self.assertEqual(q2["difficulty"], "Hard")
        self.assertEqual(data["topics"][0]["topic"], "B")  # weakest first
        self.assertEqual([t["topic"] for t in data["weak_topics"]], ["B"])

    def test_unsubmitted_attempts_are_ignored(self):
        user = User.objects.create_user("x", password="pw12345!", role="student")
        Attempt.objects.create(exam=self.exam, student=user, deadline=timezone.now() + timedelta(minutes=30))
        self.assertEqual(exam_analytics(self.exam)["n"], 0)

    def test_csv_export(self):
        self.make_attempt("a", ["Q1?", "Q2?"])
        self.client.login(username="teach", password="pw12345!")
        res = self.client.get(reverse("exam_results_csv", args=[self.exam.pk]))
        self.assertEqual(res["Content-Type"], "text/csv")
        body = res.content.decode()
        self.assertIn("Rank,Username", body)
        self.assertIn("a,", body)

    def test_csv_formula_injection_is_neutralised(self):
        self.assertEqual(csv_safe("=1+1"), "'=1+1")
        self.assertEqual(csv_safe("@SUM(A1)"), "'@SUM(A1)")
        self.assertEqual(csv_safe("normal"), "normal")


class AccountTests(TestCase):
    def test_register_creates_user_with_chosen_role_and_logs_in(self):
        data = {
            "username": "newbie", "first_name": "New", "last_name": "User", "email": "n@example.com",
            "role": "teacher", "password1": "Str0ng-pass-99", "password2": "Str0ng-pass-99",
        }
        res = self.client.post(reverse("register"), data)
        self.assertRedirects(res, reverse("dashboard"), fetch_redirect_response=False)
        user = User.objects.get(username="newbie")
        self.assertTrue(user.is_teacher)
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_logout_requires_post(self):
        User.objects.create_user("u", password="pw12345!")
        self.client.login(username="u", password="pw12345!")
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.client.post(reverse("logout"))
        self.assertNotIn("_auth_user_id", self.client.session)


class OverdueAttemptGradingTests(TestCase):
    def test_teacher_results_grade_attempts_left_unsubmitted_after_time_ran_out(self):
        teacher = User.objects.create_user("teach_overdue", password="pw12345!", role="teacher")
        student = User.objects.create_user("stud_overdue", password="pw12345!", role="student")
        exam = make_exam(teacher)
        q1 = exam.questions.get(text="Q1?")
        correct = q1.choices.get(is_correct=True)
        attempt = Attempt.objects.create(
            exam=exam, student=student, deadline=timezone.now() - timedelta(minutes=5)
        )
        Answer.objects.create(attempt=attempt, question=q1, choice=correct)

        self.client.login(username="teach_overdue", password="pw12345!")
        self.client.get(reverse("exam_results", args=[exam.pk]))

        attempt.refresh_from_db()
        self.assertTrue(attempt.is_submitted)
        self.assertEqual(attempt.score, 2)


class ClassEnrolmentTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user("t_cls", password="pw12345!", role="teacher")
        self.in_class = User.objects.create_user("s_in", password="pw12345!", role="student")
        self.outsider = User.objects.create_user("s_out", password="pw12345!", role="student")
        self.classroom = ClassRoom.objects.create(teacher=self.teacher, name="CSE 101")
        self.class_exam = make_exam(self.teacher)
        self.class_exam.classroom = self.classroom
        self.class_exam.save()
        self.open_exam = make_exam(self.teacher)  # no class: visible to everyone

    def test_join_with_code_shows_class_exam(self):
        self.client.login(username="s_in", password="pw12345!")
        self.client.post(reverse("class_join"), {"code": self.classroom.code.lower()})
        self.assertTrue(Enrollment.objects.filter(classroom=self.classroom, student=self.in_class).exists())
        resp = self.client.get(reverse("dashboard"))
        self.assertContains(resp, self.class_exam.title)

    def test_student_outside_class_cannot_see_or_start_class_exam(self):
        self.client.login(username="s_out", password="pw12345!")
        self.assertEqual(self.client.get(reverse("exam_start", args=[self.class_exam.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("exam_start", args=[self.open_exam.pk])).status_code, 200)

    def test_bad_code_is_rejected(self):
        self.client.login(username="s_in", password="pw12345!")
        self.client.post(reverse("class_join"), {"code": "NOPE00"})
        self.assertFalse(Enrollment.objects.filter(student=self.in_class).exists())


class TabSwitchTests(TestCase):
    def test_tab_hidden_events_are_counted_and_shown_to_teacher(self):
        teacher = User.objects.create_user("t_tab", password="pw12345!", role="teacher")
        student = User.objects.create_user("s_tab", password="pw12345!", role="student")
        exam = make_exam(teacher)
        attempt = Attempt.objects.create(exam=exam, student=student, deadline=timezone.now() + timedelta(minutes=20))
        self.client.login(username="s_tab", password="pw12345!")
        url = reverse("attempt_event", args=[attempt.pk])
        self.client.post(url, {"type": "tab_hidden"})
        self.client.post(url, {"type": "tab_hidden"})
        attempt.refresh_from_db()
        self.assertEqual(attempt.tab_switches, 2)
        self.assertFalse(attempt.is_submitted)  # events never change the grade or status

    def test_event_after_deadline_is_refused(self):
        teacher = User.objects.create_user("t_tab2", password="pw12345!", role="teacher")
        student = User.objects.create_user("s_tab2", password="pw12345!", role="student")
        exam = make_exam(teacher)
        attempt = Attempt.objects.create(exam=exam, student=student, deadline=timezone.now() - timedelta(minutes=1))
        self.client.login(username="s_tab2", password="pw12345!")
        resp = self.client.post(reverse("attempt_event", args=[attempt.pk]), {"type": "tab_hidden"})
        self.assertEqual(resp.status_code, 403)
        attempt.refresh_from_db()
        self.assertEqual(attempt.tab_switches, 0)
