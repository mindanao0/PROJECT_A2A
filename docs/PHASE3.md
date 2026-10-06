# Phase 3 — Measurements and decisions

วันที่วัด: 2026-10-06 · codex-cli 0.160.1 · claude 2.1.291 (Sonnet 5.5) · เครื่องเดียว ผู้ใช้คนเดียว · ผลทั้งหมดมาจากการรัน CLI จริงผ่าน Runner

## สิ่งที่ Runtime วัดให้แล้ว (OD-012)

ต่อ attempt: ขนาด prompt ที่ Navis ส่ง (bytes), เวลา, outcome และ usage ที่ CLI เลือกเปิดเผย — Codex: tokens ต่อ turn (`turn.completed.usage`, ไม่มีราคา); Claude: tokens, cache read/creation, `total_cost_usd`, จำนวน turn ฟิลด์ที่ CLI ไม่เปิดเผยเป็น `None` ไม่เดา
ดูด้วย `navis-cli usage [-p project] [--hours N]` (แยกตาม agent × implement/review) ที่เก็บ cache hit ใช้เฉพาะตัวเลข cached tokens ที่ CLI รายงานเอง ไม่ใช่ context fingerprint

## Benchmark: agent เดี่ยว vs implement → review

`python3 probes/bench.py` — 3 งานเล็กที่ requirement ชัด (slugify, parse_duration, merge_intervals) agent เห็น requirement + test ที่มองเห็นได้ 2–3 ข้อ; ผลถูกตัดสินด้วย hidden tests (7–12 เคสต่องาน ที่ harness รันใน sandbox ไม่มีเน็ต) ตรวจแล้วว่า reference solution ผ่านครบและ stub ที่ไม่ทำอะไรล้มทั้งหมด (`--selftest`)

| Config | Hidden tests | เวลาเฉลี่ย | Input tokens เฉลี่ย (cached) | Output tokens | Prompt ของ Navis | Cost ที่ CLI รายงาน |
| --- | --- | --- | --- | --- | --- | --- |
| Claude เดี่ยว | 3/3 งานผ่านครบ | 13 s | 36.7k (89%) | 1.0k | ~1.0 KB | $0.033 |
| Codex เดี่ยว | 3/3 ผ่านครบ | 42 s | 79.7k (88%) | 1.1k | ~1.0 KB | ไม่เปิดเผย |
| Codex เขียน → Claude รีวิว | 3/3 ผ่านครบ, รีวิว approve ทั้ง 3 | 55 s | 102.1k (87%) | 2.0k | ~5.1 KB | $0.029 (เฉพาะส่วน Claude) |

ทุก attempt ผ่านในครั้งแรก (ไม่มี retry, ไม่มี revision) รายละเอียดดิบ: ทุกเซลล์ผ่าน visible check และ hidden tests

## ข้อสรุป (และขอบเขตของมัน)

