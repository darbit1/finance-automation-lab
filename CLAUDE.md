# finance-automation-lab — working agreement for Claude Code

## Purpose
A public portfolio of AI-powered finance automations, built in public. Each folder = one build.

## Golden rules
- RIGHT-SIZE THE AI: deterministic code for calculation, exact matching, anything auditable.
  Use the LLM only to (a) turn messy input into structure and (b) explain results in words.
- ALL DATA IS SYNTHETIC. No real company names, account numbers, GL codes, or field IDs anywhere.
- Reproducibility first: deterministic steps must be unit-tested and produce identical output on identical input.

## Stack
Python 3.11 + pandas for calc/matching; pytest for tests. Node/JS where a build needs it.
NetSuite access via the official AI Connector (MCP). n8n for orchestration builds.

## Conventions
- Each build: a calc/deterministic layer, an AI layer, and a tests/ folder, kept separate.
- Functions small and pure where possible. Type hints. Docstrings explaining the finance logic.
- Every AI call documents: which model, why that model (cost/quality), and the prompt.

## When generating code
Prefer clarity over cleverness. Explain finance assumptions in comments. Suggest the cheapest
model that meets the quality bar. Flag anywhere an LLM is doing work that code should do.
