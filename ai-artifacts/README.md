# AI Artifacts

**Mandatory for submission:** raw `.jsonl` session logs covering every phase — problem framing,
domain research, planning, coding, documentation, testing, and QA.

Place all session log files in this directory before submitting the zip/tarball.

Curated Markdown summaries or screenshots do **not** substitute for raw JSONL logs.

## Session logs

| File | Phase |
|---|---|
| `9fcbe927-0464-4599-9ab7-3a96bfb93101.jsonl` | Problem framing, domain research, scope, technical plan, domain model, decisions, test matrix |
| `73d1bb11-4380-429e-a649-b581f37de978.jsonl` | Implementation reconnaissance, requirement clarifications, skeleton, domain primitives, git push |
| `8e47651d-9929-4e4e-9a5b-58424b1071a7.jsonl` | LLM architecture docs, Gemini extraction slice, D30/D31, extraction tests |
| `414fe4c0-d180-4a12-8547-7db3bced942a.jsonl` | Adjudication e2e: pricing, accumulators, deductible, limits, lifecycle derivation, duplicate detection |
| `f1a6817f-7e80-4f39-a427-4f9fbf281fa9.jsonl` | Subagent of 414fe4c0: pricing-stage codebase reconnaissance |
| `14ae934f-f88d-48d8-870a-00171bee14a7.jsonl` | SQLite persistence, submit_claim use case, FastAPI boundary, demo-flow API tests |
| `50932c60-4666-4dbe-8d07-81b383f2da7f.jsonl` | Review, disputes, payments, and EOB: fact correction, appeals, exact payment, member-facing explanation |

These are copies of Cursor agent transcript logs from `.cursor/projects/.../agent-transcripts/`.
**Before each `git push`**, refresh them from that folder (see `.cursor/rules/implementation.mdc`).
Add a row here when new session files appear.
