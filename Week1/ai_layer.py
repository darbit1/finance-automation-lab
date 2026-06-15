"""
ai_layer.py  -  THE THIN AI LAYER  (Day 3)

AI sits ONLY at the two edges:
  read_in()    : messy/unstructured input  -> structured rows   (read messy input IN)
  explain_out(): a single FluxFact         -> one-line narrative (explain results OUT)

It never computes a variance. The numbers come from flux_engine.py.
eval_check.py then verifies the narrative only contains numbers from the facts.

Each function has TWO modes:
  - "template" : deterministic, offline, no API key. Used for the demo + tests.
  - "llm"      : the real Anthropic call (the production path). Guarded so the
                 demo runs without a key; swap mode="llm" when you have one.
"""

import re
import pandas as pd


# ============================================================================
# READ-IN  : messy input -> structured DataFrame
# ============================================================================
def read_in(text: str, mode: str = "template") -> pd.DataFrame:
    """
    Honest right-size note: if the paste is already tabular, deterministic
    parsing is cheaper and more correct than an LLM. Escalate to mode='llm'
    only for genuinely messy input (OCR'd PDFs, free-form email tables).
    """
    if mode == "template":
        return _read_in_regex(text)
    if mode == "llm":
        return _read_in_llm(text)
    raise ValueError("mode must be 'template' or 'llm'")


def _num(s: str) -> float:
    """Parse '1,440,000', '(90 000)', 'EUR 35.000' -> float. Parens = negative."""
    s = s.strip()
    neg = s.startswith("(") and s.endswith(")")
    s = re.sub(r"[^\d.,-]", "", s)            # strip currency words/symbols
    s = s.replace(" ", "")
    # treat both ',' and '.' as thousands separators when used as groupers
    s = s.replace(",", "").replace(".", "") if s.count(".") > 1 or s.count(",") > 1 else s.replace(",", "")
    val = float(re.sub(r"[^\d.-]", "", s) or 0)
    return -val if neg else val


def _read_in_regex(text: str) -> pd.DataFrame:
    """Deterministic parser for reasonably structured pastes."""
    rows = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line or line.lower().startswith(("account", "total")):
            continue
        # split on 2+ spaces, tabs, or | so account names keep their single spaces
        parts = re.split(r"\s{2,}|\t|\|", line)
        parts = [p for p in (p.strip() for p in parts) if p]
        if len(parts) < 3:
            continue
        account = parts[0]
        prior, current = _num(parts[-2]), _num(parts[-1])
        atype = parts[1] if len(parts) >= 4 else "unknown"
        rows.append({"account": account, "account_type": atype,
                     "period_prior": prior, "period_current": current})
    return pd.DataFrame(rows)


def _read_in_llm(text: str) -> pd.DataFrame:
    """
    Production path. The LLM ONLY restructures - it is told not to compute or
    invent. Output is strict JSON, which we parse and hand to the deterministic
    engine. (Requires the anthropic SDK + ANTHROPIC_API_KEY.)
    """
    import json, anthropic
    client = anthropic.Anthropic()
    prompt = (
        "Convert this trial balance into JSON: a list of objects with keys "
        "account, account_type, period_prior, period_current. "
        "Copy numbers EXACTLY as written; do NOT compute, round, or invent. "
        "Return ONLY the JSON array.\n\n" + text
    )
    resp = client.messages.create(
        model="claude-sonnet-4-20250514", max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = "".join(b.text for b in resp.content if b.type == "text")
    raw = re.sub(r"^```json|```$", "", raw.strip()).strip()
    return pd.DataFrame(json.loads(raw))


# ============================================================================
# EXPLAIN-OUT : one FluxFact -> one-line narrative
# ============================================================================
def explain_out(fact, mode: str = "template") -> str:
    if mode == "template":
        return _explain_template(fact)
    if mode == "llm":
        return _explain_llm(fact)
    raise ValueError("mode must be 'template' or 'llm'")


def _fmt_money(v: float, ccy: str) -> str:
    return f"{ccy} {v:,.0f}"


def _fmt_pct(p) -> str:
    return "n/a" if p is None else f"{p*100:+.1f}%"


def _explain_template(fact) -> str:
    """Deterministic narrative. Uses ONLY numbers present in the fact."""
    d = fact.to_dict()
    sign = "+" if d["variance_abs"] >= 0 else "-"
    abs_str = _fmt_money(abs(d["variance_abs"]), d["currency"])
    if d["direction"] == "new":
        return (f"{d['account']}: new this period at "
                f"{_fmt_money(d['current'], d['currency'])} "
                f"(prior {_fmt_money(d['prior'], d['currency'])}). [{d['tier']}]")
    if d["direction"] == "cleared":
        return (f"{d['account']}: cleared to {_fmt_money(d['current'], d['currency'])} "
                f"from {_fmt_money(d['prior'], d['currency'])} "
                f"({sign}{abs_str}). [{d['tier']}]")
    return (f"{d['account']}: {d['direction']} of {sign}{abs_str} "
            f"({_fmt_pct(d['variance_pct'])}), "
            f"{_fmt_money(d['prior'], d['currency'])} -> "
            f"{_fmt_money(d['current'], d['currency'])}. "
            f"Driver: <reviewer to confirm>. [{d['tier']}]")


def _explain_llm(fact) -> str:
    """
    Production path. The fact dict is the ONLY data the model sees. The prompt
    forbids new numbers and forbids inventing causes. eval_check.py then
    verifies compliance - that is the maker-checker seam.
    """
    import anthropic
    client = anthropic.Anthropic()
    prompt = (
        "Write ONE sentence explaining this account movement for a flux report. "
        "Use ONLY the numbers in this data. Do not introduce any other figure. "
        "Do not state a cause; if a driver is unknown, write '<reviewer to confirm>'.\n\n"
        f"{fact.to_dict()}"
    )
    resp = client.messages.create(
        model="claude-sonnet-4-20250514", max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in resp.content if b.type == "text").strip()
