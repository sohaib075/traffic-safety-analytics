"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api, setToken, wsUrl } from "./api";
import type { Incident, LiveProgress, Me } from "./types";

interface AppState {
  me: Me | null;
  ready: boolean;
  can: (perm: string) => boolean;
  login: (u: string, p: string) => Promise<Me>;
  /** Store a session returned by login / setup / change-password. */
  setSession: (res: Me & { token: string }) => void;
  refreshMe: () => Promise<void>;
  logout: () => void;
  day: string | null; // YYYY-MM-DD or null = all time
  setDay: (d: string | null) => void;
  extent: { first: string | null; last: string | null };
  refreshExtent: () => void;
  live: {
    connected: boolean;
    incidents: Incident[]; // newest first, pushed over WebSocket this session
    progress: Record<string, LiveProgress>; // by camera id
    tick: number; // bumps on any live event; pages use it to refetch
  };
}

const Ctx = createContext<AppState | null>(null);

export function useApp() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useApp outside provider");
  return v;
}

const DAY_KEY = "roadguard.day";

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [ready, setReady] = useState(false);
  const [day, setDayState] = useState<string | null>(null);
  const [extent, setExtent] = useState<{ first: string | null; last: string | null }>({ first: null, last: null });
  const [connected, setConnected] = useState(false);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [progress, setProgress] = useState<Record<string, LiveProgress>>({});
  const [tick, setTick] = useState(0);
  const wsRef = useRef<WebSocket | null>(null);

  const refreshExtent = useCallback(() => {
    api<{ first: string | null; last: string | null }>("/api/stats/extent")
      .then((e) => {
        setExtent(e);
        setDayState((cur) => {
          if (cur !== null) return cur;
          let stored: string | null = null;
          try {
            stored = localStorage.getItem(DAY_KEY);
          } catch {
            /* ignore */
          }
          if (stored) return stored === "all" ? null : stored;
          return e.last ? e.last.slice(0, 10) : new Date().toISOString().slice(0, 10);
        });
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    // Probe /me even without a token: the backend may run with auth disabled.
    api<Me>("/api/auth/me")
      .then((m) => {
        setMe(m);
        if (!m.must_change_password) refreshExtent();
      })
      .catch(() => setMe(null))
      .finally(() => setReady(true));
  }, [refreshExtent]);

  const blocked = !me || me.must_change_password;

  // WebSocket for live incidents + processing progress.
  useEffect(() => {
    if (blocked) return;
    let stopped = false;
    let retry: ReturnType<typeof setTimeout>;
    let ping: ReturnType<typeof setInterval>;
    const connect = () => {
      const ws = new WebSocket(wsUrl());
      wsRef.current = ws;
      ws.onopen = () => {
        setConnected(true);
        ping = setInterval(() => ws.readyState === 1 && ws.send("ping"), 20000);
      };
      ws.onclose = () => {
        setConnected(false);
        clearInterval(ping);
        if (!stopped) retry = setTimeout(connect, 3000);
      };
      ws.onmessage = (m) => {
        const msg = JSON.parse(m.data) as { kind: string; data: any };
        if (msg.kind === "incident") {
          const inc = msg.data as Incident;
          setIncidents((cur) => {
            const i = cur.findIndex((c) => c.id === inc.id);
            if (i >= 0) {
              const next = cur.slice();
              next[i] = inc;
              return next;
            }
            return inc._update ? cur : [inc, ...cur].slice(0, 100);
          });
          setTick((t) => t + 1);
        } else if (msg.kind === "progress") {
          const p = msg.data as LiveProgress;
          if (p.camera_id) setProgress((cur) => ({ ...cur, [p.camera_id!]: p }));
        } else if (msg.kind === "job_done") {
          setProgress((cur) => {
            const next = { ...cur };
            delete next[msg.data.camera_id];
            return next;
          });
          setTick((t) => t + 1);
          refreshExtent();
        }
      };
    };
    connect();
    return () => {
      stopped = true;
      clearTimeout(retry);
      clearInterval(ping);
      wsRef.current?.close();
    };
  }, [blocked, refreshExtent]);

  const setSession = useCallback(
    (res: Me & { token: string }) => {
      const { token, ...m } = res;
      setToken(token);
      setMe(m);
      if (!m.must_change_password) refreshExtent();
    },
    [refreshExtent],
  );

  const login = async (username: string, password: string) => {
    const res = await api<Me & { token: string }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    setSession(res);
    return res;
  };

  const refreshMe = async () => {
    setMe(await api<Me>("/api/auth/me"));
  };

  const logout = () => {
    setToken(null);
    setMe(null);
    window.location.href = "/login";
  };

  const setDay = (d: string | null) => {
    setDayState(d);
    try {
      localStorage.setItem(DAY_KEY, d ?? "all");
    } catch {
      /* ignore */
    }
  };

  const can = (perm: string) => !!me?.permissions.includes(perm);

  return (
    <Ctx.Provider
      value={{
        me,
        ready,
        can,
        login,
        setSession,
        refreshMe,
        logout,
        day,
        setDay,
        extent,
        refreshExtent,
        live: { connected, incidents, progress, tick },
      }}
    >
      {children}
    </Ctx.Provider>
  );
}

/** Fetch helper that refetches when deps change; returns [data, error, loading, reload]. */
export function useFetch<T>(path: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [n, setN] = useState(0);
  useEffect(() => {
    if (!path) return;
    let alive = true;
    setLoading(true);
    api<T>(path)
      .then((d) => alive && (setData(d), setError(null)))
      .catch((e) => alive && setError(String(e.message || e)))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, n, ...deps]);
  return { data, error, loading, reload: () => setN((x) => x + 1) };
}
