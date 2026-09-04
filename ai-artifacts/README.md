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
| `a9641e18-417a-4ef8-9229-28ecb0c4dc3e.jsonl` | SQLite concurrency (BEGIN IMMEDIATE, closing invariant 409), `.env` setup, pre-submission fixes (README, demo flow 3, PHI-safe 422, tests) |
| `36e7bc1c-531a-4942-b930-8db0fe49d4a3.jsonl` | Live API walkthrough with a complex multi-line sample claim |
| `3e22d173-ba60-4124-b460-7d83eeacf9f8.jsonl` | Read-only audit: API routes vs technical plan and scope |
| `5b764b90-aad9-4204-bd91-b0665ae3b65c.jsonl` | Read-only audit: domain engine gate ordering and determinism |
| `3a8723f9-3f67-4ae1-9392-3941869a0c61.jsonl` | Read-only audit: SQLite schema append-only and persistence tests |

These are copies of Cursor agent transcript logs from `.cursor/projects/.../agent-transcripts/`.
**Before each `git push`**, refresh them from that folder (see `.cursor/rules/implementation.mdc`).
Add a row here when new session files appear.
