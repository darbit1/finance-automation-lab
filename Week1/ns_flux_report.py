"""
ns_flux_report.py  -  deterministic report assembler for the flux automation.

Takes the structured flux rows + the per-account narratives that PASSED the eval, and renders
a Markdown flux report. All figures come from the data; the only AI-authored text is each
narrative, and an unverified narrative is never shipped - it is replaced by a flag.

The same Markdown is the body the pipeline puts into a Gmail draft.
"""

import html as _html
from datetime import datetime, timezone


def _money(v, ccy="EUR"):
    return f"{ccy} {v:,.0f}"


def _pct(p):
    return "n/a" if p is None else f"{p*100:+.1f}%"


def _cs(p):
    """Common-size %, unsigned (a share of a base, not a movement)."""
    return "n/a" if p is None else f"{p*100:.1f}%"


def _run_at(meta):
    return meta.get("run_at") or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _enrich_text(r, ccy):
    """Deterministic per-account suffix (confidence + sensitivity). These are CODE-computed
    (ns_flux_sql.confidence_score / sensitivity), not AI text, so they are report chrome - not
    subject to the narrative eval. Returns '' when neither is present."""
    parts = []
    c = r.get("confidence")
    if c:
        parts.append(f"Confidence: {c['level']}" + (f" - {c['reason']}" if c.get("reason") else ""))
    s = r.get("sensitivity")
    if s:
        held = "yes" if s.get("flag_holds_down") else "no"
        parts.append(f"Sensitivity (±{s['pct']*100:.0f}%): variance {_money(s['variance_down'], ccy)} to "
                     f"{_money(s['variance_up'], ccy)}; flag holds at downside: {held}")
    return " | ".join(parts)


def build_report(meta: dict, review_rows: list, ok_count: int, notes=None) -> str:
    """
    meta: subsidiary, current_period, prior_period, abs_threshold, pct_threshold, currency, run_at(optional)
    review_rows: dicts with account, current_amt, prior_amt, variance_abs, variance_pct,
                 direction, narrative, eval_ok (bool)
    ok_count: number of within-tolerance (OK) accounts not shown.
    notes: optional list of reviewer-note strings (e.g. a flagged test tranid). Rendered as plain
           text so they are NOT subject to the number/provenance eval - put references with digits
           (journal ids, tranids) here, not in a narrative.
    """
    ccy = meta.get("currency", "EUR")
    run_at = _run_at(meta)
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
    show_sub = any(r.get("subsidiary") for r in review_rows)
    show_dept = any(r.get("Department") for r in review_rows)
    show_class = any(r.get("Class") for r in review_rows)
    show_sply = any(r.get("sply_amount") is not None for r in review_rows)
    show_ytd = any(r.get("ytd_amount") is not None for r in review_rows)
    show_cs = any(r.get("common_size_pct") is not None for r in review_rows)
    cols = (["Subsidiary"] if show_sub else []) + ["Account"] \
        + (["Department"] if show_dept else []) + (["Class"] if show_class else []) \
        + ["Prior", "Current"] \
        + (["SPLY"] if show_sply else []) + (["YTD"] if show_ytd else []) \
        + ["Variance", "%"] + (["% of base"] if show_cs else []) + ["Direction"]
    aligns = (["---"] if show_sub else []) + ["---"] \
        + (["---"] if show_dept else []) + (["---"] if show_class else []) \
        + ["--:", "--:"] \
        + (["--:"] if show_sply else []) + (["--:"] if show_ytd else []) \
        + ["--:", "--:"] + (["--:"] if show_cs else []) + [":--"]
    L.append("| " + " | ".join(cols) + " |")
    L.append("|" + "|".join(aligns) + "|")
    for r in review_rows:
        cells = ([r.get("subsidiary", "")] if show_sub else []) + [r["account"]] \
            + ([r.get("Department", "")] if show_dept else []) + ([r.get("Class", "")] if show_class else []) \
            + [_money(r["prior_amt"], ccy), _money(r["current_amt"], ccy)] \
            + ([_money(r["sply_amount"], ccy) if r.get("sply_amount") is not None else "n/a"] if show_sply else []) \
            + ([_money(r["ytd_amount"], ccy) if r.get("ytd_amount") is not None else "n/a"] if show_ytd else []) \
            + [_money(r["variance_abs"], ccy), _pct(r["variance_pct"])] \
            + ([_cs(r.get("common_size_pct"))] if show_cs else []) \
            + [r["direction"]]
        L.append("| " + " | ".join(str(c) for c in cells) + " |")
    L.append("")
    L.append("## Explanations")
    L.append("*AI drafted from the underlying transactions; every figure and vendor below was "
             "checked deterministically against the source data before this report was produced.*")
    L.append("")
    for r in review_rows:
        head = f"{r['subsidiary']} - {r['account']}" if (show_sub and r.get("subsidiary")) else r["account"]
        L.append(f"### {head}")
        if r.get("eval_ok"):
            L.append(r["narrative"])
            enrich = _enrich_text(r, ccy)
            if enrich:
                L.append("")
                L.append(f"*{enrich}*")
        else:
            L.append(f"> **Withheld - failed verification.** The drafted explanation contained a "
                     f"figure or vendor not traceable to the source transactions and was not shipped. "
                     f"Variance: {_money(r['variance_abs'], ccy)} ({_pct(r['variance_pct'])}). "
                     f"Manual review required.")
        for a in (r.get("assumptions") or []):
            L.append("")
            L.append(f"> **Assumption (unverified).** {a}")
        L.append("")
    for n in (notes or []):
        L.append(f"> **Reviewer note.** {n}")
        L.append("")
    L.append("---")
    L.append("*Calculation and checks are deterministic (NetSuite saved search + SuiteQL + "
             "number/provenance eval). AI is used only to turn the flagged transactions into "
             "plain-language explanations. AI drafts, code checks, human approves.*")
    return "\n".join(L)


