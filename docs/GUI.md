# Navis Local GUI

สถานะ: **GUI foundation / simulation only** — ทำหน้าควบคุมและ state contract ที่ลองใช้งานได้ก่อนมี production Agent Runner ตาม D-012/D-013

ธีม: **Cybernetics ดำ–แดง** — พื้นดำ, panel ขอบคม, accent แดง, typography สำหรับ ID/สถานะ และ focus ที่มองเห็นได้ ไม่มี animation ต่อเนื่อง

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
| Resources | slot ที่ใช้/ทั้งหมดและ active attempts; RAM แสดงว่าไม่มีข้อมูลวัดจริง |
| Runtime settings | ดูขอบเขต local transport, recovery และความสามารถที่ยังไม่มี |

1. กด **New task** ใส่ชื่อ, description/acceptance, project และ scope ที่เป็น relative path เช่น `src/, tests/`
2. เลือก scenario แล้วสร้าง task ระบบเริ่ม QUEUED และ dispatch เมื่อไม่ pause และ fake slot ว่าง
3. คลิก card เพื่อดู task/attempt, activity, pending request, instruction history, artifacts และ attempt history
4. กด **+** ข้าง PROJECTS เพื่อสร้าง project จำลอง ไม่มีการอ่าน/เชื่อม repository ตามชื่อที่ใส่
5. งานใหม่ที่ description normalize และ scope ตรงกับงานเดิมใน project เดียวกันจะแสดงงานเดิม ไม่สร้างซ้ำ (ใช้ title/scenario ต่างกันอย่างเดียวไม่ทำให้เป็นงานใหม่)
6. **Start from completed task** เลือกงานที่เสร็จใน project เดียวกัน หรือกด **Continue from this task** ในรายละเอียดงาน เก็บ source task, attempt และสำเนา artifacts ของ attempt นั้น; source ที่ไม่เสร็จหรือ attempt เปลี่ยนแล้วถูกปฏิเสธ ยังไม่มีการส่งต่อระหว่าง provider หรือสร้าง Git ref
7. ในรายละเอียดงานเลือก Results, Code diff, Agent output, Prompt / instructions หรือ Attempts ผลเต็มคัดลอกได้; เมื่อ clipboard ใช้ไม่ได้จะมีช่องข้อความให้เลือกคัดลอกเอง

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
- **Stop**: มีหน้าต่างยืนยันก่อนส่งคำสั่ง งาน active เข้า CANCELLING ก่อน จากนั้น simulation acknowledge แล้ว CANCELLED; queued/quota task ยกเลิกทันทีเพราะไม่มี worker active
- **Kill simulation**: มีหน้าต่างยืนยันก่อน revoke simulated attempt ไม่มี OS process ให้ kill และไม่ใช่หลักฐานว่า production process-tree kill ผ่านแล้ว หน้าต่างยืนยันจับ attempt ที่ผู้ใช้เห็นก่อนเปิด; ถ้า attempt เปลี่ยนแล้ว server ปฏิเสธคำสั่ง ไม่ส่งไปฆ่า attempt ใหม่
- **Retry as new attempt**: ใช้กับ FAILED/CANCELLED/BLOCKED; เก็บ attempt/artifact เดิมและเริ่ม attempt ใหม่
- **Save instruction**: บันทึก versioned guidance; simulated result ระบุ instruction version ไม่มี model รับข้อความจริง
- **Approve/Reject/Send answer**: ใช้กับ request และ attempt ที่หน้าจอเห็นเท่านั้น; payload เก่าหรือ request ที่แก้ไปแล้วถูกปฏิเสธ

ยังไม่มี Reassign, Rollback, dependency graph, diff ของ Git, Take over, real resource usage และ token budget จึงไม่แสดงปุ่มที่อ้างว่าทำงานเหล่านี้ได้

## Persistence และ reconnect

Core อยู่ใน `navis/core.py` แยกจาก UI/HTTP; SQLite transaction เดียวบันทึก snapshot และ event เมื่อคำสั่งสำเร็จ ข้อมูลอยู่ใน `control.sqlite3` ไม่เขียน config ลง VELA

UI poll snapshot/event ทุก 1.5 วินาที; event ใช้ cursor และส่งครั้งละไม่เกิน 300 รายการเพื่อ backpressure snapshot ไม่ส่ง artifact body หรือ full event output; เมื่อเปิด task UI ขอ `/api/tasks/<task_id>` เพื่ออ่าน evidence และ output ของ task นั้น และจะขอใหม่เมื่อ `updated_at` เปลี่ยน UI แสดง event ล่าสุด 1,000 รายการ แต่ event เก่ายังอยู่ใน database การ disconnect browser ไม่ยกเลิก task และเมื่อเชื่อมใหม่ในหน้าเดิมจะอ่านต่อจาก cursor เดิม

