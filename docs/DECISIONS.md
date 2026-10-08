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
| D-010 | Runtime commit ได้ใน clone ของ attempt | snapshot อยู่ใน clone และ `refs/axon/*` ของ repo หลักเท่านั้น; branch ของผู้ใช้, push, merge และ deploy ยังเป็นของผู้ใช้ |
| D-011 | ชื่อโปรเจกต์คือ Axon (เดิม Navis, เปลี่ยน 2026-10-07 เพราะฟังคล้าย Jarvis) | repo/folder ชื่อ `PROJECT_AXON`; CLI, config dir, refs และ systemd units ใช้ `axon` |
| D-012 | Core เขียนด้วย Python | Python ≥ 3.11 (ตรงกับ VELA) ใช้ stdlib ก่อน |
| D-013 | สร้างและทดสอบกับ `fake-agent` ให้เสร็จก่อนใช้ CLI จริง | probes ที่ใช้ quota (Execution Design §10) เลื่อนไปหลัง Runtime ผ่าน acceptance scenarios กับ fake แล้ว |
| D-014 | Merge: ผู้ใช้สั่ง, Runtime รวมงานบน integration branch ของ Axon | Runtime rebase/merge ผลของ task บน `refs/axon/integration/<project>` แล้วรัน check ซ้ำบน commit สุดท้าย; ผู้ใช้ fast-forward เข้า branch ของตัวเองเอง (CLI ก่อน, GUI ภายหลัง) Runtime ไม่แตะ branch หรือ working tree ของผู้ใช้ และไม่มี auto-merge ใน MVP (OD-008) |

### ยืนยันเพิ่ม 2026-10-08 (บันทึกตามที่ implement แล้ว)

| ID | คำตัดสินที่ยืนยันแล้ว | ผลต่อ MVP |
| --- | --- | --- |
| D-015 | UI เป็น browser UI ที่ Axon serve เอง | `axon/web` ไม่มี framework/build step; ไม่ทำ desktop wrapper จนกว่าจะมีความต้องการที่ browser ทำไม่ได้ (OD-002) |
| D-016 | Transport: HTTP บน loopback + polling, WebSocket เฉพาะ terminal ของ Chat, Unix socket ต่อ attempt สำหรับ agent | เปลี่ยนเป็น SSE เมื่อ polling ช้าหรือเปลืองจนวัดได้ (OD-003) |
| D-017 | Storage: SQLite (WAL) เป็น state หลัก ไฟล์ของ attempt อยู่ข้าง ๆ | ไม่ใช้ embedded DB อื่น (OD-004) |
| D-018 | Adapter ใช้โหมด noninteractive แบบมีโครงสร้างของ CLI ทางการ + MCP tools ของ Axon | ไม่ใช้ PTY/app-server; Runner ไม่พึ่ง resume ของ provider (OD-006) |
| D-019 | Clone ต่อ attempt (`git clone --shared`) ไม่ใช้ worktree | ผลกลับเป็น bundle ที่ `refs/axon/attempts/<id>` (OD-007) |
| D-020 | Project config เป็น TOML นอก repo ทั้งหมด | ไม่มีส่วนไหน commit ลง repo ของ project (OD-010) |
| D-021 | Usage accounting ต่อ attempt: prompt bytes, เวลา, model/effort และ usage เท่าที่ CLI เปิดเผย | ค่าที่ไม่เปิดเผยเป็น `None`; fair scheduling ใช้ wall time (OD-012) |
| D-022 | Sandbox: bwrap + systemd user scope ต่อ attempt | คำสั่งของ agent และ checks ไม่มีเน็ต; Chat เป็นข้อยกเว้นที่ผู้ใช้คุมเอง (OD-021) |
| D-023 | Trust precedence: Runtime policy > ผู้ใช้ > repo instruction > agent message > web/tool content และ artifact | label ใน prompt ไม่ใช่ enforcement; งาน enforcement ที่ค้างอยู่ใน OD-013 |
| D-024 | Adapter/agent รันเป็น child process ใน sandbox ของ attempt | ไม่มีระบบ plugin จากภายนอก (OD-014) |
| D-025 | Lifecycle/controls ตามที่ implement ใน Runtime | ช่องว่างกับ MVP Contract ที่รู้แล้วอยู่ใน OD-023 |
| D-026 | Local backend คือ Ollama บน loopback, โมเดลเริ่มต้น `qwen2.5-coder:7b`; local coding คงปิด | ประเมินใหม่เมื่อมีโมเดล/ฮาร์ดแวร์ที่ดีกว่า (OD-022, Phase 4) |

## ข้อเสนอที่ยังไม่ได้ล็อก

- ผู้ใช้เป็นผู้สั่ง push/merge/deploy ช่วงแรก; local commit ใน clone ของ attempt ยืนยันแล้วใน D-010 ส่วนการรวมงานยืนยันแล้วใน D-014
- เป้าหมายเดิมคือไม่บังคับ cloud API-key workflow; การเรียก local endpoint และ structured CLI protocol ยังใช้ได้ตาม draft เดิม หากต้องการห้าม interface เหล่านี้ด้วยต้องตัดสินแยก

ความสามารถจริงของแต่ละ backend ดูจากผล probe ใน [MVP Contract](MVP_CONTRACT.md) §2 ไม่ใช่จากคำตัดสินในเอกสารนี้
