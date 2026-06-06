# FitForge — AI Fitness OS (multi-user)

A personal AI fitness tracker. Open it, type your name, take a short quiz, and
you're in — no accounts, no passwords. One profile, stored in Supabase. AI
features run on Gemini 2.5 Flash.

## How it works

- **No auth.** First visit → enter name → quiz → AI builds your routine + diet
  plan. After that it goes straight to your dashboard. "Start over" (bottom of
  the sidebar) re-takes the quiz and clears your data.
- **Single user.** It's your own tracker. The server uses Supabase's
  service-role key to read/write one fixed profile. Nothing is exposed to the
  browser, so this is safe for a personal app.

## AI features (Gemini 2.5 Flash)

- Routine generation from the quiz
- Routine evolution (EXP-gated, on the Planner page)
- Ask-trainer chat + "Motivate me" (Motivation page)
- Weekly analysis of workouts / water / sleep / food (button on Diet page)
- Daily note on the dashboard

Zero-cost (no AI): static form tips in workouts, and manual food logging
(type macros yourself, or search the seeded food database to autofill them).

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# edit .env:
#   FLASK_SECRET_KEY     -> python -c "import secrets; print(secrets.token_hex(32))"
#   SUPABASE_SERVICE_KEY -> Supabase dashboard > Settings > API > service_role
#   GEMINI_API_KEY       -> https://aistudio.google.com/apikey (free tier)
#   SUPABASE_URL is already filled

flask --app app run --debug
# open http://localhost:5000
```

Runs on **port 5000**.

## Database

Already set up on the linked Supabase project, now in single-user mode: RLS is
off (one user, server-side service key only), one fixed profile row, and seed
data (15 exercises, 15 foods). Nothing to run.

## Deploying

Standard Flask + gunicorn (`Procfile` and `runtime.txt` included). Not Vercel.

**Render (recommended, free):** New → Web Service → connect repo →
build `pip install -r requirements.txt`, start `gunicorn app:app` → add env
vars `FLASK_SECRET_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `GEMINI_API_KEY`.

Also fine: Railway (auto-detects Procfile) or PythonAnywhere.

## Structure

```
app.py                  # all routes: welcome/quiz, pages, AI endpoints, EXP, evolution
lib/
  supabase_client.py    # single service-role client + fixed USER_ID
  gemini.py             # Gemini 2.5 Flash wrapper
  exp.py                # EXP scoring + BMI
  tips.py               # static form tips (zero API)
templates/              # welcome, dashboard, workout, planner, statistics,
                        # lifestyle, diet, library, motivation, settings
static/css/style.css    # dark-minimal theme, two-colour system
```

## Security note

The service-role key bypasses all database protection — fine for a single-user
app where only your server holds it, but never expose it in the browser, and
rotate it if it ever leaks (Supabase → Settings → API).


## Recent improvements

- **Fixed:** Lifestyle page 500 error (occurred when no log existed yet for the day).
- **Smarter AI chat:** the coach now reads your real data (streak, goal, recent weight, today's water/sleep) and talks like it knows you, not a generic bot.
- **Better routine tailoring:** the generator now matches your equipment, available days, session length, injuries, experience and goal — no more baseline templates.
- **Proactive coach:** the dashboard auto-loads a weekly pattern insight ("your energy dips every day you sleep under 6h"), and the Diet page has an on-demand analysis.
- **Profile page:** identity, lifetime stats, achievements, body-weight progress, and full routine-version history. Reachable from the sidebar avatar or the Profile nav item.
- **Richer dashboard:** quick-log shortcuts for workout / water / meals.


## Multi-user (accounts)

FitForge now supports multiple people, each with their own private data.

**Two ways to sign up:**
- Email + password (password min 8 characters)
- Username + 4-digit PIN (no email needed)

**Security built in (don't remove these):**
- Passwords and PINs are hashed with PBKDF2 (werkzeug) — never stored as plaintext.
- After 5 failed login attempts an account locks for 15 minutes. This is what
  makes a 4-digit PIN safe against online guessing — a PIN alone is only 10,000
  combinations, so the lockout is essential.
- Login errors are generic ("Invalid credentials") so they never reveal whether
  an account exists.
- Every database query is scoped to the logged-in user, so people only ever see
  their own routine, logs, and progress.

**Sharing with friends:** just send them your deployed URL. They tap Sign up,
pick a method, and get their own separate account and AI plan. Anyone with the
link can sign up (no invite gate).

**Note:** moving to multi-user cleared the old single-user test data. Everyone
(including you) signs up fresh.


## Multi-user & accounts

FitForge now supports multiple people, each with their own private data.

**Two ways to sign up:**
- **Email + password** (password min 8 characters)
- **Username + 4-digit PIN** (no email needed)

Log in with either your email or your username, plus your password/PIN.

**Security built in:**
- Passwords and PINs are hashed (PBKDF2 via Werkzeug) — never stored as plaintext.
- After 5 failed login attempts an account locks for 15 minutes. This is what
  keeps a short PIN safe from guessing — do not remove it.
- Every database query is scoped to the logged-in user, so people only ever
  see their own workouts, diet, and progress.
- Login errors are generic ("invalid credentials") and never reveal whether an
  account exists.

**Sharing the app:** anyone with the link can create an account and use it with
their own separate data. Send friends your Vercel/Render URL and they sign up.

**Note:** moving to multi-user cleared the old single-user test data. Everyone
(including you) signs up fresh on first visit.
