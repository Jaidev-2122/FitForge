"""FitForge — multi-user AI fitness tracker.

Sign up with email+password or username+4-digit PIN, take the quiz, and your
AI plan is built. Each user's data is fully separated. Stored in Supabase via
the service-role key (server-side only); every query is scoped to the logged-in
user. AI features (Gemini 2.5 Flash): routine generation, evolution,
ask-trainer chat, motivation, and proactive weekly analysis. Form tips are
static. Food logging is manual with optional autofill from the food database.
"""
import os
import json
from datetime import date, timedelta, datetime
from functools import wraps

from dotenv import load_dotenv
from flask import (Flask, render_template, request, redirect, url_for,
                   jsonify, session, flash)

from lib.supabase_client import db
from lib.gemini import generate, parse_json
from lib.exp import calculate_exp, calc_bmi
from lib.tips import tips_for, TIPS
from lib import auth

load_dotenv()

app = Flask(__name__)
_secret = os.environ.get("FLASK_SECRET_KEY")
if not _secret:
    if os.environ.get("FITFORGE_ALLOW_DEV_SECRET") == "1":
        _secret = "dev-only-insecure-key"  # local development only
    else:
        raise RuntimeError(
            "FLASK_SECRET_KEY is not set. Add it to your environment variables "
            "(or set FITFORGE_ALLOW_DEV_SECRET=1 for local development only).")
app.secret_key = _secret

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def known_exercises_text():
    """Compact exercise list for AI prompts from the live database, grouped by
    category, with focus tags (flexibility/mobility/cardio) so the AI can
    program stretches and posture work — not just lifts."""
    try:
        rows = db().table("exercises").select("name,category,focus").order("category").execute().data
        by_cat = {}
        for r in rows:
            focus = r.get("focus") or "strength"
            tag = f" [{focus}]" if focus != "strength" else ""
            by_cat.setdefault(r.get("category") or "Other", []).append(r["name"] + tag)
        return "\n".join(f"{cat}: {', '.join(names)}" for cat, names in by_cat.items())
    except Exception:
        return ("Chest: Bench Press, Push-ups | Back: Barbell Row, Pull-ups | "
                "Thighs: Barbell Squat | Glutes: Romanian Deadlift | "
                "Shoulders: Overhead Press | Arms: Dumbbell Curl | Core: Plank")


# ----------------------------- helpers -----------------------------
def uid():
    """The logged-in user's id, or None."""
    return session.get("user_id")


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not uid():
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def today_str():
    return date.today().isoformat()


def first_row(query):
    """Run a query and return the first row, or None. Avoids the client's
    single-row helper which can raise when no row exists."""
    rows = query.execute().data
    return rows[0] if rows else None


def _norm_name(name):
    """Normalize an exercise name for matching: lowercase, drop any
    parenthetical or [focus] tag, strip whitespace."""
    if not name:
        return ""
    base = name.split("(")[0].split("[")[0]
    return base.strip().lower()


def build_user_context(deep=False):
    """Compact snapshot of the user's real data for AI calls.

    Kept lean by default (balanced token cost). `deep=True` adds 7-day logs
    for the proactive-coach analysis where richer context is worth it.
    """
    d = db()
    p = get_profile() or {}
    ans = p.get("onboarding_answers") or {}
    ctx = {
        "name": p.get("display_name"),
        "goal": ans.get("goal"),
        "experience": ans.get("history"),
        "equipment": ans.get("equipment"),
        "days_per_week": ans.get("days_per_week"),
        "injuries": ans.get("injuries"),
        "stage": p.get("calibration_stage"),
        "streak": p.get("current_streak"),
        "total_exp": p.get("total_exp"),
    }
    # latest weight + today's lifestyle (cheap single rows)
    bw = first_row(d.table("body_stats").select("weight_kg,bmi")
                   .eq("user_id", uid()).order("log_date", desc=True).limit(1))
    if bw:
        ctx["latest_weight_kg"] = bw.get("weight_kg")
        ctx["bmi"] = bw.get("bmi")
    today_life = first_row(d.table("lifestyle_logs").select("water_glasses,sleep_hours,energy_level")
                           .eq("user_id", uid()).eq("log_date", today_str()))
    if today_life:
        ctx["today_water_glasses"] = today_life.get("water_glasses")
        ctx["today_sleep_hours"] = today_life.get("sleep_hours")
        ctx["today_energy"] = today_life.get("energy_level")

    # Personal records + lifetime volume, so the coach can answer
    # "what's my bench PR" / "how many sessions have I done" precisely.
    try:
        logs = (d.table("workout_logs")
                .select("weight_used_kg,logged_date,day_exercise:day_exercises(exercise:exercises(name))")
                .eq("user_id", uid()).order("weight_used_kg", desc=True).limit(200).execute().data)
        ctx["total_logged_sets"] = len(logs)
        ctx["workout_days_count"] = len({l.get("logged_date") for l in logs if l.get("logged_date")})
        prs = {}
        for l in logs:
            de = l.get("day_exercise") or {}
            if isinstance(de, list):
                de = de[0] if de else {}
            ex = (de or {}).get("exercise") or {}
            if isinstance(ex, list):
                ex = ex[0] if ex else {}
            nm = ex.get("name")
            w = l.get("weight_used_kg") or 0
            if nm and w and (nm not in prs or w > prs[nm]):
                prs[nm] = w
        if prs:
            top = sorted(prs.items(), key=lambda kv: -kv[1])[:8]
            ctx["personal_records_kg"] = dict(top)
    except Exception:
        pass

    if deep:
        since = (date.today() - timedelta(days=7)).isoformat()
        ctx["workouts_7d"] = (d.table("workout_logs")
                              .select("logged_date,completed,sets_done,weight_used_kg")
                              .eq("user_id", uid()).gte("logged_date", since).execute().data)
        ctx["lifestyle_7d"] = (d.table("lifestyle_logs")
                               .select("log_date,water_glasses,sleep_hours,energy_level")
                               .eq("user_id", uid()).gte("log_date", since).execute().data)
    return ctx


