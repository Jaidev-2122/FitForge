"""Authentication for FitForge — handled with care.

Supports two sign-up methods through one custom users table:
  - email + password
  - username + 4-digit PIN

Security measures:
  - Credentials are hashed with werkzeug (PBKDF2); plaintext is never stored.
  - Login is generic about failures ("invalid credentials") so it never reveals
    whether an account exists.
  - A dummy hash check runs when no user is found, to blunt timing attacks.
  - Lockout: after MAX_ATTEMPTS failures an account locks for LOCKOUT_MINUTES.
    This is what makes a 4-digit PIN safe against online guessing.
  - Input is validated (PIN exactly 4 digits, password >= 8 chars, username
    3-20 chars, basic email shape) before anything touches the database.
"""
import re
from datetime import datetime, timedelta, timezone

from werkzeug.security import generate_password_hash, check_password_hash

MAX_ATTEMPTS = 5
LOCKOUT_MINUTES = 15

# A precomputed dummy hash so "user not found" takes about as long as a real check.
_DUMMY_HASH = generate_password_hash("dummy-value-for-timing")

_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PIN_RE = re.compile(r"^\d{4}$")


# ----------------------------- hashing -----------------------------
def hash_credential(raw: str) -> str:
    return generate_password_hash(raw)


def verify_credential(stored_hash: str, raw: str) -> bool:
    return check_password_hash(stored_hash, raw)


# ----------------------------- validation -----------------------------
def validate_email_signup(email: str, password: str):
    email = (email or "").strip().lower()
    if not _EMAIL_RE.match(email):
        return False, "Please enter a valid email address."
    if len(password or "") < 8:
        return False, "Password must be at least 8 characters."
    return True, email


def validate_pin_signup(username: str, pin: str):
    username = (username or "").strip()
    if not _USERNAME_RE.match(username):
        return False, "Username must be 3-20 letters, numbers, or underscores."
    if not _PIN_RE.match(pin or ""):
        return False, "PIN must be exactly 4 digits."
    return True, username


# ----------------------------- signup -----------------------------
def create_user(db, *, auth_type: str, credential: str,
                email: str = None, username: str = None):
    """Create a users row + a blank profile. Returns (user_id, error)."""
    # Uniqueness checks
    if email:
        existing = db.table("users").select("id").eq("email", email).execute().data
        if existing:
            return None, "An account with that email already exists."
    if username:
        existing = db.table("users").select("id").eq("username", username).execute().data
        if existing:
            return None, "That username is taken."

    row = {
        "auth_type": auth_type,
        "credential_hash": hash_credential(credential),
        "email": email,
        "username": username,
    }
    user = db.table("users").insert(row).execute().data[0]
    # Matching profile row (same id)
    db.table("profiles").insert({
        "id": user["id"],
        "display_name": username or (email.split("@")[0] if email else None),
        "onboarding_done": False,
    }).execute()
    return user["id"], None


# ----------------------------- login -----------------------------
def _is_locked(user) -> bool:
    lu = user.get("locked_until")
    if not lu:
        return False
    try:
        when = datetime.fromisoformat(lu.replace("Z", "+00:00"))
    except Exception:
        return False
    return datetime.now(timezone.utc) < when


def authenticate(db, *, identifier: str, credential: str):
    """Verify credentials by email OR username. Returns (user_id, error).

    Applies lockout. Error messages are intentionally generic.
    """
    identifier = (identifier or "").strip()
    # Find by email (lowercased) or username
    user = None
    by_email = db.table("users").select("*").eq("email", identifier.lower()).execute().data
    if by_email:
        user = by_email[0]
    else:
        by_name = db.table("users").select("*").eq("username", identifier).execute().data
        if by_name:
            user = by_name[0]

    if not user:
        # Timing-safe dummy check, then fail generically.
        check_password_hash(_DUMMY_HASH, credential or "")
        return None, "Invalid credentials."

    if _is_locked(user):
        return None, "Too many attempts. Try again in a few minutes."

    if verify_credential(user["credential_hash"], credential or ""):
        # success — reset counters
        db.table("users").update({"failed_attempts": 0, "locked_until": None}) \
          .eq("id", user["id"]).execute()
        return user["id"], None

    # failure — increment, maybe lock
    attempts = (user.get("failed_attempts") or 0) + 1
    update = {"failed_attempts": attempts}
    if attempts >= MAX_ATTEMPTS:
        locked_until = datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_MINUTES)
        update["locked_until"] = locked_until.isoformat()
        update["failed_attempts"] = 0
    db.table("users").update(update).eq("id", user["id"]).execute()
    return None, "Invalid credentials."
