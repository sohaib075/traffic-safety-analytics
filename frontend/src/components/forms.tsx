"use client";

import { createContext, useCallback, useContext, useEffect, useId, useRef, useState } from "react";
import { Check, Circle, Copy, Eye, EyeOff, X } from "lucide-react";

/* ------------------------------------------------------------------ password policy (mirrors backend auth.py) */
export const MIN_PASSWORD = 10;

export function passwordChecks(pw: string, username = "") {
  const classes = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((r) => r.test(pw)).length;
  return [
    { ok: pw.length >= MIN_PASSWORD, label: `At least ${MIN_PASSWORD} characters` },
    { ok: classes >= 3, label: "3 of: lowercase, uppercase, number, symbol" },
    { ok: !username || !pw.toLowerCase().includes(username.toLowerCase()), label: "Doesn't contain the username" },
  ];
}

export function passwordScore(pw: string): 0 | 1 | 2 | 3 | 4 {
  if (!pw) return 0;
  const classes = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((r) => r.test(pw)).length;
  const s = (pw.length >= MIN_PASSWORD ? 1 : 0) + (pw.length >= 14 ? 1 : 0) + (classes >= 3 ? 1 : 0) + (classes === 4 ? 1 : 0);
  return Math.min(4, Math.max(1, s)) as 1 | 2 | 3 | 4;
}

const STRENGTH = [
  { label: "", color: "transparent" },
  { label: "Weak", color: "#ef4444" },
  { label: "Fair", color: "#f59e0b" },
  { label: "Good", color: "#84cc16" },
  { label: "Strong", color: "#22c55e" },
];

export function PasswordChecklist({ password, username }: { password: string; username?: string }) {
  const score = passwordScore(password);
  return (
    <div className="space-y-2 text-xs">
      <div className="flex items-center gap-2">
        <div className="flex h-1.5 flex-1 gap-1">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="flex-1 rounded-full bg-[var(--color-panel-2)]">
              <div className="h-full rounded-full transition-all" style={{ width: score >= i ? "100%" : 0, background: STRENGTH[score].color }} />
            </div>
          ))}
        </div>
        <span className="w-12 text-right" style={{ color: STRENGTH[score].color }}>{STRENGTH[score].label}</span>
      </div>
      <ul className="space-y-1">
        {passwordChecks(password, username).map((c) => (
          <li key={c.label} className={`flex items-center gap-1.5 ${c.ok ? "text-emerald-600" : "text-[var(--color-muted)]"}`}>
            {c.ok ? <Check className="h-3.5 w-3.5" /> : <Circle className="h-3 w-3" />} {c.label}
          </li>
        ))}
      </ul>
    </div>
  );
}

export const passwordValid = (pw: string, username = "") => passwordChecks(pw, username).every((c) => c.ok);

/* ------------------------------------------------------------------ inputs */
export function Field({ label, hint, error, children }: { label: string; hint?: React.ReactNode; error?: string | null; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-[var(--color-muted)]">{label}</span>
      {children}
      {error ? <span className="mt-1 block text-xs text-red-600">{error}</span> : hint ? <span className="mt-1 block text-xs text-[var(--color-faint)]">{hint}</span> : null}
    </label>
  );
}

export function PasswordInput({ value, onChange, autoComplete = "current-password", placeholder, autoFocus, id }: {
  value: string;
  onChange: (v: string) => void;
  autoComplete?: string;
  placeholder?: string;
  autoFocus?: boolean;
  id?: string;
}) {
  const [show, setShow] = useState(false);
  return (
    <div className="relative">
      <input
        id={id}
        className="input w-full pr-9"
        type={show ? "text" : "password"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoComplete={autoComplete}
        placeholder={placeholder}
        autoFocus={autoFocus}
        spellCheck={false}
      />
      <button
        type="button"
        onClick={() => setShow((s) => !s)}
        className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-1 text-[var(--color-faint)] hover:text-[var(--color-ink)]"
        aria-label={show ? "Hide password" : "Show password"}
        tabIndex={-1}
      >
        {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
      </button>
    </div>
  );
}

/* ------------------------------------------------------------------ modal */
export function Modal({ open, onClose, title, children, footer, width = "max-w-md" }: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
  width?: string;
}) {
  const titleId = useId();
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    ref.current?.querySelector<HTMLElement>("input, select, button")?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-slate-900/40 p-4" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className={`panel flex max-h-[calc(100dvh-2rem)] w-full ${width} flex-col shadow-2xl`}
      >
        <div className="flex shrink-0 items-center border-b border-[var(--color-line)] px-5 py-3">
          <h2 id={titleId} className="font-semibold">{title}</h2>
          <button className="ml-auto rounded p-1 text-[var(--color-muted)] hover:text-[var(--color-ink)]" onClick={onClose} aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-5">{children}</div>
        {footer && <div className="flex shrink-0 justify-end gap-2 border-t border-[var(--color-line)] px-5 py-3">{footer}</div>}
      </div>
    </div>
  );
}

export function ConfirmDialog({ open, title, message, confirmLabel, danger, busy, onConfirm, onClose }: {
  open: boolean;
  title: string;
  message: React.ReactNode;
  confirmLabel: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      footer={
        <>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className={`btn ${danger ? "btn-danger" : "btn-primary"}`} onClick={onConfirm} disabled={busy}>
            {busy ? "Working…" : confirmLabel}
          </button>
        </>
      }
    >
      <div className="text-sm text-[var(--color-muted)]">{message}</div>
    </Modal>
  );
}

/** Shows a one-time secret with a copy button. */
export function SecretBox({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked: user can still select the text */
    }
  };
  return (
    <div className="flex items-center gap-2 rounded-md border border-[var(--color-line)] bg-[var(--color-bg)] px-3 py-2">
      <code className="flex-1 select-all font-mono text-sm">{value}</code>
      <button type="button" className="btn py-1 text-xs" onClick={copy}>
        {copied ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />} {copied ? "Copied" : "Copy"}
      </button>
    </div>
  );
}

/* ------------------------------------------------------------------ toasts */
type Toast = { id: number; text: string; kind: "ok" | "error" };
const ToastCtx = createContext<(text: string, kind?: Toast["kind"]) => void>(() => {});

export function useToast() {
  return useContext(ToastCtx);
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((text: string, kind: Toast["kind"] = "ok") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, text, kind }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 3500);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex flex-col gap-2" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`panel pointer-events-auto flex items-center gap-2 px-4 py-2.5 text-sm shadow-xl ${t.kind === "error" ? "border-red-200" : "border-emerald-200"}`}>
            {t.kind === "error" ? <X className="h-4 w-4 text-red-600" /> : <Check className="h-4 w-4 text-emerald-600" />}
            {t.text}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
