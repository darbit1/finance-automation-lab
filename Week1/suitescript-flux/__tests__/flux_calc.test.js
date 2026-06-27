/**
 * Unit tests for the deterministic calc (gate, variance, vendor bridge, trend). Mirrors the Python
 * build's test_ns_flux_pipeline.py. Run: npm test  (needs @oracle/suitecloud-unit-testing + jest).
 */
const calc = require('SuiteScripts/flux/flux_calc');

describe('tolerance gate', () => {
  test('is_review flags material / new-from-zero, not immaterial', () => {
    expect(calc.isReview(0, 30000, 25000, 0.1)).toBe(true);          // new, material abs
    expect(calc.isReview(0, 1000, 25000, 0.1)).toBe(false);          // new but below the floor
    expect(calc.isReview(100000, 140000, 25000, 0.1)).toBe(true);    // +40k / +40%
    expect(calc.isReview(1000000, 1030000, 25000, 0.1)).toBe(false); // +30k abs ok but +3% < 10%
  });

  test('flag_reviews parses, filters, enriches', () => {
    const rows = [
      { account_id: '867', current_amt: '10000000', prior_amt: '0' },
      { account_id: '797', current_amt: '7,539.70', prior_amt: '0' },
      { account_id: '583', current_amt: '-20004.03', prior_amt: '7547.75' }
    ];
    const out = calc.flagReviews(rows, 25000, 0.1);
    expect(out.reviews.map(r => r.account_id)).toEqual(['867', '583']);
    expect(out.ok_count).toBe(1);
    expect(out.reviews[0].direction).toBe('new');
    expect(out.reviews[0].current_amt).toBe(10000000);
  });
});

describe('variance metrics', () => {
  test('directions + no divide-by-zero', () => {
    expect(calc.varianceMetrics(0, 100).direction).toBe('new');
    expect(calc.varianceMetrics(100, 0).direction).toBe('cleared');
    expect(calc.varianceMetrics(100, 150).variance_pct).toBe(0.5);
    expect(calc.varianceMetrics(0, 100).variance_pct).toBeNull();
  });
});

describe('vendor bridge', () => {
  test('decomposes new vs decreased; net = variance', () => {
    const drivers = [
      { account_id: '241', subsidiary_id: '22', period_id: '294', entity: 'Vendor A', tranid: 'B0', amount: '100000' },
      { account_id: '241', subsidiary_id: '22', period_id: '295', entity: 'Vendor A', tranid: 'B1', amount: '50000' },
      { account_id: '241', subsidiary_id: '22', period_id: '295', entity: 'Vendor B', tranid: 'B2', amount: '75000' }
    ];
    const b = calc.vendorBridge(drivers, 241, 295, 294, 22);
    const by = {}; b.forEach(x => by[x.entity] = x);
    expect(by['Vendor B'].status).toBe('new');
    expect(by['Vendor B'].delta).toBe(75000);
    expect(by['Vendor A'].status).toBe('decreased');
    expect(by['Vendor A'].delta).toBe(-50000);
    expect(b[0].entity).toBe('Vendor B');                                   // sorted by |delta|
    expect(b.reduce((s, x) => s + x.delta, 0)).toBe(25000);
  });

  test('journals without an entity are bucketed by tranid', () => {
    const b = calc.vendorBridge(
      [{ account_id: '535', subsidiary_id: '20', period_id: '294', entity: null, tranid: 'JE164571', amount: '-28027' }],
      535, 295, 294, 20);
    expect(b[0].entity).toBe('(journal JE164571)');
    expect(b[0].status).toBe('dropped');
  });
});

describe('trend facts', () => {
  const hist = [
    { account_id: '867', subsidiary_id: '3', period_id: '289', amount: '20000' },
    { account_id: '867', subsidiary_id: '3', period_id: '290', amount: '21000' },
    { account_id: '867', subsidiary_id: '3', period_id: '291', amount: '22000' },
    { account_id: '867', subsidiary_id: '3', period_id: '280', amount: '18000' } // SPLY
  ];
  test('recurrence + SPLY', () => {
    const t = calc.trendFacts(hist, 867, [289, 290, 291], 3, 280);
    expect(t.periods_present).toBe(3);
    expect(t.consecutive_months).toBe(3);
    expect(t.is_recurring).toBe(true);
    expect(t.trailing_avg).toBe(21000);
    expect(t.sply_amount).toBe(18000);
  });
});

describe('sensitivity', () => {
  test('flag robustness at the downside', () => {
    const s = calc.sensitivity({ prior_amt: 0, current_amt: 100000 }, 0.05, 25000, 0.1);
    expect(s.variance_down).toBe(95000);
    expect(s.flag_holds_down).toBe(true);
    expect(calc.sensitivity({ prior_amt: 0, current_amt: 26000 }, 0.05, 25000, 0.1).flag_holds_down).toBe(false);
  });
});
