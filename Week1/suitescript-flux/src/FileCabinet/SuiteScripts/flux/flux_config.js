/**
 * flux_config.js  -  central configuration for the SuiteScript flux review.
 *
 * Edit these defaults, OR add matching Script Parameters on the deployment and they will override
 * (see README). Keeping it in one module means the orchestrator and helpers read one source of truth.
 *
 * @NApiVersion 2.1
 */
define([], function () {
  return {
    // Tolerance gate (mirrors the Python build): flag REVIEW when |variance| >= ABS and
    // (new-from-zero OR |pct| >= PCT).
    ABS_THRESHOLD: 25000,
    PCT_THRESHOLD: 0.10,

    // Accounting book to report on. transactionaccountingline holds one row per book, so pin it or a
    // multi-book account is summed across books and the variance is over-stated. 1 = Primary.
    ACCOUNTING_BOOK: 1,

    // Trailing months pulled for trend/recurrence + same-period-last-year.
    HISTORY_MONTHS: 12,

    // Cap drivers shown to the model per (account) - the material few, memos ride on these.
    TOP_DRIVERS: 8,

    // Who receives the report (the human in "AI drafts, code checks, human approves").
    REVIEWER_EMAIL: 'finance@darbit.nl',

    // Sender: NetSuite email.send requires an EMPLOYEE author. Easiest is to set the employee's
    // internal id directly here (find it on the employee record). If left blank, the script resolves
    // AUTHOR_EMAIL to an employee id at run time (and logs candidates if it can't).
    AUTHOR_EMPLOYEE_ID: '',
    AUTHOR_EMAIL: 'ilia.shabrov@ridedott.com',

    // Internal id of the File Cabinet folder to write the report into (-1 = SuiteScripts default; set
    // a real folder id for production). The run still succeeds if the file write fails.
    REPORT_FOLDER_ID: -1,

    // Embedded-AI model family (N/llm). One of: COHERE_COMMAND_R, COHERE_COMMAND_R_PLUS, META_LLAMA.
    // Default Cohere Command R is the N/llm default and the cheapest that meets the bar here.
    MODEL_FAMILY: 'COHERE_COMMAND_R',

    // Currency label for the report (display only; figures come from the ledger).
    CURRENCY: 'EUR',

    // Report heading.
    REPORT_TITLE: 'Flux review (SuiteScript + N/llm)'
  };
});
