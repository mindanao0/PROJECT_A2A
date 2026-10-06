# Initial Roadmap

> ขอบเขต MVP ยืนยันแล้วใน [Confirmed Decisions](DECISIONS.md); implementation และเกณฑ์ผ่านด้านล่างยังเป็นข้อเสนอ รายละเอียดอยู่ใน [MVP Contract](MVP_CONTRACT.md)

## Phase 0 — Linux boundary feasibility (ไม่ใช้ quota)

Boundary probes: `probes/boundary.sh` (ผ่านแล้ว 2026-10-06)
สร้าง `fake-agent` ก่อน adapter จริง เพื่อให้ acceptance scenarios ทดสอบได้โดยไม่ใช้ quota (D-013)
Core language: Python (D-012)
Exit: sandbox, cgroup และ git isolation ใช้งานได้บนเครื่องจริง

## GUI foundation ที่มีแล้ว (ยังไม่ปิด Phase 1)

`python3 -m navis` เปิด local control GUI พร้อม in-process simulated agent, SQLite snapshot/events, task board, user requests และ lifecycle controls ดู [GUI Guide](GUI.md) สำหรับผลทดสอบและข้อจำกัด

ยังไม่มี sandboxed fake-agent CLI, production Runner, MCP หรือ provider adapter; ไม่ถือว่า execution/boundary/process-tree acceptance scenarios ผ่านจากผลทดสอบ UI simulation

## Phase 1 — Single-agent MVP foundations

สร้าง daemon, project/agent registry, adapter interface, durable task/attempt state, CLI และ UI เล็กบนเครื่องเดียว

ก่อนให้ coding agent เขียนไฟล์ ต้องมี:
- assigned workspace และ execution boundary สำหรับไฟล์/process/network/secrets
- worktree/resource ownership และ shared Git operation controls
- scoped policy/approvals; repo config ยกระดับสิทธิ์ไม่ได้
- bounded queues, loop/timeout/retry limits
- Stop/Kill และ cancellation propagation
- crash reconciliation, action IDs และ stale-result rejection
- immutable artifact refs, deterministic context baseline และ verifier evidence
- local client authorization boundary; remote listener ปิด
- scope claim, task dedup, slot และ cgroup limits (D-008)
- WAITING_QUOTA และ provider cooldown (D-009)

UI แสดงงาน สถานะ backend ผลลัพธ์/diff สิ่งที่รอผู้ใช้ และปุ่มควบคุม
Local helper สรุป context/วิเคราะห์ log เท่านั้น ไม่มี write/exec tools
Exit: single-agent, boundary, controls, recovery และ local UI acceptance cases ผ่านกับ `fake-agent` พร้อม evidence

### Phase 1 evidence (`python3 -m pytest`, 65 ผ่าน, 2026-10-06; fake-agent ผ่าน runtime จริง: bwrap + systemd scope)