def build_html(meta: dict, review_rows: list, ok_count: int, notes=None) -> str:
    """HTML version of build_report, generated in code so the pipeline never hand-writes HTML
    in a tool call (a big token saver). Same inputs as build_report."""
    ccy = meta.get("currency", "EUR")
    run_at = _run_at(meta)
    flagged = len(review_rows)
    verified = sum(1 for r in review_rows if r.get("eval_ok"))
    e = _html.escape

    cell = "padding:6px 8px;border:1px solid #ddd"
    rcell = f"text-align:right;{cell}"
    H = [f'<div style="font-family:Arial,Helvetica,sans-serif;color:#1a1a1a;max-width:780px">']
    H.append(f'<h2 style="margin:0 0 2px">Flux review - {e(str(meta["subsidiary"]))}</h2>')
    H.append(f'<div style="color:#666;font-size:13px;margin-bottom:14px"><strong>{e(str(meta["current_period"]))} '
             f'vs {e(str(meta["prior_period"]))}</strong> &nbsp;|&nbsp; generated {e(run_at)}</div>')
    H.append(f'<p style="font-size:14px;margin:0 0 6px">Tolerance gate: absolute swing &ge; '
             f'{_money(meta["abs_threshold"], ccy)} <strong>and</strong> (new account <strong>or</strong> '
             f'percentage swing &ge; {meta["pct_threshold"]*100:.0f}%).</p>')
    H.append(f'<p style="font-size:14px;margin:0 0 14px"><strong>{flagged} account(s) outside tolerance</strong>, '
             f'{ok_count} within tolerance. Narratives passing the number/provenance check: '
             f'<strong>{verified}/{flagged}</strong>.</p>')
    show_sub = any(r.get("subsidiary") for r in review_rows)
    show_dept = any(r.get("Department") for r in review_rows)
    show_class = any(r.get("Class") for r in review_rows)
    show_sply = any(r.get("sply_amount") is not None for r in review_rows)
    show_ytd = any(r.get("ytd_amount") is not None for r in review_rows)
    show_cs = any(r.get("common_size_pct") is not None for r in review_rows)
    sub_th = f'<th style="text-align:left;{cell}">Subsidiary</th>' if show_sub else ''
    dept_th = f'<th style="text-align:left;{cell}">Department</th>' if show_dept else ''
    class_th = f'<th style="text-align:left;{cell}">Class</th>' if show_class else ''
    sply_th = f'<th style="{rcell}">SPLY</th>' if show_sply else ''
    ytd_th = f'<th style="{rcell}">YTD</th>' if show_ytd else ''
    cs_th = f'<th style="{rcell}">% of base</th>' if show_cs else ''
    H.append('<table style="border-collapse:collapse;font-size:13px;width:100%"><thead>'
             '<tr style="background:#f3f4f6">'
             f'{sub_th}<th style="text-align:left;{cell}">Account</th>{dept_th}{class_th}<th style="{rcell}">Prior</th>'
             f'<th style="{rcell}">Current</th>{sply_th}{ytd_th}<th style="{rcell}">Variance</th>'
             f'<th style="{rcell}">%</th>{cs_th}<th style="text-align:left;{cell}">Direction</th></tr></thead><tbody>')
    for i, r in enumerate(review_rows):
        bg = ' style="background:#fafafa"' if i % 2 else ''
        sub_td = f'<td style="{cell}">{e(str(r.get("subsidiary", "")))}</td>' if show_sub else ''
        dept_td = f'<td style="{cell}">{e(str(r.get("Department", "")))}</td>' if show_dept else ''
        class_td = f'<td style="{cell}">{e(str(r.get("Class", "")))}</td>' if show_class else ''
        sply_td = (f'<td style="{rcell}">{_money(r["sply_amount"], ccy) if r.get("sply_amount") is not None else "n/a"}</td>'
                   if show_sply else '')
        ytd_td = (f'<td style="{rcell}">{_money(r["ytd_amount"], ccy) if r.get("ytd_amount") is not None else "n/a"}</td>'
                  if show_ytd else '')
        cs_td = f'<td style="{rcell}">{_cs(r.get("common_size_pct"))}</td>' if show_cs else ''
        H.append(f'<tr{bg}>{sub_td}<td style="{cell}">{e(str(r["account"]))}</td>{dept_td}{class_td}'
                 f'<td style="{rcell}">{_money(r["prior_amt"], ccy)}</td>'
                 f'<td style="{rcell}">{_money(r["current_amt"], ccy)}</td>{sply_td}{ytd_td}'
                 f'<td style="{rcell}">{_money(r["variance_abs"], ccy)}</td>'
                 f'<td style="{rcell}">{_pct(r["variance_pct"])}</td>{cs_td}'
                 f'<td style="{cell}">{e(str(r["direction"]))}</td></tr>')
    H.append('</tbody></table>')
    H.append('<h3 style="margin:18px 0 4px">Explanations</h3>')
    H.append('<p style="color:#666;font-size:12px;font-style:italic;margin:0 0 10px">AI drafted from the '
             'underlying transactions; every figure and vendor below was checked deterministically against '
             'the source data before this report was produced.</p>')
    for r in review_rows:
        label = f'{r["subsidiary"]} - {r["account"]}' if (show_sub and r.get("subsidiary")) else r["account"]
        if r.get("eval_ok"):
            enrich = _enrich_text(r, ccy)
            enrich_html = (f'<br><span style="color:#666;font-size:12px">{e(enrich)}</span>' if enrich else '')
            H.append(f'<p style="font-size:13px;margin:0 0 10px"><strong>{e(str(label))}.</strong> '
                     f'{e(str(r["narrative"]))}{enrich_html}</p>')
        else:
            H.append(f'<p style="font-size:13px;background:#fef2f2;border:1px solid #fecaca;padding:8px 10px;'
                     f'border-radius:4px;margin:6px 0 10px"><strong>{e(str(label))} - withheld, failed '
                     f'verification.</strong> The drafted explanation contained a figure or vendor not traceable '
                     f'to source and was not shipped. Variance: {_money(r["variance_abs"], ccy)} '
                     f'({_pct(r["variance_pct"])}). Manual review required.</p>')
        for a in (r.get("assumptions") or []):
            H.append(f'<p style="font-size:12px;background:#fff7ed;border:1px solid #fed7aa;padding:7px 10px;'
                     f'border-radius:4px;margin:4px 0 10px"><strong>Assumption (unverified).</strong> '
                     f'{e(str(a))}</p>')
    for n in (notes or []):
        H.append(f'<p style="font-size:13px;background:#fff7ed;border:1px solid #fed7aa;padding:8px 10px;'
                 f'border-radius:4px;margin:6px 0 12px"><strong>Reviewer note.</strong> {e(str(n))}</p>')
    H.append('<hr style="border:none;border-top:1px solid #ddd;margin:14px 0">')
    H.append('<p style="color:#666;font-size:12px;font-style:italic;margin:0">Calculation and checks are '
             'deterministic (NetSuite saved search / SuiteQL + number/provenance eval). AI is used only to turn '
             'the flagged transactions into plain-language explanations. AI drafts, code checks, human approves.</p>')
    H.append('</div>')
    return "\n".join(H)