ถ้า Runtime restart งานที่ active/รอ input/approval/quota จะเป็น BLOCKED และ revoke attempt เดิม ไม่ replay side effects หรือ resume จำลองเงียบ ๆ ผู้ใช้ต้อง Retry เอง งาน QUEUED ยังคงรอ dispatch ตาม pause state เดิม

เมื่อเปิด launch link ครั้งแรก UI ส่ง bearer ไป `POST /api/session` แล้วลบ bearer ออกจาก memory หลังสำเร็จ server ออก **HttpOnly, SameSite=Strict session cookie** แยกจาก launch token; cookie มี Path `/api/` และชื่อผูก port เพื่อไม่ชน instance อีก port ไม่มี token ใน localStorage/sessionStorage Refresh และเปิด tab ใหม่บน origin เดิมใช้ session ได้จน browser session สิ้นสุดหรือ Runtime restart (browser บางตัว restore session cookie เมื่อเปิดใหม่ แต่ cookie เดิมใช้กับ Runtime ที่ restart ไม่ได้) หลัง restart ให้เปิด launch link เต็มอีกครั้งจาก terminal หรือ `launch.url` ใน state dir ถ้า network connection ล้ม UI แสดง stale-state warning และปิดปุ่มควบคุม

## Local authorization boundary

- HTTP bind `127.0.0.1` เท่านั้น; ไม่มี remote listener หรือ proxy endpoint
- API ทั้งอ่านและเขียนต้องมี per-launch random bearer token หรือ browser session cookie ของ instance ปัจจุบัน; session bootstrap ต้องใช้ bearer และ exact Origin, cookie อย่างเดียว bootstrap ไม่ได้
- Host ต้องตรง `127.0.0.1:<port>`; ป้องกัน DNS rebinding
- POST ต้องมี exact same Origin และ JSON content type; ไม่มี permissive CORS
- ขนาด request ไม่เกิน 16 KiB; task/project/text มีขีดจำกัด
- Static assets เป็น allowlist และมี CSP, no-store, no-referrer, frame-ancestors none
- State dir `0700`, DB/launch file `0600`, advisory process lock ป้องกันสอง instance
- ไม่มี endpoint สำหรับ shell, file access, push, merge หรือ deploy

Boundary นี้เป็น local single-user GUI foundation ไม่ได้พิสูจน์ production authentication ของ agent sockets เมื่อเพิ่ม sandbox/agent processes ต้องซ่อน control socket/transport จาก attempt และทำ authorization ตาม MVP Contract ห้ามเปิด remote ด้วยการแก้ bind addressเฉย ๆ

## รายการ UI ที่ปรับและขอบเขตที่ยังรอ runner จริง

| รายการ | รุ่นนี้ทำได้ / ข้อจำกัด |
| --- | --- |
| Diff และ policy ต่อไฟล์ | เตรียม viewer สำหรับ artifact `kind=diff`: full patch พร้อมรายการ `files` ที่มี `path`, `out_of_scope`, `protected`; unknown ไม่ถูกแสดงเป็น safe รุ่น simulation ไม่มี patch จริงหรือ REVIEW gate |
| ส่งต่องาน | เลือกงานต้นทางจาก dropdown และ Continue task ได้ใน simulation; Claude/Codex buttons disabled เพราะยังไม่มี adapters |
| เหตุผลรอคิว | snapshot ส่งเหตุผล paused, scope พร้อม task ที่บล็อก, slot เต็ม, ready และ cooldown; UI เปิด blocking task ได้ |
| Output / prompt | แสดง full artifacts `kind=agent_log` / `kind=prompt` เมื่อ Runtime ส่งมา; รุ่นนี้ไม่มีไฟล์เหล่านี้ จึงแสดง runtime messages และ task instructions พร้อมบอกว่าไม่ใช่ model output/prompt |
| ผลและ merge | Copy full result; Copy merge command แสดงเฉพาะ real-mode completed task ที่ส่ง `result_ref` เป็น `refs/navis/attempts/...` แบบไม่มี shell metacharacters ไม่มี endpoint execute/merge และ simulation ไม่สร้าง ref |
| Quota | Countdown ใน task/card และ fake-agent row; แยก task cooldown จาก provider cooldown จริงที่ยังไม่มีข้อมูล |
| Resources | Slot และ active attempts จาก snapshot; RAM เป็น Not measured ไม่แสดงค่าที่เดา |
| Add project | ซ่อนเมื่อ snapshot mode เป็น real; simulation ยังใช้ได้ |
| Stop/Kill | Native confirmation dialog, Cancel ไม่ส่ง command, ยึด observed attempt |
| Event | filter task/type และเปิด full `output` ถ้า event มี field นี้; simulation ยังไม่มี prepare/check stdout จริง |
| Real runtime controls | Banner เปลี่ยนตาม mode; REVIEW เปิด diff โดยตรงและแสดง approval; WAITING_INPUT แสดง input หรือแจ้งเมื่อ runtime ยังไม่ส่ง prompt; handoff เปิดเมื่อ `capabilities.handoff` ระบุพร้อมใช้งาน |
| Provider/resource/settings | Agents อ่าน `providers` และ `cooldown_until`; Resources อ่าน `attempt.memory_bytes` หรือ `resources.attempt_memory_bytes`; Settings อ่าน `settings.editable/items` และส่ง `update_settings` เมื่อ runtime รองรับ |
| Project setup | Add project เปิดใน real mode พร้อม path field และส่ง `create_project`; Runtime เป็นผู้ตรวจสิทธิ์และจัดเก็บ path |
| Attention | Tab title แสดงจำนวน pending requests; browser notification เป็น opt-in ใช้เมื่อแท็บอยู่เบื้องหลังและยังเปิดอยู่ ไม่ทำ background/service-worker notifications และบาง mobile browser ไม่รองรับ |
| Refresh | HttpOnly session cookie; Runtime restart หมุนทั้ง bearer/session และต้องเปิด launch link ใหม่ |

