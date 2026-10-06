# Open Decisions

เอกสารนี้เก็บสิ่งที่ **ยังไม่ได้ตัดสินใจ** เพื่อไม่ให้ discussion draft ถูกตีความว่า final design

## OD-001 Core implementation language

ตัวเลือกเบื้องต้น:
- Rust
- Go
- TypeScript/Node
- Python
- Hybrid

ต้องพิจารณา daemon/process supervision, WebSocket, PTY, plugin adapters, packaging และ cross-platform support

## OD-002 UI technology

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

## OD-007 Worktree strategy

- worktree ต่อ task
- worktree ต่อ agent
- adaptive

ต้องวัด overhead และ conflict behavior

## OD-008 Who can merge

ตัวเลือก:
- human only
- verifier + policy auto-merge
- configurable per project

Default ช่วงแรกควร conservative

## OD-009 Context Broker implementation

ต้องเลือกว่าจะเริ่มด้วย:
- deterministic Git/file retrieval
- search index
- embeddings
- Local LLM selection
- hybrid

ไม่ควรเริ่มด้วยระบบ memory ซับซ้อนเกินจำเป็น

## OD-010 Project configuration format

ตัวอย่าง:

```text
.a2a/project.yaml
```

ต้องกำหนดว่าอะไรเป็น global config และอะไร commit ลง repo

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

## OD-015 Remote control

อนาคตจะควบคุม Runtime จากโทรศัพท์/เครื่องอื่นหรือไม่ และ authentication/network boundary จะเป็นอย่างไร

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

## OD-018 First supported platforms

- Linux first
- macOS first
- Linux + macOS
- Windows later

## OD-019 Provider policy compatibility

ก่อน automate CLI ใด ต้องตรวจ official usage/policy/terms ของ provider และออกแบบ adapter ให้ใช้ช่องทางที่รองรับ ไม่ทำ browser scraping หรือ credential circumvention
