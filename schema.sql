-- FitTrack: Gym Membership & Attendance Manager
-- Database: SQLite (3NF, foreign keys enforced)

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS admins (
    admin_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plans (
    plan_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL UNIQUE,
    duration_months INTEGER NOT NULL CHECK (duration_months > 0),
    price           REAL    NOT NULL CHECK (price >= 0)
);

CREATE TABLE IF NOT EXISTS trainers (
    trainer_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    phone      TEXT NOT NULL UNIQUE,
    speciality TEXT
);

CREATE TABLE IF NOT EXISTS members (
    member_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    phone      TEXT NOT NULL UNIQUE,
    email      TEXT,
    gender     TEXT CHECK (gender IN ('Male', 'Female', 'Other')),
    join_date  TEXT NOT NULL,
    plan_id    INTEGER NOT NULL REFERENCES plans(plan_id) ON DELETE RESTRICT,
    trainer_id INTEGER REFERENCES trainers(trainer_id) ON DELETE SET NULL,
    start_date TEXT NOT NULL,
    end_date   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS payments (
    payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id  INTEGER NOT NULL REFERENCES members(member_id) ON DELETE CASCADE,
    plan_id    INTEGER NOT NULL REFERENCES plans(plan_id) ON DELETE RESTRICT,
    amount     REAL    NOT NULL CHECK (amount > 0),
    pay_date   TEXT    NOT NULL,
    method     TEXT    NOT NULL CHECK (method IN ('Cash', 'UPI', 'Card'))
);

CREATE TABLE IF NOT EXISTS attendance (
    attendance_id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id     INTEGER NOT NULL REFERENCES members(member_id) ON DELETE CASCADE,
    visit_date    TEXT NOT NULL,
    check_in_time TEXT NOT NULL,
    UNIQUE (member_id, visit_date)          -- one check-in per member per day
);

CREATE INDEX IF NOT EXISTS idx_members_end_date  ON members(end_date);
CREATE INDEX IF NOT EXISTS idx_members_trainer   ON members(trainer_id);
CREATE INDEX IF NOT EXISTS idx_payments_date     ON payments(pay_date);
CREATE INDEX IF NOT EXISTS idx_payments_member   ON payments(member_id);
CREATE INDEX IF NOT EXISTS idx_attendance_date   ON attendance(visit_date);

-- Member details joined with plan and trainer names
CREATE VIEW IF NOT EXISTS v_member_details AS
SELECT m.member_id, m.name, m.phone, m.email, m.gender, m.join_date,
       m.start_date, m.end_date,
       m.plan_id, p.name AS plan_name, p.price AS plan_price,
       m.trainer_id, t.name AS trainer_name
FROM members m
JOIN plans p          ON p.plan_id = m.plan_id
LEFT JOIN trainers t  ON t.trainer_id = m.trainer_id;