Task board แสดง 12 cards ต่อ column ก่อนและมี Show more; Activity แสดง 100 events ก่อน (ถือไว้ไม่เกิน 1,000) เพื่อลดจำนวน DOM พร้อมกัน หน้าจอมือถือมี navigation แบบเลื่อนแนวนอน, responsive panels, touch targets, skip link, live announcements และ task-evidence tabs ใช้ arrow-key navigation. ยังไม่ได้ตรวจ rendering, keyboard/screen-reader กับ browser จริง หรือทำ performance benchmark ของ task จำนวนมาก. Runtime รุ่นนี้ยังเป็น simulation จึงไม่มี agent log, provider prompt, real cgroup samples, real handoff หรือ config writer; UI จะแสดง unavailable/error ตามความสามารถที่ runtime รายงานและไม่สร้างค่า telemetry เอง

## ทดสอบ

Core/transport/startup tests ใช้ standard library:

```bash
python3 -m unittest discover -s tests -v
node --check navis/web/app.js
node tests/test-ui.cjs
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

Test นี้เปิด instance ด้วย temp state ของตัวเองแล้วทดสอบ reload/session, approval/input/stop/retry/kill และ confirmation cancellation, artifacts, search, projects, escaping, mobile form และ disconnect; ไม่แตะ state ปกติหรือ CLI account จริง `NAVIS_SCREENSHOT=/absolute/path/control-room.png` เป็น optional screenshot output

GitHub Actions รัน unittest, JS syntax, pure UI rendering/control checks และ package installation บน Python 3.11/3.12/3.13; ไม่ได้รัน browser test หรือ provider probes

ผลตรวจใน workspace วันที่ 2026-10-06: unittest 21 กรณีผ่าน, JS syntax และ pure UI rendering/control checks ผ่าน (full patch/result escaping, classification labels, captured confirmation/source attempt, Cancel ไม่ส่ง command) รุ่นก่อนตรวจ package installation ผ่านแล้ว; รุ่นนี้เปลี่ยน web assets และ stdlib code โดยไม่มี dependency ใหม่ Browser test **ยังไม่ยืนยัน** ตามที่ผู้ใช้เลือกข้าม localhost/browser check ไม่มีการอ้างว่า UI rendering/mobile interaction, accessibility หรือ performance ผ่านแล้ว

## ขั้นต่อไปที่ต้องทำก่อนใช้ AI จริง

1. ทำ fake-agent CLI + adapter interface, lease/action reconciliation และ full acceptance scenarios
2. เชื่อม project TOML config, isolated attempt clone, sandbox, cgroup และ checks
3. พิสูจน์ Stop/Kill กับ process tree รวม orphan; scope enforcement และ secret redaction
4. เปลี่ยน simulation model เป็น Runtime commands/snapshots ที่ authenticated ตามสัญญาเดิม
5. ทำ Codex/Claude/local backend probes ตาม Execution Design §10 หลัง fake runner ผ่าน
6. เพิ่ม immutable Git diff, exact-commit verifier evidence และ UI controls ที่ runner รองรับ

ไม่มีการใช้ provider quota หรือแก้ไฟล์ PROJECT_VELA เพื่อสร้าง GUI รุ่นนี้
