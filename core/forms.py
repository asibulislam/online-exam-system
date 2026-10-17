from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from .models import ClassRoom, Choice, Exam, Question, User

DT_FORMAT = "%Y-%m-%dT%H:%M"


class BootstrapMixin:
    """Adds Bootstrap classes to every widget so templates stay simple."""

    def _style(self):
        for field in self.fields.values():
            w = field.widget
            if isinstance(w, forms.CheckboxInput):
                w.attrs["class"] = "form-check-input"
            elif isinstance(w, forms.RadioSelect):
                continue
            elif isinstance(w, forms.Select):
                w.attrs["class"] = "form-select"
            else:
                w.attrs["class"] = "form-control"


class LoginForm(BootstrapMixin, AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


class RegisterForm(BootstrapMixin, UserCreationForm):
    role = forms.ChoiceField(choices=User.Role.choices, initial=User.Role.STUDENT)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "first_name", "last_name", "email", "role")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = True
        self.fields["last_name"].required = True
        self._style()

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = self.cleaned_data["role"]
        if commit:
            user.save()
        return user


class ClassRoomForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = ClassRoom
        fields = ["name"]


class JoinClassForm(BootstrapMixin, forms.Form):
    code = forms.CharField(label="Class code", max_length=8)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["code"].widget.attrs["placeholder"] = "e.g. A7K2QX"
        self._style()

    def clean_code(self):
        code = self.cleaned_data["code"].strip().upper()
        classroom = ClassRoom.objects.filter(code=code).first()
        if classroom is None:
            raise forms.ValidationError("No class has this code. Check it with your teacher.")
        self.classroom = classroom
        return code


class ExamForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Exam
        fields = [
            "title",
            "subject",
            "classroom",
            "description",
            "duration_minutes",
            "start_time",
            "end_time",
            "pass_percent",
            "shuffle",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "start_time": forms.DateTimeInput(attrs={"type": "datetime-local"}, format=DT_FORMAT),
            "end_time": forms.DateTimeInput(attrs={"type": "datetime-local"}, format=DT_FORMAT),
        }

    def __init__(self, *args, teacher=None, **kwargs):
        super().__init__(*args, **kwargs)
        classes = ClassRoom.objects.filter(teacher=teacher) if teacher else ClassRoom.objects.none()
        self.fields["classroom"].queryset = classes
        self.fields["classroom"].required = False
        self.fields["classroom"].empty_label = "Every student (no class)"
        self.fields["classroom"].label = "Class"
        self.fields["start_time"].input_formats = [DT_FORMAT]
        self.fields["end_time"].input_formats = [DT_FORMAT]
        self._style()

    def clean(self):
        data = super().clean()
        start, end = data.get("start_time"), data.get("end_time")
        if start and end and end <= start:
            self.add_error("end_time", "End time must be after the start time.")
        return data


class QuestionForm(BootstrapMixin, forms.Form):
    """One question with up to four options and exactly one correct answer."""

    text = forms.CharField(label="Question", widget=forms.Textarea(attrs={"rows": 3}))
    topic = forms.CharField(max_length=80, initial="General", help_text="Used for the weak-topic analytics.")
    marks = forms.IntegerField(min_value=1, max_value=100, initial=1)
    choice1 = forms.CharField(label="Option 1", max_length=300)
    choice2 = forms.CharField(label="Option 2", max_length=300)
    choice3 = forms.CharField(label="Option 3 (optional)", max_length=300, required=False)
    choice4 = forms.CharField(label="Option 4 (optional)", max_length=300, required=False)
    correct = forms.ChoiceField(
        label="Correct option",
        choices=[("1", "Option 1"), ("2", "Option 2"), ("3", "Option 3"), ("4", "Option 4")],
    )

    def __init__(self, *args, question=None, **kwargs):
        self.question = question
        if question is not None and not args and "initial" not in kwargs:
            initial = {"text": question.text, "topic": question.topic, "marks": question.marks}
            for i, choice in enumerate(question.choices.all(), start=1):
                initial[f"choice{i}"] = choice.text
                if choice.is_correct:
                    initial["correct"] = str(i)
            kwargs["initial"] = initial
        super().__init__(*args, **kwargs)
        self._style()

    def clean(self):
        data = super().clean()
        correct = data.get("correct")
        if correct and not data.get(f"choice{correct}"):
            self.add_error("correct", "The correct option cannot be empty.")
        return data

    def save(self, exam):
        d = self.cleaned_data
        if self.question is None:
            question = Question.objects.create(exam=exam, text=d["text"], topic=d["topic"], marks=d["marks"])
        else:
            question = self.question
            question.text, question.topic, question.marks = d["text"], d["topic"], d["marks"]
            question.save()
            question.choices.all().delete()
        for i in range(1, 5):
            text = d.get(f"choice{i}")
            if text:
                Choice.objects.create(question=question, text=text, is_correct=(str(i) == d["correct"]))
        return question
