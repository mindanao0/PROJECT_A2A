# Architecture Draft

> Discussion baseline. ขอบเขต MVP ยืนยันแล้วใน [Confirmed Decisions](DECISIONS.md); รายละเอียด execution/lifecycle/acceptance ที่เสนอต่ออยู่ใน [MVP Contract](MVP_CONTRACT.md) ยังไม่ใช่ final implementation plan หรือผลทดสอบ

MVP: Linux, Runtime-managed CLI/session, coding ภายใน assigned workspace, local helper สำหรับ context/log และ local UI พร้อม authentication boundary สำหรับ remote ในอนาคต

## 1. Problem statement

ต้องการระบบที่ทำให้ AI หลายตัว เช่น Codex/ChatGPT, Claude Code และ Local LLM ทำงานร่วมกันใน project เดียวหรือหลาย project ได้ โดยสามารถ:

- พูดคุย/เสนอ/โต้แย้งกัน
- แบ่งงานและ delegate กัน
- ทำงานพร้อมกันโดยไม่เขียนไฟล์ชนกัน
- review กันแบบอิสระ
- ใช้ terminal, Git, files และ tools
- ทำงานต่อหลัง process crash/restart
- ควบคุมผ่าน UI
- ลดการอ่าน context ซ้ำ

ระบบไม่ควรพึ่ง HANDOFF.md หรือ transcript เต็มเป็น communication bus หลัก

## 2. Core architecture

```text
                         UI / CLI
                            |
                    +-------v-------+
                    |  Team Runtime |
                    +---------------+
                    | Supervisor    |
                    | Scheduler     |
                    | Task Engine   |
                    | Agent Registry|
                    | Context Broker|
                    | Artifact Bus  |
                    | Policy Engine |
                    | Event Store   |
                    | Verifier      |
                    | Merge Manager |
                    +-------+-------+
                            |
                    Agent Message Bus
              +-------------+-------------+
              |             |             |
              v             v             v
          CodexAdapter  ClaudeAdapter  LocalAdapter
              |             |             |
          Codex CLI     Claude Code   Local Runtime
              |             |             |
           worktree A    worktree B    worktree C
              +-------------+-------------+
                            |
                         Git Repo
```

## 3. Agent adapter contract

Adapter ต้อง normalize ความต่างของ agent backend แต่ห้ามซ่อนข้อจำกัด: capability แต่ละข้อมี supported/limited/unsupported/unknown พร้อม evidence และ backend version

แยก send task, mid-turn input, interrupt turn, terminate process tree และ resume session ออกจากกัน; ไม่รับประกันว่า send() แทรกข้อความกลางงานได้ทุก backend ส่วน local inference backend แยกจาก Agent Runner

```text
start()
send()
stream()
cancel()
resume()
capabilities()
usage()
health()
shutdown()
```

อาจเพิ่ม:

```text
supports_session_resume
supports_structured_output
supports_tool_calls
supports_mcp
supports_noninteractive
supports_streaming
supports_images
context_window
cost_class
local_or_remote
```

## 4. Agent communication model

ห้ามใช้ free-form chat อย่างเดียว

ช่องทางจริง: Runtime เป็น MCP server ต่อ attempt และ agent ส่งผลผ่าน tool (`report_result`, `ask_user`, `run_check`) — ดู [Execution Design](EXECUTION_DESIGN.md) §1; message types ด้านล่างเป็น event types ใน log

Message types เบื้องต้น:

```text
MESSAGE
QUESTION
PROPOSAL
CRITIQUE
DECISION
DELEGATE
TASK_RESULT
REVIEW_REQUEST
REVIEW_RESULT
ARTIFACT
STATUS
BLOCKED
APPROVAL_REQUEST
ERROR
```

ทุก event ควรมี metadata เช่น:

```json
{
  "id": "evt_x",
  "project_id": "p1",
  "task_id": "t42",
  "from": "agent.codex",
  "to": ["agent.claude"],
  "type": "REVIEW_REQUEST",
  "artifact_refs": ["git:commit:abc123"],
  "correlation_id": "thread_7"
}
```

## 5. Task state machine

```text
NEW
  -> QUEUED
  -> ASSIGNED
  -> RUNNING
  -> WAITING_INPUT
  -> REVIEW
  -> VERIFY
  -> COMPLETED

ทางแยก:
RUNNING -> BLOCKED
RUNNING -> FAILED
*       -> CANCELLED
FAILED  -> RETRY / REASSIGN
```

State machine นี้เป็นภาพรวม; เพิ่ม WAITING_APPROVAL และ CANCELLING พร้อม transition guards ตาม MVP Contract แยก task/attempt/session/action; agent ไม่เปลี่ยน durable state ด้วยข้อความเอง

Chat เป็นเพียง discussion layer แต่ Task Engine เป็นตัวกำหนดสถานะจริง

## 6. Agent Registry / capability discovery

แต่ละ agent ลงทะเบียน capability เช่น:

