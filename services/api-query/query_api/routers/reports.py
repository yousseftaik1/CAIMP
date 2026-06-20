"""
GET /reports/pdf  — structured, multi-section PDF report readable by non-technical staff.

Sections
────────
1. Cover page  (full-bleed, logo, tagline)
2. At a Glance (KPI tiles)
3. Your Servers Right Now
4. What's Coming — Next 24 Hours (forecasts)
5. Issues Detected (anomaly log)
6. AI Analysis & Recommendations
"""

from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from ..auth import get_current_user
from ..db import get_tenant_conn

router = APIRouter(prefix="/reports", tags=["reports"])

_METRIC_LABELS: dict[str, str] = {
    "cpu_percent": "CPU",
    "memory_percent": "Memory",
    "disk_percent": "Disk",
    "system.cpu.utilization": "CPU",
    "system.memory.utilization": "Memory",
    "system.filesystem.utilization": "Disk",
}


def _label(name: str) -> str:
    return _METRIC_LABELS.get(name, name)


# ─────────────────────────────────────────────────────────────────────────────
# PDF BUILDER
# ─────────────────────────────────────────────────────────────────────────────


def _build_pdf(data: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        HRFlowable,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    PW, PH = A4
    MARGIN = 20 * mm
    CW = PW - 2 * MARGIN

    # ── Color palette (CAIMP navy/teal brand) ────────────────────────────────
    BRAND = colors.HexColor("#1a3d5c")  # navy — primary brand
    BRAND2 = colors.HexColor("#2c5282")  # lighter navy — brand-lt
    ACCENT = colors.HexColor("#2ea99f")  # teal — logo accent
    LGRY = colors.HexColor("#e8f0f8")  # pale blue — brand-pale
    MGRY = colors.HexColor("#d6e0ec")  # blue-grey border
    DGRY = colors.HexColor("#5a7a96")  # muted blue
    RED = colors.HexColor("#dc2626")
    WHITE = colors.white

    H_BRAND = "#1a3d5c"
    H_DGRY = "#5a7a96"
    H_GREEN = "#16a34a"
    H_ORANGE = "#d97706"
    H_RED = "#dc2626"

    # ── Style factory ─────────────────────────────────────────────────────────
    def _ps(name: str, **kw) -> ParagraphStyle:
        d = dict(fontName="Helvetica", fontSize=9, leading=13, textColor=BRAND)
        d.update(kw)
        return ParagraphStyle(name, **d)

    _ps("body_small", fontSize=8, textColor=DGRY, leading=11)
    NARR = _ps(
        "body_narr",
        fontSize=8.5,
        textColor=BRAND,
        fontName="Helvetica-Oblique",
        leading=13,
    )
    INTRO = _ps("body_intro", fontSize=9.5, textColor=DGRY, leading=15)
    CELL = _ps("t_cell", fontSize=8, leading=11)
    CELLB = _ps("t_cellb", fontSize=8, leading=11, fontName="Helvetica-Bold")
    CELLC = _ps("t_cellc", fontSize=8, leading=11, alignment=TA_CENTER)
    CELLR = _ps("t_cellr", fontSize=8, leading=11, alignment=TA_RIGHT)

    # ── Reusable table style fragments ───────────────────────────────────────
    _BASE = [
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.3, MGRY),
    ]
    _HDR = [
        ("BACKGROUND", (0, 0), (-1, 0), BRAND),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("LINEBELOW", (0, 0), (-1, 0), 1.5, ACCENT),
    ]
    _STRIPE = [("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LGRY])]

    def _hr() -> HRFlowable:
        return HRFlowable(
            width="100%", thickness=0.5, color=ACCENT, spaceBefore=3, spaceAfter=5
        )

    def _section(title: str, subtitle: str = "") -> list:
        uid = title.replace(" ", "")[:14]
        items: list = [
            Table(
                [
                    [
                        Paragraph(
                            title,
                            _ps(
                                f"sh_{uid}",
                                fontSize=11,
                                textColor=WHITE,
                                fontName="Helvetica-Bold",
                                leading=16,
                            ),
                        )
                    ]
                ],
                colWidths=[CW],
                style=TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), BRAND),
                        ("TOPPADDING", (0, 0), (-1, -1), 7),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                        ("LEFTPADDING", (0, 0), (-1, -1), 10),
                        ("LINEBELOW", (0, 0), (-1, -1), 2, ACCENT),
                    ]
                ),
            )
        ]
        if subtitle:
            items += [Spacer(1, 3 * mm), Paragraph(subtitle, INTRO)]
        items.append(Spacer(1, 3 * mm))
        return items

    def _pct_cell(v, warn=75.0, crit=90.0):
        if v is None:
            return Paragraph("—", CELLC)
        hx = H_RED if v >= crit else (H_ORANGE if v >= warn else H_GREEN)
        return Paragraph(f'<font color="{hx}"><b>{v:.1f}%</b></font>', CELLC)

    def _status_cell(s: str):
        m = {
            "ok": ("Healthy", H_GREEN),
            "warning": ("Watch", H_ORANGE),
            "critical": ("Critical", H_RED),
        }
        label, hx = m.get(s, (s.upper(), H_DGRY))
        return Paragraph(f'<font color="{hx}"><b>{label}</b></font>', CELLC)

    def _trend_cell(slope: float):
        if slope > 0.005:
            return Paragraph(f'<font color="{H_RED}"><b>Rising fast</b></font>', CELLC)
        if slope > 0.001:
            return Paragraph(f'<font color="{H_ORANGE}"><b>Rising</b></font>', CELLC)
        if slope < -0.005:
            return Paragraph(f'<font color="{H_GREEN}"><b>Falling</b></font>', CELLC)
        if slope < -0.001:
            return Paragraph(
                f'<font color="{H_GREEN}"><b>Easing down</b></font>', CELLC
            )
        return Paragraph(f'<font color="{H_DGRY}">Stable</font>', CELLC)

    def _anomaly_val(v: float, metric: str) -> str:
        frac = {
            "cpu_percent",
            "memory_percent",
            "disk_percent",
            "system.cpu.utilization",
            "system.memory.utilization",
            "system.filesystem.utilization",
        }
        if metric in frac:
            return f"{(v * 100 if v <= 1.0 else v):.1f}%"
        return f"{v:.3f}"

    # ── Canvas callbacks ──────────────────────────────────────────────────────

    def _cover_chrome(canvas, doc):
        canvas.saveState()
        # Full dark-navy background
        canvas.setFillColor(BRAND)
        canvas.rect(0, 0, PW, PH, fill=1, stroke=0)
        # Decorative circles (navy variants)
        canvas.setFillColor(BRAND2)
        canvas.circle(PW + 8 * mm, PH - 18 * mm, 88 * mm, fill=1, stroke=0)
        canvas.setFillColor(colors.HexColor("#0d1a26"))
        canvas.circle(-18 * mm, 28 * mm, 68 * mm, fill=1, stroke=0)
        canvas.setFillColor(colors.HexColor("#0a1520"))
        canvas.circle(PW * 0.65, PH * 0.30, 42 * mm, fill=1, stroke=0)
        # Logo — faithful SVG replica of Logo.tsx (light variant on navy bg)
        ix = MARGIN
        iy = PH * 0.60
        ic = 22 * mm  # maps SVG 36×36 viewBox → ic×ic
        sc = ic / 36  # points per SVG unit

        def _lx(x):
            return ix + x * sc

        def _ly(y):
            return iy + (36 - y) * sc  # SVG y↓ → PDF y↑

        # Connection lines
        canvas.setStrokeColor(WHITE)
        canvas.setLineWidth(1.6 * sc)
        canvas.line(_lx(6), _ly(10), _lx(18), _ly(18))
        canvas.line(_lx(6), _ly(26), _lx(18), _ly(18))
        canvas.line(_lx(12), _ly(18), _lx(18), _ly(18))

        # Peripheral nodes (teal highlight on top-left node, white for others)
        canvas.setFillColor(ACCENT)
        canvas.circle(_lx(6), _ly(10), 2.8 * sc, fill=1, stroke=0)
        canvas.setFillColor(WHITE)
        canvas.circle(_lx(6), _ly(26), 2.3 * sc, fill=1, stroke=0)
        canvas.circle(_lx(12), _ly(18), 2.0 * sc, fill=1, stroke=0)
        canvas.circle(_lx(18), _ly(18), 3.4 * sc, fill=1, stroke=0)  # central hub

        # ECG heartbeat polyline
        canvas.setStrokeColor(WHITE)
        canvas.setLineWidth(1.8 * sc)
        _cvp = canvas.beginPath()
        _cvp.moveTo(_lx(18), _ly(18))
        _cvp.lineTo(_lx(22), _ly(18))
        _cvp.lineTo(_lx(25), _ly(10))
        _cvp.lineTo(_lx(28.5), _ly(26))
        _cvp.lineTo(_lx(31.5), _ly(18))
        _cvp.lineTo(_lx(36), _ly(18))
        canvas.drawPath(_cvp, stroke=1, fill=0)

        # CAIMP wordmark
        canvas.setFont("Helvetica-Bold", 30)
        canvas.setFillColor(WHITE)
        canvas.drawString(ix + ic + 6 * mm, iy + ic * 0.42, "CAIMP")
        # Subtitle — muted white matching Logo.tsx light-variant sub color
        canvas.setFont("Helvetica", 10)
        canvas.setFillColor(colors.Color(1, 1, 1, 0.55))
        canvas.drawString(ix + ic + 6 * mm, iy + ic * 0.08, "Infrastructure Monitor")
        # Separator
        canvas.setStrokeColor(ACCENT)
        canvas.setLineWidth(1.2)
        canvas.line(MARGIN, PH * 0.555, PW - MARGIN, PH * 0.555)
        # Title
        canvas.setFont("Helvetica-Bold", 34)
        canvas.setFillColor(WHITE)
        canvas.drawString(MARGIN, PH * 0.475, "Infrastructure")
        canvas.drawString(MARGIN, PH * 0.475 - 14 * mm, "Health Report")
        # Tagline
        canvas.setFont("Helvetica", 11)
        canvas.setFillColor(ACCENT)
        canvas.drawString(
            MARGIN,
            PH * 0.475 - 25 * mm,
            "A clear, plain-language overview of your systems — powered by AI",
        )
        # Metadata
        canvas.setFont("Helvetica", 10)
        canvas.setFillColor(colors.HexColor("#8aadc8"))
        my = PH * 0.475 - 39 * mm
        canvas.drawString(MARGIN, my, f"Report Period   {data['period']}")
        canvas.drawString(MARGIN, my - 7.5 * mm, f"Generated       {data['generated']}")
        canvas.drawString(
            MARGIN, my - 15 * mm, f"Servers         {data['server_count']} monitored"
        )
        # Bottom strip
        canvas.setFillColor(colors.HexColor("#0f1e2e"))
        canvas.rect(0, 0, PW, 16 * mm, fill=1, stroke=0)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#5a7a96"))
        canvas.drawCentredString(
            PW / 2,
            6 * mm,
            "CAIMP v2  —  Centralized AI Monitoring Platform  ·  Confidential",
        )
        canvas.restoreState()

    def _page_chrome(canvas, doc):
        canvas.saveState()
        # Header bar
        canvas.setFillColor(BRAND)
        canvas.rect(0, PH - 14 * mm, PW, 14 * mm, fill=1, stroke=0)
        # Small teal badge with miniature logo icon
        bx, by, bs = MARGIN, PH - 13 * mm, 8.5 * mm
        canvas.setFillColor(ACCENT)
        canvas.roundRect(bx, by, bs, bs, 1.5 * mm, fill=1, stroke=0)

        # Draw logo icon scaled to 72% of badge (white on teal, matches Logo.tsx SVG)
        mi = bs * 0.72
        mox = bx + (bs - mi) / 2
        moy = by + (bs - mi) / 2
        ms = mi / 36

        def _hx(x):
            return mox + x * ms

        def _hy(y):
            return moy + (36 - y) * ms

        canvas.setStrokeColor(WHITE)
        canvas.setLineWidth(max(0.4, 1.6 * ms))
        canvas.line(_hx(6), _hy(10), _hx(18), _hy(18))
        canvas.line(_hx(6), _hy(26), _hx(18), _hy(18))
        canvas.line(_hx(12), _hy(18), _hx(18), _hy(18))

        canvas.setFillColor(WHITE)
        canvas.circle(_hx(6), _hy(10), max(0.7, 2.8 * ms), fill=1, stroke=0)
        canvas.circle(_hx(6), _hy(26), max(0.6, 2.3 * ms), fill=1, stroke=0)
        canvas.circle(_hx(12), _hy(18), max(0.5, 2.0 * ms), fill=1, stroke=0)
        canvas.circle(_hx(18), _hy(18), max(0.8, 3.4 * ms), fill=1, stroke=0)

        canvas.setLineWidth(max(0.4, 1.8 * ms))
        _hdp = canvas.beginPath()
        _hdp.moveTo(_hx(18), _hy(18))
        _hdp.lineTo(_hx(22), _hy(18))
        _hdp.lineTo(_hx(25), _hy(10))
        _hdp.lineTo(_hx(28.5), _hy(26))
        _hdp.lineTo(_hx(31.5), _hy(18))
        _hdp.lineTo(_hx(36), _hy(18))
        canvas.drawPath(_hdp, stroke=1, fill=0)
        # Header text
        canvas.setFont("Helvetica-Bold", 8)
        canvas.setFillColor(WHITE)
        canvas.drawString(
            bx + bs + 3 * mm, PH - 8 * mm, "CAIMP  ·  Infrastructure Health Report"
        )
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(ACCENT)
        canvas.drawRightString(PW - MARGIN, PH - 8 * mm, data["generated"])
        # Footer
        canvas.setStrokeColor(ACCENT)
        canvas.setLineWidth(0.4)
        canvas.line(MARGIN, 12 * mm, PW - MARGIN, 12 * mm)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(DGRY)
        canvas.drawCentredString(
            PW / 2, 8 * mm, f"Page {doc.page - 1}  —  Confidential"
        )
        canvas.restoreState()

    # ── Document setup ────────────────────────────────────────────────────────
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=22 * mm,
        bottomMargin=22 * mm,
        title="CAIMP Infrastructure Health Report",
        author="CAIMP v2",
    )
    story: list = []

    # ════════════════════════════════════════════════════════════════════════
    # PAGE 1 — Cover (drawn entirely by _cover_chrome; story jumps to page 2)
    # ════════════════════════════════════════════════════════════════════════
    story.append(PageBreak())

    # ════════════════════════════════════════════════════════════════════════
    # 2. AT A GLANCE — KPI tiles
    # ════════════════════════════════════════════════════════════════════════
    story.extend(
        _section(
            "At a Glance",
            "Here's a quick summary of your infrastructure's health during this report period.",
        )
    )

    s = data["summary"]

    def _kpi(label: str, value, sub: str = "", hcolor: str = H_BRAND) -> Table:
        n = label.replace(" ", "")[:10]
        rows: list = [
            [
                Paragraph(
                    str(value),
                    _ps(
                        f"kv{n}",
                        fontSize=22,
                        fontName="Helvetica-Bold",
                        leading=28,
                        textColor=colors.HexColor(hcolor),
                        alignment=TA_CENTER,
                    ),
                )
            ],
            [
                Paragraph(
                    label,
                    _ps(
                        f"kl{n}",
                        fontSize=8,
                        textColor=DGRY,
                        leading=11,
                        alignment=TA_CENTER,
                    ),
                )
            ],
        ]
        if sub:
            rows.append(
                [
                    Paragraph(
                        sub,
                        _ps(
                            f"ks{n}",
                            fontSize=7,
                            leading=10,
                            alignment=TA_CENTER,
                            textColor=colors.HexColor(hcolor),
                        ),
                    )
                ]
            )
        return Table(
            rows,
            colWidths=[CW / 4 - 3],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), LGRY),
                    ("BOX", (0, 0), (-1, -1), 0.8, ACCENT),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("TOPPADDING", (0, 0), (-1, -1), 9),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ]
            ),
        )

    an_col = H_RED if s["anomaly_count"] > 0 else H_GREEN
    fc_col = H_RED if s["critical_forecast_count"] > 0 else H_GREEN
    story.append(
        Table(
            [
                [
                    _kpi("Servers Monitored", s["server_count"], "All being checked"),
                    _kpi(
                        "Issues Detected",
                        s["anomaly_count"],
                        "Need attention" if s["anomaly_count"] > 0 else "All clear",
                        an_col,
                    ),
                    _kpi(
                        "Urgent Forecasts",
                        s["critical_forecast_count"],
                        "At risk soon"
                        if s["critical_forecast_count"] > 0
                        else "Looking good",
                        fc_col,
                    ),
                    _kpi(
                        "AI Recommendations",
                        s["ai_count"],
                        "Available below" if s["ai_count"] > 0 else "None yet",
                    ),
                ]
            ],
            colWidths=[CW / 4] * 4,
            style=TableStyle(
                [
                    ("LEFTPADDING", (0, 0), (-1, -1), 2),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                ]
            ),
        )
    )
    story.append(Spacer(1, 6 * mm))

    # ════════════════════════════════════════════════════════════════════════
    # 3. SERVER HEALTH
    # ════════════════════════════════════════════════════════════════════════
    story.append(_hr())
    story.extend(
        _section(
            "Your Servers Right Now",
            "Current resource usage for each server. Green means healthy, orange means it is under "
            "some stress, and red means action may be needed soon.",
        )
    )

    srv_rows = [
        [
            Paragraph("Server", CELLB),
            Paragraph("Hostname", CELLB),
            Paragraph("Status", CELLB),
            Paragraph("CPU", CELLB),
            Paragraph("Memory", CELLB),
            Paragraph("Disk", CELLB),
            Paragraph("Issues (24h)", CELLB),
        ]
    ]
    for srv in data["servers"]:
        cnt = srv.get("anomaly_count_24h", 0)
        srv_rows.append(
            [
                Paragraph(srv["name"], CELLB),
                Paragraph(srv["hostname"], CELL),
                _status_cell(srv["status"]),
                _pct_cell(srv.get("cpu_pct")),
                _pct_cell(srv.get("ram_pct")),
                _pct_cell(srv.get("disk_pct")),
                Paragraph(
                    f'<font color="{H_RED if cnt > 0 else H_GREEN}"><b>{cnt}</b></font>',
                    CELLC,
                ),
            ]
        )

    srv_cw = [CW * r for r in (0.18, 0.20, 0.10, 0.12, 0.12, 0.12, 0.16)]
    story.append(
        Table(
            srv_rows,
            colWidths=srv_cw,
            style=TableStyle(_BASE + _HDR + _STRIPE),
            repeatRows=1,
        )
    )
    story.append(Spacer(1, 6 * mm))

    # ════════════════════════════════════════════════════════════════════════
    # 4. FORECASTS
    # ════════════════════════════════════════════════════════════════════════
    if data["forecasts"]:
        story.append(PageBreak())
        story.extend(
            _section(
                "What's Coming — Next 24 Hours",
                "These predictions are based on how your servers have been behaving recently. "
                "'In 6 Hours' and 'In 24 Hours' show the expected usage level at those times. "
                "The 'Risk Window' tells you if and when a metric might reach a danger level — "
                "'No risk today' means you are safe for the next 24 hours.",
            )
        )

        crit_fcs = [
            fc
            for fc in data["forecasts"]
            if fc.get("time_to_critical") and fc["time_to_critical"] <= 6
        ]
        if crit_fcs:
            story.append(
                Table(
                    [
                        [
                            Paragraph(
                                f"<b>Heads up!</b> {len(crit_fcs)} metric(s) may reach a critical level "
                                f"within the next 6 hours. See the table below.",
                                _ps("wb", fontSize=9, textColor=RED, leading=13),
                            )
                        ]
                    ],
                    colWidths=[CW],
                    style=TableStyle(
                        [
                            (
                                "BACKGROUND",
                                (0, 0),
                                (-1, -1),
                                colors.HexColor("#fff1f1"),
                            ),
                            ("BOX", (0, 0), (-1, -1), 1, RED),
                            ("LEFTPADDING", (0, 0), (-1, -1), 10),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                            ("TOPPADDING", (0, 0), (-1, -1), 8),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                        ]
                    ),
                )
            )
            story.append(Spacer(1, 4 * mm))

        fc_rows = [
            [
                Paragraph("Server", CELLB),
                Paragraph("Metric", CELLB),
                Paragraph("Trend", CELLB),
                Paragraph("In 6 Hours", CELLB),
                Paragraph("In 24 Hours", CELLB),
                Paragraph("Risk Window", CELLB),
                Paragraph("Reliability", CELLB),
            ]
        ]
        for fc in data["forecasts"]:
            slope = fc.get("trend_slope") or 0.0
            p6 = f"{fc['p6'] * 100:.1f}%" if fc.get("p6") is not None else "—"
            p24 = f"{fc['p24'] * 100:.1f}%" if fc.get("p24") is not None else "—"

            ttc = fc.get("time_to_critical")
            if ttc is not None:
                h = int(ttc)
                ttc_str = (
                    "Less than 1 hour"
                    if h <= 1
                    else f"About {h} hours"
                    if h <= 6
                    else f"~{h} hours away"
                )
                ttc_hx = H_RED if ttc <= 6 else (H_ORANGE if ttc <= 12 else H_DGRY)
            else:
                ttc_str, ttc_hx = "No risk today", H_GREEN

            conf = (fc.get("llm_confidence") or "low").lower()
            conf_hx = (
                H_GREEN
                if conf == "high"
                else (H_ORANGE if conf == "medium" else H_DGRY)
            )

            fc_rows.append(
                [
                    Paragraph(fc["server_name"], CELLB),
                    Paragraph(_label(fc["metric_name"]), CELL),
                    _trend_cell(slope),
                    Paragraph(p6, CELLC),
                    Paragraph(p24, CELLC),
                    Paragraph(f'<font color="{ttc_hx}"><b>{ttc_str}</b></font>', CELLC),
                    Paragraph(
                        f'<font color="{conf_hx}"><b>{conf.capitalize()}</b></font>',
                        CELLC,
                    ),
                ]
            )

        fc_cw = [CW * r for r in (0.17, 0.11, 0.14, 0.11, 0.12, 0.21, 0.14)]
        story.append(
            Table(
                fc_rows,
                colWidths=fc_cw,
                style=TableStyle(_BASE + _HDR + _STRIPE),
                repeatRows=1,
            )
        )
        story.append(Spacer(1, 6 * mm))

        narratives = [fc for fc in data["forecasts"] if fc.get("llm_narrative")]
        if narratives:
            story.extend(
                _section(
                    "AI Forecast Explanations",
                    "Your AI has analyzed the trends and written a short plain-English explanation "
                    "for each metric.",
                )
            )
            for i, fc in enumerate(narratives):
                conf = (fc.get("llm_confidence") or "low").lower()
                conf_hx = (
                    H_GREEN
                    if conf == "high"
                    else (H_ORANGE if conf == "medium" else H_DGRY)
                )
                story.append(
                    Table(
                        [
                            [
                                Paragraph(
                                    f"{fc['server_name']}  —  {_label(fc['metric_name'])}",
                                    _ps(
                                        f"nh{i}",
                                        fontSize=8.5,
                                        textColor=WHITE,
                                        fontName="Helvetica-Bold",
                                        leading=13,
                                    ),
                                ),
                                Paragraph(
                                    f'<font color="{conf_hx}">{conf.capitalize()} reliability</font>',
                                    _ps(
                                        f"nc{i}",
                                        fontSize=8,
                                        textColor=ACCENT,
                                        fontName="Helvetica",
                                        leading=13,
                                        alignment=TA_RIGHT,
                                    ),
                                ),
                            ]
                        ],
                        colWidths=[CW * 0.72, CW * 0.28],
                        style=TableStyle(
                            [
                                ("BACKGROUND", (0, 0), (-1, -1), BRAND),
                                ("TOPPADDING", (0, 0), (-1, -1), 5),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                                ("LINEBELOW", (0, 0), (-1, -1), 1, ACCENT),
                            ]
                        ),
                    )
                )
                story.append(Paragraph(fc["llm_narrative"], NARR))
                story.append(Spacer(1, 4 * mm))

    # ════════════════════════════════════════════════════════════════════════
    # 5. ANOMALY LOG
    # ════════════════════════════════════════════════════════════════════════
    if data["anomalies"]:
        story.append(PageBreak())
        story.extend(
            _section(
                "Issues Detected",
                f"Unusual readings detected during {data['period']}. "
                "Each row shows a moment when a metric behaved differently from what was expected. "
                "This does not always mean something is broken, but each item is worth a look.",
            )
        )

        an_rows = [
            [
                Paragraph("When", CELLB),
                Paragraph("Server", CELLB),
                Paragraph("Metric", CELLB),
                Paragraph("Reading", CELLB),
                Paragraph("How Detected", CELLB),
                Paragraph("Severity", CELLB),
            ]
        ]
        for a in data["anomalies"]:
            sev_hx = H_RED if a["severity"] == "critical" else H_ORANGE
            an_rows.append(
                [
                    Paragraph(a["time"].strftime("%b %d, %H:%M"), CELL),
                    Paragraph(a["server_name"], CELLB),
                    Paragraph(_label(a["metric_name"]), CELL),
                    Paragraph(_anomaly_val(a["value"], a["metric_name"]), CELLR),
                    Paragraph(a["detector"].replace("_", " ").title(), CELL),
                    Paragraph(
                        f'<font color="{sev_hx}"><b>{a["severity"].capitalize()}</b></font>',
                        CELLC,
                    ),
                ]
            )

        an_cw = [CW * r for r in (0.17, 0.19, 0.16, 0.10, 0.24, 0.14)]
        story.append(
            Table(
                an_rows,
                colWidths=an_cw,
                style=TableStyle(_BASE + _HDR + _STRIPE),
                repeatRows=1,
            )
        )

    # ════════════════════════════════════════════════════════════════════════
    # 6. AI INSIGHTS
    # ════════════════════════════════════════════════════════════════════════
    if data["ai_insights"]:
        story.append(PageBreak())
        story.extend(
            _section(
                "AI Analysis & Recommendations",
                "For each issue detected, the AI has written a plain-English explanation of what "
                "happened, why it likely occurred, and what you should do about it.",
            )
        )

        for idx, ins in enumerate(data["ai_insights"]):
            sev_hx = H_RED if ins["severity"] == "critical" else H_ORANGE
            conf_hx = (
                H_GREEN
                if ins["confidence"] == "high"
                else (H_ORANGE if ins["confidence"] == "medium" else H_DGRY)
            )

            story.append(
                Table(
                    [
                        [
                            Paragraph(
                                f"{ins['server_name']}  —  {_label(ins['anomaly_type'])}",
                                _ps(
                                    f"ih{idx}",
                                    fontSize=9,
                                    textColor=WHITE,
                                    fontName="Helvetica-Bold",
                                    leading=13,
                                ),
                            ),
                            Paragraph(
                                f'<font color="{sev_hx}">{ins["severity"].capitalize()}</font>'
                                f"  ·  "
                                f'<font color="{conf_hx}">{ins["confidence"].capitalize()} confidence</font>',
                                _ps(
                                    f"im{idx}",
                                    fontSize=8,
                                    textColor=ACCENT,
                                    fontName="Helvetica",
                                    leading=13,
                                    alignment=TA_RIGHT,
                                ),
                            ),
                        ]
                    ],
                    colWidths=[CW * 0.55, CW * 0.45],
                    style=TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, -1), BRAND),
                            ("TOPPADDING", (0, 0), (-1, -1), 7),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                            ("LEFTPADDING", (0, 0), (-1, -1), 10),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                            ("LINEBELOW", (0, 0), (-1, -1), 2, ACCENT),
                        ]
                    ),
                )
            )

            detail_rows = []
            if ins.get("explanation"):
                detail_rows.append(
                    [
                        Paragraph("What happened", CELLB),
                        Paragraph(
                            ins["explanation"],
                            _ps(f"ed{idx}", fontSize=8.5, leading=13),
                        ),
                    ]
                )
            if ins.get("root_cause"):
                detail_rows.append(
                    [
                        Paragraph("Why it happened", CELLB),
                        Paragraph(
                            ins["root_cause"], _ps(f"rd{idx}", fontSize=8.5, leading=13)
                        ),
                    ]
                )
            if ins.get("recommended_action"):
                detail_rows.append(
                    [
                        Paragraph("What to do", CELLB),
                        Paragraph(
                            ins["recommended_action"],
                            _ps(
                                f"ad{idx}",
                                fontSize=8.5,
                                leading=13,
                                textColor=colors.HexColor("#15803d"),
                            ),
                        ),
                    ]
                )
            if detail_rows:
                story.append(
                    Table(
                        detail_rows,
                        colWidths=[32 * mm, CW - 32 * mm],
                        style=TableStyle(
                            [
                                ("BACKGROUND", (0, 0), (0, -1), LGRY),
                                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                                ("TOPPADDING", (0, 0), (-1, -1), 6),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                ("GRID", (0, 0), (-1, -1), 0.3, MGRY),
                                ("LINEBELOW", (-1, -1), (-1, -1), 1.5, ACCENT),
                            ]
                        ),
                    )
                )
            story.append(Spacer(1, 5 * mm))

    # ── Build ─────────────────────────────────────────────────────────────────
    doc.build(story, onFirstPage=_cover_chrome, onLaterPages=_page_chrome)
    return buf.getvalue()


