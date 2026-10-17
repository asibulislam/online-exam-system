from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.db.models import Sum
from django.utils import timezone


class User(AbstractUser):
    """One user table for everybody; `role` decides what they can do."""

    class Role(models.TextChoices):
        TEACHER = "teacher", "Teacher"
        STUDENT = "student", "Student"

    role = models.CharField(max_length=10, choices=Role.choices, default=Role.STUDENT)

    @property
    def is_teacher(self):
        return self.role == self.Role.TEACHER

    @property
    def is_student(self):
        return self.role == self.Role.STUDENT

    @property
    def display_name(self):
        return self.get_full_name() or self.username


def _new_class_code():
    import secrets
    import string

    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(6))


class ClassRoom(models.Model):
    """A class that a teacher creates. Students join with the code."""

    teacher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="classrooms")
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=8, unique=True, default=_new_class_code, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.code})"


class Enrollment(models.Model):
    classroom = models.ForeignKey(ClassRoom, on_delete=models.CASCADE, related_name="enrollments")
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="enrollments")
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["classroom", "student"], name="one_join_per_class")]

    def __str__(self):
        return f"{self.student} in {self.classroom}"


class Exam(models.Model):
    teacher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="exams")
    classroom = models.ForeignKey(
        ClassRoom,
        on_delete=models.CASCADE,
        related_name="exams",
        null=True,
        blank=True,
        help_text="Only students who joined this class can see the exam. Leave empty for every student.",
    )
    title = models.CharField(max_length=120)
    subject = models.CharField(max_length=80)
    description = models.TextField(blank=True)
    duration_minutes = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(300)],
        help_text="How long each student gets once they press Start.",
    )
    start_time = models.DateTimeField(help_text="Students can start from this time.")
    end_time = models.DateTimeField(help_text="Nobody can start after this time, and every attempt stops at this time.")
    pass_percent = models.PositiveIntegerField(
        default=40, validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    shuffle = models.BooleanField(default=True, verbose_name="Shuffle questions and options")
    is_published = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_time"]

    def __str__(self):
        return self.title

    def total_marks(self):
        return self.questions.aggregate(t=Sum("marks"))["t"] or 0

    def status(self, now=None):
        now = now or timezone.now()
        if now < self.start_time:
            return "upcoming"
        if now > self.end_time:
            return "closed"
        return "open"


class Question(models.Model):
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name="questions")
    text = models.TextField()
    topic = models.CharField(max_length=80, default="General")
    marks = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1), MaxValueValidator(100)])

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.text[:60]


class Choice(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="choices")
    text = models.CharField(max_length=300)
    is_correct = models.BooleanField(default=False)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.text


class Attempt(models.Model):
    """One student taking one exam. A student can attempt an exam only once."""

    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name="attempts")
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="attempts")
    started_at = models.DateTimeField(auto_now_add=True)
    deadline = models.DateTimeField()
    submitted_at = models.DateTimeField(null=True, blank=True)
    score = models.PositiveIntegerField(default=0)
    total = models.PositiveIntegerField(default=0)
    tab_switches = models.PositiveIntegerField(
        default=0, help_text="How many times the exam tab was hidden during the attempt."
    )

    class Meta:
        constraints = [models.UniqueConstraint(fields=["exam", "student"], name="one_attempt_per_student")]
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.student} - {self.exam}"

    @property
    def is_submitted(self):
        return self.submitted_at is not None

    @property
    def percent(self):
        return round(self.score * 100 / self.total, 1) if self.total else 0

    @property
    def passed(self):
        return self.percent >= self.exam.pass_percent

    @property
    def minutes_taken(self):
        if not self.submitted_at:
            return None
        return round((self.submitted_at - self.started_at).total_seconds() / 60, 1)

    def finalize(self, now=None):
        """Grade the attempt and lock it. Safe to call more than once."""
        now = now or timezone.now()
        with transaction.atomic():
            locked = Attempt.objects.select_for_update().get(pk=self.pk)
            if locked.submitted_at:
                self.refresh_from_db()
                return
            score = 0
            for ans in locked.answers.select_related("choice", "question"):
                if ans.choice and ans.choice.is_correct:
                    score += ans.question.marks
            locked.score = score
            locked.total = locked.exam.total_marks()
            locked.submitted_at = min(now, locked.deadline)
            locked.save()
        self.refresh_from_db()


class Answer(models.Model):
    attempt = models.ForeignKey(Attempt, on_delete=models.CASCADE, related_name="answers")
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="answers")
    choice = models.ForeignKey(Choice, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["attempt", "question"], name="one_answer_per_question")]
