"""
ns_flux_report.py  -  deterministic report assembler for the flux automation.

Takes the structured flux rows + the per-account narratives that PASSED the eval, and renders
a Markdown flux report. All figures come from the data; the only AI-authored text is each
narrative, and an unverified narrative is never shipped - it is replaced by a flag.

The same Markdown is the body the pipeline puts into a Gmail draft.
"""

from datetime import datetime, timezone


def _money(v, ccy="EUR"):
    return f"{ccy} {v:,.0f}"


def _pct(p):
    return "n/a" if p is None else f"{p*100:+.1f}%"


def build_report(meta: dict, review_rows: list, ok_count: int) -> str:
    """
    meta: subsidiary, current_period, prior_period, abs_threshold, pct_threshold, currency, run_at(optional)
    review_rows: dicts with account, current_amt, prior_amt, variance_abs, variance_pct,
                 direction, narrative, eval_ok (bool)
    ok_count: number of within-tolerance (OK) accounts not shown.
    """
    ccy = meta.get("currency", "EUR")
    run_at = meta.get("run_at") or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    flagged = len(review_rows)
    verified = sum(1 for r in review_rows if r.get("eval_ok"))

    L = []
    L.append(f"# Flux review - {meta['subsidiary']}")
    L.append(f"**{meta['current_period']} vs {meta['prior_period']}**  |  generated {run_at}")
    L.append("")
    L.append(f"Tolerance gate: absolute swing >= {_money(meta['abs_threshold'], ccy)} "
             f"**and** (new account **or** percentage swing >= {meta['pct_threshold']*100:.0f}%).")
    L.append(f"**{flagged} account(s) outside tolerance**, {ok_count} within tolerance. "
             f"Narratives passing the number/provenance check: {verified}/{flagged}.")
    L.append("")
    L.append("| Account | Prior | Current | Variance | % | Direction |")
    L.append("|---|--:|--:|--:|--:|:--|")
    for r in review_rows:
        L.append(f"| {r['account']} | {_money(r['prior_amt'], ccy)} | {_money(r['current_amt'], ccy)} "
                 f"| {_money(r['variance_abs'], ccy)} | {_pct(r['variance_pct'])} | {r['direction']} |")
    L.append("")
    L.append("## Explanations")
    L.append("*AI drafted from the underlying transactions; every figure and vendor below was "
             "checked deterministically against the source data before this report was produced.*")
    L.append("")
    for r in review_rows:
        L.append(f"### {r['account']}")
        if r.get("eval_ok"):
            L.append(r["narrative"])
        else:
            L.append(f"> **Withheld - failed verification.** The drafted explanation contained a "
                     f"figure or vendor not traceable to the source transactions and was not shipped. "
                     f"Variance: {_money(r['variance_abs'], ccy)} ({_pct(r['variance_pct'])}). "
                     f"Manual review required.")
        L.append("")
    L.append("---")
    L.append("*Calculation and checks are deterministic (NetSuite saved search + SuiteQL + "
             "number/provenance eval). AI is used only to turn the flagged transactions into "
             "plain-language explanations. AI drafts, code checks, human approves.*")
    return "\n".join(L)


if __name__ == "__main__":
    # Smoke test on SYNTHETIC data only.
    meta = dict(subsidiary="Demo Subsidiary Ltd", current_period="Period N",
                prior_period="Period N-1", abs_threshold=25000, pct_threshold=0.10,
                currency="EUR", run_at="2026-01-01 09:00 UTC")
    rows = [
        dict(account="Legal consultancy", prior_amt=0, current_amt=379310, variance_abs=379310,
             variance_pct=None, direction="new",
             narrative="New this period at EUR 379,310, driven by 2 vendor bills from Acme Legal Ltd.",
             eval_ok=True),
        dict(account="Suspense", prior_amt=10000, current_amt=90000, variance_abs=80000,
             variance_pct=8.0, direction="increase",
             narrative="(bad narrative withheld)", eval_ok=False),
    ]
    print(build_report(meta, rows, ok_count=2))
