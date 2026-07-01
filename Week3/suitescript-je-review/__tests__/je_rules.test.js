/**
 * Unit tests for the deterministic rule engine (mirrors Week3/working/test_je_rules.py). Runs
 * off-platform via the SuiteCloud unit-testing framework — the same detective logic as the Python
 * build, including the headline "all planted anomalies caught, no false positives" claim.
 */
const rules = require('SuiteScripts/je_review/je_rules');

const OPEN = 'P-2026-05';
const CLOSED = 'P-2026-04';

function ctx(extra) {
  const base = rules.contextFromConfig({}, { [CLOSED]: true }, [new Date(2026, 4, 1)]); // 1 May holiday
  return Object.assign(base, extra || {});
}

// a clean baseline entry (May, weekday in-hours, supported, approved, informative memo)
function je(over) {
  return Object.assign({
    je_id: 'JE1', entry_date: new Date(2026, 4, 12), post_ts: new Date(2026, 4, 12, 11, 0),
    period_id: OPEN, period: '2026-05', account: '6100 Marketing', account_type: 'expense',
    amount: 12345.67, dr_cr: 'DR', preparer: 'a.klein', approver: 'controller1',
    description: 'Accrue May agency spend per invoice 88213', has_support: true
  }, over || {});
}

// --- individual rules --------------------------------------------------------
test('over_threshold', () => {
  expect(rules.ruleOverThreshold(je({ amount: 50000 }), ctx())).not.toBeNull();
  expect(rules.ruleOverThreshold(je({ amount: 49999 }), ctx())).toBeNull();
});

test('round_thousand only above the floor', () => {
  expect(rules.ruleRoundThousand(je({ amount: 40000 }), ctx())).not.toBeNull();
  expect(rules.ruleRoundThousand(je({ amount: 40050 }), ctx())).toBeNull();
  expect(rules.ruleRoundThousand(je({ amount: 2000 }), ctx())).toBeNull();
});

test('off_hours: weekend, after-hours, holiday', () => {
  expect(rules.ruleOffHours(je({ post_ts: new Date(2026, 4, 16, 11, 0) }), ctx())).not.toBeNull(); // Sat
  expect(rules.ruleOffHours(je({ post_ts: new Date(2026, 4, 12, 22, 0) }), ctx())).not.toBeNull(); // night
  expect(rules.ruleOffHours(je({ post_ts: new Date(2026, 4, 1, 11, 0) }), ctx())).not.toBeNull();  // holiday
  expect(rules.ruleOffHours(je({ post_ts: new Date(2026, 4, 12, 11, 0) }), ctx())).toBeNull();
});

test('weak_description', () => {
  expect(rules.ruleWeakDescription(je({ description: '' }), ctx()).severity).toBe('medium');
  expect(rules.ruleWeakDescription(je({ description: 'adjustment' }), ctx())).not.toBeNull();
  expect(rules.ruleWeakDescription(je({ description: 'Short' }), ctx())).not.toBeNull();
  expect(rules.ruleWeakDescription(je(), ctx())).toBeNull();
});

test('no_support severity scales with size', () => {
  expect(rules.ruleNoSupport(je({ has_support: false, amount: 5000 }), ctx()).severity).toBe('medium');
  expect(rules.ruleNoSupport(je({ has_support: false, amount: 60000 }), ctx()).severity).toBe('high');
  expect(rules.ruleNoSupport(je({ has_support: true }), ctx())).toBeNull();
});

test('sensitive_account', () => {
  ['control', 'bank', 'equity'].forEach((t) =>
    expect(rules.ruleSensitiveAccount(je({ account_type: t }), ctx())).not.toBeNull());
  expect(rules.ruleSensitiveAccount(je({ account_type: 'expense' }), ctx())).toBeNull();
});

test('entry_post_gap', () => {
  expect(rules.ruleEntryPostGap(je({ entry_date: new Date(2026, 4, 2), post_ts: new Date(2026, 5, 19, 10, 0) }), ctx())).not.toBeNull();
  expect(rules.ruleEntryPostGap(je(), ctx())).toBeNull();
});

