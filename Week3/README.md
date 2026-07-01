# Week 3 — Manual JE anomaly reviewer

An AI **detective control** over a manual journal-entry register. Deterministic rules flag the
entries worth a controller's time; an AI **reviewer** writes the note on the ambiguous ones and an
AI **challenger** critiques it (maker-checker / four-eyes). No LLM computes a figure or decides a
disposition. Full write-up + build-vs-buy in the [repo README](../README.md#build-2--manual-je-anomaly-reviewer-detective-control--maker-checker).

## Runtime (public)
| File | Layer |
|------|-------|
| `je_rules.py` | 10 pure, unit-tested rules → `Assessment` (flags + risk score + tier) |
| `je_review.py` | reviewer + challenger subagents (`template`/`llm` modes) + the number-trace guard |
| `je_report.py` | deterministic reviewer-worklist assembler |
| `skills/je-reviewer/SKILL.md` | the reusable Agent Skill (→ `rules_reference.md` on demand) |

## Wire it up
```python
from je_rules import assess_register
from je_review import run_maker_checker
from je_report import build_worklist

assessments = assess_register(register, ctx)          # register: list[JournalEntry]
results = [run_maker_checker(a, mode="template") for a in assessments]  # or mode="llm"
print(build_worklist(results))
```

- `mode="template"` runs fully offline/deterministic (no API key) — powers the demo + tests.
- `mode="llm"` makes the real calls: **Haiku** reviewer (cheap, high-volume), **Sonnet** challenger
  (reasons about missed risk). Needs the `anthropic` SDK + `ANTHROPIC_API_KEY`.

## Run it live (scheduled Claude Routine)
Against a real ledger, the hybrid runs as a scheduled **Claude Routine**: Claude pulls the register
read-only via the NetSuite MCP connector (SuiteQL), runs these committed modules, writes the grey-zone
notes, and drafts the worklist email. The canonical, version-controlled instruction is
[je_routine_prompt.md](je_routine_prompt.md) (paste it into the Routine's message field — the flux
equivalent is [../Week1/flux_routine_prompt.md](../Week1/flux_routine_prompt.md)).

## Dev set (local, gitignored under `working/`)
- `synthetic_je.py` — a 50-row register with ~10 planted anomalies (each labelled with the rule it
  should trip; the rules never see the label).
- `run_je_demo.py` — end-to-end offline demo → prints the worklist + summary.
- `test_je_rules.py` (12) + `test_je_review.py` (9) — **21 plain-assert tests**. Headline: all 10
  planted anomalies caught, 0 false positives. Run from `working/`:
  ```
  python test_je_rules.py && python test_je_review.py
  python run_je_demo.py
  ```

## NetSuite-native sibling (SuiteScript + `N/llm`)

The same control built to run entirely inside NetSuite — deterministic rules + number-trace guard as
SuiteScript, reviewer/challenger notes from the embedded `N/llm` model, emailed + saved to the File
Cabinet. Same right-size split, same maker-checker seam, proven by 19 off-platform Jest tests. See
[suitescript-je-review/](suitescript-je-review/). An approaches comparison (hybrid vs full-AI vs
embedded `N/llm`, why NetSuite has no native detective control, when Full AI is actually better, and
SuiteQL-vs-saved-search) is in [je_approaches_comparison.md](je_approaches_comparison.md).

---

All data is synthetic. No real names, accounts, or figures.
