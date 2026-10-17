"""Fill the database with demo data so the analytics pages have something to show.

    python manage.py seed_demo

Creates 1 teacher, 14 students, a CLOSED exam with simulated results (for the
analytics demo) and an OPEN exam you can take live. Safe to run twice.
All names are made up. Do NOT leave the demo passwords on a public website.
"""
import os
import random
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Answer, Attempt, Choice, Exam, Question, User

DS_QUESTIONS = [
    ("Which data structure uses the LIFO principle?", "Stacks & Queues", ["Stack", "Queue", "Array", "Heap"], 0, 1),
    ("Which data structure uses the FIFO principle?", "Stacks & Queues", ["Stack", "Queue", "Tree", "Graph"], 1, 1),
    ("What is the time complexity of accessing an array element by index?", "Arrays", ["O(n)", "O(log n)", "O(1)", "O(n^2)"], 2, 1),
    ("What is the worst-case time complexity of linear search?", "Arrays", ["O(1)", "O(n)", "O(log n)", "O(n log n)"], 1, 1),
    ("Binary search requires the array to be:", "Arrays", ["Sorted", "Unsorted", "Of even length", "Of unique values only"], 0, 2),
    ("In a singly linked list, each node stores:", "Linked Lists", ["Only data", "Data and a pointer to the next node", "Data and two pointers", "Only a pointer"], 1, 1),
    ("Inserting a node at the head of a singly linked list takes:", "Linked Lists", ["O(n)", "O(log n)", "O(1)", "O(n^2)"], 2, 2),
    ("Which traversal of a binary search tree gives sorted output?", "Trees", ["Preorder", "Inorder", "Postorder", "Level order"], 1, 2),
    ("The maximum number of nodes at level L of a binary tree (root at level 0) is:", "Trees", ["2L", "L^2", "2^L", "L+1"], 2, 2),
    ("Which sorting algorithm has O(n log n) worst-case time?", "Sorting", ["Bubble sort", "Insertion sort", "Merge sort", "Selection sort"], 2, 2),
    ("Which sorting algorithm repeatedly swaps adjacent elements that are out of order?", "Sorting", ["Merge sort", "Bubble sort", "Quick sort", "Heap sort"], 1, 1),
    ("Which structure is best for implementing a recursion call stack?", "Stacks & Queues", ["Queue", "Stack", "Tree", "Hash table"], 1, 1),
]

PY_QUESTIONS = [
    ("What is the output of type([])?", "Basics", ["<class 'list'>", "<class 'tuple'>", "<class 'dict'>", "<class 'set'>"], 0, 1),
    ("Which keyword defines a function in Python?", "Basics", ["func", "define", "def", "function"], 2, 1),
    ("Which of these is immutable?", "Data types", ["list", "dict", "set", "tuple"], 3, 1),
    ("What does len('exam') return?", "Basics", ["3", "4", "5", "Error"], 1, 1),
    ("Which method adds an item to the end of a list?", "Data types", ["add()", "push()", "append()", "insert_end()"], 2, 1),
    ("What does 7 // 2 evaluate to?", "Operators", ["3.5", "3", "4", "2"], 1, 1),
    ("Which statement is used to handle exceptions?", "Control flow", ["try / except", "catch / throw", "if / else", "check / error"], 0, 1),
    ("What is the result of 2 ** 3?", "Operators", ["6", "5", "8", "9"], 2, 1),
]


class Command(BaseCommand):
    help = "Create demo teacher, students, exams and simulated results."

    def add_arguments(self, parser):
        parser.add_argument("--password", default=os.environ.get("DEMO_PASSWORD", "demo12345"))

    def handle(self, *args, **opts):
        random.seed(42)
        pw = opts["password"]
        now = timezone.now()

        teacher, _ = User.objects.get_or_create(
            username="teacher1",
            defaults={"first_name": "Demo", "last_name": "Teacher", "email": "teacher1@example.com", "role": "teacher"},
        )
        teacher.set_password(pw)
        teacher.save()

        first_names = ["Rafi", "Nusrat", "Tanvir", "Mim", "Sakib", "Farhana", "Imran", "Jannat", "Rakib", "Sumaiya", "Arif", "Lamia", "Shuvo", "Tasnim"]
        students = []
        for i, fn in enumerate(first_names, start=1):
            u, _ = User.objects.get_or_create(
                username=f"student{i:02d}",
                defaults={"first_name": fn, "last_name": "Demo", "email": f"student{i:02d}@example.com", "role": "student"},
            )
            u.set_password(pw)
            u.save()
            students.append(u)

        # 1) closed exam with simulated attempts -> analytics demo
        past, created = Exam.objects.get_or_create(
            teacher=teacher,
            title="Data Structures Mid-term (Demo)",
            defaults={
                "subject": "Data Structures",
                "description": "Demo exam with simulated results so the analytics page has data.",
                "duration_minutes": 30,
                "start_time": now - timedelta(days=3, hours=2),
                "end_time": now - timedelta(days=3),
                "pass_percent": 40,
                "is_published": True,
            },
        )
        if created:
            self._add_questions(past, DS_QUESTIONS)
            self._simulate(past, students, now - timedelta(days=3, hours=2))

        # 2) open exam you can take right now
        live, created = Exam.objects.get_or_create(
            teacher=teacher,
            title="Python Basics Quiz (Live Demo)",
            defaults={
                "subject": "Programming",
                "description": "Short quiz, open for the next few days. Log in as a student to try it.",
                "duration_minutes": 10,
                "start_time": now - timedelta(hours=1),
                "end_time": now + timedelta(days=5),
                "pass_percent": 50,
                "is_published": True,
            },
        )
        if created:
            self._add_questions(live, PY_QUESTIONS)

        self.stdout.write(self.style.SUCCESS("Demo data ready."))
        self.stdout.write(f"Teacher login : teacher1 / {pw}")
        self.stdout.write(f"Student login : student01 ... student14 / {pw}")

    def _add_questions(self, exam, rows):
        for text, topic, options, correct, marks in rows:
            q = Question.objects.create(exam=exam, text=text, topic=topic, marks=marks)
            for i, opt in enumerate(options):
                Choice.objects.create(question=q, text=opt, is_correct=(i == correct))

    def _simulate(self, exam, students, start):
        """Fake attempts: each student has a 'skill', harder topics get fewer right answers."""
        topic_difficulty = {"Arrays": 0.0, "Stacks & Queues": 0.0, "Linked Lists": 0.1, "Sorting": 0.15, "Trees": 0.35}
        questions = list(exam.questions.prefetch_related("choices"))
        for student in students:
            skill = random.uniform(0.35, 0.95)
            started = start + timedelta(minutes=random.randint(0, 20))
            attempt = Attempt.objects.create(exam=exam, student=student, deadline=started + timedelta(minutes=30))
            Attempt.objects.filter(pk=attempt.pk).update(started_at=started)
            for q in questions:
                if random.random() < 0.05:
                    continue  # skipped
                p_right = max(0.05, skill - topic_difficulty.get(q.topic, 0.1))
                options = list(q.choices.all())
                right = next(c for c in options if c.is_correct)
                wrong = [c for c in options if not c.is_correct]
                picked = right if random.random() < p_right else random.choice(wrong)
                Answer.objects.create(attempt=attempt, question=q, choice=picked)
            attempt.finalize(started + timedelta(minutes=random.randint(12, 29)))
