# Phase 4 — Local coding agent (optional role)

วันที่วัด: 2026-10-06 · Ollama + `qwen2.5-coder:7b` (Q4, 4.4 GB) บน GTX 1660 Ti 6 GB · ผลมาจากการรันจริงผ่าน Runner

## สถานะโดยย่อ

**กลไกพร้อมและทดสอบแล้ว แต่คุณภาพของโมเดล 7B ยังไม่ผ่านเกณฑ์ใช้งานจริง จึงแนะนำให้ปิดบทบาทนี้ไว้ (ค่าเริ่มต้นคือปิด)** ตามที่ D-004 ระบุไว้: เปิด local coding ได้ก็ต่อเมื่อ Agent Runner ผ่าน test *และ* ผู้ใช้อนุญาตบทบาทนั้น — ข้อแรกผ่านแล้ว ข้อหลังคือสวิตช์ `[local] coding = true` ที่ผู้ใช้ตัดสินเอง

## ที่สร้าง

`navis/local_agent.py` เป็น agent process แบบ `python -m navis.local_agent` ที่รัน **ใน sandbox และ cgroup เดียวกับ Codex/Claude** จึงใช้ Stop/Kill, recovery, credential scan, usage accounting เดิมได้โดยไม่เขียนซ้ำ (adapter `local` ใน `runtime.py`)
- **Model backend แยกจาก Agent Runner:** โมเดลอยู่หลัง Ollama บน loopback เท่านั้น (ปฏิเสธ URL อื่น ไม่มี fail over ไป cloud); Runner คือโค้ดของเราที่ควบคุม tool loop
- **Tools:** `list_files`, `read_file`, `write_file`, `replace_in_file`, `run_check`, `report_result`, `ask_user`, `delegate` — ไม่มี shell ไม่มีเน็ต; รันคำสั่งได้เฉพาะ `run_check` ที่ project ตั้งไว้ ผ่าน MCP socket ของ attempt
- **อ่านคำสั่งของโมเดล:** `qwen2.5-coder:7b` ใน Ollama **ไม่ส่ง `tool_calls` แบบโครงสร้าง** แต่พิมพ์ JSON เป็นข้อความ (และบางครั้งยัดหลายคำสั่งในข้อความเดียวก่อนเห็นผลคำสั่งแรก) Runner จึงแกะ JSON จากข้อความ (รวม code fence/ข้อความแทรก/รูปแบบ structured), ตรวจ schema ทุกครั้ง และรัน **เพียงคำสั่งแรกต่อข้อความ** — ยืนยันข้อความใน MVP Contract ว่า tool-calling ไม่เท่ากับ coding-agent
- **สวิตช์บทบาท:** `[local] coding = true` ใน `config.toml` (ปิดเป็นค่าเริ่มต้น; `add_task` ปฏิเสธ agent `local` ถ้าปิด; GUI แสดง "Local coding is off")
- ใช้เป็น reviewer แบบอ่านอย่างเดียวได้ด้วย (ไม่มี write tools)

## เกณฑ์ MVP Contract ก่อนเปิดบทบาท → evidence

| เกณฑ์ | Evidence (`tests/test_local_agent.py`) |
| --- | --- |
| Tool permissions / workspace | `test_nothing_outside_the_workspace_or_in_dot_git_is_reachable` (`../`, absolute, symlink ไฟล์/โฟลเดอร์, `.git`, `a/../..`); `test_boundary_violations_by_the_model_are_denied_and_leave_nothing_on_the_host` (ผ่านทั้ง sandbox จริง, ไม่มีไฟล์บน host); `test_read_only_role_has_no_write_tools` |
| Invalid-tool-call handling | `test_invalid_calls_are_fed_back_then_stop_the_run` (tool ไม่มี, args ขาด/ผิดชนิด, JSON พัง → ส่งข้อความผิดพลาดกลับให้โมเดล, ครบ 5 ครั้งหยุดแบบ failed); `Parsing.*` |
| Loop limits | turn limit (`max_turns`), คำสั่งซ้ำเดิม 3 ครั้ง, ตอบโดยไม่เรียก tool 3 ครั้ง, `num_predict` จำกัดความยาวต่อรอบ (เจอจริง: ไม่มีเพดานนี้โมเดลวนเขียนซ้ำจนหมดเวลา 600 s), จำกัดการเขียน 50 ไฟล์/100 KB, ตัด output เก่าเมื่อบทสนทนายาว |
| Cancellation | `test_stop_cancels_a_slow_model_and_leaves_no_process` (cgroup ฆ่าทั้ง tree ใน < 15 s) |
| Recovery | `test_a_runner_crash_mid_run_is_recovered_and_the_late_result_is_rejected` |
| Failure ที่ไม่ถูก retry วน | โมเดลล่ม/ไม่ตอบ/URL ไม่ใช่ loopback → รายงาน `failed` ชัดเจน ไม่ใช่ crash (`test_an_unreachable_model_is_a_clean_failure`, `test_a_remote_model_url_is_refused_local_only`) |