- coding
- architecture
- review
- debugging
- test generation
- long-context
- vision
- offline
- cheap-worker
- privacy-sensitive

Scheduler เลือก agent ตาม task ไม่ hard-code provider

## 7. Context Broker

เป้าหมาย: ไม่ส่ง repo หรือ transcript ทั้งหมดทุกครั้ง

Context Broker ทำ:

1. รับ task
2. หาไฟล์/commit/artifact ที่เกี่ยวข้อง
3. สร้าง compact context
4. ส่งเฉพาะ delta ใหม่ที่จำเป็น
5. cache context fingerprint
6. compact conversation เมื่อยาว

Local LLM สามารถเป็น worker สำหรับ retrieval/summarization โดยไม่ต้องมีสิทธิ์แก้ code

ควรแยก:
- Project facts
- Task-local context
- Conversation delta
- Decisions
- Artifacts
- Ephemeral tool output

## 8. Artifact Bus

ผลลัพธ์ใหญ่ควรส่ง reference ไม่ใช่คัดลอกเข้า chat

ตัวอย่าง:

```text
git:commit:abc123
git:diff:abc123..def456
file:src/retrieval/index.ts
test:run:892
log:artifact:71
benchmark:run:54
```

Reference ต้องผูก project และ immutable commit/content hash; file path อย่างเดียวเป็น locator ไม่ใช่ version identity

Agent ขอ content เมื่อต้องใช้จริง

## 9. Workspace isolation

ไม่แนะนำให้หลาย agent เขียน working tree เดียวกัน

Default: clone ต่อ attempt (`git clone --shared`) ใน state dir ของ Runtime ไม่ใช้ worktree เพราะ worktree แชร์ `.git/config` และ `.git/hooks` กับ checkout หลัก — ดู [Execution Design](EXECUTION_DESIGN.md) §4

```text
<state>/attempts/
  att-42-1/repo   # codex
  att-43-1/repo   # claude
```

Merge Manager จัดการ:
- ownership
- rebase
- conflict detection
- integration tests
- rollback

Clone ไม่ใช่ process sandbox; ports, databases, containers และ temp paths ต้องมีขอบเขต/ownership แยก การจำกัดสิทธิ์และ workspace/resource isolation ต้องมาก่อน multi-agent writes

File locks อาจมีได้ แต่เป็น optimization ไม่ใช่ isolation หลัก

## 10. Review modes

### Normal review
Reviewer เห็น task, implementation note, diff และ tests

### Blind review
Reviewer เห็น requirement + diff + tests แต่ไม่เห็น reasoning ของ implementer เพื่อลด anchoring/groupthink

### Adversarial review
ตั้ง reviewer ให้พยายามหา failure mode โดยเฉพาะ

## 11. Verification

Consensus ไม่ใช่ proof

Verifier ใช้หลักฐาน เช่น:
- unit/integration tests
- lint/typecheck
- build
- benchmark
- static analysis
- deterministic checks
- user-defined acceptance criteria

Task สำคัญห้าม COMPLETED ถ้า verifier ไม่ผ่าน policy ที่กำหนด

## 12. Supervisor safeguards

ต้องมี:
- max conversation rounds
- max delegation depth
- max concurrent agents
- task timeout
- retry limit
- duplicate work detection
- loop detection
- stale task detection
- cancellation propagation

ตัวอย่าง:
GPT -> Claude -> GPT -> Claude ไม่ควรวนไม่จำกัด

## 13. Permission / policy engine

ระดับตัวอย่าง:

```text
Observe
Develop
Commit
Network
Install
Privileged
HumanOnly
```

Action บางประเภทอาจ require approval:
- delete large file tree
- install package/system dependency
- network access
- modify secrets/config
- force push
- merge
- deploy
- production operation

Agent ไม่สามารถยกระดับสิทธิ์ตัวเองได้ Repo config/messages ยกระดับสิทธิ์ไม่ได้เช่นกัน

MVP ยืนยันเฉพาะอ่าน/แก้โค้ด/ทดสอบภายใน assigned workspace ต้องระบุ enforcement ของ provider sandbox/approval หรือ tool executor และครอบคลุม native subagents; ถ้าพิสูจน์ไม่ได้ให้ปฏิเสธโหมดนั้น ห้าม fallback เป็น unrestricted execution

## 14. Secrets isolation

อย่า inject environment ทั้งหมดให้ทุก process

Runtime ควรมี scoped secret broker:
- agent X เห็น secret เฉพาะ task X
- local model อาจถูก policy ห้ามเห็น cloud credentials
- logs ต้อง redact secrets
- artifact/event storage ห้ามเก็บ token ดิบ
- credential ของ agent CLI เองอยู่ใน agent home แยก แต่คำสั่งของ agent ยังอ่านได้ จึงต้อง scan แบบ exact match ก่อนข้อมูลออกจาก attempt — ดู [Execution Design](EXECUTION_DESIGN.md) §3

