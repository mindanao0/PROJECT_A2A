# Confirmed Decisions

วันที่ยืนยัน: 2026-10-06

เอกสารนี้บันทึกขอบเขตที่ผู้ใช้เลือกแล้ว ส่วนรายละเอียด implementation ที่ยังไม่เลือกอยู่ใน [Open Decisions](OPEN_DECISIONS.md) ข้อเสนอเกณฑ์ผ่านอยู่ใน [MVP Contract](MVP_CONTRACT.md) และการออกแบบที่ implement ได้อยู่ใน [Execution Design](EXECUTION_DESIGN.md)

| ID | คำตัดสินที่ยืนยันแล้ว | ผลต่อ MVP |
| --- | --- | --- |
| D-001 | เริ่มจาก CLI/session | Runtime จัดการ session ของ Codex/Claude Code; การเชื่อมแชทเดิมหรือ Project บนเว็บอยู่นอก MVP |
| D-002 | Linux first | พิสูจน์ process lifecycle และ execution boundaries บน Linux ก่อน; ระบบอื่นยังไม่อยู่ในเกณฑ์ผ่านรุ่นแรก |
| D-003 | อ่าน–แก้โค้ด–รันทดสอบได้ภายใน workspace | Agent ทำงานใน workspace ที่จัดสรรให้; ไม่อนุมานสิทธิ์เข้าถึงไฟล์อื่น ติดตั้งระบบ push merge หรือ deploy |
| D-004 | Local LLM เริ่มจากสรุป context และวิเคราะห์ log | ไม่มีเครื่องมือเขียนไฟล์หรือรันคำสั่งให้ local helper; coding เปิดได้ภายหลังเมื่อ Agent Runner ผ่านเกณฑ์ทดสอบและอนุญาตบทบาทนั้น |
| D-005 | UI บนเครื่องเดียวก่อน แต่เตรียม authentication boundary สำหรับ remote | MVP ไม่มี remote listener; ออกแบบ client identity และขอบเขตการอนุญาตก่อนเพิ่ม remote |
| D-006 | ผู้ใช้คนเดียว | ไม่มี multi-user/role; control socket ของผู้ใช้ใน `$XDG_RUNTIME_DIR` เป็น local boundary และ sandbox มองไม่เห็น |
| D-007 | Project แรกคือ PROJECT_VELA | Python 3.11 + uv + pytest/ruff/mypy; ไม่เพิ่มไฟล์ใน repo VELA; project config อยู่นอก repo เป็น TOML |
| D-008 | เป้าหมายหลัก: แบ่งงานชัด ไม่ทับกัน ไม่ทำงานที่ทำไปแล้วซ้ำ และแบ่งทรัพยากรเครื่อง | scope claim, task dedup, slot และ cgroup limits เป็นงาน Phase 1 ([Execution Design](EXECUTION_DESIGN.md) §8) |
| D-009 | ใช้ subscription แผน 20 USD | ไม่เกิน 1 session ต่อ provider; quota หมดเป็นสถานะปกติ (WAITING_QUOTA) ไม่ใช่ error |
| D-010 | Runtime commit ได้ใน clone ของ attempt | snapshot อยู่ใน clone และ `refs/navis/*` ของ repo หลักเท่านั้น; branch ของผู้ใช้, push, merge และ deploy ยังเป็นของผู้ใช้ |
| D-011 | ชื่อโปรเจกต์คือ Navis | repo/folder ชื่อ `PROJECT_NAVIS`; CLI, config dir, refs และ systemd units ใช้ `navis` |
| D-012 | Core เขียนด้วย Python | Python ≥ 3.11 (ตรงกับ VELA) ใช้ stdlib ก่อน |
| D-013 | สร้างและทดสอบกับ `fake-agent` ให้เสร็จก่อนใช้ CLI จริง | probes ที่ใช้ quota (Execution Design §10) เลื่อนไปหลัง Runtime ผ่าน acceptance scenarios กับ fake แล้ว |

## ข้อเสนอที่ยังไม่ได้ล็อก

- เริ่ม Local LLM backend เพียงหนึ่งตัว และเลือกหลัง Phase 0
- ทดลอง Codex app-server / Claude Code structured CLI interfaces ก่อน PTY
- UI เล็กในช่วง runtime skeleton; Web UI เป็นข้อเสนอ ไม่ใช่คำตัดสินเรื่อง framework
- ผู้ใช้เป็นผู้สั่ง push/merge/deploy ช่วงแรก; local commit ใน clone ของ attempt ยืนยันแล้วใน D-010 ส่วน merge policy ยังอยู่ใน OD-008
- เป้าหมายเดิมคือไม่บังคับ cloud API-key workflow; การเรียก local endpoint และ structured CLI protocol ยังใช้ได้ตาม draft เดิม หากต้องการห้าม interface เหล่านี้ด้วยต้องตัดสินแยก

คำตัดสินข้างต้นไม่ได้ยืนยัน UI framework, transport, database, sandbox technology หรือความสามารถจริงของ backend ใด
