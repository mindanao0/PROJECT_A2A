# PROJECT_A2A

ระบบกลางสำหรับให้ AI หลายตัวทำงานเป็นทีมในหลายโปรเจกต์ โดยมีเป้าหมายหลักคือให้ ChatGPT/Codex, Claude Code และ Local LLM สามารถคุย วิเคราะห์ แบ่งงาน ตรวจงาน และส่งผลลัพธ์หากันได้โดยไม่ต้องใช้ไฟล์ handoff เป็นช่องทางหลัก

> สถานะ: **Design / Discussion Draft** — เอกสารใน repo นี้เป็น baseline สำหรับคุยและปรับแผนต่อ ยังไม่ถือว่า architecture ถูกล็อก

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
