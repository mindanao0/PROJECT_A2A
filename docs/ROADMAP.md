# Initial Roadmap

> ขอบเขต MVP ยืนยันแล้วใน [Confirmed Decisions](DECISIONS.md); implementation และเกณฑ์ผ่านด้านล่างยังเป็นข้อเสนอ รายละเอียดอยู่ใน [MVP Contract](MVP_CONTRACT.md)

## Phase 0 — Linux boundary feasibility (ไม่ใช้ quota)

Boundary probes: `probes/boundary.sh` (ผ่านแล้ว 2026-10-06)
สร้าง `fake-agent` ก่อน adapter จริง เพื่อให้ acceptance scenarios ทดสอบได้โดยไม่ใช้ quota (D-013)
Core language: Python (D-012)
Exit: sandbox, cgroup และ git isolation ใช้งานได้บนเครื่องจริง

## GUI foundation ที่มีแล้ว (ยังไม่ปิด Phase 1)

`python3 -m navis` เปิด local control GUI พร้อม in-process simulated agent, SQLite snapshot/events, task board, user requests และ lifecycle controls ดู [GUI Guide](GUI.md) สำหรับผลทดสอบและข้อจำกัด

ยังไม่มี sandboxed fake-agent CLI, production Runner, MCP หรือ provider adapter; ไม่ถือว่า execution/boundary/process-tree acceptance scenarios ผ่านจากผลทดสอบ UI simulation

## Phase 1 — Single-agent MVP foundations

สร้าง daemon, project/agent registry, adapter interface, durable task/attempt state, CLI และ UI เล็กบนเครื่องเดียว

ก่อนให้ coding agent เขียนไฟล์ ต้องมี:
- assigned workspace และ execution boundary สำหรับไฟล์/process/network/secrets
- worktree/resource ownership และ shared Git operation controls
- scoped policy/approvals; repo config ยกระดับสิทธิ์ไม่ได้
- bounded queues, loop/timeout/retry limits
- Stop/Kill และ cancellation propagation
- crash reconciliation, action IDs และ stale-result rejection
- immutable artifact refs, deterministic context baseline และ verifier evidence
- local client authorization boundary; remote listener ปิด
- scope claim, task dedup, slot และ cgroup limits (D-008)
- WAITING_QUOTA และ provider cooldown (D-009)

UI แสดงงาน สถานะ backend ผลลัพธ์/diff สิ่งที่รอผู้ใช้ และปุ่มควบคุม
Local helper สรุป context/วิเคราะห์ log เท่านั้น ไม่มี write/exec tools
Exit: single-agent, boundary, controls, recovery และ local UI acceptance cases ผ่านกับ `fake-agent` พร้อม evidence

## Phase 1b — Real backend probes (ใช้ quota)

หลัง Phase 1 ผ่านกับ fake แล้วจึงรัน probes ใน [Execution Design](EXECUTION_DESIGN.md) §10 กับ Codex, Claude Code และ local backend หนึ่งตัว
ทดสอบ start, task/result, streaming, interrupt, resume, crash/restart, approval/enforcement และ usage visibility
เก็บ compatibility matrix พร้อมเวอร์ชัน, test commands และ evidence; capability ที่ไม่ผ่านให้ unsupported/limited ไม่จำลองว่ารองรับ
Exit: adapter จริงผ่าน acceptance scenarios ชุดเดียวกับ fake

## Phase 2 — Two-agent collaboration and integration

เพิ่ม proposal/critique/delegate/review, task dependencies และ bounded conversation rounds
Codex implements -> Claude independently reviews -> verifier checks integration commit
สลับบทบาทได้ตาม capability ที่พิสูจน์แล้ว

เพิ่ม merge/integration queue, conflict handling และ rollback ของ managed workspace
Review/test ต้องผูก exact commit; rebase/merge แล้วต้องตรวจ final integration commit ใหม่
รายละเอียด local commit/merge authority ยังอยู่ใน OD-008; MVP ไม่ auto push/merge/deploy

Exit: สอง agent ไม่เขียน workspace/resource ชนกัน; late result และ stale evidence ไม่ถูกยอมรับ

## Phase 3 — Context and resource optimization

เพิ่ม Git-aware retrieval, conversation delta, versioned summaries, invalidation, bounded caches และ budgets
วัดเทียบ single-agent baseline: completion quality, retry/failure rate, elapsed time, context bytes และ provider usage เมื่อ expose
ไม่ถือว่า context fingerprint เท่ากับ provider cache hit
กำหนด retention/cleanup และ project scheduling fairness ตาม usage จริง

## Phase 4 — Optional local coding

สร้าง/ขยาย Agent Runner: tool loop, validation, permission enforcement, bounded turns, cancellation และ recovery
เปิด local coding หลังผ่าน tool/permissions/workspace acceptance tests และมีการอนุญาตบทบาทนั้น
ไม่บังคับให้ local helper เปลี่ยนเป็น coder เพื่อให้ MVP เสร็จ

## Phase 5 — Advanced orchestration and UI

เพิ่ม Team/Debate, dynamic scheduling, capability matching, adversarial review, multi-project scheduling และ A2A bridge เมื่อมี use case ที่พิสูจน์แล้ว
ค่อยขยาย UI/พิจารณา desktop wrapper; framework ยังไม่ล็อก

## Phase 6 — Remote control

เป็นงานในอนาคต ไม่อยู่ใน MVP
เพิ่ม authenticated clients, authorization, secure transport, revocation และ mobile-friendly UI
ทดสอบ remote boundary ก่อนเปิด listener; ไม่ expose provider/model/shell endpoint โดยตรง

## สิ่งที่ไม่อยู่ใน MVP

- takeover แชทเดิม/Project บนเว็บ หรือ browser scraping
- autonomous swarm จำนวนมาก
- memory/vector DB ขนาดใหญ่
- local coding ก่อน Agent Runner ผ่าน tests
- auto push/merge/deploy
- unrestricted execution เมื่อ adapter enforce policy ไม่ได้
- remote listener และ desktop UI หนัก
