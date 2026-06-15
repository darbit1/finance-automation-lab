"""
flux_engine.py  -  DETERMINISTIC CORE  (Day 2)

The right-size rule in one file: every number here is computed by code.
No AI touches a figure. AI lives in ai_layer.py and only reads messy input
in / explains results out. The eval (eval_check.py) guards that boundary.

Input  : a two-period trial balance / P&L with columns
         account, account_type, period_prior, period_current
Output : the same rows enriched with variance_abs, variance_pct, direction,
         tier, thresholds_breached  +  a clean "facts object" per flagged line.
"""

from dataclasses import dataclass, asdict
from typing import Optional
import pandas as pd


# --- 1. Thresholds live in ONE place, never hard-coded inline ----------------
@dataclass(frozen=True)
class Thresholds:
    material_abs: float = 25_000     # currency units
    material_pct: float = 0.10       # 10%
    review_abs: float = 10_000
    review_pct: float = 0.05         # 5%
    currency: str = "EUR"


DEFAULT = Thresholds()


# --- 2. Per-line deterministic facts (the ONLY thing AI is later allowed to see)
@dataclass
class FluxFact:
    account: str
    account_type: str
    prior: float
    current: float
    variance_abs: float
    variance_pct: Optional[float]    # None when prior == 0 (undefined)
    direction: str                   # increase | decrease | new | cleared | flat
    tier: str                        # material | review | immaterial
    thresholds_breached: tuple       # e.g. ("abs", "pct")
    currency: str

    def to_dict(self):
        return asdict(self)


# --- 3. The deterministic computation ----------------------------------------
def _direction(prior: float, current: float, var: float) -> str:
    if prior == 0 and current != 0:
        return "new"
    if current == 0 and prior != 0:
        return "cleared"
    if var > 0:
        return "increase"
    if var < 0:
        return "decrease"
    return "flat"


def _variance_pct(prior: float, var: float) -> Optional[float]:
    if prior == 0:
        return None                  # undefined: do NOT divide by zero
    return var / abs(prior)


def _breaches(var_abs: float, var_pct: Optional[float], t: Thresholds) -> tuple:
    breached = []
    if abs(var_abs) >= t.review_abs:
        breached.append("abs")
    if var_pct is not None and abs(var_pct) >= t.review_pct:
        breached.append("pct")
    return tuple(breached)


def _tier(var_abs: float, var_pct: Optional[float], t: Thresholds) -> str:
    # from-zero lines have no pct, so tier on absolute size only
    big_abs = abs(var_abs) >= t.material_abs
    big_pct = var_pct is not None and abs(var_pct) >= t.material_pct
    if var_pct is None:
        return "material" if big_abs else ("review" if abs(var_abs) >= t.review_abs else "immaterial")
    if big_abs and big_pct:
        return "material"
    if abs(var_abs) >= t.review_abs or abs(var_pct) >= t.review_pct:
        return "review"
    return "immaterial"


def compute_flux(df: pd.DataFrame, t: Thresholds = DEFAULT) -> pd.DataFrame:
    """Add deterministic variance columns. Pure function: same input -> same output."""
    required = {"account", "account_type", "period_prior", "period_current"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")

    out = df.copy()
    out["variance_abs"] = out["period_current"] - out["period_prior"]
    out["variance_pct"] = [
        _variance_pct(p, v) for p, v in zip(out["period_prior"], out["variance_abs"])
    ]
    out["direction"] = [
        _direction(p, c, v)
        for p, c, v in zip(out["period_prior"], out["period_current"], out["variance_abs"])
    ]
    out["thresholds_breached"] = [
        _breaches(va, vp, t) for va, vp in zip(out["variance_abs"], out["variance_pct"])
    ]
    out["tier"] = [
        _tier(va, vp, t) for va, vp in zip(out["variance_abs"], out["variance_pct"])
    ]
    return out


def build_facts(row: pd.Series, t: Thresholds = DEFAULT) -> FluxFact:
    return FluxFact(
        account=row["account"],
        account_type=row["account_type"],
        prior=float(row["period_prior"]),
        current=float(row["period_current"]),
        variance_abs=float(row["variance_abs"]),
        variance_pct=(None if pd.isna(row["variance_pct"]) else float(row["variance_pct"])),
        direction=row["direction"],
        tier=row["tier"],
        thresholds_breached=tuple(row["thresholds_breached"]),
        currency=t.currency,
    )


def get_flagged_facts(df: pd.DataFrame, t: Thresholds = DEFAULT) -> list:
    """Everything that isn't immaterial -> a list of FluxFact (the AI's only input)."""
    flagged = df[df["tier"] != "immaterial"]
    return [build_facts(r, t) for _, r in flagged.iterrows()]
