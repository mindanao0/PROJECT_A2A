# MVP Contract — Proposed Acceptance Criteria

> ขอบเขตที่ยืนยันแล้วอยู่ใน [Confirmed Decisions](DECISIONS.md) เอกสารนี้เป็นข้อเสนอ implementation/acceptance เพื่อปิดจุดบอดก่อนสร้างระบบ ไม่ใช่รายงานผลทดสอบ

## 1. MVP boundary

- Linux, CLI/session ที่ Runtime จัดการ, UI บนเครื่องเดียว
- Cloud coding agent อ่าน/แก้โค้ด/ทดสอบใน assigned workspace ตามสิทธิ์ที่บังคับใช้จริง
- Local helper รับข้อความ context/log ที่ผ่าน policy แล้ว และคืน summary/analysis
- ไม่มี remote control, web-chat takeover, local coding หรือ autonomous push/merge/deploy ใน MVP
- Core language, UI technology, transport, storage และ sandbox implementation ยังเปิดอยู่

## 2. Adapter feasibility matrix

เก็บผลทดลองราย backend/version ใน Phase 0; unknown ไม่ถือว่า supported

| Capability | Codex | Claude Code | Local helper |
| --- | --- | --- | --- |
| Start และบันทึก session identity | ผ่าน: `thread.started.thread_id` (codex-cli 0.160.1, 2026-10-06) | ผ่าน: `session_id` ใน init event (claude 2.1.291, 2026-10-06) | ไม่ต้องมี session: เรียก Ollama `/api/chat` แบบ stateless (2026-10-06) |
| ส่งงานใหม่และรับผลแบบ structured | ผ่าน: `probes/adapter.py codex` ใน attempt sandbox แก้ไฟล์ → `run_check` → `report_result` → verifier → COMPLETED (16–21 s) ต้อง pre-approve MCP ของ navis เพราะ `exec` ไม่ขออนุมัติ | ผ่าน: `probes/adapter.py claude` เหมือนกัน (7–9 s) | ผ่าน: `navis-cli summarize` กับ `qwen2.5-coder:7b` คืนข้อความพร้อม ref `[event:N]` ที่ Runtime ตรวจกับ sources (2026-10-06); structured = ref ตรวจได้ ไม่ใช่ JSON schema |
| Streaming และ final-result detection | JSONL (`turn.completed`) แต่ Runner ตัดสินจาก `report_result`/exit code ไม่ parse stream | stream-json (`result`) เช่นเดียวกัน | Not tested |
| ส่งข้อความขณะกำลังรัน | ไม่รองรับใน `exec`; Runner ใช้ attempt ใหม่แทน | ไม่รองรับใน `-p`; Runner ใช้ attempt ใหม่แทน | Not tested |
| Interrupt turn / terminate process tree | ผ่าน: `probes/adapter.py codex stop` ระหว่างคำสั่งที่มี orphan หนีด้วย `setsid` — Stop แล้ว CANCELLED ใน 0.3 s, ก่อน Stop มี 9 process หลัง Stop เหลือ 0, scope inactive; `codex recover` (runner ตาย → runner ใหม่ `recover()`): task กลับ QUEUED, attempt `interrupted`, late result ถูกปฏิเสธ, ไม่มี process ค้าง (2026-10-06) | ผ่าน: `claude stop` ระหว่าง generate (0.2 s, 4 process → 0) และ `claude recover` ผลเหมือนกัน; Interrupt แบบ "turn" ไม่มี ใช้การฆ่า tree | Not tested |
| Resume session หลัง interrupt/restart | ผ่าน: kill -9 หลัง `thread.started` แล้ว `codex exec resume <id>` จำบริบทได้ | บางส่วน: resume หลัง session จบได้; ถ้า kill ก่อน session ถูกบันทึก (ทันทีหลัง init) → "No conversation found" Runner ไม่พึ่ง session ของ provider (ต่อจาก git snapshot) | Not tested |
| Approval hook และ execution boundary | Partial: `codex sandbox -P :workspace` (0.160.1) บล็อกการเขียนนอก workspace และเน็ต แต่คำสั่งอ่าน auth ของตัวเองได้; `codex exec` ผ่าน boundary probe (`probes/adapter.py codex escape`, 2026-10-06): คำสั่งของ agent ออกเน็ตไม่ได้ (curl exit 6), อ่าน credential ของ agent อื่น/state ของ Runtime/project checkout/`~/.ssh`/docker.sock/user dbus ไม่ได้; เขียน `$HOME` ล้มและเขียน `/tmp` สำเร็จแต่ลง tmpfs ส่วนตัว ไม่มีไฟล์บน host | ผ่านบางส่วน: init event แสดง tools เพียง Edit, Glob, Grep, Read, Write + MCP ของ navis (ไม่มี Bash/web/Cron/RemoteTrigger) ด้วย `--tools` แบบ default-deny; ผ่าน boundary probe (`probes/adapter.py claude escape`): Read ของ credential ของ agent อื่น/state ของ Runtime/project checkout/`~/.ssh` ได้ "File does not exist"; **Write ของ Claude เขียนนอก workspace ได้ในเลเยอร์ permission ของมันเอง** (`$HOME`, `/tmp`, `../`) ปลอดภัยเพราะลง tmpfs ส่วนตัวของ bwrap ไม่มีไฟล์บน host จึงห้ามพึ่ง permission ของ CLI เป็น boundary; ยังไม่ได้ทดสอบว่า Read อ่าน credential ของตัวเองได้ (limitation เดิมใน §3) | ไม่มี write/exec tools ตามขอบเขต MVP |
| Usage/rate-limit visibility | token ใน `turn.completed.usage` (~59k input/งานสั้น); ข้อความ rate limit จริงยังไม่เคยเกิด | `total_cost_usd`, usage และ `rate_limit_event` ใน stream; ข้อความ rate limit จริงยังไม่เคยเกิด (`QUOTA_RE` ยังเป็น pattern ทั่วไป) | Not tested |

