"""Daily road-safety PDF report."""
from __future__ import annotations

import io
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import analytics, settings
from .db import Incident, SessionLocal
from .pipeline.rules import EVENT_LABELS

INK = colors.HexColor("#0f172a")
MUTED = colors.HexColor("#64748b")
ACCENT = colors.HexColor("#2563eb")
RULE = colors.HexColor("#e2e8f0")
LEVEL_COLORS = {"LOW": "#16a34a", "MODERATE": "#ca8a04", "HIGH": "#dc2626", "CRITICAL": "#7f1d1d"}


def _table(rows, widths, header=True):
    t = Table(rows, colWidths=widths)
    style = [
        ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if header:
        style += [("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9), ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
                  ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK)]
    t.setStyle(TableStyle(style))
    return t


def build_daily_report(day: date, camera: Optional[str] = None) -> bytes:
    r = analytics.Range.for_day(day, camera)
    s = analytics.summary(r)
    ts = analytics.timeseries(r, "hour")
    zones = sorted(analytics.zone_stats(r), key=lambda z: -z["risk"]["score"])
    with SessionLocal() as db:
        q = db.query(Incident).filter(Incident.occurred_at >= r.start, Incident.occurred_at < r.end,
                                      Incident.status != "dismissed")
        if camera:
            q = q.filter(Incident.camera_id == camera)
        sev_rank = {"high": 0, "medium": 1, "low": 2}
        incidents = sorted(q.all(), key=lambda i: (sev_rank.get(i.severity, 3), i.occurred_at))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                            title=f"RoadGuard AI — Road Safety Report {day.isoformat()}")
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], alignment=0, fontSize=20, textColor=INK, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=12, textColor=INK, spaceBefore=12, spaceAfter=6)
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=9, textColor=INK, leading=13)
    small = ParagraphStyle("s", parent=body, fontSize=8, textColor=MUTED)

    story = [
        Paragraph("ROAD SAFETY REPORT", h1),
        Paragraph(f"RoadGuard AI · {day.strftime('%A %d %B %Y')}" + (f" · camera {camera}" if camera else " · all cameras"), small),
        Spacer(1, 8),
    ]
    risk = s["risk"]
    lvl_color = LEVEL_COLORS.get(risk["level"], "#0f172a")
    ev = s["events"]
    kpis = [
        ["Traffic volume (vehicles)", f"{s['vehicles']:,}"],
        ["Pedestrians", f"{s['pedestrians']:,}"],
        ["Potential near-misses", ev.get("near_miss", 0)],
        ["Potential pedestrian conflicts", ev.get("ped_conflict", 0)],
        ["Red-light events", ev.get("red_light", 0)],
        ["Potential wrong-way events", ev.get("wrong_way", 0)],
        ["Potential helmet violations", ev.get("helmet_violation", 0)],
        ["Potential illegal stopping", ev.get("illegal_stop", 0)],
        ["Congestion episodes", ev.get("congestion", 0)],
    ]
    story.append(_table([["Metric", "Value"], *kpis], [110 * mm, 40 * mm]))
    story.append(Spacer(1, 8))
    top = s["top_zone"]
    story.append(Paragraph(
        f"<b>Risk indicator:</b> <font color='{lvl_color}'><b>{risk['level']}</b></font> "
        f"(score {risk['score']} per 1,000 vehicles)"
        + (f" · <b>Highest observed risk zone:</b> {top['name']}" if top else "")
        + (f" · <b>Peak traffic hour:</b> {datetime.fromisoformat(s['peak_hour']).strftime('%H:00')}" if s["peak_hour"] else ""),
        body))
    story.append(Paragraph(risk["method"], small))

    # hourly chart
    buckets = ts["buckets"]
    if buckets:
        story.append(Paragraph("Hourly traffic volume and events", h2))
        d = Drawing(170 * mm, 60 * mm)
        bc = VerticalBarChart()
        bc.x, bc.y, bc.width, bc.height = 10 * mm, 8 * mm, 155 * mm, 48 * mm
        bc.data = [[b["vehicles"] for b in buckets]]
        bc.categoryAxis.categoryNames = [b["start"][11:13] for b in buckets]
        bc.categoryAxis.labels.fontSize = 7
        bc.valueAxis.labels.fontSize = 7
        bc.valueAxis.valueMin = 0
        bc.bars[0].fillColor = ACCENT
        bc.bars[0].strokeColor = None
        d.add(bc)
        story.append(d)
        story.append(_table(
            [["Hour", "Vehicles", "Pedestrians", "Events"]] +
            [[b["start"][11:16], b["vehicles"], b["pedestrian"], b["events"]] for b in buckets],
            [30 * mm, 35 * mm, 35 * mm, 35 * mm]))

    story.append(Paragraph("Zones by risk indicator", h2))
    story.append(_table(
        [["Zone", "Vehicles", "Events", "Score", "Level"]] +
        [[z["name"], z["vehicles"], z["events_total"], z["risk"]["score"], z["risk"]["level"]] for z in zones[:12]],
        [60 * mm, 25 * mm, 25 * mm, 25 * mm, 30 * mm]))

    if s["helmet"]["checked"]:
        h = s["helmet"]
        story.append(Paragraph("Helmet compliance", h2))
        story.append(Paragraph(f"Motorcycles: {h['motorcycles']} · checked: {h['checked']} · compliant: {h['compliant']} · "
                               f"potential violations: {h['violations']}", body))

    if incidents:
        story.append(PageBreak())
        story.append(Paragraph(f"Incident log ({len(incidents)})", h2))
        story.append(_table(
            [["#", "Time", "Event", "Zone", "Severity", "Objects", "Review"]] +
            [[i.id, i.occurred_at.strftime("%H:%M:%S"), EVENT_LABELS.get(i.type, i.type), i.zone_name or "—",
              i.severity, ", ".join(f"{c} #{t}" for c, t in zip(i.classes, i.track_ids)) or "—", i.status]
             for i in incidents[:200]],
            [10 * mm, 18 * mm, 42 * mm, 30 * mm, 16 * mm, 38 * mm, 18 * mm]))
        story.append(Paragraph("Key evidence", h2))
        for inc in incidents[:6]:
            p = settings.EVIDENCE_DIR / inc.snapshot if inc.snapshot else None
            if p and Path(p).exists():
                story.append(Paragraph(f"<b>Incident #{inc.id}</b> · {inc.occurred_at:%H:%M:%S} · "
                                       f"{EVENT_LABELS.get(inc.type, inc.type)} · {inc.zone_name or ''} · {inc.severity}", body))
                story.append(Paragraph(inc.description, small))
                img = Image(str(p))
                ratio = img.imageHeight / float(img.imageWidth)
                img.drawWidth, img.drawHeight = 150 * mm, 150 * mm * ratio
                story.append(img)
                story.append(Spacer(1, 6))

    story.append(Spacer(1, 10))
    story.append(Paragraph(
        "All events are automatically detected <i>potential</i> indicators intended for human review. "
        "They are not confirmed violations or accidents. Dismissed incidents are excluded.", small))
    doc.build(story)
    return buf.getvalue()
