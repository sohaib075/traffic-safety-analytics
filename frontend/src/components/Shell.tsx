"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  BarChart3,
  Bot,
  Clapperboard,
  FileText,
  LayoutDashboard,
  LogOut,
  Map as MapIcon,
  Menu,
  Search,
  Settings,
  ShieldCheck,
  Users,
  X,
} from "lucide-react";
import { useApp } from "@/lib/state";

const NAV = [
  { href: "/", label: "Command", icon: LayoutDashboard, perm: "view" },
  { href: "/analyze", label: "Analyze video", icon: Clapperboard, perm: "process" },
  { href: "/incidents", label: "Investigator", icon: Search, perm: "view" },
  { href: "/map", label: "Risk Map", icon: MapIcon, perm: "view" },
  { href: "/analytics", label: "Analytics", icon: BarChart3, perm: "view" },
  { href: "/analyst", label: "AI Analyst", icon: Bot, perm: "view" },
  { href: "/reports", label: "Reports", icon: FileText, perm: "report" },
  { href: "/admin", label: "Admin", icon: Settings, perm: "process" },
  { href: "/users", label: "Users", icon: Users, perm: "manage_users", authOnly: true },
];

const PUBLIC = ["/login", "/setup"];
// Pages that only make sense when accounts are switched on (ROADGUARD_AUTH=1).
const AUTH_PAGES = ["/login", "/setup", "/account", "/users"];

function initials(name: string) {
  return name.split(/[\s._-]+/).filter(Boolean).slice(0, 2).map((p) => p[0]!.toUpperCase()).join("") || "?";
}