สำหรับแต่ละช่อง บันทึก interface, backend/model version, test command, expected/observed result, evidence reference, limitation และวันที่
เลือกหนึ่ง local backend ก่อน; ไม่ต้องพิสูจน์ Ollama, llama.cpp และ LM Studio ทั้งหมดพร้อมกัน

แยก Model Backend ที่ทำ inference ออกจาก Agent Runner ที่จัดการ tool loop, policy, history และผลของเครื่องมือ
ห้ามถือว่า tool-calling support เท่ากับ coding-agent support

## 3. Execution boundaries

การออกแบบที่ implement ได้และผล probe อยู่ใน [Execution Design](EXECUTION_DESIGN.md)

- ใช้ clone ต่อ attempt แทน worktree เพราะ worktree แชร์ `.git/config` และ `.git/hooks` กับ checkout หลัก
- Process ของ agent CLI ออกเน็ตไป provider ได้ แต่คำสั่งที่ agent รันต้องไม่มีเน็ต
- ทุก sandbox ซ่อน host sockets (`/run`): read-only mount ไม่กัน `connect()` ไป docker/dbus socket
- ระบุ enforcement ของ filesystem, network, process tree และ credential exposure ให้ตรวจสอบได้
- Prompt, trust label หรือ cwd อย่างเดียวไม่ถือว่าเป็นการจำกัดสิทธิ์
- Backend ที่บังคับขอบเขตที่ต้องการไม่ได้ ต้องปฏิเสธโหมดเขียนและแจ้ง limitation; ห้ามเปลี่ยนเป็น unrestricted execution เงียบ ๆ
- Parent policy ใช้กับ provider-native subagents ด้วย; ถ้าพิสูจน์การครอบคลุมไม่ได้ให้ปิด native delegation สำหรับโหมดนั้น
- Repo instructions/config เป็นข้อมูลของ project ไม่สามารถเพิ่ม runtime permissions เองได้
- Local helper ไม่มี write/exec/network tools และไม่รับ cloud credentials; log/context ต้องผ่าน redaction และ routing policy
- การติดตั้ง dependency, network access และ side effects นอก workspace ต้องมี policy แยก ไม่อนุมานจากสิทธิ์รันทดสอบ
- Test execution เองต้องอยู่ใน execution boundary เพราะ repo scripts อาจทำ side effects
- จัดสรร port, temporary directory, test database/container namespace ต่อ attempt เมื่อ task ต้องใช้
- Git operation ที่กระทบ shared refs/config ต้องผ่าน Runtime; ownership ของไฟล์อย่างเดียวไม่เพียงพอ

## 4. Lifecycle and durable state

แยก task, attempt, provider session, turn และ action identity
Retry/reassign สร้าง attempt ใหม่ และเก็บหลักฐาน attempt เดิม

ข้อเสนอ task states:

```text
NEW -> QUEUED -> ASSIGNED -> RUNNING -> REVIEW -> VERIFY -> COMPLETED
RUNNING -> WAITING_INPUT | WAITING_APPROVAL | WAITING_QUOTA | BLOCKED | FAILED | CANCELLING
WAITING_QUOTA -> QUEUED (after provider cooldown; does not count as retry)
CANCELLING -> CANCELLED
FAILED -> QUEUED (new attempt, only after retry checks)
VERIFY -> RUNNING (new attempt for fixes) | FAILED
```

