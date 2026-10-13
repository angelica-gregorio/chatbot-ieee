# Proposed SRS changes for version 1.1 (chatbot and voice input)

The SRS v1.0 describes a typed FAQ chatbot. The team's plan uses an E-Branchformer speech model, which adds spoken questions. Under the SRS versioning rule, that is a change after acknowledgment and needs a new version agreed with the client (Chico Andre). Everything below is a **proposal**: the numbers are starting points for the team and client to agree, not commitments.

## 1. Close TBD-05 (chatbot tool)

> **TBD-05 — Closed.** Chatbot tool: a self-hosted retrieval service (`chatbot-service`) with a site-specific WordPress plugin (`org-chatbot`). Typed and spoken questions are matched against the approved FAQ set; spoken questions are transcribed by OWSM v3.1 base (E-Branchformer encoder, 101M parameters, CC-BY-4.0). The initial FAQ set remains open until the client approves it.

## 2. New functional requirement

> **FR-24 Voice question input** — Should · R2 — Source M-08, D · Interfaces IF-01, IF-11, IF-13 · Constraints / assumptions C-03, C-08, A-10 · Verification: Test
>
> The chatbot widget shall let a visitor ask a question by voice. Before the first recording in a session it shall show a notice explaining that the recording is used only to produce text, is not stored, and linking the Privacy Notice; recording starts only after the visitor agrees. The recording is transcribed by the speech model and answered exactly like a typed question (FR-21, FR-22). The transcript is shown to the visitor. Browsers without microphone support show no microphone button and typing still works.

| AC | Given | When | Then |
| --- | --- | --- | --- |
| AC1 | The 30 FR-21 test questions, each spoken by at least 5 different speakers (150 recordings) | Each recording is submitted | At least 80% receive the correct stored answer, and corpus word error rate is at most 20% (`eval/asr_eval.py`) |
| AC2 | A first-time visitor presses the microphone button | — | The consent notice appears and no microphone access is requested until they choose "Allow and record" |
| AC3 | 20 out-of-scope questions are spoken | Each is submitted | 100% receive the fallback reply with a working email link (as FR-22 AC1) |
| AC4 | A voice question has been answered | The server is inspected | 0 audio files exist on the server and the unanswered-question log holds no audio |

The 80% threshold is lower than FR-21's 85% because transcription errors add to matching errors. Set the final figure after the first `asr_eval.py` run on recordings of real members of the Organization.

## 3. New performance requirement

> **NFR-PERF-07 Voice reply time.** p95 ≤ 5 s from the end of recording to the reply appearing, over 50 spoken test questions, on the production host. Measured in the browser. Should (R2).

NFR-PERF-06 (≤ 3 s) stays for typed questions. Voice needs its own target because OWSM pads every utterance to 30 s before encoding, so its cost is roughly fixed per question and depends on the host CPU. Measure with `scripts/smoke_asr.py` on the chosen host before agreeing the figure.

## 4. Changes to existing items

| Item | Change |
| --- | --- |
| IF-11 Chatbot engine | Mechanism: self-hosted HTTPS API (`/v1/chat`, `/v1/chat/voice`). Data out: visitor question (text or 16 kHz WAV, max 15 s). Data in: stored answer, or fallback with concern email and links; transcript for voice. |
| New IF-13 Visitor microphone | Browser microphone, used only after consent; audio sent once per question to IF-11 and not stored. R2. |
| A-10 | Replace "within free-tier limits" with: "retrieval-based over the FAQ set, with an E-Branchformer speech model for voice, hosted on a server the Organization provides or approves (C-10)". Hugging Face no longer lets free accounts create Docker Spaces on CPU Basic, so the free-hosting assumption does not hold for the speech model. |
| A-05 | Note that R2 may need a small paid host or an Organization/school server; any cost needs written client approval (C-10). |
| NFR-PERF-06 | Applies to typed questions. |
| NFR-AVL-04 | Add the chatbot service domain to the blocked-domain test (already covered by the widget's offline message). |
| NFR-SEC-05 | The Content-Security-Policy must allow the chatbot service in `connect-src`. |
| NFR-CMP-01 | The Privacy Notice must cover voice questions: purpose, that audio is not stored, and that unanswered question text is kept for the retention period with identifiers masked (draft text in privacy.md). |
| NFR-CMP-03 | Add OWSM v3.1 (CC-BY-4.0, attribution required) and all-MiniLM-L6-v2 (Apache-2.0) to the asset register. |
| NFR-CMP-05 | Add the chatbot service host to the third-party service register. |
| OS-06 | Clarify: "speech-to-text transcription of the visitor's question is in scope (FR-24); generating free-form answers is not." |
| OS-10 | Voice input recognises English only (`ASR_LANG_SYM=<eng>`), in line with A-04. |
| Release plan (2.4) | R2 requirements: FR-21 to FR-24, NFR-PERF-06, NFR-PERF-07, NFR-SAF-04. |

## 5. Risks to raise with the adviser and client

1. **Latency on CPU.** Not yet measured on the target host. If p95 exceeds the agreed limit: keep `ASR_BEAM_SIZE=1`, keep int8 quantisation on, give the container more cores, or move to a host with a GPU.
2. **Accented and Taglish speech.** OWSM v3.1 is trained on public data that may under-represent Philippine English. The `asr_eval.py` per-speaker WER shows how big the gap is; fine-tuning on recordings from members (with consent) is an option for a later release.
3. **Hosting cost.** See A-10. Decide the host before R2 starts.
4. **Scope.** Voice adds work to R2, which only starts after R1 is accepted (C-03). If time runs short, FR-24 can slip with client agreement because it is a Should.
