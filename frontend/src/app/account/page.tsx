"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { KeyRound, LogOut, ShieldAlert, UserRound } from "lucide-react";
import { api } from "@/lib/api";
import { fmtDate, fmtTime } from "@/lib/format";
import { useApp } from "@/lib/state";
import type { Me } from "@/lib/types";
import { ConfirmDialog, Field, PasswordChecklist, PasswordInput, passwordValid, useToast } from "@/components/forms";
import { ErrorNote, Panel } from "@/components/ui";

const PERM_LABELS: Record<string, string> = {
  view: "View dashboards",
  investigate: "Evidence clips & journeys",
  review: "Confirm / dismiss incidents",
  report: "Reports",
  process: "Process video",
  configure: "Camera configuration",
  manage_users: "Manage users",
};

const when = (iso: string | null) => (iso ? `${fmtDate(iso)} ${fmtTime(iso, false)}` : "—");

export default function AccountPage() {
  const { me, setSession, logout, refreshMe } = useApp();
  const router = useRouter();
  const toast = useToast();
  const required = !!me?.must_change_password;

  const [fullName, setFullName] = useState(me?.full_name ?? "");
  const [savingName, setSavingName] = useState(false);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [pwError, setPwError] = useState<string | null>(null);
  const [pwBusy, setPwBusy] = useState(false);
  const [confirmLogoutAll, setConfirmLogoutAll] = useState(false);

  useEffect(() => setFullName(me?.full_name ?? ""), [me?.full_name]);
  if (!me) return null;

  const matches = next.length > 0 && next === confirm;
  const pwOk = !!current && passwordValid(next, me.username) && matches && next !== current;

  const saveName = async () => {
    setSavingName(true);
    try {
      await api<Me>("/api/auth/me", { method: "PATCH", body: JSON.stringify({ full_name: fullName }) });
      await refreshMe();
      toast("Profile updated");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setSavingName(false);
    }
  };

  const changePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!pwOk) return;
    setPwBusy(true);
    setPwError(null);
    try {
      const res = await api<Me & { token: string }>("/api/auth/change-password", {
        method: "POST",
        body: JSON.stringify({ current_password: current, new_password: next }),
      });
      setSession(res);
      setCurrent("");
      setNext("");
      setConfirm("");
      toast("Password changed — other sessions were signed out");
      if (required) router.replace("/");
    } catch (err) {
      setPwError((err as Error).message);
    } finally {
      setPwBusy(false);
    }
  };

  const logoutAll = async () => {
    try {
      await api("/api/auth/logout-all", { method: "POST" });
    } finally {
      logout();
    }
  };

  const passwordForm = (
    <form onSubmit={changePassword} className="space-y-4">
      <Field label={required ? "Current (temporary) password" : "Current password"}>
        <PasswordInput value={current} onChange={setCurrent} autoFocus={required} />
      </Field>
      <Field label="New password">
        <PasswordInput value={next} onChange={setNext} autoComplete="new-password" />
      </Field>
      <PasswordChecklist password={next} username={me.username} />
      <Field
        label="Confirm new password"
        error={confirm && !matches ? "Passwords don't match" : next && current && next === current ? "Must differ from the current password" : null}
      >
        <PasswordInput value={confirm} onChange={setConfirm} autoComplete="new-password" />
      </Field>
      <ErrorNote error={pwError} />
      <button className="btn btn-primary" disabled={!pwOk || pwBusy}>
        <KeyRound className="h-4 w-4" /> {pwBusy ? "Saving…" : required ? "Set password and continue" : "Change password"}
      </button>
    </form>
  );

  if (required) {
    return (
      <div className="mx-auto max-w-md">
        <div className="mb-4 flex items-start gap-3 rounded-lg border border-amber-500/30 bg-amber-500/10 p-4 text-sm">
          <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0 text-amber-300" />
          <div>
            <div className="font-medium text-amber-200">Set a new password to continue</div>
            <div className="mt-0.5 text-[var(--color-muted)]">
              Your account ({me.username}) is using a temporary or default password. Choose a personal one — nobody else will know it.
            </div>
          </div>
        </div>
        <Panel title="Choose your password">{passwordForm}</Panel>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Account</h1>
        <p className="text-sm text-[var(--color-muted)]">Your profile, password and sessions.</p>
      </div>

      <div className="grid gap-4 md:grid-cols-[1fr_1.1fr]">
        <Panel title={<span className="flex items-center gap-1.5"><UserRound className="h-3.5 w-3.5" /> Profile</span>}>
          <div className="space-y-4">
            <Field label="Full name">
              <div className="flex gap-2">
                <input className="input flex-1" value={fullName} onChange={(e) => setFullName(e.target.value)} maxLength={128} />
                <button className="btn" onClick={saveName} disabled={savingName || fullName === (me.full_name ?? "")}>
                  Save
                </button>
              </div>
            </Field>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
              <dt className="text-[var(--color-muted)]">Username</dt>
              <dd className="font-mono">{me.username}</dd>
              <dt className="text-[var(--color-muted)]">Role</dt>
              <dd>{me.role_label}</dd>
              <dt className="text-[var(--color-muted)]">Member since</dt>
              <dd>{when(me.created_at)}</dd>
              <dt className="text-[var(--color-muted)]">Last sign-in</dt>
              <dd>{when(me.last_login)}</dd>
              <dt className="text-[var(--color-muted)]">Password changed</dt>
              <dd>{when(me.password_changed_at)}</dd>
            </dl>
            <div>
              <div className="mb-1.5 text-xs font-medium text-[var(--color-muted)]">What you can do</div>
              <div className="flex flex-wrap gap-1.5">
                {me.permissions.map((p) => (
                  <span key={p} className="rounded-full bg-[var(--color-panel-2)] px-2.5 py-0.5 text-xs">{PERM_LABELS[p] ?? p}</span>
                ))}
              </div>
              <p className="mt-2 text-xs text-[var(--color-faint)]">Roles are assigned by an administrator.</p>
            </div>
          </div>
        </Panel>

        <Panel title={<span className="flex items-center gap-1.5"><KeyRound className="h-3.5 w-3.5" /> Password</span>}>{passwordForm}</Panel>
      </div>

      <Panel title={<span className="flex items-center gap-1.5"><LogOut className="h-3.5 w-3.5" /> Sessions</span>}>
        <div className="flex flex-wrap items-center gap-3">
          <p className="flex-1 text-sm text-[var(--color-muted)]">
            Signed in somewhere you shouldn&apos;t be, or on a shared computer? Sign out everywhere, including this browser.
          </p>
          <button className="btn" onClick={() => setConfirmLogoutAll(true)}>
            <LogOut className="h-4 w-4" /> Sign out of all devices
          </button>
        </div>
      </Panel>

      <ConfirmDialog
        open={confirmLogoutAll}
        title="Sign out of all devices?"
        message="Every session of your account ends immediately, including this one. You'll need your password to sign back in."
        confirmLabel="Sign out everywhere"
        onConfirm={logoutAll}
        onClose={() => setConfirmLogoutAll(false)}
      />
    </div>
  );
}