Solo/read-only/helper task อาจข้าม REVIEW ตาม task policy แต่ต้องตรวจ output/acceptance ของงานก่อน COMPLETED
การ skip VERIFY สำหรับงานใดต้องมี policy ชัดเจน; verifier ไม่จำเป็นต้องเป็น coding tests ทุกงาน

- Runtime เป็นผู้ยืนยัน transitions; agent result หรือ DECISION เป็น proposal ไม่ใช่สิทธิ์เปลี่ยนสถานะเอง
- Event envelope มี schema_version, event_id, project_id, task_id, attempt_id, producer sequence และ correlation/causation IDs
- Runtime ผูก producer identity กับ adapter connection; ไม่เชื่อค่า from ที่ model เขียนเอง
- State update และ event ต้องบันทึกแบบ atomic ตาม storage ที่เลือก; deduplicate event และปฏิเสธผลจาก attempt ที่หมดสิทธิ์แล้ว
- มี heartbeat/lease เพื่อไม่ให้ worker สองตัวถือ attempt เดียวกันหลัง restart/reassign
- บันทึก action intent ก่อน side effect พร้อม idempotency key และ observation ของผล
- หาก crash ระหว่าง side effect กับการบันทึกผล ให้สถานะ outcome_unknown; ตรวจสภาพจริงหรือถามผู้ใช้ก่อน retry
- Event replay กู้ state; ไม่รัน shell/push/merge/deploy ซ้ำ
- Session resume เปิดบทสนทนาต่อ ไม่รับประกันว่าคำสั่งเดิมยังรันหรือถูกย้อนกลับ
- Approval ผูกกับ action/attempt, scope, payload hash และ expiry; เมื่อ payload เปลี่ยนต้องประเมินใหม่
- Queue มีขนาดจำกัดและ backpressure; durable events ต้องไม่หายเพราะ UI อ่านช้า
- Raw provider events เป็นหลักฐาน debug ตาม retention policy ไม่ใช่ canonical task state

## 5. User controls

| Control | ผลที่เสนอ |
| --- | --- |
| Pause | หยุด dispatch งาน/turn ใหม่; งานที่กำลังรันยังทำต่อ และ UI ต้องแสดงความจริง |
| Resume | เปิด dispatch ต่อเมื่อ policy และสถานะ attempt ยังอนุญาต |
| Stop | ขอ interrupt, ป้องกันงานใหม่ของ task และรอการยืนยันว่าหยุด |
| Kill | ยุติ process tree ที่ Runtime เป็นเจ้าของและตรวจว่าไม่มีงานลูกค้าง |
| Reassign | ยุติ/revoke attempt เดิมก่อนสร้าง attempt ใหม่; ไม่รับผลเก่ามารวม |
| Add instruction | version คำสั่งใหม่; adapter ระบุว่าใช้ทันทีได้หรือรอ turn ถัดไป |
| Rollback | คืนผลใน managed workspace ตาม snapshot/commit ที่ระบุ; ไม่รับประกันย้อน network/database/deploy |

Cancel task ต้อง propagate ไป dependent/child work ตาม policy และเก็บไฟล์ที่แก้ค้างไว้ให้ตรวจได้
ห้าม UI แสดง stopped จน backend/process observation ยืนยัน; stop timeout ต้องเสนอ Kill หรือแสดง unresolved state

## 6. Context, artifacts and verification

- Artifact reference ผูก project และ immutable commit/content hash; path อย่างเดียวใช้เป็น locator ได้แต่ไม่ใช่ version identity
- Pin task requirement version, base commit, relevant instruction sources และ context fingerprint
- Summary มี source refs/version และ invalidation rule; แยกข้อเท็จจริงกับ inference
- เมื่อ session ใหม่/resume ไม่สามารถยืนยันว่ามี context เดิม ให้ส่ง baseline ที่จำเป็นก่อน delta
- Broker ลดข้อความที่ส่งซ้ำได้ แต่ไม่รับประกัน shared provider cache หรือไม่คิด token กับ session history
- มี project/file routing policy เช่น local-only และ cloud-allowed; ห้าม fail over จาก local-only ไป cloud
- Offline ต้องปิด network ที่ execution boundary และตรวจ backend ว่าใช้ local model จริง
- Reviewer เห็น requirement version + immutable diff + verifier evidence; blind review ใช้ session/context ที่ไม่ปน reasoning ของ implementer
- Review/test evidence ผูก exact commit, commands, exit status และ environment/version
- Agent report success ไม่ใช่ verifier result; test/config changes ต้องมองเห็นได้ และ acceptance สำคัญไม่ควรถูกแก้ให้ผ่านโดย implementer ฝ่ายเดียว
- Rebase/merge หรือ diff เปลี่ยนทำให้หลักฐานเดิม stale; ตรวจ integration commit สุดท้ายก่อนตัดสิน completion/merge ตาม policy
- Event/artifact/log retention, redaction และ cleanup ต้องไม่ลบ evidence ของ active task

