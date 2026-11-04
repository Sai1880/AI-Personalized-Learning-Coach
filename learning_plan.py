"""Learner input validation, study-plan prompt, and plan validation."""
from ai_service import generate_structured

LEVELS = ["Beginner", "Intermediate", "Advanced"]


def validate_profile(profile: dict) -> list:
    """Return a list of error messages (empty list = valid)."""
    errors = []
    if not profile.get("subject", "").strip():
        errors.append("Subject is required.")
    if not profile.get("goal", "").strip():
        errors.append("Learning goal is required.")
    if profile.get("level") not in LEVELS:
        errors.append("Please choose a current level.")
    if not (1 <= int(profile.get("duration_days") or 0) <= 30):
        errors.append("Duration must be between 1 and 30 days.")
    if not (10 <= int(profile.get("daily_minutes") or 0) <= 480):
        errors.append("Daily study time must be between 10 and 480 minutes.")
    return errors


def build_plan_prompt(p: dict) -> str:
    return f"""You are an expert tutor creating a personalised study plan.

Learner:
- Subject: {p['subject']}
- Goal: {p['goal']}
- Current level: {p['level']}
- Target duration: {p['duration_days']} days
- Daily study time: {p['daily_minutes']} minutes

Rules:
- Produce EXACTLY {p['duration_days']} day entries, numbered 1..{p['duration_days']}.
- Each day's estimated_minutes must not exceed {p['daily_minutes']}.
- Match difficulty and pacing to a {p['level']} learner. Include revision/quiz time near the end.
- Each day has one clear topic, 2-4 learning objectives, and 2-3 practice activities.
- Respond with JSON ONLY, in exactly this shape:
{{"title": "string", "summary": "string",
  "days": [{{"day": 1, "topic": "string", "objectives": ["string"],
             "estimated_minutes": 40, "activities": ["string"]}}]}}"""


def validate_plan(data, profile: dict) -> dict:
    """Validate/normalise the model output. Raises ValueError with a helpful message."""
    if not isinstance(data, dict):
        raise ValueError("top level must be a JSON object")
    days = data.get("days")
    if not isinstance(days, list) or not days:
        raise ValueError("'days' must be a non-empty list")
    if len(days) != profile["duration_days"]:
        raise ValueError(f"expected {profile['duration_days']} days but got {len(days)}")
    clean = []
    for i, d in enumerate(days, start=1):
        if not isinstance(d, dict):
            raise ValueError(f"day {i} must be an object")
        topic = str(d.get("topic", "")).strip()
        objectives = d.get("objectives")
        activities = d.get("activities")
        minutes = d.get("estimated_minutes")
        if not topic:
            raise ValueError(f"day {i} is missing 'topic'")
        if not isinstance(objectives, list) or not objectives:
            raise ValueError(f"day {i} needs a non-empty 'objectives' list")
        if not isinstance(activities, list) or not activities:
            raise ValueError(f"day {i} needs a non-empty 'activities' list")
        if not isinstance(minutes, (int, float)) or minutes <= 0:
            raise ValueError(f"day {i} needs a positive numeric 'estimated_minutes'")
        clean.append({
            "day": i, "topic": topic,
            "objectives": [str(o) for o in objectives],
            "activities": [str(a) for a in activities],
            "estimated_minutes": min(int(minutes), profile["daily_minutes"]),
        })
    return {"title": str(data.get("title") or f"{profile['subject']} plan").strip(),
            "summary": str(data.get("summary", "")).strip(), "days": clean}


def generate_plan(profile: dict) -> dict:
    return generate_structured(build_plan_prompt(profile), lambda d: validate_plan(d, profile))
