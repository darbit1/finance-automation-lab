# JE anomaly rules — reference

Progressive-disclosure detail for the [je-reviewer](SKILL.md) Skill. Load this
only to tune a threshold, explain why a rule fired, or add a rule. All thresholds
live in `je_rules.RuleContext` — finance-owned, versioned, unit-tested; never
buried in a spreadsheet formula. Severity weights: `high=3, medium=2, low=1`.
Risk score = sum of weights; tier = `high` if any high-severity flag *or* score
≥ 5, `medium` if score ≥ 2, else `low`.

| Rule | Fires when | Severity | Why it matters (finance) |
|------|-----------|----------|--------------------------|
| `over_threshold` | `amount ≥ approval_threshold` (50,000) | medium | Large manual entries carry the most misstatement risk; must meet delegation-of-authority approval. |
| `round_thousand` | `amount ≥ round_min` (10,000) **and** an exact multiple of 1,000 | low | Round amounts suggest an estimate or a plug rather than a figure traced to source. Small round numbers are normal, so a floor applies. |
| `off_hours` | posted on a weekend, a configured holiday, or outside `business_start..business_end` (07:00–19:00) | low | Legitimate at close, but a known pattern for entries made to avoid scrutiny. |
| `weak_description` | description blank, shorter than `short_desc_len` (15), or a generic filler ("adjustment", "reclass", "plug", …) | medium if blank, else low | An entry a reviewer cannot understand from its memo is not supportable. |
| `no_support` | `has_support` is false | **high** if `amount ≥ approval_threshold`, else medium | Unsupported entries are the core documentation gap; severity scales with size. |
| `sensitive_account` | `account_type ∈ {control, bank, equity}` | **high** | A *manual* JE to a subledger/system-owned account (AP/AR control, bank/clearing, retained earnings) is the classic reconciling item that scares auditors. |
| `entry_post_gap` | `post_date − entry_date ≥ gap_days` (30) | medium | A stale entry posted long after its effective date can distort the wrong period (cut-off risk). |
| `closed_period` | `period ∈ closed_periods` | **high** | Posting into a signed-off period reopens finalised numbers — a serious control breach. |
| `sod_breach` | `preparer == approver` | **high** | Segregation-of-duties failure: the maker approved their own work. |
| `sod_breach` | no approver recorded | medium | No independent four-eyes on the entry. |
| `near_duplicate` | another entry: same `account`, same `amount` (±0.01), within `dup_window_days` (7) | medium | A possible double-post, or an amount split across entries to slide under the approval threshold. |

## Tuning notes
- **Thresholds are policy, not code.** Change `approval_threshold`, `round_min`,
  `gap_days`, `business_start/end`, `dup_window_days`, `short_desc_len`,
  `sensitive_types`, `short_desc_len` on the `RuleContext`. Re-run the tests.
- **`sensitive_types`** should match *your* chart of accounts' control/clearing/
  equity accounts. This is the highest-value rule; get the account list right.
- **False positives** usually come from `off_hours` at close (expected) and
  `near_duplicate` on genuine instalments. Both are low/medium by design so they
  *monitor* rather than *escalate*; the challenger explicitly re-checks
  near-duplicates against their counterpart.

## Adding a rule
1. Write a pure function `rule_x(je, ctx) -> Flag | None` in `je_rules.py`.
2. Add it to the `RULES` list (order = report order).
3. Add a unit test in `working/test_je_rules.py` for the fire and no-fire cases.
4. If the AI reviewer should phrase it, add entries to `_RULE_PHRASING` and
   `_RULE_ACTION` in `je_review.py`.
