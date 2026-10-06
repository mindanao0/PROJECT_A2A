# Initial Roadmap

> ยังเป็น roadmap สำหรับ discussion ไม่ใช่ commitment

## Phase 0 — Feasibility probes

อย่าเริ่มจาก UI ใหญ่

สร้าง prototype เล็กเพื่อพิสูจน์ 3 backend:
1. Codex
2. Claude Code
3. Local LLM

ทดสอบ:
- start process/session
- send task
- stream output
- cancel
- resume
- get structured result
- crash/restart
- concurrent sessions

ผลลัพธ์ของ Phase 0 ควรเป็น compatibility matrix

## Phase 1 — Runtime skeleton

สร้าง:
- daemon
- project registry
- agent registry
- adapter interface
- event store
- basic task engine
- CLI

Use case แรก:

```text
user -> runtime -> one selected agent -> result
```

## Phase 2 — Two-agent collaboration

เพิ่ม:
- proposal
- critique
- delegate
- review
- task dependencies
- loop limits

Use case:

```text
Codex implements
Claude blind-reviews
Verifier runs tests
```

## Phase 3 — Workspace isolation

เพิ่ม:
- Git worktree manager
- ownership
- artifact references
- integration/merge queue
- rollback

## Phase 4 — Context Broker

เพิ่ม:
- task-local context
- Git-aware retrieval
- conversation delta
- summaries
- local model helper
- context cache/fingerprints

วัด token/context reduction เทียบ baseline

## Phase 5 — Policy and safety

เพิ่ม:
- permissions
- approval gates
- secret isolation
- prompt-injection labels
- audit
- action idempotency

## Phase 6 — Control UI

ทำ Web UI ก่อน:

- project dashboard
- agent status
- task graph
- conversation/events
- terminal/tool activity
- artifacts/diff
- approvals
- pause/kill/reassign

หลัง core เสถียรค่อยพิจารณา desktop wrapper

## Phase 7 — Advanced orchestration

เพิ่ม:
- Debate Mode
- dynamic scheduling
- capability matching
- budget controller
- adversarial review
- multi-project scheduling
- A2A compatibility/bridge ถ้าพิสูจน์ว่ามีประโยชน์

## Phase 8 — Remote control

ถ้าต้องการ:
- authenticated remote UI
- mobile-friendly UI
- secure tunnel/network model

## สิ่งที่ไม่ควรทำใน MVP

- สร้าง autonomous swarm จำนวนมาก
- memory/vector DB ขนาดใหญ่ตั้งแต่แรก
- auto-merge production code
- browser scraping ChatGPT/Claude
- protocol abstraction หลายชั้นก่อนพิสูจน์ CLI adapters
- desktop UI หนักก่อน runtime ทำงานจริง
