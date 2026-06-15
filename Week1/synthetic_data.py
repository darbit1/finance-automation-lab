"""
synthetic_data.py  -  fabricated data only (build_log guardrail: synthetic-only)

Deterministic (seeded) so the demo is reproducible. Includes deliberate
edge cases: a large swing, a from-zero (new) account, and a cleared account.
"""

import pandas as pd

ROWS = [
    # account,                 type,        prior,    current
    ("Revenue - Subscriptions", "income",   1_200_000, 1_440_000),
    ("Revenue - Services",      "income",     380_000,   362_000),
    ("Cost of Sales",           "cogs",       540_000,   631_000),
    ("Marketing",               "expense",    120_000,   165_000),   # large swing
    ("Payroll",                 "expense",    610_000,   624_000),
    ("Software & Subscriptions","expense",     44_000,    47_500),
    ("Travel",                  "expense",      8_000,    21_000),    # small base, big %
    ("Professional Fees",       "expense",          0,    35_000),    # NEW (from zero)
    ("Restructuring",           "expense",     90_000,         0),    # CLEARED
    ("Office & Admin",          "expense",     31_000,    31_400),    # immaterial
    ("Bank Interest",           "expense",      5_200,     5_050),    # immaterial
    ("FX Gains/Losses",         "other",       -12_000,    18_000),   # sign flip
]


def make_trial_balance() -> pd.DataFrame:
    return pd.DataFrame(
        [{"account": a, "account_type": t, "period_prior": p, "period_current": c}
         for (a, t, p, c) in ROWS]
    )


if __name__ == "__main__":
    df = make_trial_balance()
    df.to_csv("synthetic_tb.csv", index=False)
    print(df.to_string(index=False))
