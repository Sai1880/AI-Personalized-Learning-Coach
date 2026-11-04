"""Streamlit UI for the AI Personalized Learning Coach."""
import pandas as pd
import streamlit as st

import database as db
import learning_plan as lp
import quiz_manager as qm
from ai_service import AIServiceError, InvalidResponseError

st.set_page_config(page_title="AI Personalized Learning Coach", page_icon="🎓", layout="wide")

STATUS_ICON = {"pending": "⚪ Pending", "in_progress": "🟡 In progress",
               "completed": "🟢 Completed", "needs_revision": "🔴 Needs revision"}

try:
    db.init_db()
except db.DatabaseError as e:
    st.error(str(e))
    st.stop()


def load_state():
    """Return (plan, topics, attempts) for the active plan; handles DB errors."""
    try:
        plan = db.get_active_plan()
        if not plan:
            return None, [], []
        return plan, db.get_topics(plan["id"]), db.get_attempts(plan["id"])
    except db.DatabaseError as e:
        st.error(str(e))
        st.stop()


# ---------------------------------------------------------------- pages
def page_home():
    st.title("🎓 AI Personalized Learning Coach")
    st.write("Tell the coach your goal, current level, and available time. It builds a day-by-day "
             "study plan, quizzes you on each topic, scores your answers, and tells you what to "
             "revise next. Your progress is saved, so you can pick up where you left off.")
    plan, topics, attempts = load_state()
    if plan:
        done = sum(t["status"] == "completed" for t in topics)
        st.info(f"Active plan: **{plan['title']}**: {done}/{len(topics)} topics completed. "
                "Open **Progress Dashboard** to continue.")
    else:
        st.info("No plan yet. Start on the **Learner Setup** page.")


def page_setup():
    st.header("Learner Setup")
    plan, _, _ = load_state()
    if plan:
        st.caption("You already have a plan. Submitting this form creates a new one "
                   "(the old plan and its history are kept).")
    with st.form("setup"):
        subject = st.text_input("Subject", value=plan["subject"] if plan else "", placeholder="e.g. Python")
        goal = st.text_area("Learning goal", value=plan["goal"] if plan else "",
                            placeholder="e.g. Learn Python fundamentals")
        level = st.selectbox("Current level", lp.LEVELS,
                             index=lp.LEVELS.index(plan["level"]) if plan else 0)
        c1, c2 = st.columns(2)
        days = c1.number_input("Target duration (days)", 1, 30, plan["duration_days"] if plan else 7)
        mins = c2.number_input("Daily study time (minutes)", 10, 480, plan["daily_minutes"] if plan else 45, step=5)
        submitted = st.form_submit_button("Generate study plan")

    if not submitted:
        return
    profile = {"subject": subject.strip(), "goal": goal.strip(), "level": level,
               "duration_days": int(days), "daily_minutes": int(mins)}
    errors = lp.validate_profile(profile)
    if errors:
        for e in errors:
            st.error(e)
        return
    try:
        with st.spinner("Creating your personalised plan..."):
            new_plan = lp.generate_plan(profile)
            db.save_plan(profile, new_plan)
        st.success("Plan created! Open the **Study Plan** page.")
    except (AIServiceError, InvalidResponseError) as e:
        st.error(str(e))
        st.caption("Press the button again to retry.")
    except db.DatabaseError as e:
        st.error(str(e))


def page_plan():
    st.header("Study Plan")
    plan, topics, _ = load_state()
    if not plan:
        st.warning("No plan yet. Create one on the Learner Setup page.")
        return
    st.subheader(plan["title"])
    st.write(plan["summary"])
    st.caption(f"{plan['subject']} • {plan['level']} • {plan['duration_days']} days • "
               f"{plan['daily_minutes']} min/day")
    for t in topics:
        with st.expander(f"Day {t['day']}: {t['title']}  ({t['estimated_minutes']} min) "
                         f"- {STATUS_ICON[t['status']]}"):
            st.markdown("**Objectives**\n" + "\n".join(f"- {o}" for o in t["objectives"]))
            st.markdown("**Practice activities**\n" + "\n".join(f"- {a}" for a in t["activities"]))
    st.caption("To change your goal or schedule, submit the Learner Setup form again to regenerate the plan.")


