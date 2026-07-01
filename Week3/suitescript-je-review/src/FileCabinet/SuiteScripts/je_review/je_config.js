/**
 * je_config.js  -  central configuration for the SuiteScript manual-JE anomaly reviewer.
 *
 * Edit these defaults, OR add matching Script Parameters on the deployment and they will override
 * (see README). One module = one source of truth for the orchestrator and helpers. Every threshold
 * mirrors the Python build's RuleContext (Week3/je_rules.py) so the control is identical across the
 * two implementations.
 *
 * @NApiVersion 2.1
 */
define([], function () {
  return {
    // --- Scope --------------------------------------------------------------
    // Accounting book to review (transactionaccountingline holds one row per book). 1 = Primary.
    ACCOUNTING_BOOK: 1,
    // How many recent monthly periods to sweep for manual journals (usually just the open period).
    REVIEW_MONTHS: 1,

    // --- Rule thresholds (policy, not code — mirror je_rules.RuleContext) ---
    APPROVAL_THRESHOLD: 50000,   // entries at/above need scrutiny (over_threshold)
    ROUND_MIN: 10000,            // ignore small round numbers (round_thousand floor)
    GAP_DAYS: 30,                // stale entry: entry-date vs posting gap (entry_post_gap)
    BUSINESS_START: 7,           // 07:00 local — before this is "after hours" (off_hours)
    BUSINESS_END: 19,            // 19:00 local — at/after this is "after hours"
    DUP_WINDOW_DAYS: 7,          // near-duplicate look-back/ahead window
    SHORT_DESC_LEN: 15,          // memos shorter than this are uninformative (weak_description)

    // NetSuite account-type codes treated as subledger/system-owned: a MANUAL journal to one of
    // these is the classic red flag. Mapped from raw accttype via je_rules.normalizeAcctType, so the
    // categories here are the normalised ones.
    SENSITIVE_TYPES: { control: 1, bank: 1, equity: 1 },

    // Run the approver-based rule (sod_breach). Set FALSE for accounts with no JE approval workflow:
    // there the "no independent approver" branch has no signal and would flag every entry (see README
    // "Known limits"). TRUE (default) is correct wherever journals are actually approved in-platform.
    ENABLE_APPROVER_RULES: true,

    // --- Field wiring (account-specific — see README "Known limits") --------
    // Column supplying the approver identity. Out of the box NetSuite has no single "who approved"
    // column, so this defaults to the routed next-approver; point it at your approval custom field
    // (e.g. 'custbody_je_approver') if you capture the actual approver. Blank approver -> the SoD rule
    // flags "no independent approver" (medium), which is itself a legitimate finding.
    APPROVER_FIELD: 'nextapprover',
    // Checkbox body field that records whether support is attached. If you don't set one, leave blank
    // and HAS_SUPPORT_DEFAULT decides (documented in README) — the off-platform tests exercise the
    // rule directly regardless.
    HAS_SUPPORT_FIELD: '',
    HAS_SUPPORT_DEFAULT: true,   // when no field is wired, assume supported (avoids flagging everything)

    // --- Output -------------------------------------------------------------
    REVIEWER_EMAIL: 'finance@darbit.nl',      // the human in "AI drafts, code checks, human approves"
    AUTHOR_EMPLOYEE_ID: '',                    // email.send needs an EMPLOYEE author (see README)
    AUTHOR_EMAIL: 'author@example.com',
    REPORT_FOLDER_ID: -1,                      // File Cabinet folder id (-1 = resolve by name 'je_review')
    CURRENCY: 'EUR',                           // display only; figures come from the ledger
    REPORT_TITLE: 'Manual JE anomaly review (SuiteScript + N/llm)',

    // --- Embedded AI (N/llm, OCI Generative AI) -----------------------------
    // Two-agent maker-checker. The reviewer is the cheap, high-volume step; the challenger reasons
    // about MISSED risk (harder), so it gets the larger family. Families: COHERE_COMMAND_R,
    // COHERE_COMMAND_R_PLUS, META_LLAMA. (In the Python build these are Haiku / Sonnet.)
    REVIEWER_MODEL: 'COHERE_COMMAND_R',
    CHALLENGER_MODEL: 'COHERE_COMMAND_R_PLUS'
  };
});
