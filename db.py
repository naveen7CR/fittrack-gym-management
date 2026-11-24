"""Database helpers: connection, schema creation and sample data."""
import os
import random
import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta

from werkzeug.security import generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def db_path():
    return os.environ.get("GYM_DB", os.path.join(BASE_DIR, "gym.db"))


def get_db():
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def transaction():
    """Commit on success, roll back on any error."""
    conn = get_db()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def query(sql, args=(), one=False):
    conn = get_db()
    try:
        rows = conn.execute(sql, args).fetchall()
    finally:
        conn.close()
    if one:
        return rows[0] if rows else None
    return rows


def scalar(sql, args=()):
    row = query(sql, args, one=True)
    return row[0] if row else None


def add_months(d, months):
    import calendar
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def plan_end_date(start, months):
    """Last valid day of a plan that starts on `start`."""
    return add_months(start, months) - timedelta(days=1)


def init_db(seed=True):
    with open(os.path.join(BASE_DIR, "schema.sql"), encoding="utf-8") as f:
        schema = f.read()
    conn = get_db()
    try:
        conn.executescript(schema)
        conn.commit()
    finally:
        conn.close()
    if seed and scalar("SELECT COUNT(*) FROM plans") == 0:
        seed_data()


def seed_data():
    """Demo data (dates are relative to today so the demo always looks live)."""
    today = date.today()
    rnd = random.Random(7)
    plans = [("Monthly", 1, 1200), ("Quarterly", 3, 3200),
             ("Half-Yearly", 6, 5500), ("Yearly", 12, 9500)]
    trainers = [("Rahul Verma", "9810011001", "Strength & Conditioning"),
                ("Neha Kapoor", "9810011002", "Yoga & Flexibility"),
                ("Imran Khan", "9810011003", "Cardio & Weight Loss"),
                ("Simran Kaur", "9810011004", "Zumba & Functional Training")]
    # name, phone, email, gender, plan_index(1-4), trainer_index(1-4 or None), days_ago_start
    members = [
        ("Aarav Sharma", "9876500001", "aarav@example.com", "Male", 2, 1, 40),
        ("Priya Verma", "9876500002", "priya@example.com", "Female", 1, 2, 10),
        ("Rohan Mehta", "9876500003", "rohan@example.com", "Male", 4, 1, 120),
        ("Sneha Gupta", "9876500004", "sneha@example.com", "Female", 3, 4, 70),
        ("Karan Singh", "9876500005", "karan@example.com", "Male", 1, 3, 27),
        ("Meera Nair", "9876500006", "meera@example.com", "Female", 2, 2, 85),
        ("Vikram Joshi", "9876500007", "vikram@example.com", "Male", 1, None, 45),
        ("Ananya Reddy", "9876500008", "ananya@example.com", "Female", 4, 4, 200),
        ("Dev Malhotra", "9876500009", "dev@example.com", "Male", 3, 3, 150),
        ("Isha Bansal", "9876500010", "isha@example.com", "Female", 1, 2, 5),
        ("Harsh Agarwal", "9876500011", "harsh@example.com", "Male", 2, 1, 60),
        ("Pooja Yadav", "9876500012", "pooja@example.com", "Female", 1, 3, 33),
    ]
    methods = ["Cash", "UPI", "Card"]
    with transaction() as conn:
        conn.execute("INSERT INTO admins (username, password_hash) VALUES (?, ?)",
                     ("admin", generate_password_hash("admin123", method="pbkdf2:sha256")))
        conn.executemany("INSERT INTO plans (name, duration_months, price) VALUES (?,?,?)", plans)
        conn.executemany("INSERT INTO trainers (name, phone, speciality) VALUES (?,?,?)", trainers)
        for name, phone, email, gender, plan_id, trainer_id, ago in members:
            start = today - timedelta(days=ago)
            months = plans[plan_id - 1][1]
            end = plan_end_date(start, months)
            cur = conn.execute(
                "INSERT INTO members (name, phone, email, gender, join_date, plan_id, trainer_id, start_date, end_date)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (name, phone, email, gender, start.isoformat(), plan_id, trainer_id,
                 start.isoformat(), end.isoformat()))
            mid = cur.lastrowid
            conn.execute(
                "INSERT INTO payments (member_id, plan_id, amount, pay_date, method) VALUES (?,?,?,?,?)",
                (mid, plan_id, plans[plan_id - 1][2], start.isoformat(), rnd.choice(methods)))
            # attendance for the last 14 days while the membership was valid
            for d in range(0, 14):
                visit = today - timedelta(days=d)
                if start <= visit <= end and rnd.random() < 0.55:
                    conn.execute(
                        "INSERT INTO attendance (member_id, visit_date, check_in_time) VALUES (?,?,?)",
                        (mid, visit.isoformat(), "%02d:%02d" % (rnd.randint(6, 20), rnd.choice([0, 10, 20, 30, 40, 50]))))
