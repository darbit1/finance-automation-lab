"""
je_rules.py  -  THE DETERMINISTIC RULE ENGINE  (Week 3, Build 2)

A detective control over a manual-journal-entry register. Every flag here is
raised by a PURE, TESTED function - no AI touches this layer. The AI only comes
in afterwards (je_review.py) to judge the *ambiguous* flags and write a reviewer
note; a second agent then challenges it. The numbers, dates and booleans that
decide a flag are all computed here, so the control is versioned and auditable.

Right-size note: "was this posted on a Saturday?", "is the preparer also the
approver?", "does another entry have the same account+amount?" are all exact
tests. Sending them to an LLM would be slower, costlier and *non-deterministic* -
exactly what a control cannot be. Code flags; AI only explains the grey areas.

Schema of one journal entry (one row = one manual JE):
    je_id        str    document number
    entry_date   date   the effective/accounting date of the entry
    post_ts      datetime  when it was actually posted (date + time)
    period       str    accounting period, "YYYY-MM"
    account      str    primary GL account hit
    account_type str    e.g. "expense", "revenue", "control", "equity", "bank"
    amount       float  absolute magnitude of the entry (> 0)
    dr_cr        str    "DR" or "CR"
    preparer     str    who created it
    approver     str    who approved it ("" if unapproved)
    description  str    free-text memo
    has_support  bool   is a supporting document attached?
    dimensions   dict   {"department","class","location"} - "" if blank

Each rule returns a Flag or None. `evaluate()` runs them all for one entry;
`score()` turns the flags into a deterministic risk tier.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable, Optional


# ============================================================================
# Data model
# ============================================================================
@dataclass
class JournalEntry:
    je_id: str
    entry_date: date
    post_ts: datetime
    period: str
    account: str
    account_type: str
    amount: float
    dr_cr: str
    preparer: str
    approver: str
    description: str
    has_support: bool
    dimensions: dict = field(default_factory=dict)


@dataclass
class Flag:
    """One rule firing on one entry. `severity` weights the risk score."""
    rule: str
    severity: str          # "high" | "medium" | "low"
    detail: str            # human-readable, cites the exact facts that fired it


@dataclass
class RuleContext:
    """Everything a rule may need beyond the single entry it judges."""
    register: list          # all entries, for cross-entry rules (duplicates)
    closed_periods: frozenset = frozenset()
    holidays: frozenset = frozenset()          # frozenset[date]
    # thresholds (all finance-owned, versioned here rather than in a formula):
    approval_threshold: float = 50_000.0       # entries at/above need scrutiny
    round_min: float = 10_000.0                # ignore small round numbers
    gap_days: int = 30                         # entry-vs-post gap that looks stale
    business_start: int = 7                    # 07:00 local
    business_end: int = 19                     # 19:00 local
    dup_window_days: int = 7                   # near-duplicate look-back/ahead
    short_desc_len: int = 15                   # chars; below = uninformative
    # accounts that should almost never take a *manual* entry (posted by
    # subledgers / system processes). A manual JE here is the classic audit red
    # flag - see Week 8 (subledger-to-GL tie-out).
    sensitive_types: frozenset = frozenset({"control", "bank", "equity"})
    # run the approver-based rule (sod_breach). Set False for accounts with no JE
    # approval workflow: there the "no independent approver" branch has no signal
    # and would flag every entry. True is correct where journals are approved.
    enable_approver_rules: bool = True


SEVERITY_WEIGHT = {"high": 3, "medium": 2, "low": 1}


# ============================================================================
# The rules  -  each one pure: (JournalEntry, RuleContext) -> Flag | None
# ============================================================================
def rule_over_threshold(je: JournalEntry, ctx: RuleContext) -> Optional[Flag]:
    """Large manual entries carry the most misstatement risk; always reviewed."""
    if je.amount >= ctx.approval_threshold:
        return Flag("over_threshold", "medium",
                    f"amount {je.amount:,.0f} >= approval threshold "
                    f"{ctx.approval_threshold:,.0f}")
    return None


def rule_round_thousand(je: JournalEntry, ctx: RuleContext) -> Optional[Flag]:
    """
    Suspiciously round amounts (exact thousands) suggest an estimate or a plug
    rather than a figure traced to source. Small round numbers are normal, so we
    only flag round amounts at/above `round_min`.
    """
    if je.amount >= ctx.round_min and je.amount % 1000 == 0:
        return Flag("round_thousand", "low",
                    f"amount {je.amount:,.0f} is an exact multiple of 1,000")
    return None


def rule_off_hours(je: JournalEntry, ctx: RuleContext) -> Optional[Flag]:
    """
    Posted on a weekend, a holiday, or outside business hours. Legitimate at
    close, but a known pattern for entries made to avoid scrutiny.
    """
    ts = je.post_ts
    reasons = []
    if ts.weekday() >= 5:                       # 5=Sat, 6=Sun
        reasons.append("weekend")
    if ts.date() in ctx.holidays:
        reasons.append("holiday")
    if ts.hour < ctx.business_start or ts.hour >= ctx.business_end:
        reasons.append(f"{ts.hour:02d}:{ts.minute:02d} outside "
                       f"{ctx.business_start:02d}:00-{ctx.business_end:02d}:00")
    if reasons:
        return Flag("off_hours", "low",
                    "posted " + ", ".join(reasons) + f" ({ts:%Y-%m-%d %H:%M})")
    return None


def rule_weak_description(je: JournalEntry, ctx: RuleContext) -> Optional[Flag]:
    """
    Missing or uninformative memo. An entry a reviewer cannot understand from its
    description is not supportable. Generic fillers ("adjustment", "reclass",
    "to correct", "per <name>") are treated as no description.
    """
    desc = (je.description or "").strip()
    generic = {"adjustment", "adj", "reclass", "correction", "to correct",
               "true up", "true-up", "plug", "misc", "journal", "entry"}
    if not desc:
        return Flag("weak_description", "medium", "description is blank")
    low = desc.lower()
    if len(desc) < ctx.short_desc_len or low in generic:
        return Flag("weak_description", "low",
                    f"description uninformative: {desc!r}")
    return None


def rule_no_support(je: JournalEntry, ctx: RuleContext) -> Optional[Flag]:
    """
    No supporting document attached. Severity rises with size: an unsupported
    entry at/above the approval threshold is a material control gap.
    """
    if not je.has_support:
        sev = "high" if je.amount >= ctx.approval_threshold else "medium"
        return Flag("no_support", sev,
                    f"no supporting document (amount {je.amount:,.0f})")
    return None


def rule_sensitive_account(je: JournalEntry, ctx: RuleContext) -> Optional[Flag]:
    """
    Manual entry to an account normally maintained by a subledger or system
    process (AP/AR control, bank/clearing, equity/retained earnings). These are
    the reconciling items that scare auditors - a human moving a control account
    by hand outside the subledger.
    """
    if je.account_type in ctx.sensitive_types:
        return Flag("sensitive_account", "high",
                    f"manual JE to {je.account_type} account {je.account!r}")
    return None


def rule_entry_post_gap(je: JournalEntry, ctx: RuleContext) -> Optional[Flag]:
    """
    Large gap between the effective (entry) date and when it was actually posted.
    A stale entry posted long after its date can distort the wrong period and
    hints at cut-off manipulation.
    """
    gap = (je.post_ts.date() - je.entry_date).days
    if gap >= ctx.gap_days:
        return Flag("entry_post_gap", "medium",
                    f"{gap} days between entry date {je.entry_date} and posting "
                    f"{je.post_ts.date()}")
    return None


def rule_closed_period(je: JournalEntry, ctx: RuleContext) -> Optional[Flag]:
    """
    Back-dated into a period that is already closed. Posting to a closed period
    reopens signed-off numbers and is a serious control breach.
    """
    if je.period in ctx.closed_periods:
        return Flag("closed_period", "high",
                    f"posted into closed period {je.period}")
    return None


def rule_sod_breach(je: JournalEntry, ctx: RuleContext) -> Optional[Flag]:
    """
    Segregation-of-duties breach: the preparer is also the approver, or the entry
    was never independently approved. The whole point of maker-checker.
    """
    if je.approver and je.preparer == je.approver:
        return Flag("sod_breach", "high",
                    f"preparer and approver are the same person "
                    f"({je.preparer})")
    if not je.approver:
        return Flag("sod_breach", "medium",
                    f"no independent approver recorded (preparer {je.preparer})")
    return None


def rule_near_duplicate(je: JournalEntry, ctx: RuleContext) -> Optional[Flag]:
    """
    Another entry in the register hits the SAME account for the SAME amount
    within a short window - a possible double-post, or an amount split across
    entries to slide under an approval threshold.
    """
    for other in ctx.register:
        if other is je or other.je_id == je.je_id:
            continue
        if (other.account == je.account
                and abs(other.amount - je.amount) < 0.01
                and abs((other.post_ts.date() - je.post_ts.date()).days)
                <= ctx.dup_window_days):
            return Flag("near_duplicate", "medium",
                        f"matches {other.je_id}: same account {je.account!r}, "
                        f"amount {je.amount:,.0f}, within {ctx.dup_window_days}d")
    return None


# The registered rule set (order = the order flags are reported).
RULES: list[Callable[[JournalEntry, RuleContext], Optional[Flag]]] = [
    rule_over_threshold,
    rule_round_thousand,
    rule_off_hours,
    rule_weak_description,
    rule_no_support,
    rule_sensitive_account,
    rule_entry_post_gap,
    rule_closed_period,
    rule_sod_breach,
    rule_near_duplicate,
]


# ============================================================================
# Evaluation + deterministic scoring
# ============================================================================
# rules that depend on an approval workflow; skipped when enable_approver_rules is False.
_APPROVER_RULES = {rule_sod_breach}


def evaluate(je: JournalEntry, ctx: RuleContext) -> list[Flag]:
    """Run every rule against one entry; return the flags that fired, in order."""
    active = [r for r in RULES
              if ctx.enable_approver_rules or r not in _APPROVER_RULES]
    return [f for f in (rule(je, ctx) for rule in active) if f is not None]


def score(flags: list[Flag]) -> tuple[int, str]:
    """
    Deterministic risk score = sum of severity weights, mapped to a tier.
    The tier decides who the AI layer sends where:
        high   -> reviewer must look (any high-severity flag, or score >= 5)
        medium -> reviewer judges the residual risk (the AI's grey zone)
        low    -> logged, no review needed
        clear  -> nothing fired
    """
    if not flags:
        return 0, "clear"
    total = sum(SEVERITY_WEIGHT[f.severity] for f in flags)
    has_high = any(f.severity == "high" for f in flags)
    if has_high or total >= 5:
        return total, "high"
    if total >= 2:
        return total, "medium"
    return total, "low"


@dataclass
class Assessment:
    """The full deterministic verdict on one entry - the input to the AI layer."""
    je: JournalEntry
    flags: list[Flag]
    risk_score: int
    tier: str

    def flag_rules(self) -> list[str]:
        return [f.rule for f in self.flags]


def assess(je: JournalEntry, ctx: RuleContext) -> Assessment:
    flags = evaluate(je, ctx)
    s, tier = score(flags)
    return Assessment(je=je, flags=flags, risk_score=s, tier=tier)


def assess_register(register: list[JournalEntry], ctx: RuleContext) -> list[Assessment]:
    """
    Assess an entire register. We point the context at this register so the
    cross-entry rules (near-duplicate) can see every other line.
    """
    ctx.register = register
    return [assess(je, ctx) for je in register]