# ─────────────────────────────────────────────────────────────────────────────
# DATA FETCHER
# ─────────────────────────────────────────────────────────────────────────────


async def _collect(
    conn, org_id: str, t_from: datetime, t_to: datetime, server_id: str | None
) -> dict:
    now = datetime.now(tz=timezone.utc)

    srv_q = "SELECT id, name, hostname, status FROM servers WHERE org_id = $1::uuid"
    srv_p: list = [org_id]
    if server_id:
        srv_p.append(server_id)
        srv_q += f" AND id = ${len(srv_p)}::uuid"
    srv_q += " ORDER BY name"

    servers_raw = await conn.fetch(srv_q, *srv_p)
    server_map = {str(r["id"]): r["name"] for r in servers_raw}
    server_ids = list(server_map.keys())

    srv_metrics: dict[str, dict] = {
        sid: {
            "cpu_pct": None,
            "ram_pct": None,
            "disk_pct": None,
            "anomaly_count_24h": 0,
        }
        for sid in server_ids
    }
    if server_ids:
        since_5m = now - timedelta(minutes=5)
        since_24h = now - timedelta(hours=24)
        m_rows = await conn.fetch(
            """
            SELECT DISTINCT ON (server_id, metric_name) server_id, metric_name, value
            FROM metrics
            WHERE org_id = $1::uuid
              AND metric_name = ANY($2::text[])
              AND time >= $3
            ORDER BY server_id, metric_name, time DESC
            """,
            org_id,
            ["cpu_percent", "memory_percent", "disk_percent"],
            since_5m,
        )
        _key_map = {
            "cpu_percent": "cpu_pct",
            "memory_percent": "ram_pct",
            "disk_percent": "disk_pct",
        }
        for mr in m_rows:
            sid = str(mr["server_id"])
            key = _key_map.get(mr["metric_name"])
            if sid in srv_metrics and key:
                srv_metrics[sid][key] = round(float(mr["value"]) * 100, 1)

        an_counts = await conn.fetch(
            "SELECT server_id, count(*) AS cnt FROM anomaly_events "
            "WHERE org_id = $1::uuid AND time >= $2 GROUP BY server_id",
            org_id,
            since_24h,
        )
        for ar in an_counts:
            sid = str(ar["server_id"])
            if sid in srv_metrics:
                srv_metrics[sid]["anomaly_count_24h"] = int(ar["cnt"])

    servers = [
        {
            "id": str(r["id"]),
            "name": r["name"],
            "hostname": r["hostname"],
            "status": r["status"],
            **srv_metrics.get(str(r["id"]), {}),
        }
        for r in servers_raw
    ]

    an_p: list = [org_id, t_from, t_to]
    an_q = "org_id = $1::uuid AND time >= $2 AND time <= $3"
    if server_id:
        an_p.append(server_id)
        an_q += f" AND server_id = ${len(an_p)}::uuid"

    anomaly_rows = await conn.fetch(
        f"SELECT time, server_id, metric_name, value, detector, severity "
        f"FROM anomaly_events WHERE {an_q} ORDER BY time DESC LIMIT 200",
        *an_p,
    )
    anomalies = [
        {
            "time": r["time"],
            "server_name": server_map.get(str(r["server_id"]), str(r["server_id"])),
            "metric_name": r["metric_name"],
            "value": float(r["value"]),
            "detector": r["detector"],
            "severity": r["severity"],
        }
        for r in anomaly_rows
    ]

    fc_p: list = [org_id]
    fc_q = "org_id = $1::uuid"
    if server_id:
        fc_p.append(server_id)
        fc_q += f" AND server_id = ${len(fc_p)}::uuid"

    forecast_rows = await conn.fetch(
        f"""
        SELECT DISTINCT ON (server_id, metric_name)
            server_id, metric_name, trend_slope, time_to_critical,
            llm_narrative, llm_confidence, forecast_points
        FROM server_forecasts
        WHERE {fc_q}
        ORDER BY server_id, metric_name, forecasted_at DESC
        """,
        *fc_p,
    )
    forecasts = []
    for fr in forecast_rows:
        pts = fr["forecast_points"]
        if isinstance(pts, str):
            pts = json.loads(pts)
        pts = pts or []
        forecasts.append(
            {
                "server_name": server_map.get(
                    str(fr["server_id"]), str(fr["server_id"])
                ),
                "metric_name": fr["metric_name"],
                "trend_slope": fr["trend_slope"],
                "time_to_critical": fr["time_to_critical"],
                "llm_narrative": fr["llm_narrative"],
                "llm_confidence": fr["llm_confidence"],
                "p6": pts[5]["predicted"] if len(pts) >= 6 else None,
                "p24": pts[23]["predicted"] if len(pts) >= 24 else None,
            }
        )

    ai_p: list = [org_id, t_from, t_to]
    ai_q = "org_id = $1::uuid AND created_at >= $2 AND created_at <= $3"
    if server_id:
        ai_p.append(server_id)
        ai_q += f" AND server_id = ${len(ai_p)}::uuid"

    ai_rows = await conn.fetch(
        f"SELECT server_id, anomaly_type, severity, explanation, "
        f"root_cause, recommended_action, confidence "
        f"FROM ai_explanations WHERE {ai_q} ORDER BY created_at DESC LIMIT 20",
        *ai_p,
    )
    ai_insights = [
        {
            "server_name": server_map.get(str(r["server_id"]), str(r["server_id"])),
            "anomaly_type": r["anomaly_type"],
            "severity": r["severity"],
            "explanation": r["explanation"],
            "root_cause": r["root_cause"],
            "recommended_action": r["recommended_action"],
            "confidence": r["confidence"],
        }
        for r in ai_rows
    ]

    critical_fc = sum(
        1 for f in forecasts if f.get("time_to_critical") and f["time_to_critical"] <= 6
    )

    return {
        "period": f"{t_from.strftime('%Y-%m-%d %H:%M')} – {t_to.strftime('%Y-%m-%d %H:%M')} UTC",
        "generated": datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "server_count": len(servers),
        "servers": servers,
        "anomalies": anomalies,
        "forecasts": forecasts,
        "ai_insights": ai_insights,
        "summary": {
            "server_count": len(servers),
            "anomaly_count": len(anomalies),
            "critical_forecast_count": critical_fc,
            "ai_count": len(ai_insights),
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINT
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/pdf", summary="Download a structured PDF infrastructure health report")
async def download_pdf(
    from_time: datetime | None = Query(
        default=None, description="Start of report window (default: 24 h ago)"
    ),
    to_time: datetime | None = Query(
        default=None, description="End of report window (default: now)"
    ),
    server_id: str | None = Query(
        default=None, description="Filter report to a single server UUID"
    ),
    user=Depends(get_current_user),
):
    now = datetime.now(tz=timezone.utc)
    t_to = to_time or now
    t_from = from_time or (now - timedelta(hours=24))

    async with get_tenant_conn(user.org_id) as conn:
        data = await _collect(conn, user.org_id, t_from, t_to, server_id)

    pdf_bytes = _build_pdf(data)

    filename = (
        f"caimp-report-{t_from.strftime('%Y%m%d')}-to-{t_to.strftime('%Y%m%d')}.pdf"
    )
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
