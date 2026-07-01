/**
 * Unit tests for the audit seam (number-trace guard). Mirrors the guard tests in
 * Week3/working/test_je_review.py — the check the native N/llm path does not give you: an invented
 * figure in a reviewer note is rejected before the note can reach the worklist.
 */
const guard = require('SuiteScripts/je_review/je_guard');

// a minimal assessment: the guard only reads je.amount / je.account / je.je_id + risk_score + flags
function assessment(over) {
  return Object.assign({
    je: { je_id: 'JE2002', account: '2100 AP control', amount: 72000 },
    risk_score: 10, flags: [{ rule: 'no_support' }, { rule: 'sensitive_account' }]
  }, over || {});
}

test('a note citing only traceable figures passes', () => {
  const note = { note: 'JE2002 (2100 AP control, 72,000 DR): 2 flags. Risk score 10 (high). Escalate.' };
  const r = guard.guardNote(note, assessment());
  expect(r.ok).toBe(true);
  expect(r.offenders).toEqual([]);
});

test('an invented figure is rejected', () => {
  const note = { note: 'Escalate: fabricated exposure of 999,999 not in the facts.' };
  const r = guard.guardNote(note, assessment());
  expect(r.ok).toBe(false);
  expect(r.offenders.some((t) => t.indexOf('999,999') !== -1)).toBe(true);
});

test('the account code and JE id are identifiers, not invented figures', () => {
  const note = { note: 'Manual JE to control account 2100 AP control, entry JE2002.' };
  expect(guard.guardNote(note, assessment()).ok).toBe(true);
});

test('small ordinals and flag counts are not policed as money', () => {
  const note = { note: '5 flags fired; this is the 2nd control-account entry this month.' };
  expect(guard.guardNote(note, assessment()).ok).toBe(true);
});

test('a plain-string note (not an object) is accepted', () => {
  expect(guard.guardNote('Score 10, escalate for independent review.', assessment()).ok).toBe(true);
});

test('a different real amount is caught (guard is not just whitelisting any number)', () => {
  const note = { note: 'Amount 72,000 DR, plus an invented 4,500 kicker.' };
  const r = guard.guardNote(note, assessment());
  expect(r.ok).toBe(false);
  expect(r.offenders.some((t) => t.indexOf('4,500') !== -1)).toBe(true);
});
