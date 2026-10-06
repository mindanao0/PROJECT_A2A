# Navis Local GUI

สถานะ: **GUI foundation / simulation only** — ทำหน้าควบคุมและ state contract ที่ลองใช้งานได้ก่อนมี production Agent Runner ตาม D-012/D-013

ไม่ใช่รายงานว่า Phase 1 ผ่านแล้ว: ไม่มี provider CLI, sandbox, cgroup, workspace clone, MCP, local inference หรือ real verifier ใน implementation นี้ `fake-agent` ใน GUI เป็น in-process simulation ไม่ใช่ fake-agent CLI ที่มี edit/orphan/crash scenarios ใน Execution Design §6

## เปิดใช้งานบน Linux

ต้องมี Python 3.11 ขึ้นไป ไม่ต้องติดตั้ง Python dependencies, Node หรือ frontend build tool เพื่อเปิด GUI จาก source:

```bash
git clone https://github.com/mindanao0/PROJECT_NAVIS.git
cd PROJECT_NAVIS
python3 -m navis
```

ระบบเปิด browser พร้อม launch link ของ instance นั้น ถ้าเครื่องไม่เปิด browser อัตโนมัติ:

```bash
python3 -m navis --no-browser
```

คัดลอก **link เต็มที่พิมพ์ใน terminal** ไปเปิดบน browser ของเครื่องเดียวกัน ห้ามแชร์ launch link เพราะมีสิทธิ์ควบคุม instance นั้นผ่าน token ใน fragment

เลือก port ได้ แต่เลือก bind address ไม่ได้ (ล็อกเป็น `127.0.0.1`):

```bash
python3 -m navis --port 8765
```

ใช้ state สำหรับทดลองแยกจาก state ปกติ:

```bash
python3 -m navis --state-dir ~/.local/state/navis-demo
```

Directory ต้องเป็นของผู้ใช้ปัจจุบันและ permission `0700`; path ที่ไม่ปลอดภัยจะถูกปฏิเสธ ไม่แก้ permission ของ directory เดิมอัตโนมัติ ข้อมูล default อยู่ใน `$XDG_STATE_HOME/navis` หรือ `~/.local/state/navis` เมื่อไม่ตั้งตัวแปร instance เดียวใช้ state dir ได้ครั้งละหนึ่งตัว

