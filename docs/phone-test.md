# Phone line test (step 5)

The phone line (Twilio webhooks `/voice` and `/voice/gather`) is built but has never handled a real call. This test measures it with real calls, made by the owner. The website's Call button stays hidden (`ALLO_PHONE_LIVE=false`) until this test passes.

## Why locally, not on Render
The report reads the call turns from the app's SQLite database. The Render free plan has no shell access and its disk is wiped on restart, so the test runs on the owner's computer, exposed to Twilio through a tunnel (ngrok, as in `.env.example`).

## Before the calls (once)
1. In `.env`: `ALLO_TWILIO_AUTH_TOKEN` (Twilio console → Account info), `ALLO_PUBLIC_BASE_URL` = the ngrok https address (no trailing slash), `ALLO_VERIFY_TWILIO_SIGNATURE=true`.
2. Start the app with `.\dev.ps1`, then the tunnel: `ngrok http 8000`.
3. In the Twilio console, set the number's "A call comes in" webhook to `https://<ngrok address>/voice` (HTTP POST).
4. Note the UTC time just before the first call, for example `2026-11-24T10:00`.

Twilio bills each call minute and the number; check the current prices on Twilio's pricing page before starting (not verified here).

## The calls
- One call per task in [eval/phone_tasks.jsonl](../eval/phone_tasks.jsonl), **in order** (P01 to P12): the report pairs calls with tasks by order.
- Say the sentences of the task's `say` list, one per turn, as written. Speak normally; do not repeat a sentence that was misheard (that is part of the measurement).
- Hang up when the task is done or after `max_turns` answers.
- Write your own verdict in `eval/phone_verdicts.csv` (create it):

```
task_id,completed,notes
P01,yes,
P02,no,said the wrong line
```

"completed" means: by ear, the call did what the task asks, without wrong information.

## The report

```powershell
python scripts/phone_report.py --db data/allo.db --since 2026-11-24T10:00 --save
```

It prints, per task and in total: auto completion (an expected word in an answer), the owner's completion (the number to quote), word error rate of the speech recognition against the scripted sentence, turns per task, and server latency p50 / p95. Server latency covers the dialog only; Twilio's speech recognition and voice synthesis add to what the caller waits.

## Rules
- The tasks were written before any call (committed with this file) and are not changed after seeing results. A failure becomes a fix tested on new wording, then a new set of calls.
- Report real numbers, including bad ones, in `eval/CHANGES.md`.
- Caller numbers are stored only as HMAC; transcripts are deleted after 30 days (see /privacy).
