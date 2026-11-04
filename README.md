# AI Personalized Learning Coach

A Streamlit app that turns a learner's goal, level and available time into a day-by-day study plan,
quizzes them per topic, scores answers in Python, flags weak topics and recommends next steps.
Everything is stored in SQLite, so progress survives restarts.

## Setup
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # then put your GEMINI_API_KEY in .env
streamlit run app.py
```
Run tests (no API key needed, the LLM is mocked): `python -m pytest`

## Project structure
| File | Responsibility |
|---|---|
| `app.py` | Streamlit UI: Home, Learner Setup, Study Plan, Practice Quiz, Progress Dashboard |
| `ai_service.py` | Only place that calls the LLM; JSON parsing; retry-with-feedback on invalid output |
| `learning_plan.py` | Input validation, plan prompt, plan validation |
| `quiz_manager.py` | Quiz prompt/validation, **Python scoring**, weak-topic logic, recommendations |
| `database.py` | SQLite schema and queries |
| `tests/test_core.py` | Tests mapped to the brief's test table |
| `sample_data/` | Example of the plan JSON shape (not used at runtime) |

## Database schema
`learner_profiles` → `study_plans` (1 active at a time) → `topics` (status: pending / in_progress /
completed / needs_revision) → `quiz_attempts` (one row per attempt: score, total, percentage,
questions and chosen answers as JSON, timestamp).

## Design notes (for the viva)
- **LLM integration:** Gemini via `google-genai`, `response_mime_type="application/json"`, key from `.env`.
- **Prompt design:** each prompt states the learner's level/time, forces an exact JSON schema, fixes the
  number of days/questions, and tells the model not to compute scores.
- **Validation:** `validate_plan` / `validate_quiz` check structure, counts, 4 distinct options and
  `correct_index` in 0-3. On failure the error is fed back to the model and it retries (max 3), then a clear
  message is shown. Plan minutes are capped at the learner's daily time.
- **Scoring:** `quiz_manager.score_quiz` compares chosen indexes with `correct_index`. The LLM never scores.
- **Adaptation rules:** <60% → `needs_revision` and flagged as weak; 60-79% → `in_progress`;
  ≥80% → `completed` with "move on / try harder practice". The strong message says one quiz is not proof of mastery.
  Weak = the *latest* attempt for a topic is below 60%, so a good retake clears the flag.
- **Error handling:** missing inputs, API/network failure (retry button), invalid model output, DB errors.

## Limitations
- Quiz quality and correctness of LLM-written answer keys are not independently verified; an answer key could be wrong.
- Thresholds (60/80%) are simple heuristics; five questions is a small sample.
- Single-learner, local SQLite (no login). Plans are regenerated, not edited in place.
- Requires internet access and a valid API key.
