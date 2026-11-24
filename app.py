"""FitTrack - Gym Membership & Attendance Manager (Flask + SQLite)."""
import os
import re
import sqlite3
from datetime import date, datetime, timedelta

from flask import (Flask, flash, redirect, render_template, request, session,
                   url_for, abort)
from werkzeug.security import check_password_hash

from db import init_db, plan_end_date, query, scalar, transaction

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "fittrack-dev-secret")
init_db()

PAY_METHODS = ["Cash", "UPI", "Card"]
GENDERS = ["Male", "Female", "Other"]


# ----------------------------------------------------------- helpers
def today():
    return date.today()


def iso(d):
    return d.isoformat()


@app.context_processor
def inject_globals():
    return {"today_str": iso(today()), "pay_methods": PAY_METHODS, "genders": GENDERS}


@app.template_filter("money")
def money(v):
    return "Rs. {:,.0f}".format(v or 0)


@app.template_filter("pretty")
def pretty_date(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d").strftime("%d %b %Y")
    except (TypeError, ValueError):
        return s or "-"


@app.before_request
def require_login():
    if request.endpoint in (None, "login", "static"):
        return None
    if not session.get("admin"):
        return redirect(url_for("login"))
    return None


def valid_member_form(f, check_dates=False):
    errors = []
    if not f.get("name", "").strip():
        errors.append("Name is required.")
    if not re.fullmatch(r"\d{10}", f.get("phone", "").strip()):
        errors.append("Phone must be exactly 10 digits.")
    email = f.get("email", "").strip()
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        errors.append("Email is not valid.")
    if f.get("gender") not in GENDERS:
        errors.append("Select a gender.")
    if check_dates:
        try:
            date.fromisoformat(f.get("start_date", ""))
        except ValueError:
            errors.append("Start date is not valid.")
    return errors


# ----------------------------------------------------------- auth
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        row = query("SELECT * FROM admins WHERE username = ?",
                    (request.form.get("username", "").strip(),), one=True)
        if row and check_password_hash(row["password_hash"], request.form.get("password", "")):
            session["admin"] = row["username"]
            return redirect(url_for("dashboard"))
        flash("Wrong username or password.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ----------------------------------------------------------- dashboard
@app.route("/")
def dashboard():
    t = iso(today())
    month_start = iso(today().replace(day=1))
    soon = iso(today() + timedelta(days=7))
    stats = {
        "total": scalar("SELECT COUNT(*) FROM members"),
        "active": scalar("SELECT COUNT(*) FROM members WHERE end_date >= ?", (t,)),
        "expired": scalar("SELECT COUNT(*) FROM members WHERE end_date < ?", (t,)),
        "revenue": scalar("SELECT COALESCE(SUM(amount),0) FROM payments WHERE pay_date >= ?", (month_start,)),
        "checkins": scalar("SELECT COUNT(*) FROM attendance WHERE visit_date = ?", (t,)),
    }
    expiring = query("SELECT * FROM v_member_details WHERE end_date BETWEEN ? AND ? ORDER BY end_date", (t, soon))
    recent = query("""SELECT p.payment_id, p.amount, p.pay_date, p.method, m.name
                      FROM payments p JOIN members m ON m.member_id = p.member_id
                      ORDER BY p.pay_date DESC, p.payment_id DESC LIMIT 5""")
    return render_template("dashboard.html", stats=stats, expiring=expiring, recent=recent)


# ----------------------------------------------------------- members
@app.route("/members")
def members():
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "all")
    sql = "SELECT * FROM v_member_details WHERE (name LIKE ? OR phone LIKE ?)"
    args = [f"%{q}%", f"%{q}%"]
    if status == "active":
        sql += " AND end_date >= ?"
        args.append(iso(today()))
    elif status == "expired":
        sql += " AND end_date < ?"
        args.append(iso(today()))
    sql += " ORDER BY name"
    return render_template("members.html", rows=query(sql, args), q=q, status=status)


@app.route("/members/add", methods=["GET", "POST"])
def member_add():
    plans = query("SELECT * FROM plans ORDER BY duration_months")
    trainers = query("SELECT * FROM trainers ORDER BY name")
    form = {"start_date": iso(today())}
    if request.method == "POST":
        form = request.form
        errors = valid_member_form(form, check_dates=True)
        plan = query("SELECT * FROM plans WHERE plan_id = ?", (form.get("plan_id"),), one=True)
        if not plan:
            errors.append("Select a plan.")
        if form.get("method") not in PAY_METHODS:
            errors.append("Select a payment method.")
        if not errors:
            start = date.fromisoformat(form["start_date"])
            end = plan_end_date(start, plan["duration_months"])
            trainer_id = form.get("trainer_id") or None
            try:
                with transaction() as conn:
                    cur = conn.execute(
                        "INSERT INTO members (name, phone, email, gender, join_date, plan_id, trainer_id, start_date, end_date)"
                        " VALUES (?,?,?,?,?,?,?,?,?)",
                        (form["name"].strip(), form["phone"].strip(), form.get("email", "").strip() or None,
                         form["gender"], iso(today()), plan["plan_id"], trainer_id, iso(start), iso(end)))
                    conn.execute(
                        "INSERT INTO payments (member_id, plan_id, amount, pay_date, method) VALUES (?,?,?,?,?)",
                        (cur.lastrowid, plan["plan_id"], plan["price"], iso(today()), form["method"]))
                flash("Member added and first payment recorded.", "ok")
                return redirect(url_for("member_detail", member_id=cur.lastrowid))
            except sqlite3.IntegrityError:
                errors.append("A member with this phone number already exists.")
        for e in errors:
            flash(e, "error")
    return render_template("member_form.html", form=form, plans=plans, trainers=trainers, editing=False)


@app.route("/members/<int:member_id>")
def member_detail(member_id):
    m = query("SELECT * FROM v_member_details WHERE member_id = ?", (member_id,), one=True)
    if not m:
        abort(404)
    payments = query("""SELECT p.*, pl.name AS plan_name FROM payments p
                        JOIN plans pl ON pl.plan_id = p.plan_id
                        WHERE p.member_id = ? ORDER BY p.pay_date DESC, p.payment_id DESC""", (member_id,))
    visits = query("SELECT * FROM attendance WHERE member_id = ? ORDER BY visit_date DESC LIMIT 10", (member_id,))
    total_visits = scalar("SELECT COUNT(*) FROM attendance WHERE member_id = ?", (member_id,))
    plans = query("SELECT * FROM plans ORDER BY duration_months")
    return render_template("member_detail.html", m=m, payments=payments, visits=visits,
                           total_visits=total_visits, plans=plans)


@app.route("/members/<int:member_id>/edit", methods=["GET", "POST"])
def member_edit(member_id):
    m = query("SELECT * FROM members WHERE member_id = ?", (member_id,), one=True)
    if not m:
        abort(404)
    trainers = query("SELECT * FROM trainers ORDER BY name")
    form = m
    if request.method == "POST":
        form = request.form
        errors = valid_member_form(form)
        if not errors:
            try:
                with transaction() as conn:
                    conn.execute(
                        "UPDATE members SET name=?, phone=?, email=?, gender=?, trainer_id=? WHERE member_id=?",
                        (form["name"].strip(), form["phone"].strip(), form.get("email", "").strip() or None,
                         form["gender"], form.get("trainer_id") or None, member_id))
                flash("Member updated.", "ok")
                return redirect(url_for("member_detail", member_id=member_id))
            except sqlite3.IntegrityError:
                errors.append("Another member already uses this phone number.")
        for e in errors:
            flash(e, "error")
    return render_template("member_form.html", form=form, plans=[], trainers=trainers, editing=True, m=m)


@app.route("/members/<int:member_id>/renew", methods=["POST"])
def member_renew(member_id):
    m = query("SELECT * FROM members WHERE member_id = ?", (member_id,), one=True)
    plan = query("SELECT * FROM plans WHERE plan_id = ?", (request.form.get("plan_id"),), one=True)
    method = request.form.get("method")
    if not m or not plan or method not in PAY_METHODS:
        flash("Select a plan and a payment method.", "error")
        return redirect(url_for("member_detail", member_id=member_id))
    current_end = date.fromisoformat(m["end_date"])
    # still active -> new period starts after the current one, otherwise starts today
    start = current_end + timedelta(days=1) if current_end >= today() else today()
    end = plan_end_date(start, plan["duration_months"])
    with transaction() as conn:
        conn.execute("UPDATE members SET plan_id=?, start_date=?, end_date=? WHERE member_id=?",
                     (plan["plan_id"], iso(start), iso(end), member_id))
        conn.execute("INSERT INTO payments (member_id, plan_id, amount, pay_date, method) VALUES (?,?,?,?,?)",
                     (member_id, plan["plan_id"], plan["price"], iso(today()), method))
    flash(f"Membership renewed until {pretty_date(iso(end))}.", "ok")
    return redirect(url_for("member_detail", member_id=member_id))


@app.route("/members/<int:member_id>/delete", methods=["POST"])
def member_delete(member_id):
    with transaction() as conn:
        conn.execute("DELETE FROM members WHERE member_id = ?", (member_id,))
    flash("Member deleted (their payments and attendance were removed too).", "ok")
    return redirect(url_for("members"))


# ----------------------------------------------------------- plans
@app.route("/plans", methods=["GET", "POST"])
def plans():
    if request.method == "POST":
        try:
            months = int(request.form.get("duration_months", ""))
            price = float(request.form.get("price", ""))
            name = request.form.get("name", "").strip()
            if not name or months <= 0 or price < 0:
                raise ValueError
            with transaction() as conn:
                conn.execute("INSERT INTO plans (name, duration_months, price) VALUES (?,?,?)",
                             (name, months, price))
            flash("Plan added.", "ok")
        except ValueError:
            flash("Enter a name, duration (months > 0) and price (>= 0).", "error")
        except sqlite3.IntegrityError:
            flash("A plan with this name already exists.", "error")
        return redirect(url_for("plans"))
    rows = query("""SELECT pl.*, COUNT(m.member_id) AS members FROM plans pl
                    LEFT JOIN members m ON m.plan_id = pl.plan_id
                    GROUP BY pl.plan_id ORDER BY pl.duration_months""")
    return render_template("plans.html", rows=rows)


@app.route("/plans/<int:plan_id>/edit", methods=["POST"])
def plan_edit(plan_id):
    try:
        price = float(request.form.get("price", ""))
        if price < 0:
            raise ValueError
        with transaction() as conn:
            conn.execute("UPDATE plans SET price = ? WHERE plan_id = ?", (price, plan_id))
        flash("Plan price updated (old payments keep their old amount).", "ok")
    except ValueError:
        flash("Enter a valid price.", "error")
    return redirect(url_for("plans"))


@app.route("/plans/<int:plan_id>/delete", methods=["POST"])
def plan_delete(plan_id):
    try:
        with transaction() as conn:
            conn.execute("DELETE FROM plans WHERE plan_id = ?", (plan_id,))
        flash("Plan deleted.", "ok")
    except sqlite3.IntegrityError:
        flash("This plan is used by members or payments, so it cannot be deleted.", "error")
    return redirect(url_for("plans"))


# ----------------------------------------------------------- trainers
@app.route("/trainers", methods=["GET", "POST"])
def trainers():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        if not name or not re.fullmatch(r"\d{10}", phone):
            flash("Enter trainer name and a 10 digit phone number.", "error")
        else:
            try:
                with transaction() as conn:
                    conn.execute("INSERT INTO trainers (name, phone, speciality) VALUES (?,?,?)",
                                 (name, phone, request.form.get("speciality", "").strip() or None))
                flash("Trainer added.", "ok")
            except sqlite3.IntegrityError:
                flash("A trainer with this phone number already exists.", "error")
        return redirect(url_for("trainers"))
    rows = query("""SELECT t.*, COUNT(m.member_id) AS members FROM trainers t
                    LEFT JOIN members m ON m.trainer_id = t.trainer_id
                    GROUP BY t.trainer_id ORDER BY t.name""")
    return render_template("trainers.html", rows=rows)


@app.route("/trainers/<int:trainer_id>/delete", methods=["POST"])
def trainer_delete(trainer_id):
    with transaction() as conn:
        conn.execute("DELETE FROM trainers WHERE trainer_id = ?", (trainer_id,))
    flash("Trainer removed (their members are now unassigned).", "ok")
    return redirect(url_for("trainers"))


# ----------------------------------------------------------- attendance
@app.route("/attendance", methods=["GET", "POST"])
def attendance():
    if request.method == "POST":
        m = query("SELECT * FROM members WHERE member_id = ?", (request.form.get("member_id"),), one=True)
        if not m:
            flash("Select a member.", "error")
        elif m["end_date"] < iso(today()):
            flash(f"{m['name']}'s membership expired on {pretty_date(m['end_date'])}. Please renew first.", "error")
        else:
            try:
                with transaction() as conn:
                    conn.execute("INSERT INTO attendance (member_id, visit_date, check_in_time) VALUES (?,?,?)",
                                 (m["member_id"], iso(today()), datetime.now().strftime("%H:%M")))
                flash(f"{m['name']} checked in.", "ok")
            except sqlite3.IntegrityError:
                flash(f"{m['name']} has already checked in today.", "error")
        return redirect(url_for("attendance"))
    day = request.args.get("date") or iso(today())
    rows = query("""SELECT a.*, m.name, m.phone FROM attendance a
                    JOIN members m ON m.member_id = a.member_id
                    WHERE a.visit_date = ? ORDER BY a.check_in_time""", (day,))
    candidates = query("""SELECT member_id, name, phone FROM members
                          WHERE end_date >= ? AND member_id NOT IN
                                (SELECT member_id FROM attendance WHERE visit_date = ?)
                          ORDER BY name""", (iso(today()), iso(today())))
    return render_template("attendance.html", rows=rows, day=day, candidates=candidates)


# ----------------------------------------------------------- payments
@app.route("/payments")
def payments():
    month = request.args.get("month", "").strip()
    sql = """SELECT p.*, m.name, pl.name AS plan_name FROM payments p
             JOIN members m ON m.member_id = p.member_id
             JOIN plans pl ON pl.plan_id = p.plan_id"""
    args = []
    if re.fullmatch(r"\d{4}-\d{2}", month):
        sql += " WHERE p.pay_date LIKE ?"
        args.append(month + "%")
    sql += " ORDER BY p.pay_date DESC, p.payment_id DESC"
    rows = query(sql, args)
    return render_template("payments.html", rows=rows, month=month, total=sum(r["amount"] for r in rows))


# ----------------------------------------------------------- reports
@app.route("/reports")
def reports():
    t = iso(today())
    return render_template(
        "reports.html",
        by_plan=query("""SELECT pl.name, COUNT(p.payment_id) AS payments, COALESCE(SUM(p.amount),0) AS revenue
                         FROM plans pl LEFT JOIN payments p ON p.plan_id = pl.plan_id
                         GROUP BY pl.plan_id ORDER BY revenue DESC"""),
        monthly=query("""SELECT substr(pay_date,1,7) AS month, SUM(amount) AS revenue, COUNT(*) AS payments
                         FROM payments GROUP BY month ORDER BY month DESC LIMIT 6"""),
        by_trainer=query("""SELECT t.name, t.speciality, COUNT(m.member_id) AS members
                            FROM trainers t LEFT JOIN members m ON m.trainer_id = t.trainer_id
                            GROUP BY t.trainer_id ORDER BY members DESC"""),
        top=query("""SELECT m.name, COUNT(*) AS visits FROM attendance a
                     JOIN members m ON m.member_id = a.member_id
                     WHERE a.visit_date >= ? GROUP BY a.member_id ORDER BY visits DESC, m.name LIMIT 5""",
                  (iso(today() - timedelta(days=30)),)),
        expired=query("SELECT * FROM v_member_details WHERE end_date < ? ORDER BY end_date DESC", (t,)),
    )


if __name__ == "__main__":
    app.run(debug=True)