def get_profile():
    if not uid():
        return None
    return first_row(db().table("profiles").select("*").eq("id", uid()))


def apply_missed_workout_penalty():
    """If yesterday was a scheduled (non-rest) workout day and nothing was
    logged, deduct EXP once. Idempotent: tagged in exp_events so it won't
    double-charge if the dashboard is opened multiple times."""
    d = db()
    profile = get_profile()
    if not profile:
        return
    yesterday = (date.today() - timedelta(days=1))
    y_iso = yesterday.isoformat()
    tag = f"missed:{y_iso}"

    # Already penalised for yesterday?
    existing = d.table("exp_events").select("id").eq("user_id", uid()).eq("reason", tag).execute().data
    if existing:
        return

    routine = first_row(d.table("routines").select("id").eq("user_id", uid()).eq("is_active", True))
    if not routine:
        return
    y_day = first_row(d.table("workout_days").select("is_rest")
                      .eq("routine_id", routine["id"]).eq("day_of_week", yesterday.weekday()))
    if not y_day or y_day.get("is_rest"):
        return  # not a scheduled training day

    logged = d.table("workout_logs").select("id").eq("user_id", uid()).eq("logged_date", y_iso).execute().data
    if logged:
        return  # they trained, no penalty

    penalty = -30
    new_total = max(0, (profile.get("total_exp") or 0) + penalty)
    d.table("exp_events").insert({
        "user_id": uid(), "delta": penalty, "reason": tag, "running_total": new_total,
    }).execute()
    d.table("profiles").update({"total_exp": new_total}).eq("id", uid()).execute()


