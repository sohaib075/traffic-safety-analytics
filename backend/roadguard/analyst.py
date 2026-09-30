"""AI Traffic Analyst.

The LLM never sees raw video; it answers only through tools that query the structured event
database, and every answer returns the incident records it relied on as evidence. If no
Ollama server is reachable, a deterministic rule-based mode answers the common questions
from the same tools.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Optional

import httpx

from . import analytics, nlq, settings
from .pipeline.rules import EVENT_LABELS
from .pipeline.runner import incident_to_dict

log = logging.getLogger(__name__)


def reference_day() -> date:
    """'Today' if there is data today, otherwise the most recent day with data."""
    ext = analytics.data_extent()
    today = date.today()
    if ext["last"]:
        last = datetime.fromisoformat(ext["last"]).date()
        return today if last >= today else last
    return today


# --------------------------------------------------------------------------- tools
def _range(args: dict) -> analytics.Range:
    d = date.fromisoformat(args["date"]) if args.get("date") else reference_day()
    return analytics.Range.for_day(d, args.get("camera"))


def tool_summary(args: dict) -> dict:
    s = analytics.summary(_range(args))
    return {k: s[k] for k in ("range", "vehicles", "pedestrians", "volume", "events", "risk", "peak_hour", "top_zone", "helmet")}


def tool_zone_ranking(args: dict) -> list[dict]:
    zones = analytics.zone_stats(_range(args))
    key = args.get("event_type")
    zones.sort(key=lambda z: -(z["events"].get(key, 0) if key else z["risk"]["score"]))
    return [{"zone": z["name"], "zone_id": z["id"], "events": z["events"], "events_total": z["events_total"],
             "vehicles": z["vehicles"], "risk_score": z["risk"]["score"], "risk_level": z["risk"]["level"]} for z in zones[:8]]


def tool_search_incidents(args: dict) -> dict:
    total, rows = analytics.search_incidents(
        _range(args), types=args.get("types"), severities=args.get("severities"), zone=args.get("zone_id"),
        hour_from=args.get("hour_from"), hour_to=args.get("hour_to"), limit=int(args.get("limit", 10)),
        status=["new", "confirmed"])
    return {"total": total, "incidents": [
        {"id": i.id, "time": i.occurred_at.strftime("%H:%M:%S"), "type": i.type, "severity": i.severity,
         "zone": i.zone_name, "objects": [f"{c} #{t}" for c, t in zip(i.classes, i.track_ids)], "description": i.description}
        for i in rows]}


def tool_hourly(args: dict) -> list[dict]:
    ts = analytics.timeseries(_range(args), "hour")
    return [{"hour": b["start"][11:16], "vehicles": b["vehicles"], "pedestrians": b["pedestrian"], "events": b["events"]}
            for b in ts["buckets"]]


def tool_forecast(args: dict) -> dict:
    f = analytics.forecast(args.get("camera"))
    return {"expected_congestion_window": f["expected_congestion_window"], "days_of_history": f["days_of_history"],
            "method": f["method"], "hours": [h for h in f["hours"] if h["expected_vehicles"] is not None]}


TOOLS = {
    "get_summary": (tool_summary, "Totals for a day: vehicle volume by class, event counts by type, risk indicator, peak hour, top zone.", {}),
    "rank_zones": (tool_zone_ranking, "Zones ranked by risk indicator (or by one event type).",
                   {"event_type": {"type": "string", "enum": list(EVENT_LABELS)}}),
    "search_incidents": (tool_search_incidents, "Find incident records with filters. Use for evidence and lists.", {
        "types": {"type": "array", "items": {"type": "string", "enum": list(EVENT_LABELS)}},
        "severities": {"type": "array", "items": {"type": "string", "enum": ["low", "medium", "high"]}},
        "zone_id": {"type": "string"},
        "hour_from": {"type": "integer"}, "hour_to": {"type": "integer"},
        "limit": {"type": "integer"},
    }),
    "hourly_traffic": (tool_hourly, "Hour-by-hour vehicle, pedestrian and event counts for a day.", {}),
    "forecast": (tool_forecast, "Statistical hour-of-day traffic baseline and expected congestion window.", {}),
}


def _tool_schemas() -> list[dict]:
    out = []
    for name, (_, desc, props) in TOOLS.items():
        out.append({"type": "function", "function": {"name": name, "description": desc, "parameters": {
            "type": "object",
            "properties": {"date": {"type": "string", "description": "YYYY-MM-DD; omit for the reference day"},
                           "camera": {"type": "string"}, **props}}}})
    return out


# --------------------------------------------------------------------------- answer
def ask(question: str, history: Optional[list[dict]] = None) -> dict:
    history = history or []
    try:
        return _ask_ollama(question, history)
    except Exception as e:
        log.info("Ollama unavailable (%s); using rule-based analyst", e)
        return _ask_rules(question, history)


def _evidence(ids: list[int]) -> list[dict]:
    from .db import Incident, SessionLocal

    if not ids:
        return []
    with SessionLocal() as s:
        rows = s.query(Incident).filter(Incident.id.in_(ids)).all()
    order = {i: n for n, i in enumerate(ids)}
    return [incident_to_dict(i) for i in sorted(rows, key=lambda r: order.get(r.id, 0))]


def _ask_ollama(question: str, history: list[dict]) -> dict:
    day = reference_day()
    system = (
        "You are RoadGuard AI's traffic analyst. Answer ONLY from tool results; never invent numbers. "
        "Events are automatically detected *potential* indicators, not confirmed accidents or violations — word them that way. "
        f"The reference day is {day.isoformat()} (use it when the user says 'today'). Be concise: 1-4 sentences, then key figures. "
        "When the user asks for evidence, call search_incidents."
    )
    messages = [{"role": "system", "content": system}]
    messages += [{"role": m["role"], "content": m["content"]} for m in history[-6:] if m.get("role") in ("user", "assistant")]
    messages.append({"role": "user", "content": question})
    evidence_ids: list[int] = []
    tools_used = []
    with httpx.Client(base_url=settings.OLLAMA_URL, timeout=120) as client:
        client.get("/api/tags", timeout=2).raise_for_status()
        for _ in range(5):
            resp = client.post("/api/chat", json={"model": settings.OLLAMA_MODEL, "messages": messages,
                                                  "tools": _tool_schemas(), "stream": False,
                                                  "options": {"temperature": 0.1}})
            resp.raise_for_status()
            msg = resp.json()["message"]
            messages.append(msg)
            calls = msg.get("tool_calls") or []
            if not calls:
                return {"answer": msg.get("content", "").strip(), "engine": f"ollama:{settings.OLLAMA_MODEL}",
                        "tools_used": tools_used, "evidence": _evidence(evidence_ids[:8]), "reference_day": day.isoformat()}
            for call in calls:
                fn = call["function"]["name"]
                args = call["function"].get("arguments") or {}
                if isinstance(args, str):
                    args = json.loads(args or "{}")
                impl = TOOLS.get(fn, (None,))[0]
                result = impl(args) if impl else {"error": f"unknown tool {fn}"}
                tools_used.append({"tool": fn, "args": args})
                if fn == "search_incidents":
                    evidence_ids += [i["id"] for i in result["incidents"]]
                messages.append({"role": "tool", "content": json.dumps(result, default=str)[:12000]})
    raise RuntimeError("tool loop did not converge")


PLURALS = {
    "near_miss": ("potential near-miss", "potential near-misses"),
    "ped_conflict": ("potential pedestrian conflict", "potential pedestrian conflicts"),
    "red_light": ("red-light event", "red-light events"),
    "wrong_way": ("potential wrong-way event", "potential wrong-way events"),
    "illegal_stop": ("potential illegal stop", "potential illegal stops"),
    "congestion": ("congestion episode", "congestion episodes"),
    "helmet_violation": ("potential helmet violation", "potential helmet violations"),
}


def _n(n: int, etype: str) -> str:
    one, many = PLURALS.get(etype, (etype, etype + "s"))
    return f"{n} {one if n == 1 else many}"


def _fmt_events(ev: dict) -> str:
    items = sorted(ev.items(), key=lambda kv: -kv[1])
    return ", ".join(_n(n, k) for k, n in items) or "no events"


def _ask_rules(question: str, history: list[dict]) -> dict:
    q = question.lower()
    day = reference_day()
    args = {"date": day.isoformat()}
    parsed = nlq.parse(question)
    prev_user = next((m["content"] for m in reversed(history) if m.get("role") == "user"), "")
    if not parsed["types"] and prev_user:
        parsed["types"] = nlq.parse(prev_user)["types"]
    tools_used = []
    evidence_ids: list[int] = []
    day_s = "today" if day == date.today() else day.strftime("on %d %b %Y")

    def use(name, a):
        tools_used.append({"tool": name, "args": a})
        return TOOLS[name][0](a)

    if any(w in q for w in ("evidence", "show me", "clip", "video", "footage", "list")):
        res = use("search_incidents", {**args, "types": parsed["types"], "severities": parsed["severities"],
                                       "hour_from": parsed["hour_from"], "hour_to": parsed["hour_to"], "limit": 8})
        evidence_ids = [i["id"] for i in res["incidents"]]
        answer = (f"Here are {len(evidence_ids)} of {res['total']} matching incident record(s) {day_s}, with their evidence clips."
                  if evidence_ids else f"No matching incident records {day_s}.")
    elif any(w in q for w in ("forecast", "expect", "predict", "tomorrow", "will ")):
        f = use("forecast", {})
        w = f["expected_congestion_window"]
        answer = (f"Based on {f['days_of_history']} day(s) of history, the expected peak-traffic window is "
                  f"{w['start']}–{w['end']}." if w else "There is not enough history yet to estimate a traffic pattern.")
        answer += " (Hour-of-day statistical baseline.)"
    elif any(w in q for w in ("which location", "where", "zone", "hotspot", "location", "intersection", "highest", "most dangerous")):
        z = use("rank_zones", {**args, **({"event_type": parsed["types"][0]} if parsed["types"] else {})})
        z = [x for x in z if x["events_total"]]
        if z:
            top = z[0]
            what = EVENT_LABELS.get(parsed["types"][0]).lower() if parsed["types"] else "event"
            answer = (f"{top['zone']} recorded the highest observed {what} density {day_s}: {_fmt_events(top['events'])} "
                      f"across {top['vehicles']} vehicles (risk indicator {top['risk_level']}, score {top['risk_score']}).")
            if len(z) > 1:
                answer += " Next: " + "; ".join(f"{x['zone']} ({x['events_total']} events)" for x in z[1:3]) + "."
        else:
            answer = f"No zone recorded events {day_s}."
    elif any(w in q for w in ("peak", "busiest", "volume", "how many vehicles", "traffic")) and not parsed["types"]:
        hrs = use("hourly_traffic", args)
        s = use("get_summary", args)
        if hrs:
            peak = max(hrs, key=lambda h: h["vehicles"])
            vol = ", ".join(f"{v} {k}" for k, v in sorted(s["volume"].items(), key=lambda kv: -kv[1]) if k != "pedestrian")
            answer = (f"{s['vehicles']:,} vehicles were observed {day_s} ({vol}). "
                      f"The busiest hour started at {peak['hour']} with {peak['vehicles']} vehicles.")
        else:
            answer = f"No traffic was recorded {day_s}."
    elif parsed["types"] or parsed["hour_from"] is not None:
        res = use("search_incidents", {**args, "types": parsed["types"], "severities": parsed["severities"],
                                       "hour_from": parsed["hour_from"], "hour_to": parsed["hour_to"], "limit": 8})
        evidence_ids = [i["id"] for i in res["incidents"]]
        what = " / ".join(PLURALS[t][1] for t in parsed["types"]) if parsed["types"] else "events"
        sev = " (high/medium severity)" if parsed["severities"] else ""
        when = f" between {parsed['hour_from']:02d}:00 and {parsed['hour_to']:02d}:00" if parsed["hour_from"] is not None else ""
        answer = f"Matching records{when} {day_s}: {res['total']} {what}{sev}."
        if res["incidents"]:
            zones: dict[str, int] = {}
            for i in res["incidents"]:
                zones[i["zone"] or "unzoned"] = zones.get(i["zone"] or "unzoned", 0) + 1
            answer += f" Most frequent location among the latest: {max(zones, key=zones.get)}."
    else:
        s = use("get_summary", args)
        if s["vehicles"] or s["events"]:
            answer = (f"{day_s[0].upper() + day_s[1:]}, {s['vehicles']:,} vehicles and {s['pedestrians']:,} pedestrians were observed, with "
                      f"{_fmt_events(s['events'])}. The risk indicator is {s['risk']['level']} (score {s['risk']['score']}).")
            if s["top_zone"]:
                answer += f" The highest observed risk concentration was at {s['top_zone']['name']}."
            if s["peak_hour"]:
                answer += f" Peak traffic hour: {s['peak_hour'][11:16]}."
        else:
            answer = f"No processed traffic data {day_s} yet. Process a video from the Admin page first."
    return {"answer": answer, "engine": "rules (Ollama not reachable)", "tools_used": tools_used,
            "evidence": _evidence(evidence_ids), "reference_day": day.isoformat()}
