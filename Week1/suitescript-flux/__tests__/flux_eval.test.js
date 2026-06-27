/**
 * Unit tests for the audit seam (number-match + provenance + reference whitelisting). Mirrors the
 * Python build's test_ns_flux_eval.py. This is the check the native N/llm path does not give you.
 */
const ev = require('SuiteScripts/flux/flux_eval');

const FACT = { account: 'Legal consultancy', prior: 0, current: 379310, variance_abs: 379310, variance_pct: null };
const DRIVERS = [{ txn_type: 'VendBill', entity: 'Acme Legal Ltd', lines: 2, amount: 379310 }];

test('clean narrative passes', () => {
  const n = 'Legal consultancy is new at EUR 379,310, driven by 2 vendor bills from Acme Legal Ltd.';
  const r = ev.checkExplanation(n, FACT, DRIVERS);
  expect(r.ok).toBe(true);
  expect(r.bad_numbers).toEqual([]);
  expect(r.bad_entities).toEqual([]);
});

test('invented number rejected', () => {
  const n = 'New at EUR 379,310, including a EUR 999,999 one-off.';
  const r = ev.checkExplanation(n, FACT, DRIVERS);
  expect(r.ok).toBe(false);
  expect(r.bad_numbers.some(t => t.indexOf('999,999') !== -1)).toBe(true);
});

test('invented vendor rejected', () => {
  const n = 'New at EUR 379,310, driven by a bill from Globex GmbH.';
  const r = ev.checkExplanation(n, FACT, DRIVERS);
  expect(r.ok).toBe(false);
  expect(r.bad_entities.some(t => t.indexOf('Globex') !== -1)).toBe(true);
});

test('honest fallback passes (no new numbers/vendors)', () => {
  const n = 'Driver not determinable from current transactions; refer to prior-period journals.';
  expect(ev.checkExplanation(n, FACT, []).ok).toBe(true);
});

test('extra_facts ground trend figures; cited refs and memos pass', () => {
  const trend = { trailing_avg: 22000, sply_amount: 18000, vs_sply_pct: 0.44, consecutive_months: 3 };
  const n = 'Travel rose to EUR 379,310; 3rd consecutive month, up 44% on last year\'s EUR 18,000, ' +
            'trailing average EUR 22,000, posted via journal JE164589 (memo "2026 Q1 Current tax").';
  expect(ev.checkExplanation(n, FACT, DRIVERS).ok).toBe(false);                 // ungrounded
  const r = ev.checkExplanation(n, FACT, DRIVERS, {
    extra_facts: trend, allowed_refs: ['JE164589', '2026 Q1 Current tax']
  });
  expect(r.ok).toBe(true);
});

test('refs do not whitelist an unrelated invented figure', () => {
  const n = 'Posted via journal JE164589, plus an invented EUR 555,000.';
  const r = ev.checkExplanation(n, FACT, DRIVERS, { allowed_refs: ['JE164589'] });
  expect(r.ok).toBe(false);
  expect(r.bad_numbers.some(t => t.indexOf('555,000') !== -1)).toBe(true);
});
