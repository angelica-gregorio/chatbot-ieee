# Privacy and data handling (RA 10173, NFR-CMP-01/02)

This describes what the chatbot processes so the Organization's data protection officer can review it and update the Privacy Notice. It is an engineering description, not legal advice.

## What is processed and kept

| Data | Where | Kept | Notes |
| --- | --- | --- | --- |
| Typed question | Service memory | No (request only) | Not logged by the service |
| Voice recording | Visitor's browser, then service memory | No | Sent once as WAV, decoded in memory, discarded after transcription; never written to disk |
| Transcript of a voice question | Service memory, shown to the visitor | No | Used only to find the answer |
| Unanswered question text | WordPress table `wp_org_chatbot_unanswered` | Retention setting, default 90 days, purged daily | Emails, links, phone and ID numbers, "my name is ..." names and secrets are masked in the service **and** again in WordPress; stores text, times asked, times spoken, first and last date only |
| IP address | Service memory for rate limiting | Up to 60 s | Hashed with a random per-process salt; uvicorn access log is disabled (`--no-access-log`) |
| Voice consent | Visitor's `sessionStorage` | Until the tab closes | A flag only; not a cookie, not sent to any server |

The widget sets no cookies, so it does not affect the cookie banner (FR-20).

## Limits of the redaction

Pattern-based masking catches the common cases (emails, Philippine mobile and landline numbers, long ID-like numbers, "my name is ..." / "ako si ..."). It cannot catch every personal detail, such as a name mentioned in passing without an introduction. Administrators should delete any log entry that still identifies someone, and the retention period keeps the log small.

## Draft Privacy Notice section (for the client and DPO to review)

> **Chatbot.** Our website chatbot answers questions using our published FAQ. When you type or speak a question, it is sent to our chatbot service only to find the matching answer. If you use voice, your recording is converted to text and then deleted immediately; we do not store recordings. If the chatbot cannot answer, the text of your question (with names, email addresses, phone and ID numbers removed) is kept for up to 90 days so we can improve our FAQ. We do not record your IP address, name or email with it. Please avoid sharing personal details in the chat; for personal matters, email us at the address shown.

## Before go-live

- DPO reviews this page and the notice text.
- Add the chatbot service host to the third-party service register (NFR-CMP-05) and confirm where it is hosted.
- If test recordings are collected for `asr_eval.py`, get written consent from each speaker, keep the files off the public repository, and delete them after the evaluation.
