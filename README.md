# Online Exam System
**Live demo:** [https://online-exam-system-rr6z.onrender.com](https://online-exam-system-rr6z.onrender.com)
A web application for conducting timed multiple-choice exams online. Teachers create exams and manage classes, students take exams in the browser, and results are graded automatically with class-level analytics.

## Features

### Teacher
- Create classes and share a 6-character join code
- Create, edit, and delete exams, assigned to a specific class or to all students
- Add, edit, and delete multiple-choice questions with topics and marks
- Publish or unpublish exams
- View results with tab-switch counts and download them as CSV
- Open an analytics page for each exam

### Student
- Join a class using its code
- View open, upcoming, completed, and missed exams
- Take exams with a live countdown and automatic answer saving
- Submit manually or automatically at time-up
- Review scores and answers after submission

### Admin
- Manage all data through the Django admin panel at `/admin/`

### Analytics (per exam)
- Submissions, average, median, highest, and lowest score, pass rate, and average time taken
- Score distribution chart
- Performance by topic, with topics that need review
- Per-question difficulty (Easy, Medium, Hard)
- Top performers

## Tech Stack

- **Backend:** Python 3, Django 5
- **Database:** SQLite for local development, PostgreSQL for deployment
- **Frontend:** Bootstrap 5, Chart.js
- **Deployment:** Gunicorn, WhiteNoise, Render, Neon (PostgreSQL)

## Getting Started

### Prerequisites

- Python 3.10 or newer
- pip

### Installation

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

### Database setup

```bash
python manage.py migrate
python manage.py seed_demo          # optional: demo data
python manage.py createsuperuser    # optional: admin account
```

### Run the development server

```bash
python manage.py runserver
```

Open http://127.0.0.1:8000 in your browser.

### Demo accounts

After running `seed_demo`, use the following credentials (password: `demo12345`):

| Role    | Username                   |
|---------|----------------------------|
| Teacher | `teacher1`                 |
| Student | `student01` to `student14` |

### Using PostgreSQL locally

By default the app uses SQLite. To use PostgreSQL, set the `DATABASE_URL` environment variable before running any command:

```
DATABASE_URL=postgresql://USER:PASSWORD@localhost:5432/examdb
```


### Running tests

```bash
python manage.py test
```

## How It Works

1. A teacher creates an exam, adds questions, and publishes it.
2. A student sees the exam on their dashboard and presses **Start**. The server records the attempt and a deadline, calculated as the earlier of *start time + duration* and *exam end time*.
3. The exam page saves each answer to the server as the student selects it.
4. The attempt is submitted when the timer reaches zero or the student presses **Submit**. The server grades it and shows the result.

### Timer integrity

The deadline is stored on the server when the student starts the exam. The countdown in the browser is only a display. Every save and submit is checked against the server clock, so changing the device clock or editing the page does not extend the time. Answers received more than 15 seconds after the deadline are rejected, which allows for slow networks. If a student never returns after the deadline, the attempt is graded automatically the next time it is opened or viewed by the teacher.

### Classes

A teacher creates a class and shares its join code. Students enter the code on their dashboard. An exam assigned to a class is visible only to students who have joined that class. Exams with no class are visible to all students.

### Tab switch tracking

When the exam tab is hidden, the browser reports the event to the server, which records it on the attempt. The student sees a warning, and the teacher sees the count on the results page and in the CSV export. Tab switches do not affect the score.

## Security and Data Integrity

- One attempt per student per exam, enforced by a database constraint
- Questions cannot be changed after any student has started the exam
- Teachers can only access their own exams and classes
- Correct answers are never sent to the browser during an exam; they appear only on the result page after submission
- Questions and options are shuffled per student, with a stable order on page refresh
- CSV exports are sanitized against spreadsheet formula injection

## Deployment

The application can be deployed for free using Render (hosting) and Neon (PostgreSQL).

1. Push the repository to GitHub.
2. Create a PostgreSQL database on [Neon](https://neon.tech) and copy the connection string.
3. On [Render](https://render.com), create a new Blueprint or Web Service from the repository.
4. Set the following environment variables:
   - `DEBUG` = `False`
   - `SECRET_KEY` = a long random string
   - `DATABASE_URL` = the Neon connection string
   - `ALLOWED_HOSTS` = your Render domain
5. Build command: `./build.sh`. Start command: `gunicorn examsys.wsgi:application`.
6. After the first deploy, open the Render Shell and run `python manage.py createsuperuser`.

Free hosting plans change over time, so check the current limits. A free Render service sleeps when idle, so the first request after a period of inactivity may take about a minute.

## Project Structure

```
examsys/                 Project settings, root URL configuration, WSGI entry point
core/
  models.py              User, ClassRoom, Enrollment, Exam, Question, Choice, Attempt, Answer
  views.py               Teacher and student views, auto-save, submission, results
  forms.py               Registration, login, exam, and question forms
  utils.py               Analytics calculations and CSV helpers
  urls.py                Application routes
  tests.py               Automated test suite
  templates/             Base layout and page templates
  management/commands/   seed_demo command
build.sh, render.yaml, Procfile, requirements.txt    Deployment files
```
## Known Limitations

- Only single-answer multiple-choice questions are supported. Multi-select and written-answer questions are planned.
- Tab switch tracking depends on JavaScript in the browser. It is a signal for the teacher to review, not proof of misconduct, and it cannot prevent outside help.
- Teacher accounts can be created through the sign-up page. In a production setting, teacher accounts should be approved by an administrator.
- Email notifications and password reset by email are not implemented.

## License

MIT © Md. Asibul Islam, 2026