## 7. Local UI and future remote boundary

- UI รุ่นแรกแสดง task, attempt/backend, current activity, diff/result, pending input/approval และ controls
- การ disconnect UI ไม่ใช่ cancel task; reconnect อ่าน snapshot และ events ต่อจาก cursor
- Core มี authorization boundary สำหรับคำสั่งควบคุม; local transport ต้องจำกัด client ที่เข้าถึงได้
- ถ้าใช้ HTTP/WebSocket ให้ bind loopback พร้อม client authentication และตรวจ Origin/CSRF ตาม transport ที่เลือก; loopback อย่างเดียวไม่ถือว่า authenticated
- ถ้าใช้ Unix socket ให้กำหนด filesystem permissions และ peer/client identity
- Remote listener ปิดโดย default; การเปิดต้องมี authentication, authorization, secure transport และ session revocation ก่อน
- ไม่ expose provider app-server, local LLM endpoint หรือ shell endpoint ตรงออก network
- การเตรียม boundary ไม่ได้อนุมัติการเปิด remote ใน MVP

## 8. Acceptance scenarios

| Scenario | เกณฑ์ผ่านที่เสนอ |
| --- | --- |
| Single-agent coding | อ่าน/แก้/ทดสอบใน workspace ได้ และ completion อ้างหลักฐานจริง |
| Boundary escape | ทดสอบเขียนนอก workspace, unauthorized network และ repo-config escalation แล้วถูกบล็อก |
| Local helper | สรุปพร้อม source refs/วิเคราะห์ log ได้ โดยไม่มี write/exec tools หรือ credentials |
| Stop/Kill | หยุดงานที่มี child command ได้ตามนิยาม; ไม่มี process ที่ยังเขียน workspace หลังยืนยัน stopped |
| Crash/restart | กู้ task/attempt ได้ ไม่ duplicate worker และไม่ replay side effects |
| Unknown outcome | crash หลัง side effect ก่อนบันทึกผล: Phase 1 requeue ได้ เพราะ side effect นอก attempt clone จำกัดที่ `refs/navis/attempts/<id>` ซึ่งเขียนซ้ำได้ ไม่ replay และไม่มี duplicate worker; เมื่อเพิ่ม effect ภายนอก (push/merge) ต้องเข้า reconciliation ไม่ retry อัตโนมัติ |
| Approval race | approval ของ payload/attempt เก่าใช้กับงานใหม่ไม่ได้ |
| Two-agent collaboration | workspace/resource แยก; reviewer ตรวจ version ที่ถูกต้อง; integration tests ตรวจ final commit |
| Stale context/result | เปลี่ยน commit/instruction แล้ว invalidate context/evidence และปฏิเสธ late result |
| UI disconnect | Runtime ทำงานตาม policy ต่อ และ UI reconnect เห็นสถานะที่ถูกต้อง |
| Local/remote boundary | local unauthorized client ถูกปฏิเสธ; remote listener ยังไม่เปิด |
| Host socket escape | จาก attempt sandbox เข้าถึง docker socket, user dbus และ control socket ของ Runtime ไม่ได้ |
| Credential leak | token ของ agent ที่ปรากฏใน diff/artifact/message ถูก block ก่อนส่งต่อ |
| Quota limit | rate limit → WAITING_QUOTA ไม่เผา retry และกลับมาทำต่อหลัง cooldown |
| Scope overlap / duplicate | task ที่ scope ทับกันไม่รันพร้อมกัน; task key ซ้ำไม่สร้างงานใหม่ |

ทุก scenario รันกับ `fake-agent` ก่อน แล้วจึงรัน contract probes สั้น ๆ กับ CLI จริง
Phase 0 ต้องให้ evidence ของ adapter ก่อนกล่าวว่า supported
Phase 1 ต้องผ่าน single-agent/boundary/control/recovery/UI cases ที่เกี่ยวข้องก่อนเพิ่ม collaboration
Local coding ต้องมี Agent Runner ที่ผ่าน tool permissions, invalid-tool-call handling, loop limits, cancellation, recovery และ workspace tests ก่อนเปิดบทบาทนั้น