| Scenario (MVP_CONTRACT §8) | Evidence | สถานะ |
| --- | --- | --- |
| Single-agent coding | `test_done_task_is_verified_and_fetched` | ผ่าน |
| Boundary escape / host socket | `test_agent_cannot_reach_host_secrets_or_control_state`, `test_checks_have_no_network_or_host_sockets`, `test_hooks_and_config_planted_in_the_clone_never_run_on_the_host` (hook/fsmonitor ที่ agent วางใน clone รันได้เฉพาะใน sandbox), `probes/boundary.sh` | ผ่าน |
| Scope / protected paths | `test_edit_outside_scope_needs_review`, `test_protected_path_needs_review` | ผ่าน |
| Stop/Kill | `test_stop_kills_orphaned_processes` | ผ่าน |
| Crash/restart, late result | `test_runner_restart_requeues_and_rejects_stale_result` | ผ่าน |
| Approval race | `test_review_approval_is_bound_to_the_observed_attempt`, `test_stop_is_bound_to_the_observed_attempt` | ผ่าน |
| Credential leak | `test_credential_in_diff_blocks_fetch_and_is_redacted` | ผ่าน |
| Quota limit | `test_quota_waits_for_cooldown_without_using_a_retry` | ผ่าน |
| Scope overlap / duplicate | `test_overlapping_scopes_never_run_together`, `test_duplicate_task_is_not_queued` | ผ่าน |
| Local/remote boundary | `tests/test_server.py` (401/403, Origin, loopback only) | ผ่าน |
| UI disconnect | `tests/gui-smoke.cjs` | ผ่านเฉพาะ simulation |
| Stale context | `test_instruction_during_an_attempt_discards_its_result` (instruction เปลี่ยนระหว่างรัน → ทิ้งผล, รันใหม่โดยไม่เสีย retry), `test_task_stays_pinned_to_its_base_when_the_project_moves` (task ผูก base commit); stale integration commit เป็นงาน Phase 2 เพราะ Phase 1 ไม่ merge | ผ่าน (ขอบเขต Phase 1) |
| Unknown outcome | `test_crash_after_fetch_before_recording_is_rerun_once` (ผล fetch แล้วแต่ไม่ได้บันทึก → requeue, รันซ้ำครั้งเดียว, ไม่แตะ checkout ของ project); reconciliation เต็มรูปแบบเลื่อนไป Phase 2 ที่มี effect ภายนอก | ผ่าน (ตามเกณฑ์ที่แก้) |
| Local helper | `tests/test_helper.py` (4 เคส: อ้าง source ref และจับ ref ที่แต่งขึ้น, ไม่ส่ง tools/credentials, ปฏิเสธ URL ที่ไม่ใช่ loopback, ไม่ผ่าน proxy); ลองกับ Ollama `qwen2.5-coder:7b` จริงผ่าน `navis-cli summarize <id>` ใช้เวลา ~10 วินาที | ผ่าน (CLI เท่านั้น ยังไม่มีปุ่มใน GUI) |
| Two-agent collaboration | — | Phase 2 |
| cgroup MemoryMax | `test_process_over_the_memory_limit_is_killed_even_with_swap_available`; test นี้เจอว่า MemoryMax อย่างเดียวไม่เป็นเพดานจริงเมื่อมี swap (allocate 1.5 GB ใน limit 100M ยังรอด) จึงเพิ่ม `MemorySwapMax=0` | ผ่าน |

## Phase 1b — Real backend probes (ใช้ quota)

หลัง Phase 1 ผ่านกับ fake แล้วจึงรัน probes ใน [Execution Design](EXECUTION_DESIGN.md) §10 กับ Codex, Claude Code และ local backend หนึ่งตัว
ทดสอบ start, task/result, streaming, interrupt, resume, crash/restart, approval/enforcement และ usage visibility
เก็บ compatibility matrix พร้อมเวอร์ชัน, test commands และ evidence; capability ที่ไม่ผ่านให้ unsupported/limited ไม่จำลองว่ารองรับ
Exit: adapter จริงผ่าน acceptance scenarios ชุดเดียวกับ fake

### Phase 1b status (2026-10-06; codex-cli 0.160.1, claude 2.1.291)

ผ่าน: single-agent coding กับ Codex และ Claude จริงผ่าน Runner (`python3 probes/adapter.py codex|claude`), tool list ของ Claude ไม่มี Bash, resume ของ Codex หลัง kill -9, boundary escape กับทั้งสอง (`probes/adapter.py codex|claude escape`: อ่าน secret/state/checkout ไม่ได้, เน็ตของคำสั่งปิด, ไม่มีไฟล์เกิดบน host, canary ไม่รั่ว), Stop และ runner-crash recovery กลางงานกับทั้งสอง (`probes/adapter.py codex|claude stop|recover`: process tree หายหมดรวม orphan `setsid`, scope inactive, late result ถูกปฏิเสธ)
เจอจาก probe: `codex exec` ต้อง pre-approve MCP tools; Claude ต้องใช้ `--tools` เพื่อ default-deny; Claude session หายถ้า kill ก่อนบันทึก (Runner ไม่พึ่ง session ของ provider)
ยังไม่ผ่าน/ไม่ได้ทดสอบ: quota และ credential leak กับ CLI จริง (leak ไม่ได้ให้ agent จริงคัดลอก token จริงลง diff; ผ่านกับ fake-agent แล้ว), ข้อความ rate limit จริง (ไม่เผา quota เพื่อทดสอบ), local backend ใน matrix มีเฉพาะ summarize ไม่ใช่ coding

