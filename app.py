"""
AI Gym Management System
A web-based gym management app: members, plans, attendance check-ins,
payments and a dashboard with simple smart insights.

Run:  pip install -r requirements.txt
      python app.py
Open: http://localhost:5000     Login: admin / admin123  (change below or set env vars)
"""
import calendar
import os
import sqlite3
from datetime import date, datetime, timedelta
from functools import wraps

from flask import (Flask, flash, g, redirect, render_template, request,
                   session, url_for)
from jinja2 import DictLoader

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key")

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gym.db")
ADMIN_USER = os.environ.get("GYM_ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("GYM_ADMIN_PASS", "admin123")

# ---------------------------------------------------------------- database
SCHEMA = """
CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    months INTEGER NOT NULL,
    price INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT,
    email TEXT,
    plan_id INTEGER REFERENCES plans(id),
    join_date TEXT NOT NULL,
    expiry_date TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    visited_on TEXT NOT NULL,
    time_in TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    amount INTEGER NOT NULL,
    months INTEGER NOT NULL,
    paid_on TEXT NOT NULL
);
"""
DEFAULT_PLANS = [("Monthly", 1, 1000), ("Quarterly", 3, 2700), ("Yearly", 12, 9600)]


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def query(sql, args=(), one=False):
    cur = get_db().execute(sql, args)
    rows = cur.fetchall()
    return (rows[0] if rows else None) if one else rows


def execute(sql, args=()):
    db = get_db()
    cur = db.execute(sql, args)
    db.commit()
    return cur.lastrowid


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(SCHEMA)
    if db.execute("SELECT COUNT(*) FROM plans").fetchone()[0] == 0:
        db.executemany("INSERT INTO plans (name, months, price) VALUES (?,?,?)", DEFAULT_PLANS)
    db.commit()
    db.close()


# ----------------------------------------------------------------- helpers
def today():
    return date.today()


def add_months(d, months):
    """Add whole calendar months to a date (clamps to month end)."""
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def parse(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapper


@app.context_processor
def inject_globals():
    return {"today": today().isoformat()}


# ------------------------------------------------------------------ routes
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if (request.form.get("username") == ADMIN_USER
                and request.form.get("password") == ADMIN_PASS):
            session["admin"] = True
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/") else url_for("dashboard"))
        flash("Wrong username or password.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard():
    t = today().isoformat()
    soon = (today() + timedelta(days=7)).isoformat()
    month = t[:7]
    stats = {
        "total": query("SELECT COUNT(*) c FROM members", one=True)["c"],
        "active": query("SELECT COUNT(*) c FROM members WHERE expiry_date >= ?", (t,), one=True)["c"],
        "today": query("SELECT COUNT(*) c FROM attendance WHERE visited_on = ?", (t,), one=True)["c"],
        "revenue": query("SELECT COALESCE(SUM(amount),0) s FROM payments WHERE paid_on LIKE ?",
                         (month + "%",), one=True)["s"],
    }
    expiring = query(
        "SELECT * FROM members WHERE expiry_date BETWEEN ? AND ? ORDER BY expiry_date", (t, soon))
    # Smart insight: active members who have not visited in 14+ days (or never)
    cutoff = (today() - timedelta(days=14)).isoformat()
    inactive = query(
        """SELECT m.*, MAX(a.visited_on) AS last_visit
           FROM members m LEFT JOIN attendance a ON a.member_id = m.id
           WHERE m.expiry_date >= ?
           GROUP BY m.id
           HAVING last_visit IS NULL OR last_visit < ?
           ORDER BY last_visit""", (t, cutoff))
    return render_template("dashboard.html", stats=stats, expiring=expiring, inactive=inactive)


@app.route("/members")
@login_required
def members():
    search = request.args.get("q", "").strip()
    sql = """SELECT m.*, p.name AS plan_name FROM members m
             LEFT JOIN plans p ON p.id = m.plan_id"""
    args = ()
    if search:
        sql += " WHERE m.name LIKE ? OR m.phone LIKE ?"
        args = (f"%{search}%", f"%{search}%")
    rows = query(sql + " ORDER BY m.name", args)
    return render_template("members.html", members=rows, search=search)


@app.route("/members/add", methods=["GET", "POST"])
@login_required
def add_member():
    plans = query("SELECT * FROM plans ORDER BY months")
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        plan = query("SELECT * FROM plans WHERE id = ?", (request.form.get("plan_id"),), one=True)
        if not name or not plan:
            flash("Name and plan are required.", "error")
        else:
            join = today()
            member_id = execute(
                "INSERT INTO members (name, phone, email, plan_id, join_date, expiry_date) VALUES (?,?,?,?,?,?)",
                (name, request.form.get("phone", "").strip(), request.form.get("email", "").strip(),
                 plan["id"], join.isoformat(), add_months(join, plan["months"]).isoformat()))
            execute("INSERT INTO payments (member_id, amount, months, paid_on) VALUES (?,?,?,?)",
                    (member_id, plan["price"], plan["months"], join.isoformat()))
            flash(f"{name} joined on the {plan['name']} plan.", "ok")
            return redirect(url_for("members"))
    return render_template("member_form.html", plans=plans, member=None)


@app.route("/members/<int:member_id>/edit", methods=["GET", "POST"])
@login_required
def edit_member(member_id):
    member = query("SELECT * FROM members WHERE id = ?", (member_id,), one=True)
    if member is None:
        flash("Member not found.", "error")
        return redirect(url_for("members"))
    plans = query("SELECT * FROM plans ORDER BY months")
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Name is required.", "error")
        else:
            execute("UPDATE members SET name=?, phone=?, email=?, plan_id=? WHERE id=?",
                    (name, request.form.get("phone", "").strip(), request.form.get("email", "").strip(),
                     request.form.get("plan_id"), member_id))
            flash("Member updated.", "ok")
            return redirect(url_for("members"))
    return render_template("member_form.html", plans=plans, member=member)


@app.route("/members/<int:member_id>/delete", methods=["POST"])
@login_required
def delete_member(member_id):
    execute("DELETE FROM members WHERE id = ?", (member_id,))
    flash("Member deleted.", "ok")
    return redirect(url_for("members"))


@app.route("/checkin", methods=["GET", "POST"])
@login_required
def checkin():
    if request.method == "POST":
        member = query("SELECT * FROM members WHERE id = ?", (request.form.get("member_id"),), one=True)
        if member is None:
            flash("Choose a member.", "error")
        elif member["expiry_date"] < today().isoformat():
            flash(f"{member['name']}'s membership expired on {member['expiry_date']}. Record a payment first.", "error")
        elif query("SELECT 1 FROM attendance WHERE member_id=? AND visited_on=?",
                   (member["id"], today().isoformat()), one=True):
            flash(f"{member['name']} is already checked in today.", "error")
        else:
            execute("INSERT INTO attendance (member_id, visited_on, time_in) VALUES (?,?,?)",
                    (member["id"], today().isoformat(), datetime.now().strftime("%H:%M")))
            flash(f"{member['name']} checked in.", "ok")
        return redirect(url_for("checkin"))
    members_list = query("SELECT id, name FROM members WHERE expiry_date >= ? ORDER BY name",
                         (today().isoformat(),))
    recent = query("""SELECT a.*, m.name FROM attendance a JOIN members m ON m.id = a.member_id
                      ORDER BY a.visited_on DESC, a.time_in DESC LIMIT 30""")
    return render_template("checkin.html", members=members_list, recent=recent)


@app.route("/payments", methods=["GET", "POST"])
@login_required
def payments():
    if request.method == "POST":
        member = query("SELECT * FROM members WHERE id = ?", (request.form.get("member_id"),), one=True)
        plan = query("SELECT * FROM plans WHERE id = ?", (request.form.get("plan_id"),), one=True)
        if member is None or plan is None:
            flash("Choose a member and a plan.", "error")
        else:
            start = max(today(), parse(member["expiry_date"]))   # renew from expiry if still active
            new_expiry = add_months(start, plan["months"])
            execute("INSERT INTO payments (member_id, amount, months, paid_on) VALUES (?,?,?,?)",
                    (member["id"], plan["price"], plan["months"], today().isoformat()))
            execute("UPDATE members SET plan_id=?, expiry_date=? WHERE id=?",
                    (plan["id"], new_expiry.isoformat(), member["id"]))
            flash(f"Payment of Rs {plan['price']} recorded. {member['name']} is valid until {new_expiry}.", "ok")
        return redirect(url_for("payments"))
    rows = query("""SELECT p.*, m.name FROM payments p JOIN members m ON m.id = p.member_id
                    ORDER BY p.paid_on DESC, p.id DESC LIMIT 50""")
    members_list = query("SELECT id, name FROM members ORDER BY name")
    plans = query("SELECT * FROM plans ORDER BY months")
    return render_template("payments.html", payments=rows, members=members_list, plans=plans)


# --------------------------------------------------------------- templates
TEMPLATES = {
"base.html": """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{% block title %}AI Gym Management System{% endblock %}</title>
<style>
:root{--bg:#e6f3fd;--card:#fff;--text:#0a2540;--muted:#3d6080;--blue:#2563eb;--sky:#0369a1;--line:#cfe3f4;--ok:#047857;--bad:#b91c1c}
*{box-sizing:border-box}
body{margin:0;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;background:var(--bg);color:var(--text);line-height:1.5}
header{background:var(--card);border-bottom:1px solid var(--line)}
.bar{max-width:1000px;margin:auto;padding:12px 16px;display:flex;flex-wrap:wrap;gap:6px 18px;align-items:center}
.brand{font-weight:700;font-size:1.1rem;color:var(--sky);margin-right:auto}
nav a{color:var(--muted);text-decoration:none;font-weight:500;padding:4px 2px}
nav a:hover{color:var(--blue)}
main{max-width:1000px;margin:auto;padding:22px 16px 60px}
h1{font-size:1.6rem;margin:0 0 16px}h2{font-size:1.15rem;margin:0 0 10px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:14px;margin-bottom:22px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px;min-width:0}
.stat b{display:block;font-size:2rem}.stat span{color:var(--muted);font-size:.9rem}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:9px 8px;border-bottom:1px solid var(--line);font-size:.95rem}
th{color:var(--muted);font-weight:600;font-size:.82rem;text-transform:uppercase;letter-spacing:.04em}
.scroll{overflow-x:auto}
input,select{width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:10px;font:inherit;background:#fff;color:var(--text)}
label{display:block;font-weight:500;margin:12px 0 4px}
.btn{display:inline-block;background:var(--blue);color:#fff;border:0;border-radius:10px;padding:10px 18px;font:inherit;font-weight:600;cursor:pointer;text-decoration:none}
.btn.ghost{background:#fff;color:var(--blue);border:1px solid var(--line)}
.btn.small{padding:5px 12px;font-size:.85rem}.btn.danger{background:var(--bad)}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:end}.row>*{flex:1;min-width:150px}
.pill{display:inline-block;padding:2px 10px;border-radius:99px;font-size:.78rem;font-weight:600}
.pill.ok{background:#d1fae5;color:var(--ok)}.pill.bad{background:#fee2e2;color:var(--bad)}
.flash{padding:10px 14px;border-radius:10px;margin-bottom:14px;font-weight:500}
.flash.ok{background:#d1fae5;color:var(--ok)}.flash.error{background:#fee2e2;color:var(--bad)}
.muted{color:var(--muted)}form.inline{display:inline}
.narrow{max-width:420px;margin:60px auto}
</style></head><body>
{% if session.admin %}
<header><div class="bar"><span class="brand">AI Gym Management</span>
<nav><a href="{{ url_for('dashboard') }}">Dashboard</a> &nbsp;<a href="{{ url_for('members') }}">Members</a> &nbsp;
<a href="{{ url_for('checkin') }}">Check-in</a> &nbsp;<a href="{{ url_for('payments') }}">Payments</a> &nbsp;
<a href="{{ url_for('logout') }}">Log out</a></nav></div></header>
{% endif %}
<main>
{% for category, message in get_flashed_messages(with_categories=true) %}
<div class="flash {{ category }}">{{ message }}</div>{% endfor %}
{% block content %}{% endblock %}
</main></body></html>""",

"login.html": """{% extends "base.html" %}{% block content %}
<div class="card narrow"><h1>Admin login</h1>
<form method="post">
<label for="username">Username</label><input id="username" name="username" autofocus required>
<label for="password">Password</label><input id="password" name="password" type="password" required>
<p><button class="btn" type="submit">Log in</button></p></form></div>{% endblock %}""",

"dashboard.html": """{% extends "base.html" %}{% block content %}
<h1>Dashboard</h1>
<div class="grid">
<div class="card stat"><b>{{ stats.total }}</b><span>Total members</span></div>
<div class="card stat"><b>{{ stats.active }}</b><span>Active memberships</span></div>
<div class="card stat"><b>{{ stats.today }}</b><span>Check-ins today</span></div>
<div class="card stat"><b>Rs {{ stats.revenue }}</b><span>Revenue this month</span></div>
</div>
<div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(300px,1fr))">
<div class="card"><h2>Expiring in 7 days</h2>
{% if expiring %}<div class="scroll"><table><tr><th>Member</th><th>Phone</th><th>Expires</th></tr>
{% for m in expiring %}<tr><td>{{ m.name }}</td><td>{{ m.phone or '-' }}</td><td>{{ m.expiry_date }}</td></tr>{% endfor %}</table></div>
{% else %}<p class="muted">No memberships expiring this week.</p>{% endif %}</div>
<div class="card"><h2>Smart insight: at risk of leaving</h2>
<p class="muted">Active members with no visit in the last 14 days. A reminder call can bring them back.</p>
{% if inactive %}<div class="scroll"><table><tr><th>Member</th><th>Phone</th><th>Last visit</th></tr>
{% for m in inactive %}<tr><td>{{ m.name }}</td><td>{{ m.phone or '-' }}</td><td>{{ m.last_visit or 'Never' }}</td></tr>{% endfor %}</table></div>
{% else %}<p class="muted">Everyone is visiting regularly.</p>{% endif %}</div>
</div>{% endblock %}""",

"members.html": """{% extends "base.html" %}{% block content %}
<h1>Members</h1>
<form class="row card" method="get" style="margin-bottom:16px">
<div><label for="q">Search by name or phone</label><input id="q" name="q" value="{{ search }}"></div>
<div style="flex:0 0 auto"><button class="btn" type="submit">Search</button>
<a class="btn ghost" href="{{ url_for('add_member') }}">+ Add member</a></div></form>
<div class="card scroll">
{% if members %}<table><tr><th>Name</th><th>Phone</th><th>Plan</th><th>Expires</th><th>Status</th><th></th></tr>
{% for m in members %}<tr><td>{{ m.name }}</td><td>{{ m.phone or '-' }}</td><td>{{ m.plan_name or '-' }}</td>
<td>{{ m.expiry_date }}</td>
<td>{% if m.expiry_date >= today %}<span class="pill ok">Active</span>{% else %}<span class="pill bad">Expired</span>{% endif %}</td>
<td style="white-space:nowrap"><a class="btn ghost small" href="{{ url_for('edit_member', member_id=m.id) }}">Edit</a>
<form class="inline" method="post" action="{{ url_for('delete_member', member_id=m.id) }}"><button class="btn danger small" type="submit">Delete</button></form></td></tr>{% endfor %}
</table>{% else %}<p class="muted">No members found. Add your first member.</p>{% endif %}</div>{% endblock %}""",

"member_form.html": """{% extends "base.html" %}{% block content %}
<h1>{{ 'Edit member' if member else 'Add member' }}</h1>
<form class="card" method="post" style="max-width:520px">
<label for="name">Full name</label><input id="name" name="name" value="{{ member.name if member else '' }}" required>
<label for="phone">Phone</label><input id="phone" name="phone" value="{{ member.phone if member else '' }}">
<label for="email">Email</label><input id="email" name="email" type="email" value="{{ member.email if member else '' }}">
<label for="plan_id">Plan</label><select id="plan_id" name="plan_id">
{% for p in plans %}<option value="{{ p.id }}" {{ 'selected' if member and member.plan_id == p.id }}>{{ p.name }} (Rs {{ p.price }})</option>{% endfor %}</select>
<p><button class="btn" type="submit">Save</button> <a class="btn ghost" href="{{ url_for('members') }}">Cancel</a></p>
</form>{% endblock %}""",

"checkin.html": """{% extends "base.html" %}{% block content %}
<h1>Check-in</h1>
<form class="row card" method="post" style="margin-bottom:16px">
<div><label for="member_id">Member (active only)</label><select id="member_id" name="member_id" required>
<option value="">Choose a member</option>{% for m in members %}<option value="{{ m.id }}">{{ m.name }}</option>{% endfor %}</select></div>
<div style="flex:0 0 auto"><button class="btn" type="submit">Check in</button></div></form>
<div class="card scroll"><h2>Recent visits</h2>
{% if recent %}<table><tr><th>Member</th><th>Date</th><th>Time</th></tr>
{% for r in recent %}<tr><td>{{ r.name }}</td><td>{{ r.visited_on }}</td><td>{{ r.time_in }}</td></tr>{% endfor %}</table>
{% else %}<p class="muted">No visits yet.</p>{% endif %}</div>{% endblock %}""",

"payments.html": """{% extends "base.html" %}{% block content %}
<h1>Payments</h1>
<form class="row card" method="post" style="margin-bottom:16px">
<div><label for="member_id">Member</label><select id="member_id" name="member_id" required>
<option value="">Choose a member</option>{% for m in members %}<option value="{{ m.id }}">{{ m.name }}</option>{% endfor %}</select></div>
<div><label for="plan_id">Plan</label><select id="plan_id" name="plan_id">
{% for p in plans %}<option value="{{ p.id }}">{{ p.name }} (Rs {{ p.price }})</option>{% endfor %}</select></div>
<div style="flex:0 0 auto"><button class="btn" type="submit">Record payment</button></div></form>
<div class="card scroll"><h2>Recent payments</h2>
{% if payments %}<table><tr><th>Member</th><th>Date</th><th>Months</th><th>Amount</th></tr>
{% for p in payments %}<tr><td>{{ p.name }}</td><td>{{ p.paid_on }}</td><td>{{ p.months }}</td><td>Rs {{ p.amount }}</td></tr>{% endfor %}</table>
{% else %}<p class="muted">No payments yet.</p>{% endif %}</div>{% endblock %}""",
}
app.jinja_loader = DictLoader(TEMPLATES)

init_db()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
