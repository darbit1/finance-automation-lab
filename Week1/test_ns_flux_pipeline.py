"""
test_ns_flux_pipeline.py  -  run:  python test_ns_flux_pipeline.py
Covers the token-saving additions: server-side review filter + in-code email assembly.
Synthetic data only.
"""

import ns_flux_sql as q
import ns_flux_report as r

META = dict(subsidiary="Demo Sub Ltd", current_period="May 2026", prior_period="Apr 2026",
            abs_threshold=25000, pct_threshold=0.10, currency="EUR", run_at="2026-01-01 09:00 UTC")
ROWS = [dict(account="Gross salaries", prior_amt=0, current_amt=34638, variance_abs=34638,
             variance_pct=None, direction="new",
             narrative="New this period at EUR 34,638 from one payroll journal.", eval_ok=True)]


def test_review_only_adds_server_side_filter():
    sql = q.flux_sql("Demo Sub Ltd", 295, 294, 25000, 0.10, review_only=True)
    assert "within_tolerance = 'REVIEW'" in sql


def test_default_returns_all_rows():
    sql = q.flux_sql("Demo Sub Ltd", 295, 294, 25000, 0.10)
    assert "within_tolerance = 'REVIEW'" not in sql


def test_drivers_by_id_single_book():
    sql = q.drivers_by_id_sql([867, 241], [295, 294], accounting_book=1)
    assert "tal.accountingbook = 1" in sql and "tal.account IN (867, 241)" in sql


def test_build_email_shape():
    email = r.build_email(META, ROWS, ok_count=2)
    assert set(email) == {"subject", "body", "html"}
    assert email["subject"] == "Flux review - Demo Sub Ltd - May 2026"
    assert "Gross salaries" in email["html"] and email["html"].startswith("<div")
    assert "Gross salaries" in email["body"]


def test_notes_render_outside_narrative():
    body = r.build_report(META, ROWS, ok_count=2, notes=["Driver is journal JE164589 (28 lines)."])
    assert "Reviewer note" in body and "JE164589" in body


def test_html_escapes_account():
    rows = [dict(account="A & B <Ltd>", prior_amt=0, current_amt=30000, variance_abs=30000,
                 variance_pct=None, direction="new", narrative="x", eval_ok=True)]
    html = r.build_html(META, rows, ok_count=0)
    assert "A &amp; B &lt;Ltd&gt;" in html


if __name__ == "__main__":
    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"  ok  {name}"); passed += 1
    print(f"\n{passed} tests passed")
