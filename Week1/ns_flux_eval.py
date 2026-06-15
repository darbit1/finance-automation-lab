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


def allowed_numbers(fact, drivers) -> set:
    """Every number the narrative may legitimately contain."""
    f = fact.to_dict() if hasattr(fact, "to_dict") else dict(fact)
    vals = set()
    for k in ("prior", "current", "variance_abs"):
        if f.get(k) is not None:
            vals.add(round(float(f[k]), 2))
            vals.add(round(abs(float(f[k])), 2))
    if f.get("variance_pct") is not None:
        vals.add(round(float(f["variance_pct"]), 4))
        vals.add(round(abs(float(f["variance_pct"])), 4))
    for d in drivers:
        if d.get("amount") is not None:
            vals.add(round(float(d["amount"]), 2))
            vals.add(round(abs(float(d["amount"])), 2))
        if d.get("lines") is not None:
            vals.add(float(d["lines"]))           # e.g. "702 journals", "2 vendor bills"
    return vals


def allowed_entities(drivers) -> set:
    """The only organisations a narrative may name (lower-cased)."""
    return {(d.get("entity") or "").strip().lower() for d in drivers if d.get("entity")}


def check_explanation(narrative, fact, drivers, money_tol: float = 1.0, pct_tol: float = 0.001):
    """
    True only if every number traces to the facts/drivers AND every company-like name is one
    of the pulled drivers. Otherwise False plus the offending tokens.
    """
    allowed = allowed_numbers(fact, drivers)
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
