# Navis

ระบบกลางสำหรับให้ AI หลายตัวทำงานเป็นทีมในหลายโปรเจกต์ โดยมีเป้าหมายหลักคือให้ ChatGPT/Codex, Claude Code และ Local LLM สามารถคุย วิเคราะห์ แบ่งงาน ตรวจงาน และส่งผลลัพธ์หากันได้โดยไม่ต้องใช้ไฟล์ handoff เป็นช่องทางหลัก

> สถานะ: **Design + Local GUI Foundation** — ยืนยันคำตัดสินแล้ว 13 ข้อ; เปิด GUI ที่ใช้ in-process fake-agent simulation ได้ด้วย `python3 -m navis` ยังไม่มี production Agent Runner หรือ adapter จริง Boundary probes ที่ไม่ใช้ quota ผ่านแล้ว (`probes/boundary.sh`) แต่ adapter probes ยังไม่ได้ทดสอบ

## เปิด UI/GUI

ต้องใช้ Linux + Python 3.11 ขึ้นไป ไม่มี runtime dependencies เพิ่ม:

```bash
python3 -m navis
```

เปิด local launch link ที่พิมพ์ใน terminal เพื่อเข้า UI ธีม **Cybernetics ดำ–แดง**: Control room, Task board, Agents, Activity log, Artifacts, Resources และ Runtime settings การ์ดแสดงเหตุผลรอคิวและ countdown; เลือกงานที่เสร็จแล้วเป็นต้นทางได้; Stop/Kill มีหน้าต่างยืนยัน และ refresh หน้าแล้ว session ยังใช้ได้ สร้างงานและทดลอง controls ผ่าน simulation ได้ งานจำลองไม่อ่านหรือแก้ repository และไม่เรียก Codex/Claude/Local LLM จริง

### โหมด real (runtime จริง)

```bash
python3 -m navis --real
```

GUI เดียวกันแต่ขับ runtime จริง: งานรันใน sandbox (bwrap + cgroup) ผลลง `refs/navis/attempts/*` ไม่ merge/push ให้ ต้องมี project config ที่ `~/.config/navis/projects/<ชื่อ>.toml` ([ตัวอย่าง](docs/EXECUTION_DESIGN.md)) agent `fake` ใช้ทดสอบได้ทันทีโดยไม่ใช้ quota ส่วน `codex` / `claude` ต้อง login agent home ของ Navis ก่อน (แยกจาก login ปกติ) และ adapter ทั้งสองยังไม่ผ่าน probe จริง:

```bash
CLAUDE_CONFIG_DIR=~/.local/share/navis/agents/claude claude auth login
CODEX_HOME=~/.local/share/navis/agents/codex codex login --device-auth
```

`navis-cli add|ls|show|run|stop|answer|approve|reject` ใช้คิวงานจาก terminal ได้เช่นกัน และใช้ฐานข้อมูลเดียวกับ GUI

วิธีติดตั้ง การใช้งาน controls, authentication, persistence, ข้อจำกัดและผลทดสอบ: [Local GUI Guide](docs/GUI.md)

## ขอบเขต MVP ที่ยืนยันแล้ว

- เริ่มจาก CLI/session ที่ Runtime จัดการ ไม่เชื่อมแชทเดิมบนเว็บใน MVP
- Linux first
- Coding agent อ่าน–แก้โค้ด–รันทดสอบได้ภายใน assigned workspace ตามสิทธิ์ที่บังคับใช้จริง
- Local LLM เริ่มจากสรุป context และวิเคราะห์ log; เพิ่ม coding หลัง Agent Runner ผ่านการทดสอบและอนุญาตบทบาทนั้น
- UI บนเครื่องเดียวก่อน โดยเตรียม authentication/authorization boundary สำหรับ remote; ยังไม่เปิด remote listener
- ผู้ใช้คนเดียว, project แรกคือ PROJECT_VELA, ใช้ subscription แผน 20 USD
- เป้าหมายหลัก: แบ่งงานชัด ไม่ทับกัน ไม่ทำซ้ำ และแบ่งทรัพยากรเครื่อง

