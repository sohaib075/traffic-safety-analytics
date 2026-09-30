"""Command line entry points.

    python -m roadguard.cli process --camera demo_lot --video data/samples/car-detection.mp4 --start 2026-09-29T17:40:00
    python -m roadguard.cli report --date 2026-09-29 --out report.pdf

Account recovery (when nobody can sign in):

    python -m roadguard.cli users                         # list accounts
    python -m roadguard.cli set-password --all            # type new passwords for every account
    python -m roadguard.cli reset-password --username admin   # one-time temporary password
    python -m roadguard.cli create-admin --username alice     # new admin with a temporary password
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import date, datetime
from pathlib import Path

from . import settings
from .camera_config import camera_config_path, load_camera_config


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(prog="roadguard")
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("process", help="Process a video file into incidents/analytics")
    pr.add_argument("--camera", required=True, help="camera id (config/cameras/<id>.yaml)")
    pr.add_argument("--video", required=True)
    pr.add_argument("--start", help="wall-clock time of the first frame (ISO), default now")
    pr.add_argument("--max-seconds", type=float)
    pr.add_argument("--no-annotated", action="store_true", help="skip writing the full annotated video")

    rp = sub.add_parser("report", help="Write the daily PDF report")
    rp.add_argument("--date", required=True)
    rp.add_argument("--camera")
    rp.add_argument("--out", default="roadguard-report.pdf")

    sub.add_parser("users", help="List user accounts")
    rs = sub.add_parser("reset-password", help="Give an account a one-time temporary password (and re-enable it)")
    rs.add_argument("--username", required=True)
    sp = sub.add_parser("set-password", help="Type a new password for one or all accounts (hidden input)")
    grp = sp.add_mutually_exclusive_group(required=True)
    grp.add_argument("--username")
    grp.add_argument("--all", action="store_true", help="go through every account in turn")
    ca = sub.add_parser("create-admin", help="Create an administrator with a one-time temporary password")
    ca.add_argument("--username", required=True)
    ca.add_argument("--full-name", default="")

    a = p.parse_args()
    from .db import init_db

    settings.ensure_dirs()
    init_db()
    if a.cmd == "set-password":
        _set_passwords(a)
        return
    if a.cmd in ("users", "reset-password", "create-admin"):
        _accounts(a)
        return
    if a.cmd == "process":
        from .pipeline.runner import VideoProcessor, create_job

        cfg = load_camera_config(camera_config_path(a.camera))
        start = datetime.fromisoformat(a.start) if a.start else datetime.now()
        src = str(Path(a.video).resolve())
        job_id = create_job(cfg, src, start)
        summary = VideoProcessor(cfg, src, job_id, start, save_annotated=not a.no_annotated,
                                 max_seconds=a.max_seconds).run()
        print(json.dumps({"job_id": job_id, **summary}, indent=2, default=str))
    elif a.cmd == "report":
        from .reports import build_daily_report

        Path(a.out).write_bytes(build_daily_report(date.fromisoformat(a.date), a.camera))
        print(f"wrote {a.out}")


def _set_passwords(a) -> None:
    """Interactively set new passwords. Input is hidden and never echoed or logged."""
    import getpass

    from . import auth
    from .db import SessionLocal, User

    with SessionLocal() as s:
        if a.all:
            names = [u.username for u in s.query(User).order_by(User.id)]
        else:
            names = [auth.validate_username(a.username)]
    if not names:
        raise SystemExit("no accounts yet — open the dashboard to run first-time setup")

    rules = f"at least {auth.MIN_PASSWORD} characters, 3 of: lowercase / uppercase / number / symbol, not containing the username"
    print(f"Set new passwords ({rules}).\nTyping is hidden. Press Enter on an empty password to skip an account.\n")
    for name in names:
        with SessionLocal() as s:
            u = s.query(User).filter_by(username=name).one_or_none()
            if u is None:
                raise SystemExit(f"no such user: {name}")
            label = f"{u.username} ({auth.ROLE_LABELS.get(u.role, u.role)})"
            while True:
                pw = getpass.getpass(f"New password for {label}: ")
                if not pw:
                    print("  skipped\n")
                    break
                problems = auth.password_problems(pw, u.username)
                if problems:
                    print("  not accepted — needs " + "; ".join(problems))
                    continue
                if getpass.getpass("  Repeat it: ") != pw:
                    print("  the two entries didn't match, try again")
                    continue
                auth.set_password(u, pw, must_change=False)
                u.active = True
                s.commit()
                auth.audit("cli", "password_set", u.username)
                print("  saved — existing sessions for this account were signed out\n")
                break


def _accounts(a) -> None:
    from . import auth
    from .db import SessionLocal, User

    with SessionLocal() as s:
        if a.cmd == "users":
            for u in s.query(User).order_by(User.id):
                flags = [f for f, on in (("disabled", not u.active), ("must-change-password", u.must_change_password)) if on]
                print(f"{u.username:20s} {u.role:9s} last login {u.last_login or '-'}  {' '.join(flags)}")
            return
        username = auth.validate_username(a.username)
        temp = auth.generate_temp_password()
        u = s.query(User).filter_by(username=username).one_or_none()
        if a.cmd == "reset-password":
            if u is None:
                raise SystemExit(f"no such user: {username}")
            auth.set_password(u, temp, must_change=True)
            u.active = True
        else:
            if u is not None:
                raise SystemExit(f"user already exists: {username} (use reset-password)")
            u = User(username=username, full_name=a.full_name, role="admin",
                     password_hash=auth.hash_password(temp), must_change_password=True)
            s.add(u)
        s.commit()
    auth.audit("cli", a.cmd.replace("-", "_"), username)
    print(f"Temporary password for '{username}': {temp}")
    print("It must be changed at first sign-in. It is not stored and will not be shown again.")


if __name__ == "__main__":
    main()
