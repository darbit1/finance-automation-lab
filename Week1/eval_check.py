"""
eval_check.py  -  THE AUDIT SEAM  (Day 3)

A deterministic guard: every number that appears in an AI narrative must be
traceable to the FluxFact it was generated from. If the model invents a figure,
this rejects the narrative. This is what makes "AI drafts, code checks, human
approves" auditable.

Returns (passed: bool, offending_numbers: list).
"""

import re


def _normalise(token: str) -> float:
    """'EUR 42,000' / '42,000' / '+38.0%' / '90 000' -> float."""
    t = token.strip().replace(" ", "")
    is_pct = t.endswith("%")
    t = re.sub(r"[^\d.\-]", "", t)
    if t in ("", "-", ".", "-."):
        return None
    val = float(t)
    return val / 100 if is_pct else val


def extract_numbers(text: str):
    """Pull every numeric token (currency, plain, percentage) out of the text."""
    pattern = r"[-+]?\d[\d,\. ]*\d\s*%?|\d+%?"
    found = []
    for m in re.findall(pattern, text):
        v = _normalise(m)
        if v is not None:
            found.append((m.strip(), v))
    return found


def allowed_values(fact):
    """The complete set of figures a narrative is permitted to mention."""
    d = fact.to_dict()
    vals = {
        round(float(d["prior"]), 2),
        round(float(d["current"]), 2),
        round(float(d["variance_abs"]), 2),
        round(abs(float(d["variance_abs"])), 2),
    }
    if d["variance_pct"] is not None:
        vals.add(round(float(d["variance_pct"]), 4))
        vals.add(round(abs(float(d["variance_pct"])), 4))
    return vals


def check_narrative(narrative: str, fact, money_tol: float = 1.0, pct_tol: float = 0.001):
    """
    True if every number in the narrative matches an allowed value (within
    tolerance for rounding). Otherwise False + the offending tokens.
    """
    allowed = allowed_values(fact)
    offenders = []
    for token, value in extract_numbers(narrative):
        tol = pct_tol if token.endswith("%") else money_tol
        if not any(abs(value - a) <= tol for a in allowed):
            offenders.append(token)
    return (len(offenders) == 0, offenders)