ดู [Confirmed Decisions](docs/DECISIONS.md), [MVP Contract](docs/MVP_CONTRACT.md) และ [Execution Design](docs/EXECUTION_DESIGN.md) สำหรับขอบเขต เกณฑ์ผ่าน และการออกแบบที่ implement ได้

## เป้าหมาย

- ใช้งานได้กับหลาย project ไม่ผูกกับ PROJECT_VELA
- เชื่อม Cloud coding agents ผ่าน account/CLI ที่รองรับ โดยไม่บังคับให้ผู้ใช้จัดการ API key เอง
- รองรับ Local LLM เช่น Ollama / llama.cpp / LM Studio หรือ adapter อื่น
- ให้ agent คุยกันแบบมีโครงสร้าง ไม่ใช่แชร์ transcript ทั้งหมด
- ให้ agent delegate, critique, review และแบ่งงานกันได้
- มี UI สำหรับดูสถานะ ควบคุม หยุด อนุมัติ ปฏิเสธ และเข้าแทรกแซง
- ลด token/context ที่ส่งซ้ำโดยมี Context Broker และ Artifact references
- แยก workspace ของ agent เพื่อลดการแก้ไฟล์ชนกัน
- มี verifier, policy และ audit trail เพื่อไม่ให้ “AI เห็นตรงกัน” เท่ากับ “ถูกต้อง”

## แนวคิดหลัก

```text
                         Control UI
                            |
                    +-------v-------+
                    |  Team Runtime |
                    |---------------|
                    | Supervisor    |
                    | Scheduler     |
                    | Task Engine   |
                    | Context Broker|
                    | Policy Engine |
                    | Event Store   |
                    | Merge Manager |
                    +-------+-------+
                            |
                  Internal Agent Bus
              +-------------+-------------+
              |             |             |
              v             v             v
          Codex Adapter  Claude Adapter  Local Adapter
              |             |             |
          Codex CLI     Claude Code   Ollama/llama.cpp
              |             |             |
           Worktree A    Worktree B    Worktree C
              +-------------+-------------+
                            |
                         Git Repo
```

## Protocol boundary

- **Agent ↔ Agent:** ใช้ protocol/message model ของ Runtime เอง โดยสามารถออกแบบให้สอดคล้องกับแนวคิด A2A เช่น task, message, artifact, capability และ streaming
- **Agent ↔ Tool/Data:** ใช้ MCP ได้เมื่อเหมาะสม
- **Runtime ↔ Agent implementation:** ใช้ Adapter เพื่อครอบ CLI, local endpoint หรือ backend อื่น

ไม่ควรบังคับให้ Codex/Claude “พูด A2A โดยตรง” เพราะ CLI แต่ละตัวมี lifecycle และ interface ต่างกัน Runtime ควรเป็นตัว normalize ความต่างเหล่านั้น

## เอกสาร

- [Confirmed Decisions](docs/DECISIONS.md)
- [MVP Contract / Acceptance Criteria](docs/MVP_CONTRACT.md)
- [Execution Design](docs/EXECUTION_DESIGN.md)
- [Architecture Draft](docs/ARCHITECTURE_DRAFT.md)
- [Open Decisions](docs/OPEN_DECISIONS.md)
- [Initial Roadmap](docs/ROADMAP.md)

## หลักการที่ยังยึดไว้

1. Core แยกจาก UI
2. Agent เปลี่ยน/เพิ่มได้ผ่าน Adapter
3. Chat ไม่ใช่ source of truth ของ task
4. Code ใช้ Git เป็น source of truth
5. Event log ใช้สำหรับ audit/recovery แต่ไม่ส่งกลับเข้า model ทั้งหมด
6. งานสำคัญต้องผ่าน verifier/test ไม่ใช่ใช้เสียงข้างมากของ AI
7. ผู้ใช้สามารถ interrupt/override ระบบได้เสมอ
8. Default ควรประหยัด context และ token
