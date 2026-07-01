"""
je_report.py  -  THE REVIEWER WORKLIST  (Week 3, Build 2)

Deterministic assembler. Takes the maker-checker results and renders a reviewer
worklist (markdown). No AI here - it only FORMATS the decision trail the rules
and the two subagents already produced, so the numbers on the worklist are never
authored by an LLM. Ordering is by risk so a controller works top-down.
"""

from __future__ import annotations

from je_review import MakerCheckerResult

_TIER_RANK = {"high": 0, "medium": 1, "low": 2, "clear": 3}
_DISPOSITION_LABEL = {
    "escalate": "🔴 Escalate",
    "monitor": "🟡 Monitor",
    "accept": "🟢 Accept",
}


def build_worklist(results: list[MakerCheckerResult]) -> str:
    """Render a full reviewer worklist, most-risky first."""
    ordered = sorted(
        results,
        key=lambda r: (_TIER_RANK[r.assessment.tier], -r.assessment.risk_score),
    )
    n = len(results)
    escalate = sum(1 for r in results if r.final_disposition == "escalate")
    monitor = sum(1 for r in results if r.final_disposition == "monitor")
    challenges = sum(1 for r in results if r.challenge.verdict != "agree")
    guard_fail = sum(1 for r in results if not r.note_guard_passed)

    lines = [
        "# Manual JE anomaly review — reviewer worklist",
        "",
        f"- Entries assessed: **{n}**",
        f"- Escalate: **{escalate}**  ·  Monitor: **{monitor}**  ·  "
        f"Accept: **{n - escalate - monitor}**",
        f"- Challenger overrides (four-eyes changed the call): **{challenges}**",
        f"- Audit-seam failures (AI note cited an untraceable figure): "
        f"**{guard_fail}**",
        "",
        "> Flags are raised by deterministic rules; the reviewer/challenger notes "
        "are AI-drafted and code-checked. Code has the last word on disposition.",
        "",
        "---",
        "",
    ]

    for r in ordered:
        if r.assessment.tier in ("clear", "low"):
            continue    # worklist shows only what needs a human; low/clear are logged below
        lines.extend(_entry_block(r))

    # a compact tail so nothing is hidden: everything not on the worklist
    logged = [r for r in ordered if r.assessment.tier in ("clear", "low")]
    if logged:
        lines.append("## Logged (no review required)")
        lines.append("")
        for r in logged:
            je = r.assessment.je
            flags = ", ".join(r.assessment.flag_rules()) or "none"
            lines.append(f"- {je.je_id} — {je.account}, {je.amount:,.0f} "
                         f"{je.dr_cr} — score {r.assessment.risk_score} "
                         f"({flags})")
        lines.append("")

    return "\n".join(lines)


def _entry_block(r: MakerCheckerResult) -> list[str]:
    a = r.assessment
    je = a.je
    disp = _DISPOSITION_LABEL[r.final_disposition]
    guard = "" if r.note_guard_passed else "  ⚠️ *note failed the audit seam — do not rely on it*"
    out = [
        f"## {je.je_id} — {disp}  (score {a.risk_score}, {a.tier}){guard}",
        "",
        f"**Entry.** {je.account} ({je.account_type}) · {je.amount:,.2f} "
        f"{je.dr_cr} · period {je.period} · prepared by {je.preparer}"
        + (f", approved by {je.approver}" if je.approver else ", **unapproved**"),
        f"  \n*{je.description or '(no description)'}*",
        "",
        "**Flags**",
    ]
    for f in a.flags:
        out.append(f"- `{f.rule}` ({f.severity}) — {f.detail}")
    out += [
        "",
        f"**Reviewer** ({r.review.model}, {r.review.residual_risk}). "
        f"{r.review.note}",
        f"  \n*Recommended action:* {r.review.recommended_action}",
        "",
        f"**Challenger** ({r.challenge.model}, **{r.challenge.verdict}**). "
        f"{r.challenge.rationale}",
        "",
        "---",
        "",
    ]
    return out


def summarise(results: list[MakerCheckerResult]) -> dict:
    """Machine-readable summary (for logs / the eval harness in Week 4)."""
    return {
        "entries": len(results),
        "escalate": sum(1 for r in results if r.final_disposition == "escalate"),
        "monitor": sum(1 for r in results if r.final_disposition == "monitor"),
        "accept": sum(1 for r in results if r.final_disposition == "accept"),
        "challenger_overrides": sum(1 for r in results
                                    if r.challenge.verdict != "agree"),
        "note_guard_failures": sum(1 for r in results
                                   if not r.note_guard_passed),
    }