def onboarding_required(f):
    """Require login, then require completed onboarding."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not uid():
            return redirect(url_for("login"))
        p = get_profile()
        if not p or not p.get("onboarding_done"):
            return redirect(url_for("welcome"))
        return f(*args, **kwargs)
    return wrapper


def rate_limited(bucket, limit, window_seconds=3600):
    """Simple per-session sliding-window limiter. Returns True if over limit."""
    import time
    now = time.time()
    key = f"rl_{bucket}"
    hits = [t for t in session.get(key, []) if t > now - window_seconds]
    if len(hits) >= limit:
        session[key] = hits
        return True
    hits.append(now)
    session[key] = hits
    return False


@app.context_processor
def inject_shell():
    try:
        p = get_profile()
        if p and p.get("onboarding_done"):
            return {"shell": p, "active_path": request.path}
    except Exception:
        pass
    return {}


# ----------------------------- welcome + onboarding -----------------------------
@app.route("/")
def index():
    if not uid():
        return redirect(url_for("login"))
    p = get_profile()
    if p and p.get("onboarding_done"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("welcome"))


@app.route("/welcome")
@login_required
def welcome():
    p = get_profile()
    if p and p.get("onboarding_done"):
        return redirect(url_for("dashboard"))
    return render_template("welcome.html")


@app.route("/onboarding/complete", methods=["POST"])
@login_required
def onboarding_complete():
    answers = request.get_json(silent=True) or {}
    d = db()
    try:
        height = float(answers.get("height_cm") or 0)
        weight = float(answers.get("weight_kg") or 0)

        # Reset any prior data so re-taking the quiz starts clean.
        for tbl in ("exp_events", "workout_logs", "food_logs", "diet_feedback",
                    "diet_targets", "lifestyle_logs", "body_stats"):
            d.table(tbl).delete().eq("user_id", uid()).execute()
        # Remove old routines (cascades to days + day_exercises).
        d.table("routines").delete().eq("user_id", uid()).execute()

        d.table("profiles").update({
            "display_name": answers.get("name"),
            "age": int(answers.get("age") or 0) or None,
            "biological_sex": answers.get("biological_sex") or None,
            "height_cm": height or None,
            "country": answers.get("country") or None,
            "onboarding_answers": answers,
            "total_exp": 0, "current_streak": 0, "longest_streak": 0,
            "calibration_stage": "pilot", "last_workout_date": None,
        }).eq("id", uid()).execute()

        if weight:
            d.table("body_stats").insert({
                "user_id": uid(), "weight_kg": weight, "bmi": calc_bmi(weight, height),
            }).execute()

        # AI: build the pilot routine
        system = (
            "You are an elite strength coach designing a genuinely individualised week-1 plan. "
            "TAILOR HARD to this specific person — do not output a generic template. "
            "Note: some answers are arrays because the user could pick multiple options "
            "(e.g. target_areas, posture_issues) — honour ALL selected values. Concretely:\n"
            "- Match training days to exactly how many days they said they can commit.\n"
            "- Match session length to their stated time per session (fewer/shorter sessions = fewer exercises).\n"
            "- Pick exercises that fit their equipment (don't program barbell lifts for bodyweight-only).\n"
            "- Respect injuries: never program a movement that loads a stated injury.\n"
            "- Bias exercise selection and volume toward their goal (fat loss = more compound + conditioning; "
            "muscle = more sets near failure; general = balanced).\n"
            "- Scale starting load to their experience: a true beginner starts very light / bodyweight; "
            "an experienced lifter can handle real working weights.\n"
            "Weave in flexibility/mobility/posture work where the answers call for it (desk job, posture issues, poor flexibility, stated stretch goals) — e.g. finish sessions with 1-2 [flexibility] picks, use [mobility] items as warm-ups. It is still their PILOT WEEK, so set targets ~15% below their likely ceiling — but the plan should "
            "still feel clearly built FOR THEM. In ai_summary, explain in 2-3 sentences WHY this plan fits THIS person "
            "(name their goal, days, and one specific choice you made for them).\n"
            "Output strict JSON only. Schema: {\"ai_summary\": str, \"exp_gate\": int (800-1500), "
            "\"days\": [{\"day_of_week\": 0-6, \"label\": str, \"is_rest\": bool, \"est_duration_min\": int, "
            "\"exercises\": [{\"name\": str, \"target_sets\": int, \"target_reps\": int, \"target_weight_kg\": number-or-null}]}]}. "
            "Use ONLY exercises from this categorized library (the name in each entry must match EXACTLY, "
            "without the equipment in parentheses). Draw from multiple categories for balance:\n"
            f"{known_exercises_text()}\n"
            "Build exactly 7 day entries (0=Mon..6=Sun), with rest days placed sensibly around their training days."
        )
        raw = generate(system=system,
                       parts=[{"text": f"Build the week for this person:\n{json.dumps(answers, indent=2)}"}],
                       json_mode=True, temperature=0.7)
        routine = parse_json(raw)

        new_routine = d.table("routines").insert({
            "user_id": uid(), "version": 1, "is_active": True,
            "ai_summary": routine.get("ai_summary"), "exp_gate": routine.get("exp_gate", 1000),
        }).execute().data[0]
        d.table("profiles").update({"exp_to_next": routine.get("exp_gate", 1000)}).eq("id", uid()).execute()

        ex_rows = d.table("exercises").select("id,name").execute().data
        ex_map = {_norm_name(e["name"]): e["id"] for e in ex_rows}
        for day in routine.get("days", []):
            wd = d.table("workout_days").insert({
                "routine_id": new_routine["id"], "day_of_week": day["day_of_week"],
                "label": day["label"], "is_rest": day.get("is_rest", False),
                "est_duration_min": day.get("est_duration_min", 45),
            }).execute().data[0]
            if day.get("is_rest"):
                continue
            rows = []
            for i, ex in enumerate(day.get("exercises", [])):
                ex_id = ex_map.get(_norm_name(ex["name"]))
                if ex_id:
                    rows.append({"workout_day_id": wd["id"], "exercise_id": ex_id,
                                 "target_sets": ex.get("target_sets", 3), "target_reps": ex.get("target_reps", 10),
                                 "target_weight_kg": ex.get("target_weight_kg"), "order_index": i})
            if rows:
                d.table("day_exercises").insert(rows).execute()

        # Nutrition brief is generated by the separate /onboarding/diet call
        # afterwards — keeping THIS request to a single Gemini call avoids the
        # free-tier out-of-memory worker kill.

        d.table("profiles").update({"onboarding_done": True}).eq("id", uid()).execute()
        return jsonify({"ok": True, "needs_diet": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/onboarding/diet", methods=["POST"])
@login_required
def onboarding_diet():
    """Generate the nutrition brief separately after the main onboarding
    completes. Keeps the main onboarding request lean and avoids OOM kills."""
    answers = request.get_json(silent=True) or {}
    diet_system = (
        "You are a sports nutritionist. Produce daily targets and cheap, "
        "locally-available food ideas for the user's country. "
        "Output strict JSON: {\"kcal_target\": int, \"protein_g_target\": int, "
        "\"carbs_g_target\": int, \"fat_g_target\": int, \"water_ml_target\": int, "
        "\"sleep_hrs_target\": number, "
        "\"food_ideas\": [{\"name\": str, \"why\": str}] (6-8 items)}."
    )
    try:
        draw = generate(system=diet_system,
                        parts=[{"text": json.dumps(answers, indent=2)}],
                        json_mode=True, temperature=0.5)
        diet = parse_json(draw)
        db().table("diet_targets").insert({
            "user_id": uid(),
            "kcal_target": diet.get("kcal_target"),
            "protein_g_target": diet.get("protein_g_target"),
            "carbs_g_target": diet.get("carbs_g_target"),
            "fat_g_target": diet.get("fat_g_target"),
            "water_ml_target": diet.get("water_ml_target"),
            "sleep_hrs_target": diet.get("sleep_hrs_target"),
            "food_ideas": diet.get("food_ideas", []),
        }).execute()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/reset", methods=["POST"])
@login_required
def reset():
    """Start over — re-take the quiz (keeps the account, clears the plan)."""
    db().table("profiles").update({"onboarding_done": False}).eq("id", uid()).execute()
    return redirect(url_for("welcome"))


# ----------------------------- auth -----------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if uid():
        return redirect(url_for("index"))
    if request.method == "POST":
        identifier = request.form.get("identifier", "")
        credential = request.form.get("credential", "")
        user_id, err = auth.authenticate(db(), identifier=identifier, credential=credential)
        if err:
            flash(err)
            return render_template("login.html", mode="login")
        session.clear()
        session["user_id"] = user_id
        session.permanent = True
        return redirect(url_for("index"))
    return render_template("login.html", mode="login")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if uid():
        return redirect(url_for("index"))
    if request.method == "POST":
        method = request.form.get("method", "email")
        if method == "pin":
            username = request.form.get("username", "")
            pin = request.form.get("pin", "")
            ok, result = auth.validate_pin_signup(username, pin)
            if not ok:
                flash(result)
                return render_template("login.html", mode="signup")
            user_id, err = auth.create_user(db(), auth_type="pin",
                                             credential=pin, username=result)
        else:
            email = request.form.get("email", "")
            password = request.form.get("password", "")
            ok, result = auth.validate_email_signup(email, password)
            if not ok:
                flash(result)
                return render_template("login.html", mode="signup")
            user_id, err = auth.create_user(db(), auth_type="email",
                                             credential=password, email=result)
        if err:
            flash(err)
            return render_template("login.html", mode="signup")
        session.clear()
        session["user_id"] = user_id
        session.permanent = True
        return redirect(url_for("welcome"))
    return render_template("login.html", mode="signup")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ----------------------------- dashboard -----------------------------
@app.route("/dashboard")
@onboarding_required
def dashboard():
    d = db()
    try:
        apply_missed_workout_penalty()
    except Exception as e:
        app.logger.error(f"missed-penalty skipped: {e}")
    profile = get_profile()
    routine = first_row(d.table("routines").select("id,version,ai_summary")
                        .eq("user_id", uid()).eq("is_active", True))
    days = []
    if routine:
        days = (d.table("workout_days").select("day_of_week,label,is_rest")
                .eq("routine_id", routine["id"]).order("day_of_week").execute().data)
    today_idx = datetime.now().weekday()
    today_day = next((x for x in days if x["day_of_week"] == today_idx), None)

    since = (date.today() - timedelta(days=7)).isoformat()
    week_logs = (d.table("workout_logs").select("logged_date,completed")
                 .eq("user_id", uid()).gte("logged_date", since).execute().data)
    done_dates = {l["logged_date"] for l in week_logs if l["completed"]}

    week = []
    for i, name in enumerate(DAY_NAMES):
        day = next((x for x in days if x["day_of_week"] == i), None)
        week.append({"name": name[:3], "label": (day or {}).get("label", "—"),
                     "is_rest": (day or {}).get("is_rest", False), "is_today": i == today_idx})

    return render_template("dashboard.html", profile=profile, routine=routine,
                           today_day=today_day, week=week, completed_week=len(done_dates))


# ----------------------------- workout -----------------------------
@app.route("/workout")
@onboarding_required
def workout():
    d = db()
    routine = first_row(d.table("routines").select("id").eq("user_id", uid())
                        .eq("is_active", True))
    today_idx = datetime.now().weekday()
    day = None
    if routine:
        day = first_row(d.table("workout_days").select("id,label,is_rest,est_duration_min")
                        .eq("routine_id", routine["id"]).eq("day_of_week", today_idx))
    exercises, done_ids = [], set()
    if day and not day["is_rest"]:
        exercises = (d.table("day_exercises").select("*, exercise:exercises(*)")
                     .eq("workout_day_id", day["id"]).order("order_index").execute().data)
        logs = (d.table("workout_logs").select("day_exercise_id")
                .eq("user_id", uid()).eq("logged_date", today_str()).eq("completed", True).execute().data)
        done_ids = {l["day_exercise_id"] for l in logs}
    return render_template("workout.html", day=day, exercises=exercises, done_ids=done_ids, tips=TIPS)


@app.route("/workout/log", methods=["POST"])
@onboarding_required
def workout_log():
    d = db()
    de_id = request.form.get("day_exercise_id")
    sets_done = int(request.form.get("sets") or 0)
    reps_done = int(request.form.get("reps") or 0)
    weight = float(request.form.get("weight") or 0)

    de = (d.table("day_exercises").select("*, exercise:exercises(is_compound), workout_day:workout_days(routine_id)")
          .eq("id", de_id).single().execute().data)
    profile = get_profile()

    # Verify this day_exercise belongs to the logged-in user's routine.
    wd = de.get("workout_day") or {}
    routine_id = wd.get("routine_id") if isinstance(wd, dict) else (wd[0].get("routine_id") if wd else None)
    owns = False
    if routine_id:
        owner = first_row(d.table("routines").select("id").eq("id", routine_id).eq("user_id", uid()))
        owns = owner is not None
    if not owns:
        return redirect(url_for("workout"))  # silently ignore foreign/forged ids

    is_compound = bool((de.get("exercise") or {}).get("is_compound"))
    target_w = de.get("target_weight_kg") or 0
    beat = weight > target_w if target_w else False

    streak = profile.get("current_streak") or 0
    last = profile.get("last_workout_date")
    t = date.today()
    if last == t.isoformat():
        pass
    elif last == (t - timedelta(days=1)).isoformat():
        streak += 1
    else:
        streak = 1
    longest = max(profile.get("longest_streak") or 0, streak)

    # Personal record: did they beat their best-ever weight on THIS exercise?
    prev_best = first_row(d.table("workout_logs").select("weight_used_kg")
                          .eq("user_id", uid()).eq("day_exercise_id", de_id)
                          .order("weight_used_kg", desc=True).limit(1))
    prev_best_w = (prev_best or {}).get("weight_used_kg") or 0
    is_pr = weight > prev_best_w and weight > 0

    delta, reasons = calculate_exp(True, is_compound, sets_done, beat, streak)
    if is_pr:
        delta += 50
        reasons.append(f"New PR: {weight}kg")
    new_total = (profile.get("total_exp") or 0) + delta

    d.table("workout_logs").insert({
        "user_id": uid(), "day_exercise_id": de_id, "sets_done": sets_done,
        "reps_done": reps_done, "weight_used_kg": weight, "completed": True,
    }).execute()
    d.table("exp_events").insert({
        "user_id": uid(), "delta": delta, "reason": ", ".join(reasons), "running_total": new_total,
    }).execute()
    d.table("profiles").update({
        "total_exp": new_total, "current_streak": streak, "longest_streak": longest,
        "last_workout_date": t.isoformat(),
    }).eq("id", uid()).execute()
    if is_pr:
        flash(f"🏆 New personal record: {weight}kg! (+50 EXP)")
    return redirect(url_for("workout"))


# ----------------------------- workout history -----------------------------
@app.route("/history")
@onboarding_required
def history():
    d = db()
    since = (date.today() - timedelta(days=30)).isoformat()
    logs = (d.table("workout_logs")
            .select("logged_date,sets_done,reps_done,weight_used_kg,"
                    "day_exercise:day_exercises(exercise:exercises(name,category))")
            .eq("user_id", uid()).gte("logged_date", since)
            .order("logged_date", desc=True).execute().data)
    # Group by date, newest first, flattening the nested exercise name.
    grouped = {}
    for l in logs:
        de = l.get("day_exercise") or {}
        if isinstance(de, list):
            de = de[0] if de else {}
        ex = (de or {}).get("exercise") or {}
        if isinstance(ex, list):
            ex = ex[0] if ex else {}
        grouped.setdefault(l["logged_date"], []).append({
            "name": ex.get("name", "Exercise"),
            "category": ex.get("category"),
            "sets": l.get("sets_done"), "reps": l.get("reps_done"),
            "weight": l.get("weight_used_kg"),
        })
    days = [{"date": k, "entries": v} for k, v in grouped.items()]
    return render_template("history.html", days=days)


# ----------------------------- planner + evolution -----------------------------
@app.route("/planner")
@onboarding_required
def planner():
    d = db()
    profile = get_profile()
    routine = first_row(d.table("routines").select("id,version,ai_summary,evolution_reason")
                        .eq("user_id", uid()).eq("is_active", True))
    days = []
    if routine:
        raw_days = (d.table("workout_days").select("id,day_of_week,label,is_rest,est_duration_min")
                    .eq("routine_id", routine["id"]).order("day_of_week").execute().data)
        for dd in raw_days:
            names = []
            if not dd["is_rest"]:
                ex = (d.table("day_exercises").select("exercise:exercises(name)")
                      .eq("workout_day_id", dd["id"]).order("order_index").execute().data)
                for e in ex:
                    rel = e.get("exercise")
                    if isinstance(rel, list):
                        rel = rel[0] if rel else None
                    if rel:
                        names.append(rel["name"])
            days.append({"name": DAY_NAMES[dd["day_of_week"]], "label": dd["label"],
                         "is_rest": dd["is_rest"], "duration": dd["est_duration_min"], "exercises": names})
    return render_template("planner.html", profile=profile, routine=routine, days=days)


@app.route("/planner/evolve", methods=["POST"])
@onboarding_required
def planner_evolve():
    d = db()
    profile = get_profile()
    if (profile.get("total_exp") or 0) < (profile.get("exp_to_next") or 1000):
        return jsonify({"evolved": False, "reason": "EXP gate not reached yet."})

    active = first_row(d.table("routines").select("id,version").eq("user_id", uid())
                       .eq("is_active", True))
    logs = (d.table("workout_logs")
            .select("logged_date,sets_done,reps_done,weight_used_kg,difficulty_felt,completed")
            .eq("user_id", uid()).order("logged_date", desc=True).limit(60).execute().data)

    system = (
        "You are an expert coach evolving a user's routine to the next stage. Analyse logged performance: "
        "progressively overload where they succeed, regress where they struggled. The user has passed the pilot week. "
        "Output strict JSON only: {\"ai_summary\": str, \"evolution_reason\": str, \"exp_gate\": int (higher than before), "
        "\"days\": [{\"day_of_week\":0-6,\"label\":str,\"is_rest\":bool,\"est_duration_min\":int,"
        "\"exercises\":[{\"name\":str,\"target_sets\":int,\"target_reps\":int,\"target_weight_kg\":number-or-null}]}]}. "
        f"Use ONLY exercises from this categorized library (match the name EXACTLY, without the "
        f"equipment in parentheses):\n{known_exercises_text()}\nBuild exactly 7 day entries."
    )
    try:
        raw = generate(system=system, parts=[{"text":
            f"Profile goal/answers: {json.dumps(profile.get('onboarding_answers'))}\n"
            f"Stage: {profile.get('calibration_stage')}  Streak: {profile.get('current_streak')}\n"
            f"Recent logs (newest first):\n{json.dumps(logs, indent=2)}"}],
            json_mode=True, temperature=0.6)
        evolved = parse_json(raw)
    except Exception as e:
        return jsonify({"evolved": False, "error": str(e)}), 500

    new_version = (active["version"] if active else 1) + 1
    if active:
        d.table("routines").update({"is_active": False}).eq("id", active["id"]).execute()
    new_routine = d.table("routines").insert({
        "user_id": uid(), "version": new_version, "is_active": True,
        "ai_summary": evolved.get("ai_summary"), "evolution_reason": evolved.get("evolution_reason"),
        "exp_gate": evolved.get("exp_gate", 1500),
    }).execute().data[0]

    ex_rows = d.table("exercises").select("id,name").execute().data
    ex_map = {_norm_name(e["name"]): e["id"] for e in ex_rows}
    for day in evolved.get("days", []):
        wd = d.table("workout_days").insert({
            "routine_id": new_routine["id"], "day_of_week": day["day_of_week"], "label": day["label"],
            "is_rest": day.get("is_rest", False), "est_duration_min": day.get("est_duration_min", 45),
        }).execute().data[0]
        if day.get("is_rest"):
            continue
        rows = []
        for i, ex in enumerate(day.get("exercises", [])):
            ex_id = ex_map.get(_norm_name(ex["name"]))
            if ex_id:
                rows.append({"workout_day_id": wd["id"], "exercise_id": ex_id,
                             "target_sets": ex.get("target_sets", 3), "target_reps": ex.get("target_reps", 10),
                             "target_weight_kg": ex.get("target_weight_kg"), "order_index": i})
        if rows:
            d.table("day_exercises").insert(rows).execute()

    next_stage = "calibrating" if profile.get("calibration_stage") == "pilot" else "established"
    d.table("profiles").update({
        "exp_to_next": (profile.get("total_exp") or 0) + evolved.get("exp_gate", 1500),
        "calibration_stage": next_stage,
    }).eq("id", uid()).execute()
    return jsonify({"evolved": True, "version": new_version,
                    "summary": evolved.get("ai_summary"), "reason": evolved.get("evolution_reason")})


# ----------------------------- statistics -----------------------------
@app.route("/statistics")
@onboarding_required
def statistics():
    d = db()
    since = (date.today() - timedelta(days=60)).isoformat()
    body = (d.table("body_stats").select("log_date,weight_kg,bmi")
            .eq("user_id", uid()).gte("log_date", since).order("log_date").execute().data)
    life = (d.table("lifestyle_logs").select("log_date,water_glasses,sleep_hours")
            .eq("user_id", uid()).gte("log_date", since).order("log_date").execute().data)
    return render_template("statistics.html", body=json.dumps(body), life=json.dumps(life),
                           has_body=len(body) > 0, has_life=len(life) > 0)


@app.route("/statistics/weight", methods=["POST"])
@onboarding_required
def statistics_weight():
    d = db()
    w = float(request.form.get("weight") or 0)
    if w:
        prof = get_profile()
        d.table("body_stats").insert({
            "user_id": uid(), "weight_kg": w, "bmi": calc_bmi(w, prof.get("height_cm") or 0),
        }).execute()
    return redirect(url_for("statistics"))


# ----------------------------- lifestyle -----------------------------
@app.route("/lifestyle")
@onboarding_required
def lifestyle():
    d = db()
    log = first_row(d.table("lifestyle_logs").select("*")
                    .eq("user_id", uid()).eq("log_date", today_str())) or {}
    target = first_row(d.table("diet_targets").select("water_ml_target,sleep_hrs_target")
                       .eq("user_id", uid()).order("set_at", desc=True).limit(1)) or {}
    water_goal = round((target.get("water_ml_target") or 2000) / 250)
    return render_template("lifestyle.html", log=log, water_goal=water_goal,
                           sleep_goal=target.get("sleep_hrs_target") or 8)


@app.route("/lifestyle/save", methods=["POST"])
@onboarding_required
def lifestyle_save():
    db().table("lifestyle_logs").upsert({
        "user_id": uid(), "log_date": today_str(),
        "water_glasses": int(request.form.get("water") or 0),
        "sleep_hours": float(request.form.get("sleep") or 0),
        "sleep_quality": request.form.get("quality") or None,
        "energy_level": int(request.form.get("energy") or 3),
    }, on_conflict="user_id,log_date").execute()
    return redirect(url_for("lifestyle"))


# ----------------------------- diet (manual + DB autofill) -----------------------------
@app.route("/diet")
@onboarding_required
def diet():
    d = db()
    logs = (d.table("food_logs").select("*")
            .eq("user_id", uid()).eq("log_date", today_str()).order("created_at").execute().data)
    target = first_row(d.table("diet_targets").select("*")
                       .eq("user_id", uid()).order("set_at", desc=True).limit(1))
    totals = {"kcal": 0, "protein": 0, "carbs": 0, "fat": 0}
    for l in logs:
        totals["kcal"] += l.get("kcal") or 0
        totals["protein"] += l.get("protein_g") or 0
        totals["carbs"] += l.get("carbs_g") or 0
        totals["fat"] += l.get("fat_g") or 0
    totals = {k: round(v) for k, v in totals.items()}
    return render_template("diet.html", logs=logs, target=target, totals=totals)


@app.route("/diet/search")
@onboarding_required
def diet_search():
    """Autofill helper — returns per-100g macros for matching foods."""
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])
    rows = (db().table("food_items")
            .select("id,name,kcal_per_100g,protein_g,carbs_g,fat_g")
            .ilike("name", f"%{q}%").limit(8).execute().data)
    return jsonify(rows)


@app.route("/diet/log", methods=["POST"])
@onboarding_required
def diet_log():
    """Manual food entry. Macros typed directly (optionally pre-filled from search)."""
    db().table("food_logs").insert({
        "user_id": uid(), "log_date": today_str(),
        "meal_type": request.form.get("meal_type") or "snack",
        "custom_name": request.form.get("name") or "Food",
        "quantity_g": float(request.form.get("grams") or 0) or None,
        "kcal": float(request.form.get("kcal") or 0),
        "protein_g": float(request.form.get("protein") or 0),
        "carbs_g": float(request.form.get("carbs") or 0),
        "fat_g": float(request.form.get("fat") or 0),
        "ai_identified": False,
    }).execute()
    return redirect(url_for("diet"))


@app.route("/diet/delete", methods=["POST"])
@onboarding_required
def diet_delete():
    db().table("food_logs").delete().eq("id", request.form.get("id")).eq("user_id", uid()).execute()
    return redirect(url_for("diet"))


# ----------------------------- library -----------------------------
@app.route("/library")
@onboarding_required
def library():
    rows = db().table("exercises").select("*").order("category").order("name").execute().data
    for r in rows:
        r["tips"] = tips_for(r["name"])
    # Stable, distinct colour per category (used for badges + filters).
    cat_colors = {
        "Chest": "#ff6b6b", "Back": "#4dabf7", "Shoulders": "#ffd43b",
        "Arms": "#da77f2", "Thighs": "#69db7c", "Glutes": "#ff922b",
        "Core": "#3bc9db", "Calves": "#a9e34b", "Posture": "#9775fa",
        "Cardio": "#ff8787", "Other": "#888888",
    }
    categories = sorted({r.get("category") for r in rows if r.get("category")})
    return render_template("library.html", exercises=rows,
                           categories=categories, cat_colors=cat_colors)


# ----------------------------- motivation -----------------------------
@app.route("/motivation")
@onboarding_required
def motivation():
    # Recent conversation so the chat picks up where it left off, any device.
    recent = (db().table("chat_history").select("role,content")
              .eq("user_id", uid()).order("created_at", desc=True).limit(20).execute().data)
    return render_template("motivation.html", profile=get_profile(),
                           chat_history=list(reversed(recent or [])))


# ----------------------------- profile -----------------------------
@app.route("/profile")
@onboarding_required
def profile_page():
    d = db()
    profile = get_profile()
    ans = profile.get("onboarding_answers") or {}

    # Totals / history
    total_workouts = len(d.table("workout_logs").select("id")
                         .eq("user_id", uid()).eq("completed", True).execute().data)
    routines = d.table("routines").select("version,created_at,ai_summary,evolution_reason") \
                .eq("user_id", uid()).order("version").execute().data
    weights = d.table("body_stats").select("log_date,weight_kg") \
               .eq("user_id", uid()).order("log_date").execute().data
    start_w = weights[0]["weight_kg"] if weights else None
    latest_w = weights[-1]["weight_kg"] if weights else None
    weight_delta = round((latest_w - start_w), 1) if (start_w and latest_w) else None

    # Achievements (computed, no AI)
    streak = profile.get("current_streak") or 0
    longest = profile.get("longest_streak") or 0
    total_exp = profile.get("total_exp") or 0
    achievements = [
        {"icon": "▶", "name": "First Workout", "earned": total_workouts >= 1, "desc": "Log your first session"},
        {"icon": "♦", "name": "10 Workouts", "earned": total_workouts >= 10, "desc": "Complete 10 sessions"},
        {"icon": "✦", "name": "Week Warrior", "earned": longest >= 7, "desc": "Hit a 7-day streak"},
        {"icon": "★", "name": "Evolved", "earned": len(routines) >= 2, "desc": "Reach your first routine evolution"},
        {"icon": "▲", "name": "1000 EXP", "earned": total_exp >= 1000, "desc": "Earn 1000 total EXP"},
        {"icon": "◆", "name": "Consistency", "earned": longest >= 21, "desc": "Hit a 21-day streak"},
    ]

    stats = {
        "total_workouts": total_workouts,
        "total_exp": total_exp,
        "streak": streak,
        "longest": longest,
        "routine_versions": len(routines),
        "start_weight": start_w,
        "latest_weight": latest_w,
        "weight_delta": weight_delta,
    }
    return render_template("profile.html", profile=profile, ans=ans, stats=stats,
                           achievements=achievements, routines=routines)


# ----------------------------- settings -----------------------------
@app.route("/settings")
@onboarding_required
def settings():
    return render_template("settings.html", profile=get_profile(),
                           presets=PRESET_BACKGROUNDS)


@app.route("/settings/theme", methods=["POST"])
@onboarding_required
def settings_theme():
    db().table("profiles").update({
        "theme_accent_1": request.form.get("accent1", "#c8f55a"),
        "theme_accent_2": request.form.get("accent2", "#5599ff"),
        "theme_mode": request.form.get("mode", "dark"),
    }).eq("id", uid()).execute()
    return redirect(url_for("settings"))


# Built-in animated/preset wallpapers the user can choose.
PRESET_BACKGROUNDS = ["aurora", "nebula", "mesh", "sunset", "forest", "ocean"]


@app.route("/settings/background", methods=["POST"])
@onboarding_required
def settings_background():
    bg_type = request.form.get("bg_type", "waves")
    bg_value = (request.form.get("bg_value") or request.form.get("bg_value_url") or "").strip()

    # Validate to avoid storing junk / unsafe values.
    if bg_type == "image":
        # only allow http(s) image URLs
        if not (bg_value.startswith("http://") or bg_value.startswith("https://")):
            flash("Please enter a valid image URL starting with http:// or https://")
            return redirect(url_for("settings"))
    elif bg_type == "preset":
        if bg_value not in PRESET_BACKGROUNDS:
            bg_value = PRESET_BACKGROUNDS[0]
    elif bg_type in ("waves", "none"):
        bg_value = None
    else:
        bg_type, bg_value = "waves", None

    db().table("profiles").update({"bg_type": bg_type, "bg_value": bg_value}).eq("id", uid()).execute()
    return redirect(url_for("settings"))


@app.route("/settings/music", methods=["POST"])
@onboarding_required
def settings_music():
    enabled = request.form.get("music_enabled") == "on"
    url = (request.form.get("music_url") or "").strip()
    if url and not (url.startswith("http://") or url.startswith("https://")):
        flash("Music URL must start with http:// or https:// (leave blank for built-in ambient).")
        return redirect(url_for("settings"))
    db().table("profiles").update({
        "music_enabled": enabled,
        "music_url": url or None,
    }).eq("id", uid()).execute()
    return redirect(url_for("settings"))


# ----------------------------- AI endpoints -----------------------------
@app.route("/api/chat", methods=["POST"])
@onboarding_required
def api_chat():
    if rate_limited("chat", 30):
        return jsonify({"error": "You're sending messages very fast — take a short break and try again."}), 429
    payload = request.get_json(silent=True) or {}
    # New contract: client sends just {message}. Backward-compat: if an older
    # cached frontend still sends {messages: [...]}, use its last user entry.
    message = (payload.get("message") or "").strip()
    if not message:
        legacy = [m for m in payload.get("messages", []) if m.get("role") == "user"]
        message = (legacy[-1]["content"].strip() if legacy else "")
    if not message:
        return jsonify({"error": "Empty message."}), 400
    if len(message) > 2000:
        message = message[:2000]
    # Ephemeral mode (daily motivation blurb): no history load, no save —
    # keeps canned prompts out of the user's real conversation memory.
    ephemeral = bool(payload.get("ephemeral"))

    d = db()
    history = []
    if not ephemeral:
        # Server-owned memory: history lives in the DB, not the client, so it
        # can't be forged and it persists across devices/sessions.
        history = (d.table("chat_history").select("role,content")
                   .eq("user_id", uid()).order("created_at", desc=True).limit(12).execute().data)
        history = list(reversed(history or []))

    ctx = build_user_context()
    system = (
        "You are FitForge's AI coach, talking directly to {name}. You are NOT a generic chatbot — "
        "you know this person's real data (shown below) and you reference it naturally, like a coach who "
        "remembers them. If they ask about their own stats (weight, BMI, PRs, streak, workout count), "
        "answer precisely from the data. Be warm, direct, and specific. Use their name occasionally, "
        "not every line. Ask a sharp follow-up question when it helps. Keep replies to 2-4 sentences, "
        "conversational, no markdown, no bullet lists, no corporate hedging. If they're slacking, gently "
        "challenge them; if they're crushing it, hype them up."
    ).format(name=ctx.get("name") or "the user")
    convo = "\n".join(f"{m['role']}: {m['content']}" for m in history)
    convo += ("\n" if convo else "") + f"user: {message}"
    try:
        reply = generate(system=system,
                         parts=[{"text": f"Here is everything you know about {ctx.get('name')}:\n"
                                         f"{json.dumps(ctx, indent=2)}\n\nConversation so far:\n{convo}"}],
                         temperature=0.85)
        # Persist both sides AFTER a successful generation, so a failed AI call
        # doesn't leave a one-sided exchange in history.
        if not ephemeral:
            d.table("chat_history").insert([
                {"user_id": uid(), "role": "user", "content": message},
                {"user_id": uid(), "role": "assistant", "content": reply},
            ]).execute()
        return jsonify({"reply": reply})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/analysis", methods=["POST"])
@onboarding_required
def api_analysis():
    """AI qualitative analysis of routine adherence, water, and food for today/this week."""
    if rate_limited("analysis", 15):
        return jsonify({"error": "Analysis is rate-limited. Try again shortly."}), 429
    d = db()
    profile = get_profile()
    since = (date.today() - timedelta(days=7)).isoformat()
    workouts = (d.table("workout_logs").select("logged_date,completed,sets_done,weight_used_kg")
                .eq("user_id", uid()).gte("logged_date", since).execute().data)
    life = (d.table("lifestyle_logs").select("log_date,water_glasses,sleep_hours,energy_level")
            .eq("user_id", uid()).gte("log_date", since).execute().data)
    food = (d.table("food_logs").select("log_date,kcal,protein_g,carbs_g,fat_g")
            .eq("user_id", uid()).gte("log_date", since).execute().data)
    target = first_row(d.table("diet_targets").select("kcal_target,protein_g_target,water_ml_target,sleep_hrs_target")
                       .eq("user_id", uid()).order("set_at", desc=True).limit(1))

    system = ("You are {name}'s proactive fitness coach reviewing their last 7 days. Don't just summarise — "
              "spot the PATTERN. Find the one connection they probably haven't noticed (e.g. 'your energy "
              "drops every day you sleep under 6h', or 'you've hit every workout but you're under your protein "
              "target all week'). Then give ONE specific action for the next 3 days. Warm, direct, a little "
              "challenging. 3-5 sentences, plain text, no lists. Reference real numbers from the data."
              ).format(name=(profile.get("display_name") or "the user"))
    try:
        text = generate(system=system, parts=[{"text": json.dumps({
            "name": profile.get("display_name"),
            "goal": profile.get("onboarding_answers", {}).get("goal"),
            "streak": profile.get("current_streak"),
            "workouts_7d": workouts, "lifestyle_7d": life, "food_7d": food, "targets": target,
        }, indent=2)}], temperature=0.7)
        return jsonify({"analysis": text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ----------------------------- error handlers -----------------------------
@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", code=404,
                           message="That page doesn't exist."), 404


@app.errorhandler(500)
def server_error(e):
    app.logger.error(f"500 error: {e}")
    return render_template("error.html", code=500,
                           message="Something went wrong on our end."), 500


# ----------------------------- PWA static routes -----------------------------
@app.route("/manifest.json")
def manifest():
    from flask import send_from_directory
    return send_from_directory("static", "manifest.json",
                               mimetype="application/manifest+json")


@app.route("/sw.js")
def service_worker():
    from flask import send_from_directory
    resp = send_from_directory("static", "sw.js",
                               mimetype="application/javascript")
    # Allow SW to control the whole origin, not just /static/
    resp.headers["Service-Worker-Allowed"] = "/"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


if __name__ == "__main__":
    app.run(debug=True, port=5000)
