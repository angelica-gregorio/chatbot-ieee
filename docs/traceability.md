# Traceability: SRS requirements to code and checks

Requirement IDs are from *CPECAPS SRS — Organization Website (WordPress) v1.0*. FR-24 and NFR-PERF-07 are proposed in [srs-change-request.md](srs-change-request.md).

Check types: **unit** = `chatbot-service/tests` (pytest), **eval** = `chatbot-service/eval/run_eval.py`, **e2e** = `wordpress-plugin/dev/e2e_widget.py` (headless Chromium), **wp** = `wordpress-plugin/dev/wp-integration/run.sh` (real WordPress 7.1.3 on SQLite), **lint** = PHPCS / ESLint / Stylelint / ruff.

| Requirement | Implemented in | Verified by | Status on sample data |
| --- | --- | --- | --- |
| FR-17 FAQ page (KB source) | `class-org-chatbot-faq.php` (post type, `[org_faq]` shortcode with `<details>`) | wp "[org_faq] renders <details> entries with anchors"; click, Enter and Space come from native `<details>` | Pass |
| FR-21 Chatbot FAQ answering | `app/matcher.py`, `app/responder.py`, widget on all public pages (`class-org-chatbot-widget.php`) | eval FR-21 AC1 (≥ 26/30 reworded, ≤ 3 s each); unit `test_typed_question_gets_stored_answer`; e2e "Typed question gets the stored answer" | Lexical baseline 25/30 (fails by 1); embedding matcher must be calibrated on your machine |
| FR-22 Redirection and escalation | `responder.decide`, `choose_concern`, concern settings | eval FR-22 AC1 (20/20 fallback with email), AC2 (concern email and links); unit `test_fallback_routes_by_keyword`; e2e "Unmatched event question" | Pass |
| FR-23 KB administration | Chatbot box per FAQ entry (enable, alternate phrasings, links); `Org_Chatbot_Log` + admin screen | wp: AC1 edited answer live through the refresh webhook (cache TTL 600 s, so not the timer); disabled entry never answered; log lists question, date, count with 0 names, emails or phone numbers; create/delete from the log; unit tests for the same in the service | Pass; demonstrate on staging for acceptance |
| FR-24 Voice question input (proposed) | `app/asr.py`, `app/audio.py`, widget recorder + `recorder-worklet.js` | unit `test_spoken_question_is_transcribed_then_answered`, ASR wrapper tests; e2e "Spoken question" (fake mic); `eval/asr_eval.py` for WER and spoken accuracy | Pipeline verified with a stand-in transcriber; real-model accuracy and latency not yet measured |
| NFR-PERF-06 Reply time p95 ≤ 3 s | Sub-millisecond matching; ASR single-flight lock | eval NFR-PERF-06 (in-process or `--service-url`) | Typed: p95 < 1 ms matching. Voice: measure with `scripts/smoke_asr.py` |
| NFR-SAF-04 Answer safety | Retrieval-only replies; coverage-weighted matching; no prompts for data | eval NFR-SAF-04 (50 adversarial questions) | Pass: 0 unapproved, 0 sensitive requests, 0/43 should-fallback answered |
| NFR-AVL-04 Third-party failure isolation | Deferred widget script; offline message from WordPress config | e2e "Service down: page intact" | Pass |
| NFR-USE-01 WCAG 2.2 AA | Widget: labelled dialog, live log, focus handling, 44 px targets, reduced motion | e2e axe-core scan (wcag2a/aa, 21aa, 22aa) | Pass: 0 violations |
| NFR-USE-02 Responsive | `chat-widget.css` | e2e 360 px layout | Pass |
| NFR-SAF-03 Motion safety | `prefers-reduced-motion` disables the recording pulse | Inspection | Implemented |
| NFR-SEC-05 Security headers | CSP needs `connect-src` for the service (see deployment.md) | Inspection | Documented |
| NFR-CMP-01/02 Privacy | No audio stored; redaction in service and plugin; log keeps text, counts, dates only; retention purge; `--no-access-log` | unit privacy tests; wp "Log stores redacted text only" | Pass; Privacy Notice text drafted in privacy.md |
| NFR-CMP-03 Licensing | OWSM v3.1 CC-BY-4.0, all-MiniLM-L6-v2 Apache-2.0 credited in README | Inspection | Add to the asset register |
| NFR-MNT-01 No core/plugin edits | All WordPress code in a site-specific plugin | Inspection | Pass |
| NFR-MNT-02 Version control | This repository; tag each release | Inspection | Tag on release |
| NFR-MNT-05 Code quality | `phpcs.xml.dist`, `eslint.config.mjs`, `.stylelintrc.json`, ruff in `pyproject.toml` | lint in CI | Pass: PHPCS 0 errors 0 warnings, ESLint 0, Stylelint 0, ruff 0 |
