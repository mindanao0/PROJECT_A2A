# Open Decisions

เอกสารนี้เก็บสิ่งที่ **ยังไม่ได้ตัดสินใจ** และสถานะคำตัดสินที่เกี่ยวข้อง รายการที่ยืนยันแล้วอ้าง [Confirmed Decisions](DECISIONS.md); ข้อเสนอ acceptance อยู่ใน [MVP Contract](MVP_CONTRACT.md)

Confirmed scope ไม่ได้ล็อก framework transport storage หรือ sandbox implementation

## OD-001 Core implementation language — RESOLVED

D-012: Python ≥ 3.11 ใช้ stdlib ก่อน

## OD-002 UI technology — PARTIALLY RESOLVED

D-005 ยืนยัน UI บนเครื่องเดียวก่อน เตรียม authentication boundary สำหรับ remote ส่วน technology ยังเปิดอยู่

ตัวเลือก:
- Browser UI only
- Tauri
- Electron
- Flutter desktop
- Web UI ก่อนแล้วค่อย desktop wrapper

## OD-003 Runtime transport

ระหว่าง UI ↔ daemon:
- WebSocket
- local HTTP + SSE
- Unix socket / named pipe + WebSocket bridge
- combination

## OD-004 Internal message persistence

ตัวเลือก:
- SQLite event store
- SQLite + append-only files
- embedded DB อื่น

## OD-005 Protocol compatibility

Internal protocol จะ:
- เป็น native schema แล้วทำ A2A bridge
- ใช้ A2A-compatible schema ตั้งแต่แรก
- รองรับ A2A เฉพาะ external agents ในภายหลัง

ยังไม่ควรตัดสินจน prototype lifecycle กับ Codex/Claude/Local ได้ก่อน

## OD-006 Agent backend integration

ต้องทดลองจริงว่า adapter แต่ละตัวควบคุมได้ระดับไหน:
- start
- noninteractive input
- streaming output
- cancel
- resume
- structured output
- approval/tool hooks
- usage visibility

## OD-007 Worktree strategy — PROPOSED

ข้อเสนอ: clone ต่อ attempt (`git clone --shared`) แทน worktree เพราะ worktree แชร์ `.git/config` และ `.git/hooks` กับ checkout หลัก; ผล probe อยู่ใน [Execution Design](EXECUTION_DESIGN.md) §4
ยังต้องวัด overhead กับ VELA จริง (checkout ประมาณ 482 MB ต่อ clone)

## OD-008 Who can merge — RESOLVED

D-014: ผู้ใช้เป็นผู้สั่ง; Runtime รวมงานบน integration branch ของ Navis (`refs/navis/integration/<project>`) แล้วรัน check ซ้ำบน commit สุดท้าย ผู้ใช้ fast-forward เข้า branch ของตัวเอง ไม่มี auto-merge
เหตุผล: เกณฑ์ Phase 2 (evidence ผูก exact commit, stale เมื่อ rebase) ทำได้ก็ต่อเมื่อ Runtime เป็นคนสร้าง integration commit; ปลายทางเป็น branch ของ Navis จึงไม่แตะ working tree ของผู้ใช้
เลื่อนไปก่อน: verifier + policy auto-merge (ต้องมีหลักฐานว่า verifier ตรงกับการตัดสินของผู้ใช้พอก่อน) และ config `merge` per project (เพิ่มเมื่อมีโหมดที่สองจริง)

## OD-009 Context Broker implementation

ต้องเลือกว่าจะเริ่มด้วย:
- deterministic Git/file retrieval
- search index
- embeddings
- Local LLM selection
- hybrid

ไม่ควรเริ่มด้วยระบบ memory ซับซ้อนเกินจำเป็น

## OD-010 Project configuration format — PROPOSED

