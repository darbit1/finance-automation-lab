"""
test_flux.py  -  run with:  python3 test_flux.py
Plain asserts (no pytest needed). Tests the deterministic core + the seam.
"""

import pandas as pd
from flux_engine import compute_flux, get_flagged_facts, Thresholds, build_facts
from eval_check import check_narrative, extract_numbers
from ai_layer import explain_out

T = Thresholds(material_abs=25_000, material_pct=0.10, review_abs=10_000, review_pct=0.05)


def df(rows):
    return pd.DataFrame(rows, columns=["account", "account_type", "period_prior", "period_current"])


def test_basic_variance():
    f = compute_flux(df([("A", "expense", 100, 150)]), T)
    assert f.loc[0, "variance_abs"] == 50
    assert abs(f.loc[0, "variance_pct"] - 0.5) < 1e-9
    assert f.loc[0, "direction"] == "increase"


def test_from_zero_no_division():
    f = compute_flux(df([("New", "expense", 0, 35_000)]), T)
    assert pd.isna(f.loc[0, "variance_pct"])      # undefined, not infinity
    assert f.loc[0, "direction"] == "new"


def test_cleared():
    f = compute_flux(df([("Old", "expense", 90_000, 0)]), T)
    assert f.loc[0, "direction"] == "cleared"
    assert f.loc[0, "tier"] == "material"


def test_tiering():
    f = compute_flux(df([
        ("Big", "expense", 100_000, 140_000),   # +40k / +40%  -> material
        ("Mid", "expense", 100_000, 108_000),   # +8k  / +8%   -> review (pct)
        ("Small", "expense", 100_000, 100_400), # +400 / +0.4% -> immaterial
    ]), T)
    assert list(f["tier"]) == ["material", "review", "immaterial"]


def test_flagged_excludes_immaterial():
    f = compute_flux(df([
        ("Big", "expense", 100_000, 140_000),
        ("Small", "expense", 100_000, 100_400),
    ]), T)
    facts = get_flagged_facts(f, T)
    assert [x.account for x in facts] == ["Big"]


def test_seam_passes_clean_narrative():
    f = compute_flux(df([("Marketing", "expense", 120_000, 165_000)]), T)
    fact = build_facts(f.loc[0], T)
    ok, offenders = check_narrative(explain_out(fact, "template"), fact)
    assert ok and offenders == []


def test_seam_rejects_invented_number():
    f = compute_flux(df([("Marketing", "expense", 120_000, 165_000)]), T)
    fact = build_facts(f.loc[0], T)
    ok, offenders = check_narrative("Marketing rose by EUR 99,999.", fact)
    assert not ok and "99,999" in offenders[0]


if __name__ == "__main__":
    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"  ok  {name}"); passed += 1
    print(f"\n{passed} tests passed")
