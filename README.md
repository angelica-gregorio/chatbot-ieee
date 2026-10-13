# Organization FAQ Chatbot

Release 2 of the Organization website redevelopment (CPECAPS). A chatbot on every public page that answers **typed and spoken** questions using only the client-approved FAQ, and hands everything else to the right inquiry email. Spoken questions are transcribed by an **E-Branchformer** speech model (OWSM v3.1 base via ESPnet).

It implements SRS v1.0 FR-21 to FR-23, NFR-PERF-06 and NFR-SAF-04, and proposes FR-24 (voice input) for SRS v1.1 — see [docs/srs-change-request.md](docs/srs-change-request.md).

```
org-faq-chatbot/
├── chatbot-service/          Python service: FAQ matching + E-Branchformer speech recognition
│   ├── app/                  FastAPI app (matcher, ASR, KB sync, redaction, rate limit)
│   ├── tests/                pytest suite (models replaced by fakes; no downloads)
│   ├── eval/                 SRS acceptance checks, threshold calibration, ASR WER
│   ├── scripts/              model download, ASR smoke test, local dev server
│   └── Dockerfile
├── wordpress-plugin/
│   ├── org-chatbot/          WordPress plugin: FAQ fields, settings, log, chat widget
│   └── dev/                  demo page, widget browser test, real-WordPress integration test
├── docs/                     architecture, traceability, SRS change request, deployment, privacy
└── .github/workflows/ci.yml  tests and linters on every push
```

## How it works

1. Administrators keep FAQ entries in WordPress (question, answer, other ways people ask it, category). The plugin publishes them to the service, which reloads within seconds of any edit.
2. A visitor types, or presses the microphone and speaks. The widget records in the browser, converts to 16 kHz mono WAV, and uploads it once. The service transcribes it with OWSM v3.1's E-Branchformer encoder; the audio is never stored.
3. The question (typed or transcribed) is matched against the FAQ. A confident match returns the stored answer word for word; anything else gets a fixed fallback with the inquiry email and links for the most relevant concern. Nothing is generated, so nothing can be invented.
4. Unanswered questions are logged in WordPress for the FAQ owners, with names, emails, phone and ID numbers masked.

Details: [docs/architecture.md](docs/architecture.md).

## Quick start (no WordPress, no model download)

Python 3.12 or 3.13.

```bash
cd chatbot-service
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python scripts/dev_server.py --fake-asr "how can i volunteer"
```

In a second terminal:

```bash
cd wordpress-plugin && python -m http.server 8081
# open http://127.0.0.1:8081/dev/demo.html
```

`--fake-asr` replaces the speech model with a stand-in that always "hears" the given text, for widget work on a laptop. `/health` reports its encoder as `FakeEncoder` so it can't be mistaken for the real thing.

## Running the real E-Branchformer model

```bash
pip install --index-url https://download.pytorch.org/whl/cpu "torch==2.11.*" "torchaudio==2.11.*"
pip install -r requirements-ml.txt
python scripts/smoke_asr.py question1.wav question2.wav --runs 5
```

The first run downloads `espnet/owsm_v3.1_ebf_base` (~0.5 GB with the embedding model). `smoke_asr.py` prints the encoder class (must be `EBranchformerEncoder`), each transcript, and p50/p95 decode time. Then run `python scripts/dev_server.py` without `--fake-asr`.

Key settings (`.env.example` has all of them):

| Variable | Default | Meaning |
| --- | --- | --- |
| `ASR_MODEL_TAG` | `espnet/owsm_v3.1_ebf_base` | Any ESPnet speech-to-text checkpoint |
| `ASR_REQUIRE_EBRANCHFORMER` | `true` | Refuse to enable voice unless the encoder is `EBranchformerEncoder` |
| `ASR_BEAM_SIZE` | `1` | Greedy decoding for speed; 3-5 for accuracy |
| `ASR_QUANTIZE` | `true` | Dynamic int8 quantisation on CPU |
| `MATCHER` | `embedding` | `embedding` (all-MiniLM-L6-v2) or `lexical` (no download) |
| `MATCH_THRESHOLD` | per matcher | Set from `eval/run_eval.py --calibrate` |

## Checks