ข้อเสนอ: TOML นอก repo ที่ `~/.config/navis/projects/<project>.toml` (ตัวอย่างใน [Execution Design](EXECUTION_DESIGN.md) §9) เพื่อไม่เพิ่มไฟล์ใน repo ของ project (D-007)
ยังต้องตัดสินว่ามีส่วนไหนควร commit ลง repo หรือไม่

## OD-011 Agent identity and roles

Roles เป็น:
- static config
- dynamically assigned per task
- hybrid

## OD-012 Cost/usage accounting

Cloud subscription CLI อาจไม่ expose token/cost แบบ API ต้องกำหนด fallback metric เช่น turns/time/context size

## OD-013 Prompt-injection boundary

ต้องออกแบบ trust labels สำหรับ:
- user instruction
- repo instruction
- web/tool content
- agent message
- generated artifact

และกำหนด precedence ที่ชัดเจน

## OD-014 Plugin/adapter sandbox

Adapters/plugins จะรัน:
- same process
- child process
- WASM
- container

ควรออกแบบ failure isolation ตั้งแต่ต้น

## OD-015 Remote control — DEFERRED / BOUNDARY CONFIRMED

D-005 ยืนยัน local UI สำหรับ MVP และเตรียม authentication boundary สำหรับ remote ในอนาคต ยังไม่เปิด remote listener

Remote implementation, transport/auth mechanism และการควบคุมจากโทรศัพท์ยังไม่ได้ตัดสิน

## OD-016 Persistent agent relationships

ควรให้ agent มี long-lived session ข้าม task หรือสร้าง session ต่อ task?

ต้องเทียบ:
- context continuity
- token/context bloat
- contamination ระหว่างงาน
- crash recovery

## OD-017 Consensus mechanism

Debate mode จบอย่างไร:
- designated lead
- verifier-based
- score/vote
- human escalation
- hybrid

ไม่ควรใช้ majority vote อย่างเดียว

## OD-018 First supported platforms — RESOLVED

D-002: Linux first ยืนยันแล้ว ระบบอื่นเป็นงานภายหลังและยังไม่อยู่ในเกณฑ์ผ่าน MVP

## OD-019 Provider policy compatibility

ก่อน automate CLI ใด ต้องตรวจ official usage/policy/terms ของ provider และออกแบบ adapter ให้ใช้ช่องทางที่รองรับ ไม่ทำ browser scraping หรือ credential circumvention

## OD-020 Initial backend surface — RESOLVED

D-001: เริ่มจาก CLI/session ที่ Runtime จัดการ การเชื่อมแชทเดิมหรือ Project บนเว็บอยู่นอก MVP
Interface ราย backend ยังต้องผ่าน OD-006 feasibility probes

## OD-021 Initial execution scope — RESOLVED SCOPE / OPEN ENFORCEMENT

D-003: อ่าน–แก้โค้ด–รันทดสอบภายใน assigned workspace
Sandbox/tool-policy technology ยังเปิดอยู่ ต้องพิสูจน์ enforcement ก่อนอนุญาต writes; ไม่อนุมานสิทธิ์ side effects นอก workspace

## OD-022 Initial Local LLM role — RESOLVED

D-004: เริ่มจากสรุป context และวิเคราะห์ log
เพิ่ม coding หลัง Agent Runner ผ่านการทดสอบและอนุญาตบทบาทนั้น Local backend/model/hardware budget ยังไม่ได้เลือก

## OD-023 Lifecycle, evidence and controls — OPEN

กำหนด state transition guards, event schema, action reconciliation, approval binding, Pause/Stop/Kill semantics และ immutable verification evidence
ข้อเสนอ baseline อยู่ใน MVP Contract; ต้องพิสูจน์กับ adapter จริงก่อนล็อก implementation

## OD-024 Project name — RESOLVED

D-011: Navis — ชื่อเดิม "A2A" ชนกับ Agent2Agent (A2A) protocol ซึ่ง OD-005 อาจทำ bridge ไปหาในอนาคต
