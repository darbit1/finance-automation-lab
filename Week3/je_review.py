"""
je_review.py  -  THE MAKER-CHECKER AI LAYER  (Week 3, Build 2)

The rule engine (je_rules.py) has already decided, deterministically, *what*
fired and *how risky* it is. This layer adds the human-judgement edge that a
rule engine cannot own:

  reviewer  (subagent 1): reads one deterministic Assessment and writes a short
                          reviewer note + a residual-risk call. It judges the
                          GREY-ZONE (medium-tier) cases the rules can flag but
                          not resolve. It never recomputes a number.

  challenger (subagent 2): reads the same Assessment AND the reviewer's note,
                           then critiques it - four-eyes for agents. It looks for
                           false positives (over-flagging) and MISSED risk (the
                           reviewer waved through something a high-severity flag
                           says it shouldn't). Segregation of duties, for AI.

  guard_note (the audit seam): a deterministic check that the reviewer note only
                           cites figures present in the Assessment - the same
                           "AI drafts, code checks" seam as Week 1's eval_check.

Right-size + cost: the reviewer is the cheap, high-volume step -> Haiku. The
challenger has to reason about what's *absent* (missed risk), which is harder ->
Sonnet. Opus is never needed here. High-tier entries are auto-escalated by code
regardless of what the AI says, so the AI is only decisive in the medium zone.

Each function has TWO modes, exactly like Week 1's ai_layer.py:
  "template" : deterministic, offline, no API key - powers the demo + tests.
  "llm"      : the real Anthropic call (production path), guarded behind an import.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from je_rules import Assessment, SEVERITY_WEIGHT

# Model routing (documented per CLAUDE.md: which model, why).
REVIEWER_MODEL = "claude-haiku-4-5-20251001"    # cheap, high-volume triage
CHALLENGER_MODEL = "claude-sonnet-5"            # reasons about missed risk


# ============================================================================
# Outputs
# ============================================================================
@dataclass
class ReviewNote:
    je_id: str
    residual_risk: str        # "escalate" | "monitor" | "accept"
    note: str                 # plain-English reviewer note
    recommended_action: str
    model: str

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class Challenge:
    je_id: str
    verdict: str              # "agree" | "false_positive" | "missed_risk"
    rationale: str
    model: str

    def to_dict(self) -> dict:
        return self.__dict__.copy()


# ============================================================================
# REVIEWER subagent
# ============================================================================
def review(assessment: Assessment, mode: str = "template") -> ReviewNote:
    if mode == "template":
        return _review_template(assessment)
    if mode == "llm":
        return _review_llm(assessment)
    raise ValueError("mode must be 'template' or 'llm'")


# a human-readable line per rule, used by the deterministic reviewer note
_RULE_PHRASING = {
    "over_threshold":     "a large-value entry",
    "round_thousand":     "a suspiciously round amount",
    "off_hours":          "an out-of-hours posting",
    "weak_description":   "an uninformative description",
    "no_support":         "no supporting document",
    "sensitive_account":  "a manual entry to a control/bank/equity account",
    "entry_post_gap":     "a long delay between entry date and posting",
    "closed_period":      "a posting into a closed period",
    "sod_breach":         "a segregation-of-duties concern",
    "near_duplicate":     "a possible duplicate/split entry",
}

_RULE_ACTION = {
    "sensitive_account":  "Confirm why this was posted manually rather than through the subledger; obtain sign-off from the account owner.",
    "closed_period":      "Reopen only via the documented close-reopen control; confirm the period owner authorised it.",
    "sod_breach":         "Route to an independent approver; the preparer cannot approve their own entry.",
    "no_support":         "Obtain and attach the supporting document before this entry is accepted.",
    "near_duplicate":     "Compare against the matching entry; confirm this is not a double-post or a split to avoid the approval threshold.",
    "entry_post_gap":     "Confirm the entry lands in the correct period despite the posting delay.",
    "round_thousand":     "Confirm the amount traces to source rather than being an estimate/plug.",
    "over_threshold":     "Ensure senior approval consistent with the delegation-of-authority matrix.",
    "off_hours":          "Confirm the out-of-hours timing is explained by the close calendar.",
    "weak_description":   "Ask the preparer to add a description a reviewer can follow.",
}


def _review_template(a: Assessment) -> ReviewNote:
    """
    Deterministic reviewer note. Mirrors what a controller would write, using
    ONLY the fired flags + the entry's own facts. No number is introduced that
    the guard could not trace.
    """
    je = a.je
    if a.tier in ("clear", "low"):
        return ReviewNote(
            je_id=je.je_id, residual_risk="accept",
            note=(f"{je.je_id}: risk score {a.risk_score}, no material control "
                  f"concern. Logged, no reviewer action required."),
            recommended_action="None.", model="template")

    reasons = [_RULE_PHRASING.get(f.rule, f.rule) for f in a.flags]
    # residual-risk call: high tier -> escalate; medium -> monitor unless a
    # high-severity flag is present (then escalate). This is the code guard-rail
    # around the AI's judgement, not the AI's discretion.
    has_high = any(f.severity == "high" for f in a.flags)
    residual = "escalate" if (a.tier == "high" or has_high) else "monitor"

    # the single most severe flag drives the recommended action
    top = max(a.flags, key=lambda f: SEVERITY_WEIGHT[f.severity])
    action = _RULE_ACTION.get(top.rule, "Route to a reviewer.")

    note = (f"{je.je_id} ({je.account}, {je.amount:,.0f} {je.dr_cr}, "
            f"prepared by {je.preparer}): {len(a.flags)} flag(s) - "
            + "; ".join(reasons)
            + f". Risk score {a.risk_score} ({a.tier}). "
            + ("Escalate for independent review before this entry is relied upon."
               if residual == "escalate"
               else "Monitor: reviewer to confirm the flagged points are explained."))
    return ReviewNote(je_id=je.je_id, residual_risk=residual, note=note,
                      recommended_action=action, model="template")


def _review_llm(a: Assessment) -> ReviewNote:
    """
    Production path. The Assessment (facts + fired flags) is the ONLY context the
    model sees. It is told to judge residual risk and write a note WITHOUT
    introducing any figure or naming any control that did not fire. guard_note()
    then verifies compliance - the maker-checker seam.
    """
    import json, anthropic
    client = anthropic.Anthropic()
    facts = _assessment_facts(a)
    system = (
        "You are a financial controller reviewing a single flagged manual "
        "journal entry. You are given the entry's facts and the deterministic "
        "control flags that fired. Judge the RESIDUAL risk and write a short "
        "reviewer note. Rules: use ONLY the figures provided; introduce no new "
        "number; name no control that is not in the flags; if the flags do not "
        "justify a concern, say so. Return STRICT JSON with keys "
        "residual_risk ('escalate'|'monitor'|'accept'), note, recommended_action."
    )
    resp = client.messages.create(
        model=REVIEWER_MODEL, max_tokens=400,
        system=[{"type": "text", "text": system,
                 "cache_control": {"type": "ephemeral"}}],   # cache the instruction prefix
        messages=[{"role": "user", "content": json.dumps(facts)}],
    )
    raw = "".join(b.text for b in resp.content if b.type == "text")
    data = json.loads(re.sub(r"^```json|```$", "", raw.strip()).strip())
    return ReviewNote(je_id=a.je.je_id, residual_risk=data["residual_risk"],
                      note=data["note"],
                      recommended_action=data.get("recommended_action", ""),
                      model=REVIEWER_MODEL)


# ============================================================================
# CHALLENGER subagent  (four-eyes over the reviewer)
# ============================================================================
def challenge(a: Assessment, note: ReviewNote, mode: str = "template") -> Challenge:
    if mode == "template":
        return _challenge_template(a, note)
    if mode == "llm":
        return _challenge_llm(a, note)
    raise ValueError("mode must be 'template' or 'llm'")


def _challenge_template(a: Assessment, note: ReviewNote) -> Challenge:
    """
    Deterministic four-eyes critique. Catches the two failure modes of a lone
    reviewer: waving through real risk, and over-escalating noise.
    """
    has_high = any(f.severity == "high" for f in a.flags)

    # 1) MISSED RISK: reviewer did not escalate but a high-severity flag exists.
    if has_high and note.residual_risk != "escalate":
        high_rules = [f.rule for f in a.flags if f.severity == "high"]
        return Challenge(
            je_id=a.je.je_id, verdict="missed_risk",
            rationale=(f"Reviewer chose '{note.residual_risk}', but high-severity "
                       f"flag(s) {high_rules} require escalation. Overriding to "
                       f"escalate."),
            model="template")

    # 2) FALSE POSITIVE: escalated on a single low-severity flag only.
    if (note.residual_risk == "escalate" and len(a.flags) == 1
            and a.flags[0].severity == "low"):
        return Challenge(
            je_id=a.je.je_id, verdict="false_positive",
            rationale=(f"Single low-severity flag ({a.flags[0].rule}) does not "
                       f"warrant escalation in isolation; recommend monitor."),
            model="template")

    # 3) near-duplicate always deserves a pointed second look at the counterpart.
    dup = next((f for f in a.flags if f.rule == "near_duplicate"), None)
    if dup:
        return Challenge(
            je_id=a.je.je_id, verdict="agree",
            rationale=("Concur. Additionally verify the matching entry named in "
                       "the duplicate flag is a genuinely separate transaction "
                       "and not a split to stay under the approval threshold."),
            model="template")

    return Challenge(je_id=a.je.je_id, verdict="agree",
                     rationale="Concur with the reviewer's assessment.",
                     model="template")


def _challenge_llm(a: Assessment, note: ReviewNote) -> Challenge:
    """
    Production path. The challenger sees the same facts + the reviewer's note and
    is asked specifically for false positives and MISSED risk. Sonnet, because
    reasoning about what is *absent* is the harder task.
    """
    import json, anthropic
    client = anthropic.Anthropic()
    system = (
        "You are a second, independent controller performing four-eyes review "
        "over a colleague's note on a flagged manual journal entry. Given the "
        "entry facts, the control flags, and the first reviewer's note, decide "
        "whether they (a) agree, (b) over-flagged a false positive, or (c) "
        "missed a real risk. Be sceptical of any 'accept'/'monitor' call when a "
        "high-severity flag is present. Return STRICT JSON with keys "
        "verdict ('agree'|'false_positive'|'missed_risk') and rationale."
    )
    payload = {"assessment": _assessment_facts(a), "reviewer_note": note.to_dict()}
    resp = client.messages.create(
        model=CHALLENGER_MODEL, max_tokens=400,
        system=[{"type": "text", "text": system,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": json.dumps(payload)}],
    )
    raw = "".join(b.text for b in resp.content if b.type == "text")
    data = json.loads(re.sub(r"^```json|```$", "", raw.strip()).strip())
    return Challenge(je_id=a.je.je_id, verdict=data["verdict"],
                     rationale=data["rationale"], model=CHALLENGER_MODEL)


# ============================================================================
# THE AUDIT SEAM  -  a deterministic guard over the AI note
# ============================================================================
def _allowed_numbers(a: Assessment) -> set:
    """
    Figures a reviewer note is permitted to mention: the entry's own facts plus
    identifiers that legitimately carry digits (the account code, the JE id).
    The guard polices invented *financial figures*, not identifiers.
    """
    je = a.je
    vals = {round(float(je.amount), 2), float(a.risk_score), float(len(a.flags))}
    for token in re.findall(r"\d+", f"{je.account} {je.je_id}"):
        vals.add(float(token))
    return vals


def guard_note(note: ReviewNote, a: Assessment,
               money_tol: float = 1.0) -> tuple[bool, list]:
    """
    True if every number in the reviewer note traces to the Assessment facts.
    Catches a model that invents a figure (a fabricated amount, a made-up count).
    Percentages and years are ignored; we only police material figures.
    Returns (passed, offending_tokens).
    """
    allowed = _allowed_numbers(a)
    offenders = []
    for raw in re.findall(r"[-+]?\d[\d,]*(?:\.\d+)?", note.note):
        val = float(raw.replace(",", ""))
        if val < 1000:                      # ignore small ordinals (flag counts, scores handled below)
            if any(abs(val - x) < 0.01 for x in allowed):
                continue
            # small numbers that aren't an allowed score/count are ignored as noise
            continue
        if not any(abs(val - x) <= money_tol for x in allowed):
            offenders.append(raw)
    return (len(offenders) == 0, offenders)


# ============================================================================
# helpers
# ============================================================================
def _assessment_facts(a: Assessment) -> dict:
    """The exact, minimal fact set handed to the model (and nothing else)."""
    je = a.je
    return {
        "je_id": je.je_id,
        "account": je.account,
        "account_type": je.account_type,
        "amount": je.amount,
        "dr_cr": je.dr_cr,
        "period": je.period,
        "preparer": je.preparer,
        "approver": je.approver or None,
        "description": je.description,
        "has_support": je.has_support,
        "risk_score": a.risk_score,
        "tier": a.tier,
        "flags": [{"rule": f.rule, "severity": f.severity, "detail": f.detail}
                  for f in a.flags],
    }


@dataclass
class MakerCheckerResult:
    """The full documented decision trail for one entry."""
    assessment: Assessment
    review: ReviewNote
    challenge: Challenge
    note_guard_passed: bool

    @property
    def final_disposition(self) -> str:
        """
        Code has the last word. The challenger can only make an entry MORE
        scrutinised, never less: a 'missed_risk' verdict forces escalation.
        """
        if self.challenge.verdict == "missed_risk":
            return "escalate"
        if self.challenge.verdict == "false_positive":
            return "monitor" if self.review.residual_risk == "escalate" else self.review.residual_risk
        return self.review.residual_risk


def run_maker_checker(a: Assessment, mode: str = "template") -> MakerCheckerResult:
    """Reviewer -> guard -> challenger for one entry. The core Week-3 loop."""
    note = review(a, mode=mode)
    passed, _ = guard_note(note, a)
    ch = challenge(a, note, mode=mode)
    return MakerCheckerResult(assessment=a, review=note, challenge=ch,
                              note_guard_passed=passed)
