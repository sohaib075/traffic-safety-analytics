"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AlertTriangle, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import { useApp } from "@/lib/state";
import type { Me } from "@/lib/types";
import { Field, PasswordChecklist, PasswordInput, passwordValid } from "@/components/forms";

const USERNAME_RE = /^[a-z0-9][a-z0-9._-]{2,31}$/;

/** First-run: create the first administrator (only possible while no accounts exist). */
export default function SetupPage() {
  const { setSession } = useApp();
  const router = useRouter();
  const [checking, setChecking] = useState(true);
  const [fullName, setFullName] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<{ setup_needed: boolean }>("/api/auth/status")
      .then((s) => (s.setup_needed ? setChecking(false) : router.replace("/login")))
      .catch(() => {
        setChecking(false);
        setError("Can't reach the RoadGuard API.");
      });
  }, [router]);

  const uname = username.trim().toLowerCase();
  const usernameOk = USERNAME_RE.test(uname);
  const matches = password.length > 0 && password === confirm;
  const valid = usernameOk && passwordValid(password, uname) && matches;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api<Me & { token: string }>("/api/auth/setup", {
        method: "POST",
        body: JSON.stringify({ username: uname, full_name: fullName, password }),
      });
      setSession(res);
      router.replace("/");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (checking) return <div className="grid h-screen place-items-center text-sm text-[var(--color-muted)]">Checking setup…</div>;

  return (
    <div className="grid min-h-screen place-items-center p-6">
      <div className="w-full max-w-md">
        <div className="mb-6 flex items-center gap-2">
          <ShieldCheck className="h-6 w-6 text-[var(--color-accent)]" />
          <span className="text-lg font-semibold tracking-wide">ROADGUARD AI</span>
        </div>
        <div className="panel p-6">
          <h1 className="text-xl font-semibold">Welcome — create the administrator</h1>
          <p className="mt-1 text-sm text-[var(--color-muted)]">
            This is a new installation. The first account is an administrator who can then invite operators and analysts.
          </p>
          <form onSubmit={submit} className="mt-6 space-y-4">
            <Field label="Full name">
              <input className="input w-full" value={fullName} onChange={(e) => setFullName(e.target.value)} autoComplete="name" autoFocus />
            </Field>
            <Field
              label="Username"
              error={username && !usernameOk ? "3–32 characters: lowercase letters, numbers, . _ -" : null}
              hint="Used to sign in."
            >
              <input className="input w-full" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoCapitalize="none" spellCheck={false} />
            </Field>
            <Field label="Password">
              <PasswordInput value={password} onChange={setPassword} autoComplete="new-password" />
            </Field>
            <PasswordChecklist password={password} username={uname} />
            <Field label="Confirm password" error={confirm && !matches ? "Passwords don't match" : null}>
              <PasswordInput value={confirm} onChange={setConfirm} autoComplete="new-password" />
            </Field>
            {error && (
              <div role="alert" className="flex items-start gap-2 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> {error}
              </div>
            )}
            <button className="btn btn-primary w-full justify-center py-2" disabled={!valid || busy}>
              {busy ? "Creating…" : "Create administrator and sign in"}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
