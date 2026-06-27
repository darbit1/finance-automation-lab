"""
ns_flux_eval.py  -  audit seam for AI driver explanations (extends eval_check.py)

When the AI explains a flagged account from its driver transactions, two deterministic
checks guard each narrative before it can reach a report or an email:

  1. NUMBER-MATCH  (hard guarantee): every figure in the narrative must trace to the
     account facts (prior, current, variance, variance %) OR to a pulled driver amount /
     line count. Reuses eval_check.extract_numbers.
  2. ENTITY PROVENANCE  (allowlist, heuristic): the narrative may only name organisations
     that appear in the pulled drivers. Any company-like name not in the driver set is
     rejected, so the AI cannot invent a vendor or a cause.

Honesty path: if no driver explains the swing, the AI is instructed to say so (e.g.
"driver not determinable from current transactions"); that text carries no new numbers or
vendors and so passes both checks. AI drafts, code checks, human approves - now at
transaction level.

Returns (ok: bool, offending_numbers: list, offending_entities: list).
"""

import re
from eval_check import extract_numbers

# Company-name heuristic: a Capitalised run ending in a legal-form suffix.
# Deliberately conservative - it is the entity check that is heuristic; the number
# check is the hard guarantee.
_COMPANY = re.compile(
    r"[A-Z][\w&.\-]*(?:\s+[A-Z0-9][\w&.\-]*)*\s+"
    r"(?:AB|B\.?V\.?|Ltd|Limited|GmbH|SAS|S\.?R\.?L\.?|Inc|LLC|Oy|AG|SE|S\.?A\.?)\b"
)

# Strip dates so day/year numerals are not mistaken for financial figures.
_MONTHS = (r"Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|"
           r"January|February|March|April|June|July|August|September|October|November|December")
_DATE_PATTERNS = [
    re.compile(rf"\b\d{{1,2}}\s+(?:{_MONTHS})\b", re.I),       # 29 Jan
    re.compile(rf"\b(?:{_MONTHS})\s+\d{{1,2}}\b", re.I),       # Jan 29
    re.compile(rf"\b(?:{_MONTHS})\s+\d{{4}}\b", re.I),         # Jan 2026 (period name)
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),                       # 2026-01-29
    re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b"),                 # 29/01/2026
]


def _strip_dates(text: str) -> str:
    for pat in _DATE_PATTERNS:
        text = pat.sub(" ", text)
    return text


def _add_number(vals: set, v) -> None:
    """Add a value in both money (2dp) and percentage (4dp) forms, plus absolutes, so a token is
    accepted whether it reads as '22,000' or '44%'."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return
    for n in (round(x, 2), round(abs(x), 2), round(x, 4), round(abs(x), 4)):
        vals.add(n)


def allowed_numbers(fact, drivers, extra_facts=None) -> set:
    """Every number the narrative may legitimately contain.

    extra_facts widens the allowlist to the deterministically-computed comparison figures the AI is
    allowed to cite - trend_facts (trailing_avg, sply_amount, vs_sply_pct, consecutive_months, ...),
    a YTD total, a sensitivity figure. Pass a dict (values used) or a flat list of numbers. Only
    figures CODE computed reach here, so 'recurring / SPLY / expected to normalise' stays grounded.
    """
    f = fact.to_dict() if hasattr(fact, "to_dict") else dict(fact)
    vals = set()
    # Accept either the engine's keys (prior/current) or the report's (prior_amt/current_amt).
    for keys in (("prior", "prior_amt"), ("current", "current_amt"), ("variance_abs",)):
        v = next((f[k] for k in keys if f.get(k) is not None), None)
        if v is not None:
            vals.add(round(float(v), 2))
            vals.add(round(abs(float(v)), 2))
    if f.get("variance_pct") is not None:
        vals.add(round(float(f["variance_pct"]), 4))
        vals.add(round(abs(float(f["variance_pct"])), 4))
    for d in drivers:
        if d.get("amount") is not None:
            vals.add(round(float(d["amount"]), 2))
            vals.add(round(abs(float(d["amount"])), 2))
        if d.get("lines") is not None:
            vals.add(float(d["lines"]))           # e.g. "702 journals", "2 vendor bills"
    if extra_facts:
        items = extra_facts.values() if hasattr(extra_facts, "values") else extra_facts
        for v in items:
            _add_number(vals, v)
    return vals


def allowed_entities(drivers) -> set:
    """The only organisations a narrative may name (lower-cased)."""
    return {(d.get("entity") or "").strip().lower() for d in drivers if d.get("entity")}


def check_explanation(narrative, fact, drivers, money_tol: float = 1.0, pct_tol: float = 0.001,
                      extra_facts=None):
    """
    True only if every number traces to the facts/drivers (or the code-computed extra_facts) AND
    every company-like name is one of the pulled drivers. Otherwise False plus the offending tokens.

    extra_facts: trend/SPLY/YTD/sensitivity figures from ns_flux_sql, so grounded comparison numbers
    pass while invented ones are still rejected.
    """
    allowed = allowed_numbers(fact, drivers, extra_facts)
    clean = _strip_dates(narrative)

    bad_numbers = []
    for token, value in extract_numbers(clean):
        tol = pct_tol if token.endswith("%") else money_tol
        if not any(abs(value - a) <= tol for a in allowed):
            bad_numbers.append(token)

    ents = allowed_entities(drivers)
    bad_entities = []
    for m in _COMPANY.finditer(narrative):
        name = m.group(0).strip().lower()
        if not any(name in e or e in name for e in ents):
            bad_entities.append(m.group(0).strip())

    ok = not bad_numbers and not bad_entities
    return ok, bad_numbers, bad_entities
