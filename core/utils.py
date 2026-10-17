import statistics

from django.db.models import Count, Q


def csv_safe(value):
    """Stop spreadsheet formula injection when a teacher opens the exported CSV in Excel."""
    value = str(value)
    if value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def difficulty_label(pct_correct):
    if pct_correct >= 70:
        return "Easy"
    if pct_correct >= 40:
        return "Medium"
    return "Hard"


def exam_analytics(exam):
    """Everything the analytics page shows, calculated from submitted attempts only."""
    attempts = list(exam.attempts.filter(submitted_at__isnull=False).select_related("student"))
    n = len(attempts)
    result = {
        "n": n,
        "avg": 0,
        "median": 0,
        "highest": 0,
        "lowest": 0,
        "pass_count": 0,
        "pass_rate": 0,
        "avg_minutes": 0,
        "distribution": [0] * 10,
        "questions": [],
        "topics": [],
        "weak_topics": [],
        "top": [],
    }
    if n == 0:
        return result

    percents = [a.percent for a in attempts]
    result["avg"] = round(sum(percents) / n, 1)
    result["median"] = round(statistics.median(percents), 1)
    result["highest"] = max(percents)
    result["lowest"] = min(percents)
    result["pass_count"] = sum(1 for a in attempts if a.passed)
    result["pass_rate"] = round(result["pass_count"] * 100 / n, 1)
    result["avg_minutes"] = round(sum(a.minutes_taken for a in attempts) / n, 1)

    bins = [0] * 10
    for p in percents:
        bins[min(int(p // 10), 9)] += 1
    result["distribution"] = bins

    ranked = sorted(attempts, key=lambda a: (-a.percent, a.minutes_taken))
    result["top"] = ranked[:5]

    # Per-question difficulty: how many of ALL submitted attempts got it right.
    # A skipped question counts as wrong, so we divide by n, not by "answered".
    done = Q(answers__attempt__submitted_at__isnull=False)
    questions = exam.questions.annotate(
        correct_count=Count("answers", filter=done & Q(answers__choice__is_correct=True)),
        answered_count=Count("answers", filter=done & Q(answers__choice__isnull=False)),
    )
    topic_totals = {}
    for q in questions:
        pct = round(q.correct_count * 100 / n, 1)
        result["questions"].append(
            {
                "id": q.id,
                "text": q.text,
                "topic": q.topic,
                "marks": q.marks,
                "correct": q.correct_count,
                "skipped": n - q.answered_count,
                "pct": pct,
                "difficulty": difficulty_label(pct),
            }
        )
        t = topic_totals.setdefault(q.topic, {"earned": 0, "possible": 0, "questions": 0})
        t["earned"] += q.correct_count * q.marks
        t["possible"] += n * q.marks
        t["questions"] += 1

    topics = [
        {
            "topic": name,
            "pct": round(t["earned"] * 100 / t["possible"], 1),
            "questions": t["questions"],
        }
        for name, t in topic_totals.items()
    ]
    topics.sort(key=lambda t: t["pct"])
    result["topics"] = topics
    result["weak_topics"] = [t for t in topics if t["pct"] < 50][:3]
    return result