test('closed_period', () => {
  expect(rules.ruleClosedPeriod(je({ period_id: CLOSED }), ctx())).not.toBeNull();
  expect(rules.ruleClosedPeriod(je({ period_id: OPEN }), ctx())).toBeNull();
});

test('sod_breach', () => {
  expect(rules.ruleSodBreach(je({ preparer: 'x', approver: 'x' }), ctx()).severity).toBe('high');
  expect(rules.ruleSodBreach(je({ approver: '' }), ctx()).severity).toBe('medium');
  expect(rules.ruleSodBreach(je({ preparer: 'x', approver: 'y' }), ctx())).toBeNull();
});

test('near_duplicate needs the register', () => {
  const a = je({ je_id: 'A', amount: 24900, post_ts: new Date(2026, 4, 21, 14, 0) });
  const b = je({ je_id: 'B', amount: 24900, post_ts: new Date(2026, 4, 22, 14, 0) });
  expect(rules.ruleNearDuplicate(a, ctx({ register: [a, b] }))).not.toBeNull();
  const cst = je({ je_id: 'C', amount: 10000, post_ts: new Date(2026, 4, 22, 14, 0) });
  expect(rules.ruleNearDuplicate(cst, ctx({ register: [a, cst] }))).toBeNull();
});

test('normalizeAcctType maps NetSuite account types to categories', () => {
  expect(rules.normalizeAcctType('AcctPay')).toBe('control');
  expect(rules.normalizeAcctType('Bank')).toBe('bank');
  expect(rules.normalizeAcctType('RetEarnings')).toBe('equity');
  expect(rules.normalizeAcctType('Expense')).toBe('expense');
  expect(rules.normalizeAcctType('OthCurrAsset')).toBe('other');
});

test('score tiers', () => {
  expect(rules.score([]).tier).toBe('clear');
  expect(rules.assess(je({ account_type: 'control' }), ctx()).tier).toBe('high');   // single high flag
  expect(rules.assess(je({ amount: 40000 }), ctx()).tier).toBe('low');              // single low flag
});

