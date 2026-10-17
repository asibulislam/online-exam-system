# Online Exam System with Analytics

A web app where teachers create timed multiple-choice exams, students take them in the browser, and the system grades instantly and shows analytics on how the class performed.

Built for **CSE-326 Software Engineering Lab**, First Capital University of Bangladesh.

**Stack:** Python 3 · Django 5 · PostgreSQL (SQLite for local development) · Bootstrap 5 · Chart.js

## Features

| Role | What they can do |
|---|---|
| **Teacher** | Create classes and share a 6-character join code · create / edit / delete exams (for one class or everyone) · add, edit, delete MCQ questions with topic and marks · publish or unpublish · see results table with tab-switch counts · download results as CSV · open the analytics page |
| **Student** | Join a class with its code · see open, upcoming, completed and missed exams · read the rules · take the exam with a live countdown · answers auto-save · automatic submit at time-up · instant score with full answer review |
| **Admin** | Django admin at `/admin/` for managing every table |

**Analytics page (per exam):** submissions, average, median, highest, lowest, pass rate, average time taken · score distribution chart · performance by topic with "topics to revisit" · per-question difficulty (Easy / Medium / Hard) · top performers.

## Run it on your computer

```bash
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Linux / macOS
pip install -r requirements.txt

python manage.py migrate
python manage.py seed_demo      # optional: demo teacher, 14 students, 2 exams with results
python manage.py createsuperuser   # optional: for /admin/
python manage.py runserver
```

Open http://127.0.0.1:8000

Demo logins (after `seed_demo`), password `demo12345`:
- Teacher: `teacher1`
- Students: `student01` ... `student14`

Without `DATABASE_URL` set, the app uses a local SQLite file. To use PostgreSQL locally, set
`DATABASE_URL=postgresql://USER:PASSWORD@localhost:5432/examdb` before running.

Run the tests: `python manage.py test` (40 tests).

If you updated from an older version, also run `python manage.py migrate` (adds classes and tab-switch tracking).

## Deploy (free) with Render + Neon

1. Push this folder to a GitHub repository.
2. Create a free PostgreSQL database on [Neon](https://neon.tech) and copy its connection string.
3. On [Render](https://render.com): **New > Blueprint** (or **Web Service**), choose your repository.
   - Build command: `./build.sh`
   - Start command: `gunicorn examsys.wsgi:application`
4. Add environment variables: `DEBUG=False`, `SECRET_KEY=<long random string>`, `DATABASE_URL=<Neon string>`.
5. After the first deploy, open the Render **Shell** (or run locally with the same `DATABASE_URL`) and run
   `python manage.py createsuperuser`. For a demo site you may also run
   `python manage.py seed_demo --password <something-private>`.

Free plans change often, so check the current limits on both sites. A free Render service sleeps when idle, so the first page load after a break can take about a minute. Open the site a few minutes before a demo.

## How it works

```
Teacher creates exam ──► adds questions ──► publishes
                                               │
Student sees exam on dashboard ◄───────────────┘
        │  press Start  → Attempt row created, deadline = min(now + duration, exam end)
        ▼
Exam page  ── every click → POST /attempt/<id>/save/  (server checks deadline, stores answer)
        │  timer reaches 0 or student presses Submit
        ▼
POST /attempt/<id>/submit/ → server grades (sum of marks of correct choices) → result page
```

**Why the timer is trustworthy:** the deadline is stored in the database when the student presses Start. The browser countdown is only a display. Every save and submit is checked against the server's clock, so changing the computer clock or editing the page gives no extra time. Answers sent more than 15 seconds after the deadline are ignored (the grace period covers slow networks). If a student leaves and never comes back, their attempt is graded automatically the next time anyone opens it.

**Classes:** a teacher creates a class and shares its code. Students enter the code on their dashboard. An exam can be set to one class, so only that class's students see it.

**Tab switches:** when the exam tab is hidden, the browser reports it to the server, which counts it on the attempt. The student sees a warning. The teacher sees the count on the results page and in the CSV. It never changes the score.

**Other rules built in**
- One attempt per student per exam (database unique constraint).
- Questions lock once any student has started, so grades cannot change afterwards.
- A teacher can only see and edit their own exams.
- The exam page never sends the correct answers to the browser. They appear only on the result page, after submission.
- Questions and options are shuffled per student (same order after a refresh).
- CSV export neutralises spreadsheet formula injection.

## Project structure

```
examsys/            project settings, root urls, wsgi
core/
  models.py         User, ClassRoom, Enrollment, Exam, Question, Choice, Attempt, Answer
  views.py          teacher views, student views, auto-save, submit, result
  forms.py          register, login, exam and question forms
  utils.py          analytics calculations, CSV safety helper
  urls.py           all routes
  tests.py          40 automated tests
  templates/        base layout + one template per page
  management/commands/seed_demo.py   demo data
build.sh · render.yaml · Procfile · requirements.txt     deployment files
```

## Database (ER summary)

- **User** (role: teacher / student)
- **Exam** — belongs to a teacher (User); has title, subject, duration, start/end time, pass %, published flag
- **Question** — belongs to an Exam; has text, topic, marks
- **Choice** — belongs to a Question; `is_correct` flag
- **Attempt** — one Student × one Exam; deadline, submitted time, score, total
- **Answer** — belongs to an Attempt; points to the Question and the Choice picked

## Known limitations (future work)

- Multiple-choice questions with a single correct answer only (no written or multi-select questions).
- Exams without a class are visible to every student. Exams with a class are visible only to students who joined it.
- Tab switching is recorded, but a determined student can still get outside help (for example on a second device). The count is a signal for the teacher, not proof.
- Teacher accounts can be created through the sign-up page. In a real deployment an admin should approve teachers.
- Tab switches are only recorded in the browser, so a student who turns off JavaScript or uses devtools can avoid being counted. Live proctoring is out of scope.
- No email notifications or password reset by email.
