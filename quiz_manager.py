"""Quiz generation/validation, Python-side scoring, weak-topic detection, recommendations."""
from ai_service import generate_structured

WEAK_BELOW = 60     # percent: below this -> revise
STRONG_FROM = 80    # percent: at/above this -> move forward


def build_quiz_prompt(topic: dict, level: str, subject: str, n: int = 5) -> str:
    objectives = "; ".join(topic["objectives"])
    return f"""Create a {n}-question multiple-choice quiz for a {level} learner of {subject}.
Topic: {topic['title']}
Learning objectives: {objectives}

Rules:
- Exactly {n} questions, each with exactly 4 options and exactly ONE correct option.
- "correct_index" is the 0-based index (0-3) of the correct option.
- Vary the position of the correct answer. Keep difficulty appropriate for {level}.
- "explanation" briefly says why the answer is correct, in language suited to a {level}.
- Do NOT calculate any score. Respond with JSON ONLY:
{{"questions": [{{"question": "string", "options": ["A","B","C","D"],
                  "correct_index": 0, "explanation": "string"}}]}}"""


def validate_quiz(data, n: int = 5) -> list:
    if not isinstance(data, dict) or not isinstance(data.get("questions"), list):
        raise ValueError("expected an object with a 'questions' list")
    qs = data["questions"]
    if len(qs) != n:
        raise ValueError(f"expected {n} questions but got {len(qs)}")
    clean = []
    for i, q in enumerate(qs, start=1):
        if not isinstance(q, dict):
            raise ValueError(f"question {i} must be an object")
        text = str(q.get("question", "")).strip()
        options = q.get("options")
        idx = q.get("correct_index")
        if not text:
            raise ValueError(f"question {i} has no text")
        if not isinstance(options, list) or len(options) != 4 or len({str(o) for o in options}) != 4:
            raise ValueError(f"question {i} needs exactly 4 distinct options")
        if isinstance(idx, bool) or not isinstance(idx, int) or not 0 <= idx <= 3:
            raise ValueError(f"question {i} needs 'correct_index' between 0 and 3")
        clean.append({"question": text, "options": [str(o) for o in options],
                      "correct_index": idx, "explanation": str(q.get("explanation", "")).strip()})
    return clean


def generate_quiz(topic: dict, level: str, subject: str, n: int = 5) -> list:
    return generate_structured(build_quiz_prompt(topic, level, subject, n), lambda d: validate_quiz(d, n))


def score_quiz(questions: list, answers: list) -> dict:
    """Score from the answer key. answers[i] is the chosen option index (or None)."""
    results = []
    for q, a in zip(questions, answers):
        results.append({"correct": a == q["correct_index"], "chosen": a,
                        "correct_index": q["correct_index"], "explanation": q["explanation"]})
    score = sum(r["correct"] for r in results)
    total = len(questions)
    return {"score": score, "total": total,
            "percentage": round(100 * score / total, 1) if total else 0.0, "results": results}


def status_for(percentage: float) -> str:
    if percentage >= STRONG_FROM:
        return "completed"
    if percentage >= WEAK_BELOW:
        return "in_progress"
    return "needs_revision"


def recommend(topic_title: str, percentage: float, attempt_count: int) -> dict:
    """Rule-based next step. Deliberately avoids claiming mastery from one short quiz."""
    if percentage >= STRONG_FROM:
        msg = (f"Strong result on '{topic_title}' (attempt #{attempt_count}). "
               "Move on to the next topic, or try harder practice questions. "
               "One short quiz is not proof of mastery, so revisit it briefly later.")
        return {"level": "strong", "message": msg}
    if percentage >= WEAK_BELOW:
        return {"level": "ok", "message": f"Decent progress on '{topic_title}'. Review the questions you missed, "
                                          "then take another quiz to confirm."}
    return {"level": "weak", "message": f"'{topic_title}' needs revision. Re-read the objectives, "
                                        "review the explanations below, then retake a fresh quiz."}


def weak_topics(topics: list, attempts: list) -> list:
    """Topics whose most recent attempt is below the weak threshold."""
    latest = {}
    for a in attempts:  # attempts are newest-first
        latest.setdefault(a["topic_id"], a)
    return [t for t in topics if t["id"] in latest and latest[t["id"]]["percentage"] < WEAK_BELOW]


def next_action(topics: list, attempts: list) -> str:
    weak = weak_topics(topics, attempts)
    if weak:
        return f"Revise **{weak[0]['title']}** (Day {weak[0]['day']}) and retake its quiz."
    for t in topics:
        if t["status"] != "completed":
            return f"Continue with **{t['title']}** (Day {t['day']})."
    return "All topics completed. Take a final review quiz or create a new plan."
