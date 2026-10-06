# Initial Roadmap

> ขอบเขต MVP ยืนยันแล้วใน [Confirmed Decisions](DECISIONS.md); implementation และเกณฑ์ผ่านด้านล่างยังเป็นข้อเสนอ รายละเอียดอยู่ใน [MVP Contract](MVP_CONTRACT.md)

## Phase 0 — Linux adapter feasibility

พิสูจน์ Codex, Claude Code และ local backend หนึ่งตัวผ่าน CLI/session หรือ local endpoint
เริ่มจาก read-only probes; ไม่ต้องทำ UI ใหญ่หรือ coding agent สำหรับ local model

ทดสอบ start, task/result, streaming, interrupt, process-tree termination, resume, crash/restart, concurrent sessions, approval/enforcement และ usage visibility
เก็บ compatibility matrix พร้อมเวอร์ชัน, test commands และ evidence; capability ที่ไม่ผ่านให้ unsupported/limited ไม่จำลองว่ารองรับ

เลือก core language/transport/storage หลังได้ผล lifecycle ที่จำเป็น
Exit: รู้ interface และข้อจำกัดจริงของ backend ทั้งสามบทบาท

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

UI แสดงงาน สถานะ backend ผลลัพธ์/diff สิ่งที่รอผู้ใช้ และปุ่มควบคุม
Local helper สรุป context/วิเคราะห์ log เท่านั้น ไม่มี write/exec tools
Exit: single-agent, boundary, controls, recovery และ local UI acceptance cases ผ่านพร้อม evidence

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
