"""
run_flux_demo.py  -  end-to-end on synthetic data

Pipeline:  messy paste --read_in--> rows --compute_flux--> flagged facts
           --explain_out--> narrative --check_narrative--> pass/fail
"""

import pandas as pd
from synthetic_data import make_trial_balance
from flux_engine import compute_flux, get_flagged_facts, DEFAULT
from ai_layer import read_in, explain_out
from eval_check import check_narrative

pd.set_option("display.width", 120)
pd.set_option("display.max_columns", None)

MODE = "template"   # switch to "llm" once ANTHROPIC_API_KEY is set


def main():
    # 0. (Optional) prove the read-in edge works on a messy paste
    messy = """
    Account            Type       Prior        Current
    Marketing          expense    120,000      165,000
    Travel             expense    8 000        21,000
    Professional Fees  expense    0            35,000
    """
    parsed = read_in(messy, mode="template")
    print("=== read_in() on a messy paste (AI edge #1) ===")
    print(parsed.to_string(index=False), "\n")

    # 1. The real run: synthetic trial balance -> deterministic flux
    tb = make_trial_balance()
    flux = compute_flux(tb, DEFAULT)
    print("=== Deterministic flux table (no AI) ===")
    cols = ["account", "period_prior", "period_current",
            "variance_abs", "variance_pct", "direction", "tier"]
    show = flux[cols].copy()
    show["variance_pct"] = show["variance_pct"].apply(
        lambda p: "" if pd.isna(p) else f"{p*100:+.1f}%")
    print(show.to_string(index=False), "\n")

    # 2. Flagged facts -> narrative (AI edge #2) -> eval (the seam)
    facts = get_flagged_facts(flux, DEFAULT)
    print(f"=== {len(facts)} flagged lines: narrate + number-match eval ===")
    all_pass = True
    for f in facts:
        narrative = explain_out(f, mode=MODE)
        ok, offenders = check_narrative(narrative, f)
        all_pass &= ok
        flag = "PASS" if ok else f"REJECT {offenders}"
        print(f"[{flag}] {narrative}")

    # 3. Demonstrate the seam catching a hallucinated number
    print("\n=== Seam test: a narrative with an invented figure ===")
    bad = "Marketing: increase of EUR 45,000 (+38.0%), driven by a EUR 9,999 one-off."
    ok, offenders = check_narrative(bad, facts[[x.account for x in facts].index("Marketing")])
    print(f"[{'PASS' if ok else 'REJECT'}] offenders={offenders}  <- 45,000 and 9,999 are not in the facts")

    print(f"\nALL NARRATIVES CLEAN: {all_pass}")


if __name__ == "__main__":
    main()
