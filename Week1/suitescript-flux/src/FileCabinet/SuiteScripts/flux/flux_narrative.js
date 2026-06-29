/**
 * flux_narrative.js  -  the ONLY AI step: turn the flagged facts + drivers into one paragraph using
 * NetSuite's embedded LLM (N/llm.generateText, OCI Generative AI). The model writes prose only; it
 * never sees a query and never produces a figure that code did not already compute. flux_eval then
 * verifies the result before it can ship.
 *
 * @NApiVersion 2.1
 */
define(['N/llm'], function (llm) {

  function money(v, ccy) {
    var n = Math.round(Number(v) || 0);
    return ccy + ' ' + n.toLocaleString('en-US');
  }

  /**
   * Build the prompt + the list of references the narrative is allowed to cite (tranids + memos),
   * which flux_eval will strip before the number check.
   */
  function buildContext(row, drivers, bridge, trend, meta) {
    var ccy = meta.currency;
    var refs = [];
    var driverLines = (drivers || []).slice(0, 8).map(function (d) {
      if (d.tranid) refs.push(d.tranid);
      if (d.txn_memo) refs.push(d.txn_memo);
      if (d.line_memo) refs.push(d.line_memo);
      return '- ' + (d.entity || ('journal ' + (d.tranid || 'n/a'))) +
        ': ' + money(d.amount, ccy) + ' (' + (d.txn_type || 'txn') +
        (d.tranid ? ' ' + d.tranid : '') + (d.txn_memo ? ", memo '" + d.txn_memo + "'" : '') + ')';
    });
    var bridgeLines = (bridge || []).slice(0, 6).map(function (b) {
      return '- ' + b.entity + ': ' + b.status + ' ' + money(b.delta, ccy) +
        ' (prior ' + money(b.prior, ccy) + ' -> current ' + money(b.current, ccy) + ')';
    });

    var facts = [
      'Account: ' + row.account + (row.subsidiary ? ' [' + row.subsidiary + ']' : ''),
      'Prior period: ' + money(row.prior_amt, ccy) + '; current period: ' + money(row.current_amt, ccy),
      'Variance: ' + money(row.variance_abs, ccy) +
        (row.variance_pct == null ? ' (new from zero)' : ' (' + (row.variance_pct * 100).toFixed(1) + '%)') +
        '; direction: ' + row.direction
    ];
    if (trend) {
      facts.push('Trend: present in ' + trend.periods_present + ' of the trailing periods, ' +
        trend.consecutive_months + ' consecutive; ' + (trend.is_recurring ? 'recurring' : 'not recurring') +
        (trend.sply_amount != null ? '; same period last year ' + money(trend.sply_amount, ccy) : '') +
        (trend.trailing_avg ? '; trailing average ' + money(trend.trailing_avg, ccy) : '') + '.');
    }

    var prompt = [
      'You are a finance analyst writing ONE concise paragraph (max 4 sentences) explaining a flagged',
      'account movement for a monthly flux review. Use ONLY the facts below. Do not invent numbers,',
      'vendors, or causes. You may cite the exact journal id / bill name / memo shown. If several',
      'vendors moved, decompose the change ("new vendor B +X, vendor A down Y, net Z"). If the current',
      'period has no activity and the prior period held an accrual, explain it as recurring timing and',
      'say the next charge is expected at the next close - do NOT say the driver is undeterminable when',
      'a prior-period driver is shown. Only if NO driver appears in either period and there is no memo,',
      'write: "driver not determinable from current transactions - refer to prior-period journals".',
      'Refer to vendors by name. Do NOT write calendar dates, numeric reference codes, or percentages',
      'that are not in the facts, and do not restate the subsidiary name.',
      '',
      'FACTS:',
      facts.join('\n'),
      '',
      'DRIVERS (' + (driverLines.length) + '):',
      driverLines.length ? driverLines.join('\n') : '(none in either period)',
      '',
      'VENDOR BRIDGE:',
      bridgeLines.length ? bridgeLines.join('\n') : '(no vendor-level split)',
      '',
      'Write the paragraph now. Plain text, no headings, no bullet points.'
    ].join('\n');

    return { prompt: prompt, refs: refs };
  }

  /** Call the embedded LLM. Throws on quota/feature errors; the caller withholds the row on failure. */
  function generate(prompt, modelFamilyName) {
    var family = (llm.ModelFamily && llm.ModelFamily[modelFamilyName]) || (llm.ModelFamily && llm.ModelFamily.COHERE_COMMAND_R);
    var resp = llm.generateText({
      prompt: prompt,
      modelFamily: family,
      modelParameters: {
        maxTokens: 350, temperature: 0.2, topK: 0, topP: 0.75,
        frequencyPenalty: 0, presencePenalty: 0
      }
    });
    return (resp && resp.text ? resp.text : '').trim();
  }

  return { buildContext: buildContext, generate: generate };
});
