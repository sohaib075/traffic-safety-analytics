"use client";

import { useMemo, useState } from "react";
import { KeyRound, Search, Trash2, UserPlus } from "lucide-react";
import { api } from "@/lib/api";
import { fmtDate, fmtTime } from "@/lib/format";
import { useApp, useFetch } from "@/lib/state";
import type { Account, Role } from "@/lib/types";
import { ConfirmDialog, Field, Modal, PasswordChecklist, PasswordInput, SecretBox, passwordValid, useToast } from "@/components/forms";
import { Empty, ErrorNote, Panel } from "@/components/ui";

const ROLES: { value: Role; label: string; hint: string }[] = [
  { value: "admin", label: "Administrator", hint: "Everything, incl. cameras & users" },
  { value: "operator", label: "Traffic operator", hint: "Monitor, investigate, review, process video" },
  { value: "analyst", label: "Analyst", hint: "Dashboards, analytics & reports only" },
];
const USERNAME_RE = /^[a-z0-9][a-z0-9._-]{2,31}$/;

function ago(iso: string | null) {
  if (!iso) return "Never";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "Just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  if (s < 86400 * 7) return `${Math.floor(s / 86400)} d ago`;
  return fmtDate(iso);
}

export default function UsersPage() {
  const { me, can } = useApp();
  const toast = useToast();
  const { data: users, error, reload } = useFetch<Account[]>(can("manage_users") ? "/api/users" : null);
  const [q, setQ] = useState("");
  const [roleFilter, setRoleFilter] = useState<"" | Role>("");
  const [adding, setAdding] = useState(false);
  const [secret, setSecret] = useState<{ username: string; password: string; created: boolean } | null>(null);
  const [resetTarget, setResetTarget] = useState<Account | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Account | null>(null);
  const [busy, setBusy] = useState(false);

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (users ?? []).filter(
      (u) => (!roleFilter || u.role === roleFilter) && (!needle || u.username.includes(needle) || u.full_name.toLowerCase().includes(needle)),
    );
  }, [users, q, roleFilter]);

  if (!can("manage_users")) return <Empty>Only administrators can manage users.</Empty>;

  const patch = async (u: Account, body: Partial<Pick<Account, "role" | "active" | "full_name">>, msg: string) => {
    try {
      await api(`/api/users/${u.id}`, { method: "PATCH", body: JSON.stringify(body) });
      toast(msg);
      reload();
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  const doReset = async () => {
    if (!resetTarget) return;
    setBusy(true);
    try {
      const r = await api<{ temporary_password: string }>(`/api/users/${resetTarget.id}/reset-password`, { method: "POST" });
      setSecret({ username: resetTarget.username, password: r.temporary_password, created: false });
      setResetTarget(null);
      reload();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  const doDelete = async () => {
    if (!deleteTarget) return;
    setBusy(true);
    try {
      await api(`/api/users/${deleteTarget.id}`, { method: "DELETE" });
      toast(`Deleted ${deleteTarget.username}`);
      setDeleteTarget(null);
      reload();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  const counts = { total: users?.length ?? 0, active: users?.filter((u) => u.active).length ?? 0, pending: users?.filter((u) => u.must_change_password).length ?? 0 };

  return (
    <div className="mx-auto max-w-6xl space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex-1">
          <h1 className="text-xl font-semibold">Users</h1>
          <p className="text-sm text-[var(--color-muted)]">
            {counts.total} accounts · {counts.active} active{counts.pending ? ` · ${counts.pending} awaiting first sign-in / password change` : ""}
          </p>
        </div>
        <button className="btn btn-primary" onClick={() => setAdding(true)}>
          <UserPlus className="h-4 w-4" /> Add user
        </button>
      </div>

      <div className="flex flex-wrap gap-2">
        <div className="relative min-w-[220px] flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-faint)]" />
          <input className="input w-full pl-9" placeholder="Search name or username" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <select className="input" value={roleFilter} onChange={(e) => setRoleFilter(e.target.value as "" | Role)} aria-label="Filter by role">
          <option value="">All roles</option>
          {ROLES.map((r) => (
            <option key={r.value} value={r.value}>{r.label}</option>
          ))}
        </select>
      </div>

      <ErrorNote error={error} />

      <Panel bodyClass="p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-[var(--color-muted)]">
              <tr className="border-b border-[var(--color-line)]">
                <th className="px-4 py-2.5 font-medium">User</th>
                <th className="px-2 py-2.5 font-medium">Role</th>
                <th className="px-2 py-2.5 font-medium">Status</th>
                <th className="px-2 py-2.5 font-medium">Last sign-in</th>
                <th className="hidden px-2 py-2.5 font-medium md:table-cell">Created</th>
                <th className="px-4 py-2.5 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-line)]">
              {rows.map((u) => {
                const self = u.id === me?.id;
                return (
                  <tr key={u.id} className={u.active ? "" : "opacity-60"}>
                    <td className="px-4 py-2.5">
                      <div className="font-medium">
                        {u.full_name || u.username}
                        {self && <span className="ml-2 rounded bg-[var(--color-accent)]/15 px-1.5 py-0.5 text-[10px] font-semibold text-[var(--color-accent)]">YOU</span>}
                      </div>
                      <div className="font-mono text-xs text-[var(--color-faint)]">{u.username}</div>
                    </td>
                    <td className="px-2 py-2.5">
                      <select
                        className="input py-1 text-xs"
                        value={u.role}
                        disabled={self}
                        title={self ? "You can't change your own role" : "Change role"}
                        onChange={(e) => patch(u, { role: e.target.value as Role }, `${u.username} is now ${ROLES.find((r) => r.value === e.target.value)?.label}`)}
                      >
                        {ROLES.map((r) => (
                          <option key={r.value} value={r.value}>{r.label}</option>
                        ))}
                      </select>
                    </td>
                    <td className="px-2 py-2.5">
                      <label className={`inline-flex items-center gap-2 text-xs ${self ? "cursor-not-allowed" : "cursor-pointer"}`}>
                        <button
                          type="button"
                          role="switch"
                          aria-checked={u.active}
                          disabled={self}
                          onClick={() => patch(u, { active: !u.active }, `${u.username} ${u.active ? "disabled — signed out everywhere" : "enabled"}`)}
                          className={`relative h-5 w-9 rounded-full transition-colors disabled:opacity-50 ${u.active ? "bg-emerald-500" : "bg-[var(--color-panel-2)] ring-1 ring-[var(--color-line)]"}`}
                        >
                          <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-all ${u.active ? "left-[18px]" : "left-0.5"}`} />
                        </button>
                        {u.active ? "Active" : "Disabled"}
                      </label>
                      {u.must_change_password && u.active && <div className="mt-1 text-[11px] text-amber-300">Must set password</div>}
                    </td>
                    <td className="px-2 py-2.5 text-[var(--color-muted)]" title={u.last_login ? `${fmtDate(u.last_login)} ${fmtTime(u.last_login)}` : undefined}>
                      {ago(u.last_login)}
                    </td>
                    <td className="hidden px-2 py-2.5 text-[var(--color-muted)] md:table-cell">{u.created_at ? fmtDate(u.created_at) : "—"}</td>
                    <td className="px-4 py-2.5">
                      <div className="flex justify-end gap-1.5">
                        <button className="btn px-2 py-1 text-xs" onClick={() => setResetTarget(u)} title="Reset password">
                          <KeyRound className="h-3.5 w-3.5" /> <span className="hidden lg:inline">Reset password</span>
                        </button>
                        <button
                          className="btn px-2 py-1 text-xs hover:border-red-500/50 hover:text-red-300"
                          onClick={() => setDeleteTarget(u)}
                          disabled={self}
                          title={self ? "You can't delete your own account" : "Delete user"}
                          aria-label={`Delete ${u.username}`}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {users && rows.length === 0 && <Empty>No users match.</Empty>}
        </div>
      </Panel>

      <div className="grid gap-3 text-xs text-[var(--color-muted)] md:grid-cols-3">
        {ROLES.map((r) => (
          <div key={r.value} className="panel px-3 py-2">
            <div className="font-medium text-[var(--color-ink)]">{r.label}</div>
            {r.hint}
          </div>
        ))}
      </div>

      <AddUserDialog
        open={adding}
        onClose={() => setAdding(false)}
        onCreated={(username, temp) => {
          setAdding(false);
          reload();
          if (temp) setSecret({ username, password: temp, created: true });
          else toast(`Created ${username}`);
        }}
      />

      <ConfirmDialog
        open={!!resetTarget}
        title={`Reset password for ${resetTarget?.username}?`}
        message="A one-time temporary password is generated. Their current sessions end immediately and they must choose a new password when they next sign in."
        confirmLabel="Reset password"
        busy={busy}
        onConfirm={doReset}
        onClose={() => setResetTarget(null)}
      />

      <ConfirmDialog
        open={!!deleteTarget}
        title={`Delete ${deleteTarget?.username}?`}
        message={
          <>
            This permanently removes the account. Their past actions stay in the audit log. To keep the account but block access,
            <b className="text-[var(--color-ink)]"> disable</b> it instead.
          </>
        }
        confirmLabel="Delete user"
        danger
        busy={busy}
        onConfirm={doDelete}
        onClose={() => setDeleteTarget(null)}
      />

      <Modal
        open={!!secret}
        onClose={() => setSecret(null)}
        title={secret?.created ? "User created" : "Password reset"}
        footer={<button className="btn btn-primary" onClick={() => setSecret(null)}>Done</button>}
      >
        {secret && (
          <div className="space-y-3 text-sm">
            <p className="text-[var(--color-muted)]">
              Give <b className="text-[var(--color-ink)]">{secret.username}</b> this temporary password through a secure channel.
              They must change it the first time they sign in.
            </p>
            <SecretBox value={secret.password} />
            <p className="text-xs text-amber-300">It is shown only once and is not stored anywhere — copy it now.</p>
          </div>
        )}
      </Modal>
    </div>
  );
}

function AddUserDialog({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (username: string, temp: string | null) => void }) {
  const [username, setUsername] = useState("");
  const [fullName, setFullName] = useState("");
  const [role, setRole] = useState<Role>("operator");
  const [mode, setMode] = useState<"temp" | "set">("temp");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const uname = username.trim().toLowerCase();
  const usernameOk = USERNAME_RE.test(uname);
  const valid = usernameOk && (mode === "temp" || passwordValid(password, uname));

  const reset = () => {
    setUsername("");
    setFullName("");
    setRole("operator");
    setMode("temp");
    setPassword("");
    setError(null);
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api<{ temporary_password: string | null }>("/api/users", {
        method: "POST",
        body: JSON.stringify({ username: uname, full_name: fullName, role, password: mode === "set" ? password : null }),
      });
      onCreated(uname, r.temporary_password);
      reset();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={() => {
        reset();
        onClose();
      }}
      title="Add user"
      footer={
        <>
          <button className="btn" onClick={() => { reset(); onClose(); }}>Cancel</button>
          <button className="btn btn-primary" form="add-user" disabled={!valid || busy}>
            {busy ? "Creating…" : "Create user"}
          </button>
        </>
      }
    >
      <form id="add-user" onSubmit={submit} className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Full name">
            <input className="input w-full" value={fullName} onChange={(e) => setFullName(e.target.value)} />
          </Field>
          <Field label="Username" error={username && !usernameOk ? "3–32: a-z 0-9 . _ -" : null}>
            <input className="input w-full" value={username} onChange={(e) => setUsername(e.target.value)} autoCapitalize="none" spellCheck={false} />
          </Field>
        </div>
        <fieldset>
          <legend className="mb-1.5 text-xs font-medium text-[var(--color-muted)]">Role</legend>
          <div className="space-y-1.5">
            {ROLES.map((r) => (
              <label key={r.value} className={`flex cursor-pointer items-start gap-2.5 rounded-md border px-3 py-2 text-sm ${role === r.value ? "border-[var(--color-accent)] bg-[var(--color-accent)]/10" : "border-[var(--color-line)]"}`}>
                <input type="radio" name="role" className="mt-1" checked={role === r.value} onChange={() => setRole(r.value)} />
                <span>
                  <span className="block font-medium">{r.label}</span>
                  <span className="text-xs text-[var(--color-muted)]">{r.hint}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>
        <fieldset>
          <legend className="mb-1.5 text-xs font-medium text-[var(--color-muted)]">Password</legend>
          <div className="flex gap-4 text-sm">
            <label className="flex items-center gap-1.5"><input type="radio" checked={mode === "temp"} onChange={() => setMode("temp")} /> Generate a temporary password</label>
            <label className="flex items-center gap-1.5"><input type="radio" checked={mode === "set"} onChange={() => setMode("set")} /> Set one now</label>
          </div>
          {mode === "set" && (
            <div className="mt-3 space-y-3">
              <PasswordInput value={password} onChange={setPassword} autoComplete="new-password" />
              <PasswordChecklist password={password} username={uname} />
            </div>
          )}
          <p className="mt-2 text-xs text-[var(--color-faint)]">Either way, the user must choose their own password at first sign-in.</p>
        </fieldset>
        <ErrorNote error={error} />
      </form>
    </Modal>
  );
}
