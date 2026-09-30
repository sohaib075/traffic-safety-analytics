export const API_BASE = (process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8010").replace(/\/$/, "");

const TOKEN_KEY = "roadguard.token";

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable */
  }
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (res.status === 401 && typeof window !== "undefined" && !path.startsWith("/api/auth/login")) {
    setToken(null);
    if (!window.location.pathname.startsWith("/login")) window.location.href = "/login";
  }
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = await res.json();
      msg = typeof body.detail === "string" ? body.detail : formatValidation(body.detail) ?? JSON.stringify(body);
    } catch {
      /* not json */
    }
    if (res.status === 403 && msg === "password_change_required" && typeof window !== "undefined" &&
        !window.location.pathname.startsWith("/account")) {
      window.location.href = "/account?required=1";
    }
    throw new ApiError(res.status, msg);
  }
  const ct = res.headers.get("content-type") || "";
  return (ct.includes("application/json") ? res.json() : res.blob()) as Promise<T>;
}

/** FastAPI 422 bodies are lists of {loc, msg}; turn them into one readable sentence. */
function formatValidation(detail: unknown): string | null {
  if (!Array.isArray(detail)) return null;
  return detail
    .map((d: any) => `${(d.loc ?? []).filter((x: unknown) => x !== "body").join(".")}: ${d.msg}`)
    .join("; ");
}

/** Absolute URL for media (img/video src) that carries the token as a query param. */
export function mediaUrl(path: string | null | undefined): string | undefined {
  if (!path) return undefined;
  const token = getToken();
  const sep = path.includes("?") ? "&" : "?";
  return `${API_BASE}${path}${token ? `${sep}token=${encodeURIComponent(token)}` : ""}`;
}

export function wsUrl(): string {
  const token = getToken();
  return `${API_BASE.replace(/^http/, "ws")}/ws${token ? `?token=${encodeURIComponent(token)}` : ""}`;
}

export function qs(params: Record<string, string | number | undefined | null | false>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "" && v !== false) p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}