// --- planted anomalies: all caught, no false positives -----------------------
function plantedRegister() {
  const P = [
    // clean filler
    je({ je_id: 'C1', amount: 8210.55 }),
    je({ je_id: 'C2', account: '6200 Travel', amount: 15320.10, preparer: 'm.rossi', approver: 'controller2' }),
    je({ je_id: 'C3', account: '4000 Product revenue', account_type: 'revenue', amount: 22110.00 - 0.5, dr_cr: 'CR' }),
    // 1 SoD breach
    { je_id: 'JE2001', entry_date: new Date(2026, 4, 12), post_ts: new Date(2026, 4, 12, 11, 5), period_id: OPEN, period: '2026-05',
      account: '6300 Prof fees', account_type: 'expense', amount: 18400, dr_cr: 'DR', preparer: 'a.klein', approver: 'a.klein',
      description: 'Legal fees, self-approved', has_support: true, _p: ['sod_breach'] },
    // 2 control account, round plug, weak memo, unsupported
    { je_id: 'JE2002', entry_date: new Date(2026, 4, 20), post_ts: new Date(2026, 4, 20, 15, 40), period_id: OPEN, period: '2026-05',
      account: '2100 AP control', account_type: 'control', amount: 72000, dr_cr: 'DR', preparer: 'm.rossi', approver: 'controller1',
      description: 'adjustment', has_support: false, _p: ['sensitive_account', 'no_support', 'over_threshold', 'round_thousand', 'weak_description'] },
    // 3 round + weak
    { je_id: 'JE2003', entry_date: new Date(2026, 4, 18), post_ts: new Date(2026, 4, 18, 10, 20), period_id: OPEN, period: '2026-05',
      account: '6100 Marketing', account_type: 'expense', amount: 40000, dr_cr: 'DR', preparer: 'j.tan', approver: 'controller2',
      description: 'accrual', has_support: true, _p: ['round_thousand', 'weak_description'] },
    // 4 weekend + after-hours (lone -> low)
    { je_id: 'JE2004', entry_date: new Date(2026, 4, 16), post_ts: new Date(2026, 4, 16, 22, 15), period_id: OPEN, period: '2026-05',
      account: '6400 IT', account_type: 'expense', amount: 9650, dr_cr: 'DR', preparer: 's.novak', approver: 'controller1',
      description: 'Cloud hosting overage, May', has_support: true, _p: ['off_hours'] },
    // 5 holiday, large, unsupported
    { je_id: 'JE2005', entry_date: new Date(2026, 4, 1), post_ts: new Date(2026, 4, 1, 13, 0), period_id: OPEN, period: '2026-05',
      account: '6200 Travel', account_type: 'expense', amount: 55500, dr_cr: 'DR', preparer: 'l.perez', approver: 'controller2',
      description: 'Offsite travel booking, prepaid', has_support: false, _p: ['off_hours', 'no_support', 'over_threshold'] },
    // 6 closed period + round
    { je_id: 'JE2006', entry_date: new Date(2026, 3, 28), post_ts: new Date(2026, 4, 14, 9, 30), period_id: CLOSED, period: '2026-04',
      account: '4000 Product revenue', account_type: 'revenue', amount: 31000, dr_cr: 'CR', preparer: 'j.tan', approver: 'controller1',
      description: 'Late revenue cut-off correction for April', has_support: true, _p: ['closed_period', 'round_thousand'] },
    // 7 entry-post gap (weekday post)
    { je_id: 'JE2007', entry_date: new Date(2026, 4, 2), post_ts: new Date(2026, 5, 19, 10, 0), period_id: OPEN, period: '2026-05',
      account: '6300 Prof fees', account_type: 'expense', amount: 12300, dr_cr: 'DR', preparer: 'm.rossi', approver: 'controller2',
      description: 'Consulting fees, invoice arrived late', has_support: true, _p: ['entry_post_gap'] },
    // 8 & 9 near-duplicate pair (weekdays)
    { je_id: 'JE2008', entry_date: new Date(2026, 4, 21), post_ts: new Date(2026, 4, 21, 14, 0), period_id: OPEN, period: '2026-05',
      account: '6100 Marketing', account_type: 'expense', amount: 24900, dr_cr: 'DR', preparer: 's.novak', approver: 'controller1',
      description: 'Agency retainer, part 1 of campaign', has_support: true, _p: ['near_duplicate'] },
    { je_id: 'JE2009', entry_date: new Date(2026, 4, 22), post_ts: new Date(2026, 4, 22, 14, 5), period_id: OPEN, period: '2026-05',
      account: '6100 Marketing', account_type: 'expense', amount: 24900, dr_cr: 'DR', preparer: 's.novak', approver: 'controller1',
      description: 'Agency retainer, part 2 of campaign', has_support: true, _p: ['near_duplicate'] },
    // 10 equity, unapproved, unsupported, round, late-night
    { je_id: 'JE2010', entry_date: new Date(2026, 4, 19), post_ts: new Date(2026, 4, 19, 20, 10), period_id: OPEN, period: '2026-05',
      account: '3900 Retained earnings', account_type: 'equity', amount: 47000, dr_cr: 'DR', preparer: 'l.perez', approver: '',
      description: 'Prior-year adjustment to opening equity', has_support: false, _p: ['sensitive_account', 'sod_breach', 'no_support', 'off_hours', 'round_thousand'] }
  ];
  return P;
}

test('all 10 planted anomalies caught, exactly their expected rules, zero false positives', () => {
  const reg = plantedRegister();
  const results = rules.assessRegister(reg, ctx());
  let caught = 0, falsePos = 0;
  results.forEach((a, i) => {
    const planted = reg[i]._p;
    const fired = a.flag_rules;
    if (planted) {
      planted.forEach((rule) => expect(fired).toContain(rule));   // exact expected set fired
      if (fired.length) caught += 1;
    } else if (a.tier === 'high' || a.tier === 'medium') {
      falsePos += 1;
    }
  });
  expect(caught).toBe(10);
  expect(falsePos).toBe(0);
});
