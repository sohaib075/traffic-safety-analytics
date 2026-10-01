"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  BarChart3,
  Bot,
  CalendarDays,
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
import type { LucideIcon } from "lucide-react";
import { useApp } from "@/lib/state";

type NavItem = { href: string; label: string; icon: LucideIcon; perm: string; authOnly?: boolean; hint: string };

const NAV_GROUPS: { label: string; items: NavItem[] }[] = [
  {
    label: "Monitor",
    items: [
      { href: "/", label: "Command center", icon: LayoutDashboard, perm: "view", hint: "Live overview of traffic, risk and incidents" },
      { href: "/analyze", label: "Analyze video", icon: Clapperboard, perm: "process", hint: "Upload any traffic video for automatic analysis" },
    ],
  },
  {
    label: "Investigate",
    items: [
      { href: "/incidents", label: "Investigator", icon: Search, perm: "view", hint: "Search, review and verify incidents with evidence" },
      { href: "/map", label: "Risk map", icon: MapIcon, perm: "view", hint: "Where potential safety events concentrate" },
    ],
  },
  {
    label: "Insights",
    items: [
      { href: "/analytics", label: "Analytics", icon: BarChart3, perm: "view", hint: "Traffic volume, events over time and forecasts" },
      { href: "/analyst", label: "AI analyst", icon: Bot, perm: "view", hint: "Ask questions about traffic and safety events" },
      { href: "/reports", label: "Reports", icon: FileText, perm: "report", hint: "Daily road safety reports as PDF" },
    ],
  },
  {
    label: "System",
    items: [
      { href: "/admin", label: "Admin", icon: Settings, perm: "process", hint: "Processing jobs, cameras and audit log" },
      { href: "/users", label: "Users", icon: Users, perm: "manage_users", authOnly: true, hint: "Accounts and roles" },
    ],
  },
];
const ALL_NAV = NAV_GROUPS.flatMap((g) => g.items);

const PUBLIC = ["/login", "/setup"];
// Pages that only make sense when accounts are switched on (ROADGUARD_AUTH=1).
const AUTH_PAGES = ["/login", "/setup", "/account", "/users"];

function initials(name: string) {
  return name.split(/[\s._-]+/).filter(Boolean).slice(0, 2).map((p) => p[0]!.toUpperCase()).join("") || "?";
}

