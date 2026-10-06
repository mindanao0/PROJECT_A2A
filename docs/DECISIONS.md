# Confirmed Decisions

วันที่ยืนยัน: 2026-10-06

เอกสารนี้บันทึกขอบเขตที่ผู้ใช้เลือกแล้ว ส่วนรายละเอียด implementation ที่ยังไม่เลือกอยู่ใน [Open Decisions](OPEN_DECISIONS.md) และข้อเสนอเกณฑ์ผ่านอยู่ใน [MVP Contract](MVP_CONTRACT.md)

| ID | คำตัดสินที่ยืนยันแล้ว | ผลต่อ MVP |
| --- | --- | --- |
| D-001 | เริ่มจาก CLI/session | Runtime จัดการ session ของ Codex/Claude Code; การเชื่อมแชทเดิมหรือ Project บนเว็บอยู่นอก MVP |
| D-002 | Linux first | พิสูจน์ process lifecycle และ execution boundaries บน Linux ก่อน; ระบบอื่นยังไม่อยู่ในเกณฑ์ผ่านรุ่นแรก |
| D-003 | อ่าน–แก้โค้ด–รันทดสอบได้ภายใน workspace | Agent ทำงานใน workspace ที่จัดสรรให้; ไม่อนุมานสิทธิ์เข้าถึงไฟล์อื่น ติดตั้งระบบ push merge หรือ deploy |
| D-004 | Local LLM เริ่มจากสรุป context และวิเคราะห์ log | ไม่มีเครื่องมือเขียนไฟล์หรือรันคำสั่งให้ local helper; coding เปิดได้ภายหลังเมื่อ Agent Runner ผ่านเกณฑ์ทดสอบและอนุญาตบทบาทนั้น |
| D-005 | UI บนเครื่องเดียวก่อน แต่เตรียม authentication boundary สำหรับ remote | MVP ไม่มี remote listener; ออกแบบ client identity และขอบเขตการอนุญาตก่อนเพิ่ม remote |

## ข้อเสนอที่ยังไม่ได้ล็อก

- เริ่ม Local LLM backend เพียงหนึ่งตัว และเลือกหลัง Phase 0
- ทดลอง Codex app-server / Claude Code structured CLI interfaces ก่อน PTY
- UI เล็กในช่วง runtime skeleton; Web UI เป็นข้อเสนอ ไม่ใช่คำตัดสินเรื่อง framework
- ผู้ใช้เป็นผู้สั่ง push/merge/deploy ช่วงแรก; รายละเอียดสิทธิ์ local commit และ merge policy ยังอยู่ใน OD-008
- เป้าหมายเดิมคือไม่บังคับ cloud API-key workflow; การเรียก local endpoint และ structured CLI protocol ยังใช้ได้ตาม draft เดิม หากต้องการห้าม interface เหล่านี้ด้วยต้องตัดสินแยก

คำตัดสินข้างต้นไม่ได้ยืนยันภาษา core, UI framework, transport, database, sandbox technology หรือความสามารถจริงของ backend ใด