## Phase 2 — Two-agent collaboration and integration

เพิ่ม proposal/critique/delegate/review, task dependencies และ bounded conversation rounds
Codex implements -> Claude independently reviews -> verifier checks integration commit
สลับบทบาทได้ตาม capability ที่พิสูจน์แล้ว

เพิ่ม merge/integration queue, conflict handling และ rollback ของ managed workspace
Review/test ต้องผูก exact commit; rebase/merge แล้วต้องตรวจ final integration commit ใหม่
รายละเอียด local commit/merge authority ยังอยู่ใน OD-008; MVP ไม่ auto push/merge/deploy

Exit: สอง agent ไม่เขียน workspace/resource ชนกัน; late result และ stale evidence ไม่ถูกยอมรับ

### Phase 2 status

มีแล้ว: integration branch ตาม D-014 (`navis/integrate.py`): `navis-cli integrate <task>` รวมผล task ที่ COMPLETED บน `refs/navis/integration/<project>` ด้วย `git merge-tree` (ไม่แตะ working tree), รัน check ใน clone ของ commit ที่รวมแล้ว และเลื่อน ref ก็ต่อเมื่อผ่าน; `navis-cli integration <project>` ดูสถานะ; `navis-cli promote <project>` (หรือปุ่ม **Fast-forward** ใน GUI โหมด real และปุ่ม **Add to integration branch** ในรายละเอียดงาน) fast-forward branch ของผู้ใช้ โดยปฏิเสธเมื่อ working tree สกปรก, HEAD ไม่ใช่ branch, branch ขยับไปจาก integration, หรือไม่มี check ที่ผ่านบน commit นั้นพอดี และไม่รัน hooks
ยังไม่มี: task dependencies, `request_review`/`delegate`, review ที่ผูก exact commit, integration ข้ามหลาย project, rollback ของ integration branch (ลบ ref ด้วย git เอง)

## Phase 3 — Context and resource optimization

เพิ่ม Git-aware retrieval, conversation delta, versioned summaries, invalidation, bounded caches และ budgets
วัดเทียบ single-agent baseline: completion quality, retry/failure rate, elapsed time, context bytes และ provider usage เมื่อ expose
ไม่ถือว่า context fingerprint เท่ากับ provider cache hit
กำหนด retention/cleanup และ project scheduling fairness ตาม usage จริง

## Phase 4 — Optional local coding

สร้าง/ขยาย Agent Runner: tool loop, validation, permission enforcement, bounded turns, cancellation และ recovery
เปิด local coding หลังผ่าน tool/permissions/workspace acceptance tests และมีการอนุญาตบทบาทนั้น
ไม่บังคับให้ local helper เปลี่ยนเป็น coder เพื่อให้ MVP เสร็จ

## Phase 5 — Advanced orchestration and UI

เพิ่ม Team/Debate, dynamic scheduling, capability matching, adversarial review, multi-project scheduling และ A2A bridge เมื่อมี use case ที่พิสูจน์แล้ว
ค่อยขยาย UI/พิจารณา desktop wrapper; framework ยังไม่ล็อก

## Phase 6 — Remote control

เป็นงานในอนาคต ไม่อยู่ใน MVP
เพิ่ม authenticated clients, authorization, secure transport, revocation และ mobile-friendly UI
ทดสอบ remote boundary ก่อนเปิด listener; ไม่ expose provider/model/shell endpoint โดยตรง

## สิ่งที่ไม่อยู่ใน MVP

- takeover แชทเดิม/Project บนเว็บ หรือ browser scraping
- autonomous swarm จำนวนมาก
- memory/vector DB ขนาดใหญ่
- local coding ก่อน Agent Runner ผ่าน tests
- auto push/merge/deploy
- unrestricted execution เมื่อ adapter enforce policy ไม่ได้
- remote listener และ desktop UI หนัก
