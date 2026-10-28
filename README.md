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

## Getting started: step by step

Follow these steps in order the first time. Commands are shown for **Windows (Command Prompt)** and **macOS / Linux**; run them in a terminal (in VS Code: **Terminal > New Terminal**).

### Step 1. Install Python 3.12 or 3.13 and Git

The speech model library (ESPnet) only works with **Python 3.12 or 3.13**, not 3.11 or 3.14.

- **Windows:** download Python 3.13 from [python.org/downloads](https://www.python.org/downloads/). In the installer, tick **"Add python.exe to PATH"**. Install [Git for Windows](https://git-scm.com/download/win) too.
- **macOS:** `brew install python@3.13 git` (or the python.org installer).
- **Linux:** install `python3.13` (or 3.12) and `python3.13-venv` with your package manager.

Check it worked (open a *new* terminal first):

| Windows | macOS / Linux |
| --- | --- |
| `py -3.13 --version` | `python3.13 --version` |

You should see `Python 3.13.x` (or 3.12.x). Also make sure you have about **3 GB of free disk space**.

### Step 2. Download the project

```bash
git clone https://github.com/angelica-gregorio/chatbot-ieee.git
cd chatbot-ieee
```

### Step 3. Run the setup script (once)

| Windows | macOS / Linux |
| --- | --- |
| `powershell -ExecutionPolicy Bypass -File setup.ps1` | `./setup.sh` |

This takes **10–20 minutes** the first time. It:

1. creates a private Python environment in `chatbot-service/.venv` (so nothing is installed system-wide),
2. installs the packages, including CPU-only PyTorch and ESPnet,
3. downloads the two models, ~0.5 GB in total (see [Where the models are](#where-the-models-are)).

When it ends with **"Setup complete"**, continue. If it stops with an error, see [Troubleshooting](#troubleshooting).

> Only working on the widget or tests, or short on disk space? Use the light setup, which skips PyTorch and the models: `setup.ps1 -Light` / `./setup.sh --light`. Voice then runs with a stand-in (Step 6).

### Step 4. Activate the environment

Do this **every time you open a new terminal** for this project:

| Windows (Command Prompt) | Windows (PowerShell) | macOS / Linux |
| --- | --- | --- |
| `cd chatbot-service` | `cd chatbot-service` | `cd chatbot-service` |
| `.venv\Scripts\activate` | `.venv\Scripts\Activate.ps1` | `. .venv/bin/activate` |

Your prompt now starts with `(.venv)`. In VS Code, also pick this Python: **Ctrl+Shift+P > Python: Select Interpreter >** `chatbot-service/.venv`.

### Step 5. Check that everything works

```bash
pytest
```

You should see a row of dots ending in `100%`, with no failures. (The tests use stand-ins for the models, so they take seconds.)

### Step 6. Start the chatbot service (terminal 1)

```bash
python scripts/dev_server.py
```

Leave this terminal running. The speech model takes **about a minute** to load the first time. Open http://127.0.0.1:8000/health in your browser: when it shows `"state":"ready"` and `"encoder":"EBranchformerEncoder"`, voice is ready (typed questions work right away).

With the light setup, run `python scripts/dev_server.py --fake-asr "how can i volunteer"` instead: every recording then "transcribes" to that sentence, and `/health` reports `FakeEncoder`.

### Step 7. Open the demo page (terminal 2)

Open a **second** terminal (in VS Code, the **+** in the terminal panel), go to the project folder, and run:

```bash
cd wordpress-plugin
python -m http.server 8081
```

Then open **http://127.0.0.1:8081/dev/demo.html** and click the round chat button in the bottom-right corner.

### Step 8. Try it

1. **Type** a question, for example *How do I become a member?* You get the stored FAQ answer.
2. Ask something the FAQ does not cover, for example *Is parking free?* You get the fallback with the inquiry email.
3. Press the **microphone**, allow access, speak a question, and press it again to send. The reply shows *You said: ...* followed by the answer.

To preview a logo in the header, save it in `wordpress-plugin/dev/` and open `demo.html?logo=logo.png`.

### Step 9. Stop

Press **Ctrl+C** in both terminals.

### Next time

You only repeat Steps 4, 6 and 7. After pulling teammates' changes (`git pull`), run the setup script again if any `requirements*.txt` file changed; it skips what is already installed.

### Where the models are

They are **not in this repository**: model files are too large for git. The setup script downloads them into the Hugging Face cache on your machine, where the code finds them automatically:

| Model | Used for | Size | Folder |
| --- | --- | --- | --- |
| `espnet/owsm_v3.1_ebf_base` | Speech to text (E-Branchformer encoder) | ~0.4 GB | `~/.cache/huggingface/hub/models--espnet--owsm_v3.1_ebf_base` (Windows: `C:\Users\<you>\.cache\huggingface\hub\...`) |
| `sentence-transformers/all-MiniLM-L6-v2` | Matching questions to FAQ entries | ~0.1 GB | same folder |

To download them again (or another checkpoint set in `ASR_MODEL_TAG`): `python scripts/download_models.py`.

To check the speech model on your own recordings (16 kHz mono WAV): `python scripts/smoke_asr.py question1.wav question2.wav --runs 5`. It prints the encoder class (must be `EBranchformerEncoder`), each transcript, and the decode time.

### Working on the code with git

- Never commit `.venv/`, `node_modules/`, `.env` or recordings; `.gitignore` already hides them. If VS Code's Source Control shows thousands of changes, one of these folders is not being ignored: refresh the panel and check `.gitignore`.
- Work on a branch and open a pull request: `git checkout -b my-change`, then `git add <files>`, `git commit -m "..."`, `git push -u origin my-change`.
- Before pushing, run `pytest` and `ruff check .` in `chatbot-service`, and `npm run lint` in the project folder if you changed the widget (needs Node.js 20+ and `npm ci` once). GitHub runs the same checks on every push.

### Packaging for WordPress

The project ships as two pieces, because WordPress hosting cannot run Python or the speech model:

1. **The plugin** (chat widget, FAQ screens, settings). Build the zip:
   ```bash
   python wordpress-plugin/dev/package_plugin.py      # -> dist/org-chatbot-<version>.zip
   ```
   In WordPress: **Plugins > Add New > Upload Plugin**, choose the zip, then **Activate**. Bump the version in `org-chatbot.php` (header and `ORG_CHATBOT_VERSION`) and `readme.txt` (`Stable tag`, changelog) for every release, so browsers load the new CSS and JS.
2. **The chatbot service** runs on its own server as a Docker container and must be reachable over HTTPS: `docker build -t org-faq-chatbot chatbot-service`.

Then connect them: set the same shared secret on both sides, enter the service URL in **Chatbot > Settings**, and add the FAQ entries. [docs/deployment.md](docs/deployment.md) walks through all of it.

### Troubleshooting

| Problem | Fix |
| --- | --- |
| `Could not find a version that satisfies the requirement espnet==...` | The environment uses the wrong Python. Delete `chatbot-service/.venv` and run the setup script again with Python 3.12 or 3.13 installed. |
| PowerShell: "running scripts is disabled on this system" | Use `cmd` and `.venv\Scripts\activate`, or run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once. |
| Voice transcripts are a bit off | Start the service with `ASR_BEAM_SIZE=3` (cmd: `set ASR_BEAM_SIZE=3`) for more accurate decoding, at about 1–1.6 s per question. |
| The mic button is missing | The page must be on `http://127.0.0.1` / `localhost` or HTTPS, and the browser must support `AudioWorklet`. |
| The first start takes ~2 minutes | The speech model is loading; text questions work meanwhile. Later starts are faster. |

### Settings

Settings are environment variables; `chatbot-service/.env.example` lists all of them with defaults. Copy it to `.env` for Docker (`docker run --env-file .env ...`); never commit `.env`. Key ones:

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
| `python wordpress-plugin/dev/e2e_widget.py --service-python chatbot-service/.venv/bin/python` (Windows: `.venv\Scripts\python.exe`). Needs `npm ci`, `pip install playwright`, `python -m playwright install chromium`, and ports 8000/8081 free (stop your own dev servers first) | Headless Chromium: typed answer, fallback, voice via fake mic, axe-core WCAG 2.2 AA, 360 px, offline | FR-21, FR-22, NFR-USE-01/02, NFR-AVL-04 |
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
