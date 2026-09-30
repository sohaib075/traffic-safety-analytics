"""`roadguard.cli set-password` with scripted (hidden) input."""
import sys

from roadguard import auth, cli
from roadguard.db import SessionLocal, User, init_db


def test_set_password_all(monkeypatch, capsys):
    init_db()
    with SessionLocal() as s:
        s.query(User).delete()
        s.add(User(username="boss", role="admin", password_hash=auth.hash_password("x"), must_change_password=True, active=False))
        s.add(User(username="op", role="operator", password_hash=auth.hash_password("y")))
        s.commit()
    answers = iter([
        "short",                                # boss: rejected by policy
        "Harbor-4821-Pine", "Harbor-4821-Pinx",  # boss: mismatch
        "Harbor-4821-Pine", "Harbor-4821-Pine",  # boss: saved
        "",                                      # op: skipped
    ])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(answers))
    monkeypatch.setattr(sys, "argv", ["roadguard", "set-password", "--all"])
    cli.main()
    out = capsys.readouterr().out
    assert "not accepted" in out and "didn't match" in out and "skipped" in out
    assert "Harbor" not in out  # never echoed
    with SessionLocal() as s:
        boss = s.query(User).filter_by(username="boss").one()
        op = s.query(User).filter_by(username="op").one()
        assert auth.verify_password("Harbor-4821-Pine", boss.password_hash)
        assert boss.active and not boss.must_change_password
        assert auth.verify_password("y", op.password_hash)  # untouched