## 15. Event Store and recovery

เก็บ event แบบ append-only เพื่อ:
- audit
- resume
- debug
- replay state machine
- crash recovery

แต่ Event Store ไม่ใช่ prompt history ที่ต้องส่งให้ model ทุกครั้ง

ควร snapshot state เป็นระยะเพื่อไม่ต้อง replay event จำนวนมากหลัง restart

Replay ใช้กู้ state ไม่ใช้รัน side effects ซ้ำ: บันทึก intent/ผลพร้อม action ID; crash ระหว่างสองขั้นให้ outcome_unknown และ reconcile ก่อน retry มี attempt lease และ stale-result rejection

## 16. Budget controller

แม้ใช้ subscription CLI ก็ยังมีข้อจำกัด usage/context/time

Budget อาจประกอบด้วย:
- max agent turns
- max debate rounds
- max wall-clock runtime
- provider usage counters ถ้าดึงได้
- local compute budget
- context size
- concurrency

งานง่ายควรเลือก single-agent path ก่อน

## 17. Escalation

เมื่อ:
- agents ขัดแย้งหลัง max rounds
- verifier กับ implementation ขัดกัน
- confidence ต่ำ
- permission สูง
- requirements กำกวม

ให้ escalate ไป UI แทนการเดา

## 18. Modes

### Solo
หนึ่ง agent ทำงาน

### Pair
Implementer + reviewer

### Team
หลาย agent แบ่งงาน

### Debate
หลาย agent เสนอ/critique ก่อนตัดสินใจ

### Dry Run
วิเคราะห์/วางแผนเท่านั้น ห้ามแก้ workspace

### Offline
ใช้เฉพาะ local agents/tools

## 19. UI requirements

MVP ใช้ UI บนเครื่องเดียวและทำ UI เล็กพร้อม runtime skeleton; framework ยังไม่ล็อก เตรียม client authorization boundary แต่ remote listener ปิด รายละเอียด controls และ reconnect อยู่ใน MVP Contract

UI ไม่ควรเป็น chat-only

อย่างน้อยต้องเห็น:
- projects
- agents / health
- current tasks
- dependency graph
- conversation/events
- tool activity
- artifacts
- diff
- verifier results
- approvals
- budgets
- worktree ownership

Controls:
- Pause
- Resume
- Stop
- Kill
- Take over
- Reassign
- Add instruction
- Approve/Reject
- Retry
- Rollback

## 20. Multi-project runtime

Daemon หนึ่งตัวดูแลหลาย project ได้ แต่ isolate:
- task namespace
- agent sessions
- event store
- worktrees
- permissions
- secrets
- context cache

## 21. Local LLM roles

MVP ที่ยืนยันแล้ว: Local LLM สรุป context และวิเคราะห์ log เท่านั้น ไม่มี write/exec tools Coding และบทบาทอื่นด้านล่างเป็น future candidates; coding ต้องมี Agent Runner ผ่าน tool/policy/cancellation/recovery/workspace tests และอนุญาตบทบาทนั้นก่อน

Local LLM ไม่ควรถูกจำกัดเป็น coder เท่านั้น

สามารถเป็น:
- Context selector
- Summarizer
- Log analyzer
- Cheap reviewer
- Test classifier
- Routing assistant
- Offline primary agent

## 22. A2A and MCP

แนวทางปัจจุบัน:
- ศึกษา A2A สำหรับ semantics ของ agent discovery/tasks/artifacts/inter-agent communication
- ใช้ MCP สำหรับ tool/data access เมื่อ backend รองรับ
- Runtime มี internal protocol ของตัวเองเพื่อควบคุม lifecycle ได้แน่นอน
- อย่าผูก core กับ protocol ภายนอกจนเปลี่ยนไม่ได้

Compatibility layer สามารถเพิ่มทีหลัง

## 23. Non-API cloud access

เป้าหมายคือไม่บังคับ API-key workflow ถ้าผู้ให้บริการมี official CLI/account login ที่ใช้งานได้

อย่างไรก็ตาม cloud agent ยังคงใช้ network/backend ของผู้ให้บริการ

ถ้าต้องการ no-network จริง ๆ ต้องใช้ Local Mode

## 24. จุดที่ต้องระวังเพิ่ม

- provider CLI output/schema เปลี่ยนได้
- account/subscription terms อาจจำกัด automation บางประเภท
- session resume ของแต่ละ provider ไม่เหมือนกัน
- structured output อาจไม่ deterministic
- agent อาจ report success ทั้งที่ command ล้มเหลว จึงต้องเชื่อ verifier/tool exit status
- prompt injection จาก repo/docs/tool output ต้องถือว่าเป็น untrusted input
- malicious dependency/tool output ต้องไม่สามารถยกระดับสิทธิ์
- agent identity ต้อง authenticated ภายใน runtime เพื่อกัน spoof event
- idempotency สำคัญกับ retry เพื่อไม่ให้ทำ action ซ้ำ