## ผลวัดคุณภาพ (`probes/bench.py --configs local,local+review`; ชุดเดียวกับ Phase 3)

| งาน | Local 7B | Local → Claude รีวิว → Local แก้ 1 รอบ | (เทียบ) Claude / Codex เดี่ยว |
| --- | --- | --- | --- |
| slugify | 11/12 (พลาด `a---b___c`: ถือ `_` เป็นตัวอักษร) | 11/12 — รีวิวบอก changes แต่แก้ไม่หาย | 12/12 |
| parse_duration | **ไม่มีผล**: ถามผู้ใช้ซ้ำจนติด `WAITING_INPUT` | เหมือนกัน | 7/7 |
| merge_intervals | 6/18 (พลาด adjacent, mutation, คืน tuple) | 6/18 — แก้ไม่ดีขึ้น | 11/11 |

เวลา 8–16 s ต่อ attempt (เมื่อจบ), input 3k–10k tokens, ไม่มีค่าใช้จ่าย cloud; ถ้ามี Claude รีวิว ใช้ ~$0.02–0.03 ต่อรอบและเวลา ~30 s
**ไม่มีงานใดผ่านครบทั้งสามงาน** และรอบ revision ที่ Claude รีวิวไม่ช่วย (โมเดลฟังข้อเสนอแต่แก้ไม่ถูก) ตัวอย่างเล็ก (3 งาน × 1 รอบ) แต่ช่องว่างกับ cloud ใหญ่พอจะสรุปทิศทางได้: **โมเดล 7B ในเครื่องนี้ไม่เหมาะเป็น coder อัตโนมัติ**

การปรับเกราะที่เกิดจากการวัด (ไม่ใช่การจูนให้ผ่าน benchmark): ตีกลับคำถามขอยืนยัน 3 ครั้งก่อนส่งถึงผู้ใช้ (โมเดลถามว่า "ควรสร้างไฟล์ไหม?" ทั้งที่งานบอกชัดแล้ว), จำกัดความยาวต่อรอบ

## การใช้ GPU (6 GB)

ค่าเริ่มต้นของ Ollama วางโมเดลแบบ CPU/GPU 15%/85% ทั้งที่ VRAM ว่างเหลือ ~1.4 GB (CPU 720% GPU ~50% เพราะ GPU ต้องรอ layer บน CPU) แก้โดย
1. `OLLAMA_FLASH_ATTENTION=1` + `OLLAMA_KV_CACHE_TYPE=q8_0` (KV cache เล็กลง) — ตั้งผ่าน systemd drop-in `~/.config/systemd/user/ollama.service.d/navis-gpu.conf` (ลบไฟล์เดียวเพื่อย้อนกลับ; service นี้ใช้ร่วมกับ PROJECT_VELA)
2. `[local] num_gpu = 99` บังคับให้ทุก layer ขึ้น GPU: `100% GPU`, 4.8 GB, **47 tok/s เทียบกับ 28 tok/s** (+67%)
ค่า `num_gpu` ใน `config.toml` ของผู้ใช้ยังเป็น 0 (ให้ Ollama ตัดสินใจ); benchmark ตั้ง 99 ให้เอง บนเครื่องที่ VRAM น้อยกว่านี้ควรคงเป็น 0

## ข้อจำกัด

- ผลวัดเป็นของโมเดลเดียว (`qwen2.5-coder:7b`) ไม่ได้ลองโมเดลอื่นหรือ quantization อื่น และ VRAM 6 GB จำกัดขนาดโมเดล
- ไม่มี streaming/ยกเลิกกลางคำตอบของโมเดล (ยกเลิกด้วยการฆ่า process ทั้ง tree) และไม่มี resume บทสนทนา (กู้คืนต่อจาก git snapshot ของ Runner)
- Local helper ที่สรุป log (`navis-cli summarize`) กับ local coding ใช้ GPU ตัวเดียวกัน ยังไม่มีการจองคิว GPU ระหว่างกัน (slot `local` = 1 กันเฉพาะ coding ด้วยกันเอง)
- เพดานบริบท 8192 tokens กับงานที่ต้องอ่านไฟล์ใหญ่จะตัด output เก่าทิ้ง

## คำแนะนำ

คง `coding = false`; ใช้ local model เป็น helper สรุป/วิเคราะห์ log ตาม D-004 เดิม และถ้าอยากทดลอง local coding ให้ใช้กับงานเล็กที่มี check ชัดเจนและมี reviewer cloud ตรวจเสมอ (`require_review`) ก่อนเชื่อผล