export function Logo({ light = true }: { light?: boolean }) {
  return (
    <span className="flex items-center gap-2.5">
      <span className="grid h-8 w-8 place-items-center rounded-lg bg-gradient-to-br from-blue-500 to-indigo-600 shadow-md shadow-blue-900/30">
        <ShieldCheck className="h-[18px] w-[18px] text-white" />
      </span>
      <span className={`text-[15px] font-semibold tracking-tight ${light ? "text-white" : "text-[var(--color-ink)]"}`}>
        RoadGuard <span className={light ? "text-blue-300" : "text-[var(--color-accent)]"}>AI</span>
      </span>
    </span>
  );
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
    return (
      <div className="grid h-screen place-items-center">
        <div className="flex flex-col items-center gap-3 text-sm text-[var(--color-muted)]">
          <Logo light={false} />
          <span className="flex items-center gap-2"><span className="h-2 w-2 animate-pulse rounded-full bg-[var(--color-accent)]" /> Connecting…</span>
        </div>
      </div>
    );
  }
  if (locked) {
    // Until the temporary / default password is replaced, only the account page is reachable.
    return (
      <div className="min-h-screen">
        <header className="flex h-16 items-center gap-2 border-b border-[var(--color-line)] bg-white px-5">
          <Logo light={false} />
          <button className="btn ml-auto" onClick={logout}>
            <LogOut className="h-4 w-4" /> Sign out
          </button>
        </header>
        <main className="p-4 md:p-8">{children}</main>
      </div>
    );
  }

  const liveCams = Object.keys(live.progress);
  const current = ALL_NAV.find((n) => (n.href === "/" ? path === "/" : path.startsWith(n.href)));
  const today = extent.last?.slice(0, 10);

  return (
    <div className="flex min-h-screen">
      {/* ---------------------------------------------------------------- sidebar */}
      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-64 shrink-0 flex-col bg-[var(--color-nav)] text-[var(--color-nav-ink)] transition-transform md:sticky md:top-0 md:h-screen md:translate-x-0 ${
          open ? "translate-x-0 shadow-2xl" : "-translate-x-full"
        }`}
      >
        <div className="flex h-16 shrink-0 items-center px-5">
          <Link href="/" aria-label="RoadGuard AI home">
            <Logo />
          </Link>
          <button className="ml-auto rounded-md p-1 text-[var(--color-nav-muted)] hover:text-white md:hidden" onClick={() => setOpen(false)} aria-label="Close menu">
            <X className="h-5 w-5" />
          </button>
        </div>

        <nav className="min-h-0 flex-1 space-y-5 overflow-y-auto px-3 py-3">
          {NAV_GROUPS.map((g) => {
            const items = g.items.filter((n) => can(n.perm) && (authOn || !n.authOnly));
            if (!items.length) return null;
            return (
              <div key={g.label}>
                <div className="mb-1.5 px-3 text-[11px] font-semibold uppercase tracking-[0.08em] text-[var(--color-nav-muted)]/80">{g.label}</div>
                <div className="space-y-0.5">
                  {items.map((n) => {
                    const active = n === current;
                    return (
                      <Link
                        key={n.href}
                        href={n.href}
                        title={n.hint}
                        aria-current={active ? "page" : undefined}
                        className={`group relative flex items-center gap-3 rounded-lg px-3 py-2 text-[13.5px] font-medium transition-colors ${
                          active ? "bg-white/10 text-white" : "text-[var(--color-nav-muted)] hover:bg-white/5 hover:text-white"
                        }`}
                      >
                        {active && <span className="absolute inset-y-1.5 left-0 w-1 rounded-r-full bg-blue-400" />}
                        <n.icon className={`h-[18px] w-[18px] ${active ? "text-blue-300" : "text-[var(--color-nav-muted)] group-hover:text-white"}`} />
                        {n.label}
                      </Link>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </nav>

        <div className="shrink-0 border-t border-white/10 p-3 text-xs">
          {!authOn ? (
            <div className="flex items-center gap-3 rounded-lg bg-white/5 px-3 py-2.5" title="Login is switched off (ROADGUARD_AUTH=1 turns it on)">
              <span className="grid h-8 w-8 place-items-center rounded-full bg-emerald-400/15 text-emerald-300">
                <ShieldCheck className="h-4 w-4" />
              </span>
              <span className="min-w-0">
                <span className="block font-medium text-white">Local mode</span>
                <span className="block text-[var(--color-nav-muted)]">Full access · no login</span>
              </span>
            </div>
          ) : (
            <div className="flex items-center gap-1">
              <Link
                href="/account"
                className={`flex min-w-0 flex-1 items-center gap-2.5 rounded-lg p-2 hover:bg-white/5 ${path === "/account" ? "bg-white/10" : ""}`}
                title="Account settings"
              >
                <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-blue-500/25 text-[11px] font-semibold text-blue-200">
                  {initials(me.full_name || me.username)}
                </span>
                <span className="min-w-0">
                  <span className="block truncate font-medium text-white">{me.full_name || me.username}</span>
                  <span className="block truncate text-[var(--color-nav-muted)]">{me.role_label ?? me.role}</span>
                </span>
              </Link>
              <button className="rounded-lg p-2 text-[var(--color-nav-muted)] hover:bg-white/5 hover:text-white" onClick={logout} title="Sign out" aria-label="Sign out">
                <LogOut className="h-4 w-4" />
              </button>
            </div>
          )}
        </div>
      </aside>
      {open && <div className="fixed inset-0 z-30 bg-slate-900/40 backdrop-blur-[1px] md:hidden" onClick={() => setOpen(false)} />}

      {/* ---------------------------------------------------------------- main */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-16 items-center gap-3 border-b border-[var(--color-line)] bg-white/90 px-4 backdrop-blur md:px-8">
          <button className="rounded-lg p-1.5 text-[var(--color-muted)] hover:bg-[var(--color-panel-2)] md:hidden" onClick={() => setOpen(true)} aria-label="Open menu">
            <Menu className="h-5 w-5" />
          </button>
          <div className="hidden min-w-0 lg:block">
            <div className="truncate text-[15px] font-semibold tracking-tight">{current?.label ?? "RoadGuard AI"}</div>
            <div className="truncate text-xs text-[var(--color-faint)]">{current?.hint}</div>
          </div>

          <div className="ml-auto flex items-center gap-2">
            <div className="flex items-center gap-1 rounded-xl border border-[var(--color-line)] bg-[var(--color-panel-2)] p-1">
              <label className="flex items-center gap-1.5 rounded-lg bg-white px-2 py-1 shadow-sm ring-1 ring-[var(--color-line)]">
                <CalendarDays className="h-4 w-4 text-[var(--color-faint)]" />
                <span className="sr-only">Day</span>
                <input
                  type="date"
                  className="w-[124px] bg-transparent text-[13px] text-[var(--color-ink)] outline-none"
                  value={day ?? ""}
                  onChange={(e) => setDay(e.target.value || null)}
                  max={today}
                />
              </label>
              {today && day !== today && (
                <button className="hidden rounded-lg px-2.5 py-1 text-[13px] font-medium text-[var(--color-muted)] hover:bg-white hover:text-[var(--color-ink)] sm:block" onClick={() => setDay(today)}>
                  Latest
                </button>
              )}
              <button
                className={`rounded-lg px-2.5 py-1 text-[13px] font-medium ${day === null ? "bg-white text-[var(--color-accent)] shadow-sm ring-1 ring-[var(--color-line)]" : "text-[var(--color-muted)] hover:bg-white hover:text-[var(--color-ink)]"}`}
                onClick={() => setDay(null)}
              >
                All time
              </button>
            </div>

            {liveCams.length > 0 && (
              <span className="hidden items-center gap-1.5 rounded-full bg-red-50 px-3 py-1.5 text-xs font-semibold text-red-700 ring-1 ring-inset ring-red-200 sm:flex">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-red-500" />
                Processing {liveCams.length}
              </span>
            )}
            <span
              className={`flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-semibold ring-1 ring-inset ${
                live.connected ? "bg-emerald-50 text-emerald-700 ring-emerald-200" : "bg-slate-100 text-slate-600 ring-slate-200"
              }`}
              title={live.connected ? "Live connection to the RoadGuard engine" : "Reconnecting to the RoadGuard engine"}
            >
              <span className={`h-2 w-2 rounded-full ${live.connected ? "bg-emerald-500" : "bg-slate-400"}`} />
              <span className="hidden sm:inline">{live.connected ? "Online" : "Reconnecting"}</span>
            </span>
          </div>
        </header>
        <main className="min-w-0 flex-1 px-4 py-6 md:px-8">{children}</main>
      </div>
    </div>
  );
}
