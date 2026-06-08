# FitForge — AI Fitness OS

A personal AI fitness companion built with Python and Flask. Sign up, take a 30-question onboarding quiz, and Gemini 2.5 Flash builds you a personalised weekly training plan and nutrition brief. Log your workouts, earn EXP, and your routine evolves as you progress.

**Live:** [fit-forge-02r9.onrender.com](https://fit-forge-02r9.onrender.com)

---

## What it does

**AI features (Gemini 2.5 Flash)**
- Generates a personalised weekly routine from your quiz answers — matches your equipment, available days, injuries, experience, and goal
- Evolves the routine when you earn enough EXP, using your last 60 workout logs to decide what to progress and what to regress
- AI coach chat that knows your real data (streak, weight, today's water and sleep) — not a generic chatbot
- Proactive weekly pattern analysis on the dashboard ("your energy drops every day you sleep under 6h")
- Motivation page with AI-generated push messages

**Training**
- 52 exercises across 10 colour-coded categories: Chest, Back, Shoulders, Arms, Thighs, Glutes, Core, Calves, Posture, Cardio
- Step-by-step form instructions and static form tips for every exercise (zero API cost)
- EXP system: compound lifts worth more, progressive overload rewarded, streaks multiply earnings
- Personal record detection — beat your best weight on a lift and you get +50 EXP and a trophy notification
- Miss a scheduled workout and lose 30 EXP (idempotent — checked once per day on dashboard load)
- Rest timer built into the workout modal (60s / 90s / 2 min)
- Workout history — last 30 days of logged sessions

**Tracking**
- Diet tracker: search the food database to autofill macros, or type them manually. Macro donut chart and AI weekly analysis
- Lifestyle: water intake (tap-to-log cups), sleep hours and quality, daily energy
- Statistics: weight, BMI, water, and sleep charts over 60 days
- Profile page: lifetime stats, achievements, body weight progress, and full routine version history

**Customisation**
- Two-colour accent theme (pick any two colours, light or dark mode)
- Animated dust-waves background on every page, or choose a preset gradient wallpaper (aurora, nebula, mesh, sunset, forest, ocean), paste a custom image URL, or go plain

**Auth**
- Sign up with email + password, or username + 4-digit PIN
- Accounts locked for 15 minutes after 5 failed attempts (makes the short PIN safe)
- Each user's data is completely private

---

## Tech stack

| Layer | What |
|---|---|
| Backend | Python 3.12, Flask 3.0 |
| Database | Supabase (Postgres + custom auth) |
| AI | Gemini 2.5 Flash via REST |
| Deployment | Render (gunicorn, single worker) |
| Frontend | Server-rendered Jinja2, vanilla JS |
| PWA | Web manifest + service worker (installable on iPhone) |

---

## Project structure

```
app.py                  — all routes: auth, pages, AI, EXP, evolution
lib/
  auth.py               — hashing (PBKDF2), validation, lockout logic
  supabase_client.py    — service-role Supabase client
  gemini.py             — Gemini 2.5 Flash REST wrapper
  exp.py                — EXP scoring engine (pure functions)
  tips.py               — static form tips (zero API cost)
templates/              — 16 Jinja2 templates
static/
  css/style.css         — dark-minimal theme, animations
  manifest.json         — PWA manifest
  sw.js                 — service worker
```

---

## Running locally

```bash
git clone https://github.com/Jaidev-2122/FitForge.git
cd FitForge

python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# Fill in FLASK_SECRET_KEY, SUPABASE_SERVICE_KEY, GEMINI_API_KEY

FITFORGE_ALLOW_DEV_SECRET=1 flask --app app run --debug
# Open http://localhost:5000
```

---

## Deploying to Render

1. Push repo to GitHub
2. Render → **New → Web Service** → connect repo
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn app:app --workers 1 --threads 4 --timeout 120`
5. Add environment variables:

| Variable | Where to get it |
|---|---|
| `FLASK_SECRET_KEY` | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `SUPABASE_URL` | Supabase dashboard → Settings → API |
| `SUPABASE_SERVICE_KEY` | Supabase dashboard → Settings → API → service_role |
| `GEMINI_API_KEY` | aistudio.google.com/apikey |

> `--workers 1` is required on the free tier. Multiple workers cause out-of-memory crashes during the AI onboarding step.

---

## Installing as a mobile app

FitForge is a Progressive Web App — no App Store needed.

**iPhone:** Safari → Share button → **Add to Home Screen**

**Android:** Chrome → three-dot menu → **Add to Home screen**

---

## Security

- Passwords and PINs hashed with PBKDF2 via Werkzeug — plaintext never stored
- 5-attempt lockout makes the 4-digit PIN safe against guessing — do not remove this
- Supabase service-role key stays server-side only
- Every query scoped to the logged-in user's ID
- `FLASK_SECRET_KEY` is required — app refuses to start without it in production
- `.env` is gitignored — never commit secrets

---

## Not built yet

- CSRF protection on forms
- Password reset via email
- Open Food Facts integration
- Body measurements tracking
- Server-side chat history
- Weekly email summary
- CSV data export

---

## Built by

Jaidev — systems-oriented builder working toward AI Systems Engineering.
Built as a learning exercise in AI integration, full-stack Python, and product thinking.