export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const { me, ready, can, logout, day, setDay, extent, live } = useApp();
  const [open, setOpen] = useState(false);

  const authOn = me?.auth_enabled !== false;
  const isPublic = PUBLIC.includes(path) && authOn;
  const locked = authOn && !!me?.must_change_password;

  useEffect(() => {
    if (!ready) return;
    if (me && !authOn && AUTH_PAGES.includes(path)) router.replace("/"); // local mode: no login pages
    else if (!me && !isPublic) router.replace("/login");
    else if (locked && path !== "/account") router.replace("/account?required=1");
  }, [ready, me, authOn, isPublic, locked, path, router]);

  useEffect(() => {
    setOpen(false);
  }, [path]);

  if (isPublic) return <>{children}</>;
  if (me && !authOn && AUTH_PAGES.includes(path)) return null;
  if (!ready || !me) {
    return <div className="grid h-screen place-items-center text-sm text-[var(--color-muted)]">Connecting to RoadGuard…</div>;
  }
  if (locked) {
    // Until the temporary / default password is replaced, only the account page is reachable.
    return (
      <div className="min-h-screen">
        <header className="flex h-14 items-center gap-2 border-b border-[var(--color-line)] px-4">
          <ShieldCheck className="h-5 w-5 text-[var(--color-accent)]" />
          <span className="font-semibold tracking-wide">ROADGUARD AI</span>
          <button className="btn ml-auto py-1 text-xs" onClick={logout}>
            <LogOut className="h-3.5 w-3.5" /> Sign out
          </button>
        </header>
        <main className="p-4 md:p-6">{children}</main>
      </div>
    );
  }

  const liveCams = Object.keys(live.progress);

  return (
    <div className="flex min-h-screen">
      {/* sidebar */}
      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-56 shrink-0 flex-col border-r border-[var(--color-line)] bg-[var(--color-panel)] transition-transform md:sticky md:top-0 md:h-screen md:translate-x-0 ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex h-14 items-center gap-2 border-b border-[var(--color-line)] px-4">
          <ShieldCheck className="h-5 w-5 text-[var(--color-accent)]" />
          <span className="font-semibold tracking-wide">ROADGUARD AI</span>
          <button className="ml-auto md:hidden" onClick={() => setOpen(false)} aria-label="Close menu">
            <X className="h-4 w-4" />
          </button>
        </div>
        <nav className="flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto p-2">
          {NAV.filter((n) => can(n.perm) && (authOn || !n.authOnly)).map((n) => {
            const active = n.href === "/" ? path === "/" : path.startsWith(n.href);
            return (
              <Link
                key={n.href}
                href={n.href}
                className={`flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors ${
                  active
                    ? "bg-[var(--color-panel-2)] text-white"
                    : "text-[var(--color-muted)] hover:bg-[var(--color-panel-2)] hover:text-white"
                }`}
              >
                <n.icon className={`h-4 w-4 ${active ? "text-[var(--color-accent)]" : ""}`} />
                {n.label}
              </Link>
            );
          })}
        </nav>
        <div className="shrink-0 border-t border-[var(--color-line)] p-2 text-xs">
          {!authOn ? (
            <div className="flex items-center gap-2.5 p-1.5 text-[var(--color-muted)]" title="Login is switched off (ROADGUARD_AUTH=1 turns it on)">
              <span className="h-2 w-2 rounded-full bg-[var(--color-ok)]" /> Local mode · no login
            </div>
          ) : (
          <div className="flex items-center gap-1">
            <Link
              href="/account"
              className={`flex min-w-0 flex-1 items-center gap-2.5 rounded-md p-1.5 hover:bg-[var(--color-panel-2)] ${path === "/account" ? "bg-[var(--color-panel-2)]" : ""}`}
              title="Account settings"
            >
              <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-[var(--color-accent)]/20 text-[11px] font-semibold text-[var(--color-accent)]">
                {initials(me.full_name || me.username)}
              </span>
              <span className="min-w-0">
                <span className="block truncate font-medium text-[var(--color-ink)]">{me.full_name || me.username}</span>
                <span className="block truncate text-[var(--color-muted)]">{me.role_label ?? me.role}</span>
              </span>
            </Link>
            <button className="btn px-2 py-1.5" onClick={logout} title="Sign out" aria-label="Sign out">
              <LogOut className="h-3.5 w-3.5" />
            </button>
          </div>
          )}
        </div>
      </aside>
      {open && <div className="fixed inset-0 z-30 bg-black/50 md:hidden" onClick={() => setOpen(false)} />}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-[var(--color-line)] bg-[var(--color-bg)]/90 px-4 backdrop-blur">
          <button className="md:hidden" onClick={() => setOpen(true)} aria-label="Open menu">
            <Menu className="h-5 w-5" />
          </button>
          <div className="flex items-center gap-2 text-sm">
            <span className="hidden text-[var(--color-muted)] sm:inline">Day</span>
            <input
              type="date"
              className="input py-1"
              value={day ?? ""}
              onChange={(e) => setDay(e.target.value || null)}
              max={extent.last?.slice(0, 10)}
            />
            <button className={`btn py-1 ${day === null ? "border-[var(--color-accent)]" : ""}`} onClick={() => setDay(null)}>
              All
            </button>
            {extent.last && day !== extent.last.slice(0, 10) && (
              <button className="btn hidden py-1 sm:inline-flex" onClick={() => setDay(extent.last!.slice(0, 10))}>
                Latest
              </button>
            )}
          </div>
          <div className="ml-auto flex items-center gap-3 text-xs">
            {liveCams.length > 0 && (
              <span className="flex items-center gap-1.5 rounded-full bg-red-500/10 px-2.5 py-1 text-red-300">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-red-400" />
                PROCESSING {liveCams.length}
              </span>
            )}
            <span className="flex items-center gap-1.5 text-[var(--color-muted)]">
              <span className={`h-2 w-2 rounded-full ${live.connected ? "bg-[var(--color-ok)]" : "bg-[var(--color-faint)]"}`} />
              <span className="hidden sm:inline">{live.connected ? "SYSTEM ONLINE" : "RECONNECTING"}</span>
            </span>
          </div>
        </header>
        <main className="min-w-0 flex-1 p-4 md:p-5">{children}</main>
      </div>
    </div>
  );
}
