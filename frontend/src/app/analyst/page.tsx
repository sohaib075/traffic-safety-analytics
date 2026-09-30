"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Bot, Send, User, Wrench } from "lucide-react";
import { api, mediaUrl } from "@/lib/api";
import { fmtTime } from "@/lib/format";
import type { Incident } from "@/lib/types";
import { EventBadge, SeverityBadge } from "@/components/ui";

interface Msg {
  role: "user" | "assistant";
  content: string;
  evidence?: Incident[];
  engine?: string;
  tools?: { tool: string; args: Record<string, unknown> }[];
}

const SUGGESTIONS = [
  "What were the major safety events today?",
  "Which location had the highest event density?",
  "Show me the evidence",
  "Serious events between 5 PM and 8 PM",
  "How busy was traffic?",
  "When is traffic expected to peak?",
];

export default function AnalystPage() {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth" });
  }, [msgs, busy]);

  const ask = async (q: string) => {
    if (!q.trim() || busy) return;
    const history = msgs.map(({ role, content }) => ({ role, content }));
    setMsgs((m) => [...m, { role: "user", content: q }]);
    setInput("");
    setBusy(true);
    try {
      const res = await api<{ answer: string; evidence: Incident[]; engine: string; tools_used: Msg["tools"] }>("/api/analyst", {
        method: "POST",
        body: JSON.stringify({ question: q, history }),
      });
      setMsgs((m) => [...m, { role: "assistant", content: res.answer, evidence: res.evidence, engine: res.engine, tools: res.tools_used }]);
    } catch (e: any) {
      setMsgs((m) => [...m, { role: "assistant", content: `Error: ${e.message}` }]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto flex h-[calc(100vh-96px)] max-w-4xl flex-col">
      <div className="flex-1 space-y-4 overflow-y-auto pb-4">
        {msgs.length === 0 && (
          <div className="pt-10 text-center">
            <Bot className="mx-auto h-10 w-10 text-[var(--color-accent)]" />
            <h1 className="mt-3 text-xl font-semibold">AI Traffic Analyst</h1>
            <p className="mx-auto mt-2 max-w-lg text-sm text-[var(--color-muted)]">
              Ask about traffic and safety events. Answers come from the structured incident database through query tools, and cite
              the incident records they rely on.
            </p>
            <div className="mx-auto mt-6 flex max-w-2xl flex-wrap justify-center gap-2">
              {SUGGESTIONS.map((s) => (
                <button key={s} className="btn text-xs" onClick={() => ask(s)}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {msgs.map((m, i) => (
          <div key={i} className={`flex gap-3 ${m.role === "user" ? "justify-end" : ""}`}>
            {m.role === "assistant" && <Bot className="mt-1 h-5 w-5 shrink-0 text-[var(--color-accent)]" />}
            <div className={`max-w-[85%] space-y-2 ${m.role === "user" ? "rounded-lg bg-[var(--color-accent)]/15 px-3 py-2" : ""}`}>
              <p className="whitespace-pre-wrap text-sm leading-relaxed">{m.content}</p>
              {m.evidence && m.evidence.length > 0 && (
                <div className="grid gap-2 sm:grid-cols-2">
                  {m.evidence.map((e) => (
                    <Link key={e.id} href={`/incidents?id=${e.id}`} className="panel block overflow-hidden hover:border-[var(--color-accent)]">
                      {e.clip_url ? (
                        <video src={mediaUrl(e.clip_url)} muted loop autoPlay playsInline className="aspect-video w-full bg-black object-cover" />
                      ) : e.snapshot_url ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={mediaUrl(e.snapshot_url)} alt="" className="aspect-video w-full object-cover" />
                      ) : null}
                      <div className="flex items-center justify-between gap-2 px-2.5 py-1.5 text-xs">
                        <EventBadge t={e.type} />
                        <span className="num text-[var(--color-muted)]">{fmtTime(e.occurred_at, false)}</span>
                        <SeverityBadge s={e.severity} />
                      </div>
                    </Link>
                  ))}
                </div>
              )}
              {m.role === "assistant" && m.engine && (
                <div className="flex flex-wrap items-center gap-2 text-[11px] text-[var(--color-faint)]">
                  <span>{m.engine}</span>
                  {m.tools?.map((t, n) => (
                    <span key={n} className="inline-flex items-center gap-1 rounded bg-[var(--color-panel-2)] px-1.5 py-0.5">
                      <Wrench className="h-3 w-3" /> {t.tool}
                    </span>
                  ))}
                </div>
              )}
            </div>
            {m.role === "user" && <User className="mt-1 h-5 w-5 shrink-0 text-[var(--color-muted)]" />}
          </div>
        ))}
        {busy && <div className="pl-8 text-sm text-[var(--color-muted)]">Querying incident database…</div>}
        <div ref={end} />
      </div>
      <form
        className="flex gap-2 border-t border-[var(--color-line)] pt-3"
        onSubmit={(e) => {
          e.preventDefault();
          ask(input);
        }}
      >
        <input className="input flex-1" placeholder="Ask about traffic, events, locations…" value={input} onChange={(e) => setInput(e.target.value)} />
        <button className="btn btn-primary" disabled={busy || !input.trim()}>
          <Send className="h-4 w-4" />
        </button>
      </form>
    </div>
  );
}