1. **งานเหล่านี้ง่ายเกินจะแยกแยะ**: ทุก config ได้คะแนนเต็ม จึง *ไม่มีหลักฐาน* ว่า review ช่วยเรื่องคุณภาพในงานแบบนี้ และไม่มีหลักฐานว่าไม่ช่วย (การจับบั๊กฝังเองใน Phase 2 ยังเป็นหลักฐานเดียวว่า reviewer จับของจริงได้) ตัวอย่างเพียง 3 งาน × 1 รอบ ไม่มีค่าความแปรปรวน ไม่ควรสรุปเชิงสถิติ
2. **Review มีต้นทุนจริงโดยไม่ได้อะไรเพิ่มในงานง่าย**: pipeline ใช้เวลา ~4× ของ Claude เดี่ยวและ input tokens ~2.8× (Claude เดี่ยวใช้ 36.7k; pipeline 102.1k) ซึ่งสอดคล้องกับการออกแบบเดิมที่ให้ review เฉพาะ task ที่ `review = true` หรือแตะ `protected` paths (EXECUTION_DESIGN §5) และ `require_review` เป็น policy ต่อ project ไม่ใช่ค่าเริ่มต้นของทุกงาน
3. **Context ที่ Navis ส่งเป็นส่วนน้อยมากของ token**: prompt ของ Navis ~1 KB (งานเดี่ยว) ถึง ~5 KB (review ที่แนบ diff) หรือราว 0.3–1.3k tokens เทียบกับ input 37k–80k tokens ต่อ attempt ส่วนที่เหลือคือ overhead ของ CLI เอง (system prompt, tool definitions: แค่ถาม "pong" ข้อเดียวใน Claude ก็ ~25k input tokens) และ ~87–89% ของ input เป็น cached tokens
   → การทำ Git-aware retrieval / versioned summaries / conversation delta ในตอนนี้จะลดได้อย่างมากแค่ ~1–4% ของ input tokens ในงานระดับนี้ จึง **แนะนำให้ยังไม่สร้าง Context Broker** (OD-009) จนกว่าจะมีงานจริงที่ prompt ใหญ่ (เช่น VELA) และวัดแล้วว่า context ของ Navis เป็นสัดส่วนสำคัญ ข้อสรุปนี้มาจากงานเล็ก ถ้างานจริงต้องแนบ diff/log ขนาดใหญ่ ตัวเลขจะเปลี่ยน วิธีวัดอยู่ที่ `navis-cli usage` (คอลัมน์ PROMPT KB เทียบกับ IN TOK)
4. **ตัวเลือกที่คุ้มกว่าการย่อ context**: เลือกว่าจะเรียก agent เมื่อไร/ตัวไหน — Claude เล็ก 13 s ต่อ attempt vs Codex 42 s ในงานชุดนี้ (ความต่างของ latency มาจาก CLI และโมเดล ไม่ได้บอกคุณภาพ) และไม่เรียก reviewer โดยไม่จำเป็น
5. Codex ไม่เปิดเผยราคา จึงเทียบ cost รวมของ pipeline ไม่ได้ ตัวเลข $0.029 คือส่วน Claude เท่านั้น

## ที่เพิ่มใน Phase 3

- **Usage accounting** (`navis/usage.py`, `navis-cli usage`)
- **Fair scheduling ระหว่าง project ตาม usage จริง**: เลือกงานถัดไปจาก project ที่มี attempt วิ่งอยู่น้อยสุด แล้วที่ใช้เวลารวมใน `[limits] fairness_hours` (6) ล่าสุดน้อยสุด แล้วค่อยตาม task id (project ที่เงียบไม่ถูก project ที่คิวยาวกินหมด; test: `test_a_quiet_project_goes_before_a_busy_one_even_with_a_higher_task_id`)
- **Retention** (`navis-cli gc [--days N] [--dry-run]`, `[limits] retention_days` = 30): ลบ directory ของ attempt (log, prompt, bundle) ของ task ที่จบแล้วและเก่ากว่ากำหนดเท่านั้น ไม่แตะ attempt ของงานที่ยังไม่จบ, `refs/navis/attempts/*` (ทำให้ retry/continue/integrate ได้) และตาราง events (หลักฐาน check/verdict ยัง query ได้)
- **Bounded cache**: cache ของ diff ใน GUI จำกัด 64 รายการ

## ที่ยังไม่ได้ทำใน Phase 3

Git-aware retrieval, conversation delta, versioned summaries/invalidation, budgets ต่อ project — เลื่อนตามข้อ 3 (ยังไม่มีหลักฐานว่าคุ้ม); local helper สรุป log ก่อนส่ง cloud ยังเป็น CLI เดี่ยว (`navis-cli summarize`) ไม่ได้ต่อเข้า prompt; ยังไม่มี budget ที่หยุดงานเมื่อเกิน token; ยังไม่ได้วัดงานที่ยากพอจะให้ review มีผลต่อคะแนน
