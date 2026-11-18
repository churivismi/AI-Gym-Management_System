# AI Gym Management System

A web-based gym management project that organizes gym-related information
and management activities through a digital platform.

Built as an academic project during my B.Tech in Artificial Intelligence and
Machine Learning at St. John College of Engineering and Management, Palghar.

## Features
- Admin login
- Members: add, edit, delete and search
- Membership plans (Monthly, Quarterly, Yearly) with prices
- Payments: recording a payment renews the membership automatically
- Attendance check-in (expired memberships are blocked, one check-in per day)
- Dashboard: total and active members, check-ins today, revenue this month,
  memberships expiring in 7 days
- Smart insight: active members with no visit in 14 days, so staff can follow up

## Tech stack
Python, Flask, SQLite, HTML and CSS. The database file (`gym.db`) is created
automatically on first run.

## How to run
    pip install -r requirements.txt
    python app.py
Then open http://localhost:5000

Default login: `admin` / `admin123`
To change it, set the environment variables `GYM_ADMIN_USER`, `GYM_ADMIN_PASS`
and `SECRET_KEY` before running.

## Author
Vismi Churi
- GitHub: github.com/vismi21
- LinkedIn: linkedin.com/in/vismi-churi-753837406
- Email: churivismi@gmail.com