def build_email(meta: dict, review_rows: list, ok_count: int, notes=None) -> dict:
    """One call -> the whole draft. Pass these straight to Gmail create_draft (subject, body=plain
    markdown, html_body=html) instead of hand-writing HTML each run."""
    return {
        "subject": f"Flux review - {meta['subsidiary']} - {meta['current_period']}",
        "body": build_report(meta, review_rows, ok_count, notes),
        "html": build_html(meta, review_rows, ok_count, notes),
    }


if __name__ == "__main__":
    # Smoke test on SYNTHETIC data only.
    meta = dict(subsidiary="Demo Subsidiary Ltd", current_period="Period N",
                prior_period="Period N-1", abs_threshold=25000, pct_threshold=0.10,
                currency="EUR", run_at="2026-01-01 09:00 UTC")
    rows = [
        dict(account="Legal consultancy", prior_amt=0, current_amt=379310, variance_abs=379310,
             variance_pct=None, direction="new", sply_amount=0, ytd_amount=379310,
             common_size_pct=0.12,
             narrative="New this period at EUR 379,310, driven by 2 vendor bills from Acme Legal Ltd.",
             confidence=dict(level="high", reason="drivers explain the swing and memo context is available",
                             coverage=0.97),
             sensitivity=dict(pct=0.05, variance_up=398276, variance_down=360345, flag_holds_down=True),
             assumptions=["One-off M&A advisory; expected to normalise next quarter (per controller)."],
             eval_ok=True),
        dict(account="Suspense", prior_amt=10000, current_amt=90000, variance_abs=80000,
             variance_pct=8.0, direction="increase",
             narrative="(bad narrative withheld)", eval_ok=False),
    ]
    print(build_report(meta, rows, ok_count=2))