| Command | What it checks | SRS |
| --- | --- | --- |
| `cd chatbot-service && pytest` | 57 unit and API tests: matching, fallback routing, redaction, KB refresh, audio validation, ESPnet wrapper | FR-21-23 |
| `python eval/run_eval.py --matcher lexical` | Acceptance criteria on the sample data | FR-21, FR-22, NFR-PERF-06, NFR-SAF-04 |
| `python eval/asr_eval.py recordings.csv` | WER, spoken-question accuracy, ASR latency | FR-24, NFR-PERF-07 (proposed) |
| `python wordpress-plugin/dev/e2e_widget.py --service-python chatbot-service/.venv/bin/python` | Headless Chromium: typed answer, fallback, voice via fake mic, axe-core WCAG 2.2 AA, 360 px, offline | FR-21, FR-22, NFR-USE-01/02, NFR-AVL-04 |
| `wordpress-plugin/dev/wp-integration/run.sh` | Installs a throwaway WordPress 7.1.3 on SQLite, adds the plugin and sample FAQ, runs the service against it: REST and secret, disabled entries, redacted log, refresh webhook, admin screens, settings save, front-page widget, no PHP notices | FR-17, FR-21-23, NFR-CMP-02 |
| `vendor/bin/phpcs` (after `composer install`) | WordPress Coding Standards | NFR-MNT-05 |
| `npm run lint` | ESLint and Stylelint | NFR-MNT-05 |
| `ruff check . && ruff format --check .` (in `chatbot-service`) | Python lint and format | NFR-MNT-05 |

### Current results

On the sample data in `chatbot-service/eval/data` (placeholder FAQ, 30 + 20 + 50 test questions):

| Criterion | Lexical matcher (threshold 0.15) |
| --- | --- |
| FR-21 AC1: ≥ 26/30 reworded questions answered correctly | **25/30 — fails by one** |
| FR-22 AC1: 20/20 out-of-scope get fallback with email | Pass |
| FR-22 AC2: concern-specific email and links | Pass (6/6) |
| NFR-PERF-06: p95 ≤ 3 s | Pass (matching < 1 ms) |
| NFR-SAF-04: 0 unapproved answers, 0 requests for sensitive data | Pass (0/43 should-fallback answered) |

The widget passes all 10 headless-browser checks with 0 axe-core violations. On a real WordPress 7.1.3 site all 26 integration checks pass with no PHP notices; that run caught and fixed three bugs that static checks missed (settings sanitiser not idempotent on first save, a crash when settings change outside wp-admin, translations loading before `init`). PHPCS reports 0 errors and 0 warnings, and ESLint, Stylelint and ruff are clean.

**Not yet measured:** the embedding matcher (the default) and the real E-Branchformer model, because the build environment could not download from Hugging Face. Run `eval/run_eval.py --matcher embedding --calibrate` and `scripts/smoke_asr.py` on your machine; both are expected to change the numbers above. The lexical result holds at only one threshold, so treat it as a fallback and baseline, not the primary matcher.

## Open items

- **FAQ set (TBD-05):** replace the sample data with the client-approved FAQ and test questions, then calibrate.
- **Hosting:** free Hugging Face Docker Spaces are no longer available to new free accounts; pick a host ([docs/deployment.md](docs/deployment.md)) and get approval for any cost (C-10).
- **Voice latency and accuracy:** measure on the chosen host and with recordings from members before agreeing FR-24 / NFR-PERF-07.
- **SRS v1.1:** agree the changes in [docs/srs-change-request.md](docs/srs-change-request.md) with the client.
- **Privacy Notice:** DPO review of [docs/privacy.md](docs/privacy.md).
- **Licence:** choose a licence for this repository. The plugin header uses GPL-2.0-or-later, the usual licence for WordPress plugins.

Tag each release (`v0.1.0`, `v0.2.0`, ...) per NFR-MNT-02.

## Credits

- **OWSM v3.1 base** (`espnet/owsm_v3.1_ebf_base`), CMU WAVLab, CC-BY-4.0. Peng et al., "OWSM v3.1: Better and Faster Open Whisper-Style Speech Models based on E-Branchformer", INTERSPEECH 2024.
- **E-Branchformer**: Kim et al., "E-Branchformer: Branchformer with Enhanced merging for speech recognition", IEEE SLT 2022.
- **ESPnet** speech toolkit, Apache-2.0.
- **all-MiniLM-L6-v2** sentence embeddings, sentence-transformers, Apache-2.0.
