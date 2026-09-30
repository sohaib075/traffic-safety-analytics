"""Accounts and role-based auth.

* Passwords: PBKDF2-SHA256 (200k iterations) with per-user salt, plus a password policy.
* Sessions: HMAC-signed bearer tokens that carry the user's ``token_version``. Every request
  re-checks the user in the database, so disabling an account, changing its role, resetting or
  changing its password, or "sign out everywhere" takes effect immediately.
* First run: no default passwords. If the database has no users, ``/api/auth/setup`` creates the
  first admin. (Optional dev seeding from config/users.example.yaml with ROADGUARD_SEED_USERS=1.)
* Brute force: repeated failed logins lock the username/IP pair for a few minutes.
* New/reset accounts get a one-time temporary password and must change it at first login.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import string
import threading
import time
from datetime import datetime
from typing import Optional

import yaml
from fastapi import Depends, HTTPException, Request, status

from . import settings
from .db import AuditLog, SessionLocal, User

ROLES = ("admin", "operator", "analyst")

# What each role may do (spec §20).
PERMISSIONS = {
    "admin": {"view", "investigate", "review", "report", "configure", "manage_users", "process"},
    "operator": {"view", "investigate", "review", "report", "process"},
    "analyst": {"view", "report"},
}
ROLE_LABELS = {"admin": "Administrator", "operator": "Traffic operator", "analyst": "Analyst"}

USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")
MIN_PASSWORD = 10
_COMMON = {
    "password", "password1", "password123", "123456789", "1234567890", "qwertyuiop", "letmein123",
    "welcome123", "admin12345", "iloveyou12", "roadguard", "roadguard1", "changeme12",
}

# Endpoints a user who must change their password may still call.
PASSWORD_CHANGE_ALLOWED = {"/api/auth/me", "/api/auth/change-password", "/api/auth/logout-all"}


# --------------------------------------------------------------------------- passwords
def hash_password(pw: str, salt: Optional[bytes] = None) -> str:
    salt = salt or os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 200_000)
    return f"pbkdf2${salt.hex()}${dk.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, salt, dk = stored.split("$")
    except ValueError:
        return False
    return hmac.compare_digest(hash_password(pw, bytes.fromhex(salt)), stored)


def password_problems(pw: str, username: str = "") -> list[str]:
    """Human-readable reasons a password is not acceptable (empty list = OK)."""
    problems = []
    if len(pw) < MIN_PASSWORD:
        problems.append(f"at least {MIN_PASSWORD} characters")
    classes = sum(bool(re.search(p, pw)) for p in (r"[a-z]", r"[A-Z]", r"\d", r"[^A-Za-z0-9]"))
    if classes < 3:
        problems.append("at least 3 of: lowercase, uppercase, digit, symbol")
    if username and username.lower() in pw.lower():
        problems.append("must not contain the username")
    if pw.lower() in _COMMON:
        problems.append("too common")
    return problems


def check_password(pw: str, username: str = "") -> None:
    problems = password_problems(pw, username)
    if problems:
        raise HTTPException(422, "Password needs " + "; ".join(problems))


def generate_temp_password() -> str:
    """Readable one-time password that satisfies the policy, e.g. 'Kite-7342-Moss-Rq'."""
    words = ["Amber", "Brook", "Cedar", "Delta", "Ember", "Fjord", "Grove", "Harbor", "Iris", "Juniper",
             "Kite", "Lumen", "Maple", "Nova", "Orbit", "Pine", "Quartz", "Ridge", "Sage", "Tide"]
    tail = "".join(secrets.choice(string.ascii_letters) for _ in range(2))
    return f"{secrets.choice(words)}-{secrets.randbelow(9000) + 1000}-{secrets.choice(words)}-{tail}"


def validate_username(username: str) -> str:
    u = username.strip().lower()
    if not USERNAME_RE.match(u):
        raise HTTPException(422,
                            "Username must be 3–32 characters: lowercase letters, digits, '.', '_' or '-'")
    return u


# --------------------------------------------------------------------------- tokens
def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_token(user: User) -> str:
    payload = _b64(json.dumps({"u": user.username, "v": user.token_version,
                               "exp": int(time.time()) + settings.TOKEN_TTL_HOURS * 3600}).encode())
    sig = _b64(hmac.new(settings.secret_key(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def read_token(token: str) -> Optional[dict]:
    """Signature + expiry check only (no database lookup)."""
    try:
        payload, sig = token.split(".")
        good = _b64(hmac.new(settings.secret_key(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(good, sig):
            return None
        data = json.loads(_unb64(payload))
    except (ValueError, json.JSONDecodeError):
        return None
    return data if data.get("exp", 0) > time.time() else None


class Principal:
    def __init__(self, username: str, role: str, must_change_password: bool = False, user_id: int = 0):
        self.username, self.role = username, role
        self.must_change_password = must_change_password
        self.user_id = user_id

    def can(self, perm: str) -> bool:
        return perm in PERMISSIONS.get(self.role, set())


def principal_from_token(token: str) -> Optional[Principal]:
    """Validate a token against the live user record (active, token_version)."""
    data = read_token(token) if token else None
    if not data:
        return None
    with SessionLocal() as s:
        u = s.query(User).filter_by(username=data.get("u")).one_or_none()
    if u is None or not u.active or u.token_version != data.get("v", -1):
        return None
    return Principal(u.username, u.role, u.must_change_password, u.id)


def current_user(request: Request) -> Principal:
    if not settings.AUTH_ENABLED:
        return Principal("dev", "admin")
    header = request.headers.get("authorization", "")
    token = header[7:] if header.lower().startswith("bearer ") else request.query_params.get("token", "")
    p = principal_from_token(token)
    if p is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    if p.must_change_password and request.url.path not in PASSWORD_CHANGE_ALLOWED:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "password_change_required")
    return p


def require(perm: str):
    def dep(user: Principal = Depends(current_user)) -> Principal:
        if not user.can(perm):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Role '{user.role}' lacks permission '{perm}'")
        return user

    return dep


def audit(user: Principal | str, action: str, detail: str = "") -> None:
    with SessionLocal() as s:
        s.add(AuditLog(username=user if isinstance(user, str) else user.username, action=action, detail=detail))
        s.commit()


# --------------------------------------------------------------------------- login throttling
class LoginThrottle:
    """After MAX_FAILS failures within WINDOW_S, a (username, ip) pair is locked for LOCK_S."""

    MAX_FAILS, WINDOW_S, LOCK_S = 5, 300, 300

    def __init__(self):
        self._fails: dict[tuple[str, str], list[float]] = {}
        self._locked: dict[tuple[str, str], float] = {}
        self._lock = threading.Lock()

    def retry_after(self, key: tuple[str, str]) -> int:
        with self._lock:
            until = self._locked.get(key, 0)
            return max(0, int(until - time.time()) + 1) if until > time.time() else 0

    def fail(self, key: tuple[str, str]) -> None:
        now = time.time()
        with self._lock:
            fails = [t for t in self._fails.get(key, []) if now - t < self.WINDOW_S] + [now]
            self._fails[key] = fails
            if len(fails) >= self.MAX_FAILS:
                self._locked[key] = now + self.LOCK_S
                self._fails[key] = []

    def success(self, key: tuple[str, str]) -> None:
        with self._lock:
            self._fails.pop(key, None)
            self._locked.pop(key, None)


throttle = LoginThrottle()


# --------------------------------------------------------------------------- account helpers
def user_dict(u: User) -> dict:
    return {
        "id": u.id, "username": u.username, "full_name": u.full_name or "", "role": u.role,
        "role_label": ROLE_LABELS.get(u.role, u.role), "active": bool(u.active),
        "must_change_password": bool(u.must_change_password),
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "last_login": u.last_login.isoformat() if u.last_login else None,
        "password_changed_at": u.password_changed_at.isoformat() if u.password_changed_at else None,
    }


def set_password(u: User, new: str, must_change: bool = False) -> None:
    u.password_hash = hash_password(new)
    u.must_change_password = must_change
    u.token_version = (u.token_version or 0) + 1  # sign out existing sessions
    u.password_changed_at = datetime.now()


def active_admin_count(s, exclude_id: Optional[int] = None) -> int:
    q = s.query(User).filter(User.role == "admin", User.active.is_(True))
    if exclude_id is not None:
        q = q.filter(User.id != exclude_id)
    return q.count()


def setup_needed() -> bool:
    with SessionLocal() as s:
        return s.query(User).count() == 0


# --------------------------------------------------------------------------- dev seed + migration
def _dev_seed_entries() -> list[dict]:
    for name in ("users.example.yaml", "users.yaml"):
        path = settings.CONFIG_DIR / name
        if path.exists():
            return [e for e in (yaml.safe_load(path.read_text(encoding="utf-8")) or []) if e.get("role") in ROLES]
    return []


def seed_users() -> None:
    """Startup hook.

    * Accounts still using a published dev password are forced to change it at next login.
    * With ROADGUARD_SEED_USERS=1 (development only), missing dev accounts are created — also
      flagged to change their password on first login.
    """
    entries = _dev_seed_entries()
    with SessionLocal() as s:
        for e in entries:
            u = s.query(User).filter_by(username=e["username"]).one_or_none()
            if u is not None and not u.must_change_password and verify_password(e["password"], u.password_hash):
                u.must_change_password = True
        if os.environ.get("ROADGUARD_SEED_USERS") == "1":
            for e in entries:
                if s.query(User).filter_by(username=e["username"]).one_or_none() is None:
                    s.add(User(username=e["username"], password_hash=hash_password(e["password"]), role=e["role"],
                               full_name=e.get("full_name", ""), must_change_password=True))
        s.commit()
