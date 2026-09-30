"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AlertTriangle, BarChart3, Film, Map as MapIcon, ShieldCheck } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useApp } from "@/lib/state";
import { Field, PasswordInput } from "@/components/forms";

export default function LoginPage() {
  const { login, me, ready } = useApp();
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<{ setup_needed: boolean }>("/api/auth/status")
      .then((s) => s.setup_needed && router.replace("/setup"))
      .catch(() => setError("Can't reach the RoadGuard API. Is the backend running on port 8010?"));
  }, [router]);

  useEffect(() => {
    if (ready && me) router.replace(me.must_change_password ? "/account?required=1" : "/");
  }, [ready, me, router]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const m = await login(username.trim(), password);
      router.replace(m.must_change_password ? "/account?required=1" : "/");
    } catch (err) {
      const status = err instanceof ApiError ? err.status : 0;
      setError(status === 0 ? "Can't reach the RoadGuard API." : (err as Error).message);
      setPassword("");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid min-h-screen lg:grid-cols-[1.1fr_1fr]">
      {/* brand panel */}
      <div className="relative hidden overflow-hidden border-r border-[var(--color-line)] bg-[var(--color-panel)] p-12 lg:flex lg:flex-col">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-6 w-6 text-[var(--color-accent)]" />
          <span className="text-lg font-semibold tracking-wide">ROADGUARD AI</span>
        </div>
        <div className="my-auto max-w-md">
          <h1 className="text-3xl font-semibold leading-tight">See the road. Understand the risk. Investigate every incident.</h1>
          <ul className="mt-8 space-y-4 text-sm text-[var(--color-muted)]">
            {[
              [Film, "Detection, tracking and evidence clips for every potential incident"],
              [MapIcon, "Risk heatmaps and zone rankings across cameras"],
              [BarChart3, "Traffic analytics, AI analyst and daily PDF reports"],
            ].map(([Icon, text], i) => {
              const I = Icon as typeof Film;
              return (
                <li key={i} className="flex items-start gap-3">
                  <I className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-accent)]" />
                  {text as string}
                </li>
              );
            })}
          </ul>
        </div>
        <p className="text-xs text-[var(--color-faint)]">Access is logged. Evidence is restricted by role.</p>
      </div>

      {/* form */}
      <div className="grid place-items-center p-6">
        <div className="w-full max-w-sm">
          <div className="mb-8 lg:hidden">
            <ShieldCheck className="mb-3 h-9 w-9 text-[var(--color-accent)]" />
            <div className="text-xl font-semibold tracking-wide">ROADGUARD AI</div>
          </div>
          <h2 className="text-xl font-semibold">Sign in</h2>
          <p className="mt-1 text-sm text-[var(--color-muted)]">Use the account your administrator created for you.</p>

          <form onSubmit={submit} className="mt-6 space-y-4">
            <Field label="Username">
              <input
                className="input w-full"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                autoCapitalize="none"
                spellCheck={false}
                autoFocus
              />
            </Field>
            <Field label="Password">
              <PasswordInput value={password} onChange={setPassword} />
            </Field>
            {error && (
              <div role="alert" className="flex items-start gap-2 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> {error}
              </div>
            )}
            <button className="btn btn-primary w-full justify-center py-2" disabled={busy || !username || !password}>
              {busy ? "Signing in…" : "Sign in"}
            </button>
          </form>
          <p className="mt-6 text-xs leading-relaxed text-[var(--color-faint)]">
            Forgot your password? Ask an administrator to reset it. Administrators locked out can run{" "}
            <code className="text-[var(--color-muted)]">python -m roadguard.cli reset-password --username &lt;name&gt;</code> on the server.
          </p>
        </div>
      </div>
    </div>
  );
}
