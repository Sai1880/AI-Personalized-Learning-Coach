"""SQLite persistence layer: learner profiles, plans, topics, quiz attempts."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

DB_PATH = Path(os.getenv("LEARNING_COACH_DB", "learning_coach.db"))

STATUSES = ("pending", "in_progress", "completed", "needs_revision")


class DatabaseError(Exception):
    """Raised for any database problem, with a user-friendly message."""


@contextmanager
def get_conn():
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
        conn.commit()
    except sqlite3.Error as exc:
        if conn:
            conn.rollback()
        raise DatabaseError(f"Database error: {exc}") from exc
    finally:
        if conn:
            conn.close()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS learner_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT NOT NULL,
                goal TEXT NOT NULL,
                level TEXT NOT NULL,
                duration_days INTEGER NOT NULL,
                daily_minutes INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS study_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                learner_id INTEGER NOT NULL REFERENCES learner_profiles(id),
                title TEXT NOT NULL,
                summary TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS topics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_id INTEGER NOT NULL REFERENCES study_plans(id) ON DELETE CASCADE,
                day INTEGER NOT NULL,
                title TEXT NOT NULL,
                objectives TEXT NOT NULL,          -- JSON list
                estimated_minutes INTEGER NOT NULL,
                activities TEXT NOT NULL,          -- JSON list
                status TEXT NOT NULL DEFAULT 'pending',
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS quiz_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
                score INTEGER NOT NULL,
                total INTEGER NOT NULL,
                percentage REAL NOT NULL,
                questions_json TEXT NOT NULL,
                answers_json TEXT NOT NULL,
                taken_at TEXT NOT NULL
            );
            """
        )


def save_plan(profile: dict, plan: dict) -> int:
    """Store the profile + plan; older plans are deactivated (history is kept)."""
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO learner_profiles (subject, goal, level, duration_days, daily_minutes, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (profile["subject"], profile["goal"], profile["level"],
             profile["duration_days"], profile["daily_minutes"], _now()),
        )
        learner_id = cur.lastrowid
        conn.execute("UPDATE study_plans SET is_active = 0")
        cur = conn.execute(
            "INSERT INTO study_plans (learner_id, title, summary, is_active, created_at) VALUES (?,?,?,1,?)",
            (learner_id, plan["title"], plan.get("summary", ""), _now()),
        )
        plan_id = cur.lastrowid
        for d in plan["days"]:
            conn.execute(
                "INSERT INTO topics (plan_id, day, title, objectives, estimated_minutes, activities, status, updated_at)"
                " VALUES (?,?,?,?,?,?, 'pending', ?)",
                (plan_id, d["day"], d["topic"], json.dumps(d["objectives"]),
                 d["estimated_minutes"], json.dumps(d["activities"]), _now()),
            )
        return plan_id


def get_active_plan():
    with get_conn() as conn:
        row = conn.execute(
            "SELECT p.*, l.subject, l.goal, l.level, l.duration_days, l.daily_minutes "
            "FROM study_plans p JOIN learner_profiles l ON l.id = p.learner_id "
            "WHERE p.is_active = 1 ORDER BY p.id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def _topic_row(row) -> dict:
    d = dict(row)
    d["objectives"] = json.loads(d["objectives"])
    d["activities"] = json.loads(d["activities"])
    return d


def get_topics(plan_id: int) -> list:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM topics WHERE plan_id = ? ORDER BY day", (plan_id,)).fetchall()
        return [_topic_row(r) for r in rows]


def get_topic(topic_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM topics WHERE id = ?", (topic_id,)).fetchone()
        return _topic_row(row) if row else None


def update_topic_status(topic_id: int, status: str) -> None:
    if status not in STATUSES:
        raise DatabaseError(f"Invalid status: {status}")
    with get_conn() as conn:
        conn.execute("UPDATE topics SET status = ?, updated_at = ? WHERE id = ?", (status, _now(), topic_id))


def save_attempt(topic_id: int, score: int, total: int, questions: list, answers: list) -> int:
    pct = round(100 * score / total, 1) if total else 0.0
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO quiz_attempts (topic_id, score, total, percentage, questions_json, answers_json, taken_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (topic_id, score, total, pct, json.dumps(questions), json.dumps(answers), _now()),
        )
        return cur.lastrowid


def get_attempts(plan_id: int, topic_id: int = None, limit: int = None) -> list:
    """Attempts for a plan (newest first), optionally for one topic."""
    sql = ("SELECT a.id, a.topic_id, t.title AS topic, t.day, a.score, a.total, a.percentage, a.taken_at "
           "FROM quiz_attempts a JOIN topics t ON t.id = a.topic_id WHERE t.plan_id = ?")
    params = [plan_id]
    if topic_id is not None:
        sql += " AND a.topic_id = ?"
        params.append(topic_id)
    sql += " ORDER BY a.id DESC"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