def page_quiz():
    st.header("Practice Quiz")
    plan, topics, _ = load_state()
    if not plan:
        st.warning("Create a study plan first.")
        return
    labels = {f"Day {t['day']}: {t['title']}": t for t in topics}
    choice = st.selectbox("Choose a topic", list(labels))
    topic = labels[choice]

    # Reset quiz state if the topic changes
    if st.session_state.get("quiz_topic_id") != topic["id"]:
        for k in ("quiz_questions", "quiz_result", "quiz_nonce"):
            st.session_state.pop(k, None)
        st.session_state["quiz_topic_id"] = topic["id"]

    if st.button("Generate new quiz"):
        try:
            with st.spinner("Writing quiz questions..."):
                st.session_state["quiz_questions"] = qm.generate_quiz(topic, plan["level"], plan["subject"])
            st.session_state.pop("quiz_result", None)
            st.session_state["quiz_nonce"] = st.session_state.get("quiz_nonce", 0) + 1
        except (AIServiceError, InvalidResponseError) as e:
            st.error(str(e))
            st.caption("Press 'Generate new quiz' to retry.")

    questions = st.session_state.get("quiz_questions")
    if not questions:
        st.info("Press **Generate new quiz** to begin.")
        return

    result = st.session_state.get("quiz_result")
    if result is None:
        with st.form(f"quiz_form_{st.session_state.get('quiz_nonce', 0)}"):
            picks = []
            for i, q in enumerate(questions):
                picks.append(st.radio(f"**Q{i+1}. {q['question']}**", range(4), index=None,
                                      format_func=lambda j, q=q: q["options"][j], key=f"q{i}_{st.session_state.get('quiz_nonce',0)}"))
            submit = st.form_submit_button("Submit answers")
        if submit:
            if any(p is None for p in picks):
                st.error("Please answer every question before submitting.")
                return
            scored = qm.score_quiz(questions, picks)
            try:
                db.save_attempt(topic["id"], scored["score"], scored["total"], questions, picks)
                db.update_topic_status(topic["id"], qm.status_for(scored["percentage"]))
                n = len(db.get_attempts(plan["id"], topic["id"]))
            except db.DatabaseError as e:
                st.error(f"Your score was calculated but could not be saved: {e}")
                n = 1
            st.session_state["quiz_result"] = {"scored": scored, "attempt_no": n}
            st.rerun()
    else:
        scored, n = result["scored"], result["attempt_no"]
        st.subheader(f"Score: {scored['score']}/{scored['total']} ({scored['percentage']}%)")
        rec = qm.recommend(topic["title"], scored["percentage"], n)
        {"strong": st.success, "ok": st.info, "weak": st.warning}[rec["level"]](rec["message"])
        for i, (q, r) in enumerate(zip(questions, scored["results"]), start=1):
            icon = "✅" if r["correct"] else "❌"
            st.markdown(f"{icon} **Q{i}. {q['question']}**")
            if r["chosen"] is not None:
                st.write(f"Your answer: {q['options'][r['chosen']]}")
            if not r["correct"]:
                st.write(f"Correct answer: {q['options'][r['correct_index']]}")
            st.caption(q["explanation"])
        if st.button("Try another quiz on this topic"):
            for k in ("quiz_questions", "quiz_result"):
                st.session_state.pop(k, None)
            st.rerun()


def page_dashboard():
    st.header("Progress Dashboard")
    plan, topics, attempts = load_state()
    if not plan:
        st.warning("No plan yet.")
        return
    done = sum(t["status"] == "completed" for t in topics)
    c1, c2, c3 = st.columns(3)
    c1.metric("Completed topics", f"{done}/{len(topics)}")
    c2.metric("Pending topics", sum(t["status"] == "pending" for t in topics))
    c3.metric("Quiz attempts", len(attempts))
    st.progress(done / len(topics) if topics else 0)

    st.subheader("Next step")
    st.write(qm.next_action(topics, attempts))

    weak = qm.weak_topics(topics, attempts)
    if weak:
        st.subheader("Topics flagged for revision")
        for t in weak:
            st.warning(f"Day {t['day']}: {t['title']}")

    st.subheader("Topics")
    st.dataframe(pd.DataFrame([{"Day": t["day"], "Topic": t["title"], "Minutes": t["estimated_minutes"],
                                "Status": STATUS_ICON[t["status"]]} for t in topics]),
                 hide_index=True, use_container_width=True)

    st.subheader("Recent quiz scores")
    if attempts:
        df = pd.DataFrame(attempts)
        st.line_chart(df.sort_values("id").set_index("id")["percentage"])
        show = df.head(10)[["taken_at", "topic", "score", "total", "percentage"]]
        st.dataframe(show, hide_index=True, use_container_width=True)
    else:
        st.info("No quizzes taken yet.")


PAGES = {"Home": page_home, "Learner Setup": page_setup, "Study Plan": page_plan,
         "Practice Quiz": page_quiz, "Progress Dashboard": page_dashboard}

st.sidebar.title("Learning Coach")
PAGES[st.sidebar.radio("Navigate", list(PAGES))]()
