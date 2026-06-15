"""
test_ns_flux_eval.py  -  run:  python test_ns_flux_eval.py
Synthetic data only. Tests the transaction-level audit seam (number-match + provenance).
"""

from ns_flux_eval import check_explanation, allowed_numbers, allowed_entities

# A synthetic flagged account + its (synthetic) driver transactions.
FACT = {
    "account": "Legal consultancy",
    "prior": 0.0, "current": 379310.0,
    "variance_abs": 379310.0, "variance_pct": None,
    "direction": "new",
}
DRIVERS = [{"txn_type": "VendBill", "entity": "Acme Legal Ltd", "lines": 2, "amount": 379310.0}]


def test_clean_narrative_passes():
    n = "Legal consultancy is new at EUR 379,310, driven by 2 vendor bills from Acme Legal Ltd."
    ok, bad_n, bad_e = check_explanation(n, FACT, DRIVERS)
    assert ok and bad_n == [] and bad_e == []


def test_invented_number_rejected():
    n = "Legal consultancy is new at EUR 379,310, including a EUR 999,999 one-off."
    ok, bad_n, bad_e = check_explanation(n, FACT, DRIVERS)
    assert not ok and any("999,999" in t for t in bad_n)


def test_invented_vendor_rejected():
    n = "Legal consultancy is new at EUR 379,310, driven by a bill from Globex GmbH."
    ok, bad_n, bad_e = check_explanation(n, FACT, DRIVERS)
    assert not ok and any("Globex" in t for t in bad_e)


def test_unknown_driver_path_passes():
    # No driver explains it -> the honest fallback carries no new numbers/vendors.
    n = "Driver not determinable from current transactions; refer to prior-period journals."
    ok, bad_n, bad_e = check_explanation(n, FACT, [])
    assert ok and bad_n == [] and bad_e == []


def test_date_not_flagged_as_amount():
    # A bare day/period reference must not be mistaken for an invented figure.
    n = "New at EUR 379,310 from one bill dated 29 Jan (Acme Legal Ltd)."
    ok, bad_n, bad_e = check_explanation(n, FACT, DRIVERS)
    assert ok, f"dates leaked into number check: {bad_n}"


def test_line_count_allowed():
    n = "Driven by 2 vendor bills from Acme Legal Ltd totalling EUR 379,310."
    ok, bad_n, bad_e = check_explanation(n, FACT, DRIVERS)
    assert ok and bad_n == []


if __name__ == "__main__":
    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"  ok  {name}"); passed += 1
    print(f"\n{passed} tests passed")
