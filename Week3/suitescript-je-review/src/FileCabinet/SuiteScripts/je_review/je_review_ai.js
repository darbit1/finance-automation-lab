/**
 * je_review_ai.js  -  THE MAKER-CHECKER AI LAYER (embedded N/llm; ported from Week3/je_review.py).
 *
 * Two agents, both prose-only:
 *   review(assessment)          -> reviewer note + residual-risk call on the grey-zone cases.
 *   challenge(assessment, note) -> a second, sceptical pass: false positive, or MISSED risk?
 *
 * The model sees ONLY the deterministic assessment (facts + fired flags). It never recomputes a
 * figure; je_guard then verifies the note, and code (je_scheduled) has the last word on disposition.
 * The reviewer uses the cheaper family; the challenger uses the larger one because reasoning about
 * what is ABSENT (missed risk) is the harder task. Weaker OCI models sometimes ignore "return JSON";
 * parseVerdict degrades gracefully so the control never depends on the model formatting correctly.
 *
 * @NApiVersion 2.1
 */
define(['N/llm'], function (llm) {

  function money(v) { return (Math.round(Number(v) || 0)).toLocaleString('en-US'); }

  /** The exact, minimal fact block handed to the model (and nothing else). */
  function factBlock(a) {
    var je = a.je;
    var lines = [
      'Journal ' + je.je_id + ' | account ' + je.account + ' (' + je.account_type + ')',
      'Amount ' + money(je.amount) + ' ' + (je.dr_cr || '') + ' | period ' + (je.period || je.period_id),
      'Prepared by ' + (je.preparer || 'n/a') + ' | approver ' + (je.approver || '(none)'),
      'Description: ' + (je.description ? '"' + je.description + '"' : '(none)'),
      'Supporting document attached: ' + (je.has_support ? 'yes' : 'no'),
      'Deterministic risk score ' + a.risk_score + ' (' + a.tier + ')',
      'Flags that fired:'
    ];
    (a.flags || []).forEach(function (f) {
      lines.push('  - ' + f.rule + ' [' + f.severity + ']: ' + f.detail);
    });
    return lines.join('\n');
  }

  function reviewerPrompt(a) {
    return [
      'You are a financial controller reviewing ONE flagged manual journal entry. You are given the',
      "entry's facts and the deterministic control flags that fired. Judge the RESIDUAL risk and write",
      'a short reviewer note (max 3 sentences). Rules: use ONLY the figures shown; introduce no new',
      'number; name no control that is not in the flags; if the flags do not justify concern, say so.',
      'Return STRICT JSON on one line: {"residual_risk":"escalate|monitor|accept","note":"...",',
      '"recommended_action":"..."}. No prose outside the JSON.',
      '',
      'ENTRY:',
      factBlock(a)
    ].join('\n');
  }

  function challengerPrompt(a, note) {
    return [
      'You are a SECOND, independent controller performing four-eyes review over a colleague\'s note on',
      'a flagged manual journal entry. Given the facts, the flags, and the first note, decide whether',
      'you (a) agree, (b) they over-flagged a false positive, or (c) they MISSED a real risk. Be',
      'sceptical of any accept/monitor call when a high-severity flag is present. Use only the figures',
      'shown. Return STRICT JSON on one line: {"verdict":"agree|false_positive|missed_risk",',
      '"rationale":"..."}. No prose outside the JSON.',
      '',
      'ENTRY:',
      factBlock(a),
      '',
      'FIRST REVIEWER NOTE:',
      '  residual_risk: ' + note.residual_risk,
      '  note: ' + note.note
    ].join('\n');
  }

  /** Call the embedded LLM. Throws on quota/feature errors; the caller withholds/degrades on failure. */
  function generate(prompt, modelFamilyName, maxTokens) {
    var family = (llm.ModelFamily && llm.ModelFamily[modelFamilyName]) ||
      (llm.ModelFamily && llm.ModelFamily.COHERE_COMMAND_R);
    var resp = llm.generateText({
      prompt: prompt,
      modelFamily: family,
      modelParameters: { maxTokens: maxTokens || 320, temperature: 0.2, topK: 0, topP: 0.75,
                         frequencyPenalty: 0, presencePenalty: 0 }
    });
    return (resp && resp.text ? resp.text : '').trim();
  }

  /** Pull the first {...} JSON object out of a model response; null if none/malformed. */
  function parseJson(text) {
    if (!text) return null;
    var s = text.indexOf('{'), e = text.lastIndexOf('}');
    if (s === -1 || e === -1 || e <= s) return null;
    try { return JSON.parse(text.substring(s, e + 1)); } catch (x) { return null; }
  }

  var VALID_RISK = { escalate: 1, monitor: 1, accept: 1 };
  var VALID_VERDICT = { agree: 1, false_positive: 1, missed_risk: 1 };

  /** Reviewer subagent. Degrades to a tier-derived risk + raw text if the model won't return JSON. */
  function review(a, modelFamilyName) {
    var raw = generate(reviewerPrompt(a), modelFamilyName, 320);
    var j = parseJson(raw) || {};
    var risk = VALID_RISK[j.residual_risk] ? j.residual_risk : riskFromTier(a.tier);
    var note = (j.note && String(j.note).trim()) || raw || ('Risk score ' + a.risk_score + ' (' + a.tier + ').');
    return {
      je_id: a.je.je_id, residual_risk: risk, note: note,
      recommended_action: (j.recommended_action || '').toString(),
      model: modelFamilyName
    };
  }

  /** Challenger subagent. Degrades to a deterministic four-eyes check if the model won't return JSON. */
  function challenge(a, note, modelFamilyName) {
    var raw = generate(challengerPrompt(a, note), modelFamilyName, 260);
    var j = parseJson(raw);
    if (j && VALID_VERDICT[j.verdict]) {
      return { je_id: a.je.je_id, verdict: j.verdict, rationale: (j.rationale || '').toString(), model: modelFamilyName };
    }
    return deterministicChallenge(a, note, modelFamilyName + ' (fallback)');
  }

  function riskFromTier(tier) { return tier === 'high' ? 'escalate' : (tier === 'medium' ? 'monitor' : 'accept'); }

  /** The same four-eyes logic as the Python template challenger — used as a safety net. */
  function deterministicChallenge(a, note, model) {
    var hasHigh = (a.flags || []).some(function (f) { return f.severity === 'high'; });
    if (hasHigh && note.residual_risk !== 'escalate') {
      var highRules = a.flags.filter(function (f) { return f.severity === 'high'; }).map(function (f) { return f.rule; });
      return { je_id: a.je.je_id, verdict: 'missed_risk',
        rationale: "Reviewer chose '" + note.residual_risk + "', but high-severity flag(s) " +
          JSON.stringify(highRules) + ' require escalation.', model: model };
    }
    if (note.residual_risk === 'escalate' && a.flags.length === 1 && a.flags[0].severity === 'low') {
      return { je_id: a.je.je_id, verdict: 'false_positive',
        rationale: 'Single low-severity flag (' + a.flags[0].rule + ') does not warrant escalation in isolation.',
        model: model };
    }
    return { je_id: a.je.je_id, verdict: 'agree', rationale: 'Concur with the reviewer.', model: model };
  }

  return {
    factBlock: factBlock, reviewerPrompt: reviewerPrompt, challengerPrompt: challengerPrompt,
    generate: generate, parseJson: parseJson, review: review, challenge: challenge,
    riskFromTier: riskFromTier, deterministicChallenge: deterministicChallenge
  };
});
