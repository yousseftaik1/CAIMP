from __future__ import annotations

# ── Output schema (validated by the caller) ───────────────────────────────────

_OUTPUT_SCHEMA = """\
Respond ONLY with this JSON object — no preamble, no markdown fences, no extra keys:
{
  "explanation": "2-3 plain sentences describing what is happening in terms a non-technical person can understand",
  "root_cause": "The most likely reason this happened — explain it like you're talking to a developer who has never used monitoring tools",
  "recommended_action": "The single most important thing they should do right now, written as a concrete step",
  "confidence": "high|medium|low"
}"""


def build_prompt(
    event: dict,
    metric_history: list[dict],
    rag_docs: list[dict],
) -> str:
    """
    Build a small-team-friendly LLM prompt for anomaly explanation.

    The target audience is a startup developer with no DevOps background who
    just wants to know: what broke, why, and what to do about it.
    """
    history_lines = "\n".join(
        f"  {r['time']}: {r['value']:.1%}" if r['value'] <= 1.0 else f"  {r['time']}: {r['value']:.1f}%"
        for r in metric_history[:20]
    ) or "  No recent history available"

    rag_lines = "\n\n".join(
        f"[{d['type'].upper()}] {d['title'] or 'Past incident'}:\n{d['content'][:400]}"
        for d in rag_docs
    ) or "  No similar incidents in knowledge base"

    metric = event.get('metric_name', 'unknown metric')
    value  = event.get('value', 0)
    pct    = f"{value * 100:.1f}%" if value <= 1.0 else f"{value:.1f}%"
    sev    = event.get('severity', 'warning')

    return f"""Server alert: {sev.upper()} — {metric.replace('system.', '').replace('.', ' ')} at {pct}.

Recent readings: {history_lines[:200]}

Respond ONLY with valid JSON (no markdown, no extra text):
{{"explanation":"2 sentences explaining what happened in plain language","root_cause":"most likely cause","recommended_action":"one concrete action to take now","confidence":"low"}}"""
