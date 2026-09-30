"""Account endpoints: first-run setup, login, own account, and admin user management."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from . import auth, settings
from .auth import Principal, audit, current_user, require
from .db import SessionLocal, User

router = APIRouter()
Role = Literal["admin", "operator", "analyst"]


def _login_response(u: User) -> dict:
    return {"token": auth.make_token(u), **_me_dict(u)}


def _me_dict(u: User) -> dict:
    return {**auth.user_dict(u), "permissions": sorted(auth.PERMISSIONS[u.role]),
            "auth_enabled": settings.AUTH_ENABLED}


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


# --------------------------------------------------------------------------- first run
@router.get("/api/auth/status")
def auth_status():
    """Public: tells the login page whether first-run setup is required."""
    return {"setup_needed": auth.setup_needed(), "auth_enabled": settings.AUTH_ENABLED,
            "password_policy": {"min_length": auth.MIN_PASSWORD, "classes": 3}}


class SetupIn(BaseModel):
    username: str
    full_name: str = ""
    password: str


@router.post("/api/auth/setup")
def setup(body: SetupIn):
    """Create the first administrator. Only possible while the database has no users."""
    username = auth.validate_username(body.username)
    auth.check_password(body.password, username)
    with SessionLocal() as s:
        if s.query(User).count() > 0:
            raise HTTPException(409, "Setup has already been completed")
        u = User(username=username, full_name=body.full_name.strip()[:128], role="admin",
                 password_hash=auth.hash_password(body.password), password_changed_at=datetime.now(),
                 last_login=datetime.now())
        s.add(u)
        s.commit()
        s.refresh(u)
        audit(username, "setup_first_admin")
        return _login_response(u)


# --------------------------------------------------------------------------- session
class LoginIn(BaseModel):
    username: str
    password: str


@router.post("/api/auth/login")
def login(body: LoginIn, request: Request):
    username = body.username.strip().lower()
    key = (username, _client_ip(request))
    wait = auth.throttle.retry_after(key)
    if wait:
        raise HTTPException(429, f"Too many failed attempts. Try again in {wait} s.", headers={"Retry-After": str(wait)})
    with SessionLocal() as s:
        u = s.query(User).filter_by(username=username).one_or_none()
        if not u or not auth.verify_password(body.password, u.password_hash):
            auth.throttle.fail(key)
            audit(username or "?", "login_failed", _client_ip(request))
            raise HTTPException(401, "Invalid username or password")
        if not u.active:
            audit(username, "login_blocked_disabled")
            raise HTTPException(403, "This account is disabled. Contact an administrator.")
        auth.throttle.success(key)
        u.last_login = datetime.now()
        s.commit()
        s.refresh(u)
        audit(username, "login")
        return _login_response(u)


@router.get("/api/auth/me")
def me(user: Principal = Depends(current_user)):
    if not settings.AUTH_ENABLED:
        return {"username": "dev", "full_name": "Auth disabled", "role": "admin", "role_label": "Administrator",
                "permissions": sorted(auth.PERMISSIONS["admin"]), "must_change_password": False,
                "auth_enabled": False, "active": True}
    with SessionLocal() as s:
        return _me_dict(s.get(User, user.user_id))


class ProfileIn(BaseModel):
    full_name: str = Field("", max_length=128)


@router.patch("/api/auth/me")
def update_profile(body: ProfileIn, user: Principal = Depends(current_user)):
    with SessionLocal() as s:
        u = s.get(User, user.user_id)
        u.full_name = body.full_name.strip()
        s.commit()
        return _me_dict(u)


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str


@router.post("/api/auth/change-password")
def change_password(body: ChangePasswordIn, request: Request, user: Principal = Depends(current_user)):
    key = (user.username, _client_ip(request))
    if auth.throttle.retry_after(key):
        raise HTTPException(429, "Too many failed attempts. Try again later.")
    with SessionLocal() as s:
        u = s.get(User, user.user_id)
        if not auth.verify_password(body.current_password, u.password_hash):
            auth.throttle.fail(key)
            raise HTTPException(400, "Current password is incorrect")
        if body.new_password == body.current_password:
            raise HTTPException(422, "New password must be different from the current one")
        auth.check_password(body.new_password, u.username)
        auth.set_password(u, body.new_password, must_change=False)
        s.commit()
        s.refresh(u)
        audit(user, "password_change")
        return _login_response(u)  # fresh token; all other sessions are now signed out


@router.post("/api/auth/logout-all")
def logout_all(user: Principal = Depends(current_user)):
    """Invalidate every session of this account (including the current one)."""
    with SessionLocal() as s:
        u = s.get(User, user.user_id)
        u.token_version = (u.token_version or 0) + 1
        s.commit()
    audit(user, "logout_all")
    return {"ok": True}


# --------------------------------------------------------------------------- user management
@router.get("/api/users")
def list_users(user: Principal = Depends(require("manage_users"))):
    with SessionLocal() as s:
        return [auth.user_dict(u) for u in s.query(User).order_by(User.id).all()]


class UserCreateIn(BaseModel):
    username: str
    full_name: str = Field("", max_length=128)
    role: Role
    password: Optional[str] = None  # omitted → a one-time temporary password is generated


@router.post("/api/users", status_code=201)
def create_user(body: UserCreateIn, user: Principal = Depends(require("manage_users"))):
    username = auth.validate_username(body.username)
    temp = None
    if body.password:
        auth.check_password(body.password, username)
        password = body.password
    else:
        password = temp = auth.generate_temp_password()
    with SessionLocal() as s:
        if s.query(User).filter_by(username=username).one_or_none():
            raise HTTPException(409, f"User '{username}' already exists")
        u = User(username=username, full_name=body.full_name.strip(), role=body.role,
                 password_hash=auth.hash_password(password), must_change_password=True)
        s.add(u)
        s.commit()
        s.refresh(u)
        audit(user, "user_create", f"{username} ({body.role})")
        # The temporary password is returned exactly once and never stored in plain text.
        return {"user": auth.user_dict(u), "temporary_password": temp}


class UserUpdateIn(BaseModel):
    full_name: Optional[str] = Field(None, max_length=128)
    role: Optional[Role] = None
    active: Optional[bool] = None


def _get_user(s, user_id: int) -> User:
    u = s.get(User, user_id)
    if u is None:
        raise HTTPException(404, "User not found")
    return u


@router.patch("/api/users/{user_id}")
def update_user(user_id: int, body: UserUpdateIn, user: Principal = Depends(require("manage_users"))):
    with SessionLocal() as s:
        u = _get_user(s, user_id)
        changes = []
        if body.full_name is not None and body.full_name.strip() != (u.full_name or ""):
            u.full_name = body.full_name.strip()
            changes.append("name")
        if body.role is not None and body.role != u.role:
            if u.id == user.user_id:
                raise HTTPException(409, "You cannot change your own role")
            if u.role == "admin" and u.active and auth.active_admin_count(s, exclude_id=u.id) == 0:
                raise HTTPException(409, "At least one active administrator is required")
            changes.append(f"role {u.role}→{body.role}")
            u.role = body.role
        if body.active is not None and body.active != u.active:
            if u.id == user.user_id:
                raise HTTPException(409, "You cannot disable your own account")
            if not body.active and u.role == "admin" and auth.active_admin_count(s, exclude_id=u.id) == 0:
                raise HTTPException(409, "At least one active administrator is required")
            u.active = body.active
            if not body.active:
                u.token_version = (u.token_version or 0) + 1  # end their sessions now
            changes.append("enabled" if body.active else "disabled")
        s.commit()
        s.refresh(u)
        if changes:
            audit(user, "user_update", f"{u.username}: {', '.join(changes)}")
        return auth.user_dict(u)


@router.post("/api/users/{user_id}/reset-password")
def reset_password(user_id: int, user: Principal = Depends(require("manage_users"))):
    """Issue a one-time temporary password; the user must change it at next sign-in."""
    temp = auth.generate_temp_password()
    with SessionLocal() as s:
        u = _get_user(s, user_id)
        auth.set_password(u, temp, must_change=True)
        s.commit()
        s.refresh(u)
        audit(user, "password_reset", u.username)
        return {"user": auth.user_dict(u), "temporary_password": temp}


@router.delete("/api/users/{user_id}", status_code=204)
def delete_user(user_id: int, user: Principal = Depends(require("manage_users"))):
    with SessionLocal() as s:
        u = _get_user(s, user_id)
        if u.id == user.user_id:
            raise HTTPException(409, "You cannot delete your own account")
        if u.role == "admin" and u.active and auth.active_admin_count(s, exclude_id=u.id) == 0:
            raise HTTPException(409, "At least one active administrator is required")
        name = u.username
        s.delete(u)
        s.commit()
    audit(user, "user_delete", name)