ถ้าต้องการติดตั้งคำสั่ง `navis` ใช้ virtual environment:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
navis
```

ปิดด้วย Ctrl+C ใน terminal ที่รันอยู่ ข้อมูล task/event ยังอยู่ แต่ token จะเปลี่ยนทุกครั้งที่เปิด และ launch file จะถูกลบเมื่อปิดปกติ

## หน้าจอและวิธีใช้

| หน้า | ใช้ทำอะไร |
| --- | --- |
| Overview | จำนวนงาน, task board, agent fleet, recent activity และงานรอผู้ใช้ |
| Task board | ค้นหางาน, filter สถานะ, เลือก project, เปิดรายละเอียดงาน |
| Agents | ดู backend/capability ที่ยังไม่ทดสอบ; Codex/Claude/Local ถูกปิด |
| Activity log | ดู event ที่ Runtime บันทึกพร้อม task/attempt และ cursor |
| Artifacts | ดู simulated result/verifier evidence พร้อม content hash และ attempt ID |
| Runtime settings | ดูขอบเขต local transport, recovery และความสามารถที่ยังไม่มี |

1. กด **New task** ใส่ชื่อ, description/acceptance, project และ scope ที่เป็น relative path เช่น `src/, tests/`
2. เลือก scenario แล้วสร้าง task ระบบเริ่ม QUEUED และ dispatch เมื่อไม่ pause และ fake slot ว่าง
3. คลิก card เพื่อดู task/attempt, activity, pending request, instruction history, artifacts และ attempt history
4. กด **+** ข้าง PROJECTS เพื่อสร้าง project จำลอง ไม่มีการอ่าน/เชื่อม repository ตามชื่อที่ใส่
5. งานใหม่ที่ description normalize และ scope ตรงกับงานเดิมใน project เดียวกันจะแสดงงานเดิม ไม่สร้างซ้ำ (ใช้ title/scenario ต่างกันอย่างเดียวไม่ทำให้เป็นงานใหม่)

| Scenario | สิ่งที่ทดลองได้ |
| --- | --- |
| Successful result | RUNNING → VERIFY → COMPLETED; ใช้ fake verifier เท่านั้น |
| Ask for user input | WAITING_INPUT → ส่งคำตอบ → RUNNING |
| Wait for approval | WAITING_APPROVAL → Approve หรือ Reject; request ผูก attempt/payload และหมดอายุหลัง 10 นาที |
| Quota cooldown | WAITING_QUOTA 15 วินาที → QUEUED; ปล่อย fake slot; ไม่ใช้ quota จริง |
| Agent failure | FAILED; กด Retry เพื่อสร้าง attempt ใหม่ |
| Verification failure | เข้า VERIFY แล้ว FAILED; evidence มี fake exit code 1 |
| Long-running | ไม่จบเอง; ใช้ทดลอง Stop/Kill |

### ความหมายปุ่ม

- **Pause dispatch**: หยุดการเริ่มงานใหม่ งานจำลองที่กำลังทำยังเดินต่อ
- **Resume dispatch**: เปิดการเริ่มงานใหม่
- **Stop**: งาน active เข้า CANCELLING ก่อน จากนั้น simulation acknowledge แล้ว CANCELLED; queued/quota task ยกเลิกทันทีเพราะไม่มี worker active
- **Kill simulation**: revoke simulated attempt ทันที ไม่มี OS process ให้ kill และไม่ใช่หลักฐานว่า production process-tree kill ผ่านแล้ว
- **Retry as new attempt**: ใช้กับ FAILED/CANCELLED/BLOCKED; เก็บ attempt/artifact เดิมและเริ่ม attempt ใหม่
- **Save instruction**: บันทึก versioned guidance; simulated result ระบุ instruction version ไม่มี model รับข้อความจริง
- **Approve/Reject/Send answer**: ใช้กับ request และ attempt ที่หน้าจอเห็นเท่านั้น; payload เก่าหรือ request ที่แก้ไปแล้วถูกปฏิเสธ

ยังไม่มี Reassign, Rollback, dependency graph, diff ของ Git, Take over, real resource usage และ token budget จึงไม่แสดงปุ่มที่อ้างว่าทำงานเหล่านี้ได้

## Persistence และ reconnect

Core อยู่ใน `navis/core.py` แยกจาก UI/HTTP; SQLite transaction เดียวบันทึก snapshot และ event เมื่อคำสั่งสำเร็จ ข้อมูลอยู่ใน `control.sqlite3` ไม่เขียน config ลง VELA

UI poll snapshot/event ทุก 1.5 วินาที; event ใช้ cursor และส่งครั้งละไม่เกิน 300 รายการเพื่อ backpressure UI แสดงล่าสุด 1,000 รายการ แต่ event เก่ายังอยู่ใน database การ disconnect browser ไม่ยกเลิก task และเมื่อเชื่อมใหม่ในหน้าเดิมจะอ่านต่อจาก cursor เดิม

ถ้า Runtime restart งานที่ active/รอ input/approval/quota จะเป็น BLOCKED และ revoke attempt เดิม ไม่ replay side effects หรือ resume จำลองเงียบ ๆ ผู้ใช้ต้อง Retry เอง งาน QUEUED ยังคงรอ dispatch ตาม pause state เดิม

Token อยู่ใน browser memory และถูกลบออกจาก address bar หลังเปิด link ไม่เก็บใน localStorage/sessionStorage ถ้า reload/เปิด tab ใหม่ต้องเปิด launch link เต็มอีกครั้ง (ดู terminal หรือไฟล์ `launch.url` ใน state dir) ถ้า network connection ล้ม UI แสดง stale-state warning และปิดปุ่มควบคุม

## Local authorization boundary

- HTTP bind `127.0.0.1` เท่านั้น; ไม่มี remote listener หรือ proxy endpoint
- API ทั้งอ่านและเขียนต้องมี per-launch random bearer token
- Host ต้องตรง `127.0.0.1:<port>`; ป้องกัน DNS rebinding
- POST ต้องมี exact same Origin และ JSON content type; ไม่มี permissive CORS
- ขนาด request ไม่เกิน 16 KiB; task/project/text มีขีดจำกัด
- Static assets เป็น allowlist และมี CSP, no-store, no-referrer, frame-ancestors none
- State dir `0700`, DB/launch file `0600`, advisory process lock ป้องกันสอง instance
- ไม่มี endpoint สำหรับ shell, file access, push, merge หรือ deploy

Boundary นี้เป็น local single-user GUI foundation ไม่ได้พิสูจน์ production authentication ของ agent sockets เมื่อเพิ่ม sandbox/agent processes ต้องซ่อน control socket/transport จาก attempt และทำ authorization ตาม MVP Contract ห้ามเปิด remote ด้วยการแก้ bind addressเฉย ๆ

## ทดสอบ

Core/transport/startup tests ใช้ standard library:

```bash
python3 -m unittest discover -s tests -v
node --check navis/web/app.js
```

ตรวจ packaging:

```bash
python3 -m pip install .
navis --help
```

Browser integration test เป็น optional dev dependency ต้องใช้ Node 18+ และ Playwright พร้อม Chromium; ติดตั้งไว้นอก repo ได้:

```bash
npm install --prefix /tmp/navis-browser-check playwright
/tmp/navis-browser-check/node_modules/.bin/playwright install chromium
NODE_PATH=/tmp/navis-browser-check/node_modules node tests/gui-smoke.cjs
```

Test นี้เปิด instance ด้วย temp state ของตัวเองแล้วทดสอบ approval/input/stop/retry/kill, artifacts, search, projects, escaping, mobile form และ disconnect; ไม่แตะ state ปกติหรือ CLI account จริง `NAVIS_SCREENSHOT=/absolute/path/control-room.png` เป็น optional screenshot output

GitHub Actions รัน unittest, JS syntax และ package installation บน Python 3.11/3.12/3.13; ไม่ได้รัน browser test หรือ provider probes

ผลตรวจใน workspace วันที่ 2026-10-06: unittest 17 กรณีผ่าน, JS syntax ผ่าน, wheel ติดตั้งพร้อม web assets และ entry point ผ่าน Browser test **ยังไม่ยืนยัน**: Chromium download ไม่สำเร็จและ cloud browser ถูกปฏิเสธสิทธิ์เข้าถึง localhost ผู้ใช้เลือกข้ามการทดสอบนี้และตรวจ UI เองหลังส่งขึ้น GitHub จึงไม่มี screenshot หรือการอ้างว่า UI rendering/mobile interaction ผ่านแล้ว

## ขั้นต่อไปที่ต้องทำก่อนใช้ AI จริง

1. ทำ fake-agent CLI + adapter interface, lease/action reconciliation และ full acceptance scenarios
2. เชื่อม project TOML config, isolated attempt clone, sandbox, cgroup และ checks
3. พิสูจน์ Stop/Kill กับ process tree รวม orphan; scope enforcement และ secret redaction
4. เปลี่ยน simulation model เป็น Runtime commands/snapshots ที่ authenticated ตามสัญญาเดิม
5. ทำ Codex/Claude/local backend probes ตาม Execution Design §10 หลัง fake runner ผ่าน
6. เพิ่ม immutable Git diff, exact-commit verifier evidence และ UI controls ที่ runner รองรับ

ไม่มีการใช้ provider quota หรือแก้ไฟล์ PROJECT_VELA เพื่อสร้าง GUI รุ่นนี้
