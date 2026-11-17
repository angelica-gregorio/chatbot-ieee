# Deployment

Follow NFR-SAF-02: every step below goes to **staging first**, passes the smoke checks, and is logged before it reaches production.

## 1. Choose where the service runs

The service is a standard Docker container. It needs a public HTTPS address the visitor's browser can reach, outbound access to the WordPress site, and enough CPU for the speech model (101M parameters, padded to 30 s of audio per question).

| Option | Notes |
| --- | --- |
| Organization or school server / VM | Usually the cheapest; put it behind the existing reverse proxy for HTTPS |
| Google Cloud Run | Sleeps when nobody is chatting, so it usually stays inside the free tier; a cold start makes the first visitor after a quiet period wait about a minute. Step-by-step guide: [section 5](#5-google-cloud-run) |
| Cloud VM or container platform | Check current free-tier terms and memory limits before relying on them |
| Hugging Face Space | Since mid-2026, free accounts can no longer create Docker Spaces on CPU Basic; a paid plan is needed, which requires written client approval (C-10) |

Whatever you pick, run `scripts/smoke_asr.py` on it with a few recordings first and compare p95 with the voice target you agree (proposed NFR-PERF-07). Record the host in the third-party service register (NFR-CMP-05).

## 2. Build and run the service

```bash
cd chatbot-service
cp .env.example .env          # fill in WP_BASE_URL, WP_SHARED_SECRET, ALLOWED_ORIGINS
docker build -t org-faq-chatbot .
docker run -d --name org-faq-chatbot --restart unless-stopped \
  --env-file .env -p 127.0.0.1:8000:8000 org-faq-chatbot
curl -s http://127.0.0.1:8000/health
```

The build downloads OWSM v3.1 base and all-MiniLM-L6-v2 into the image (`PRELOAD_MODELS=true`), so containers start without network downloads. `/health` reports `"asr": {"state": "ready", "encoder": "EBranchformerEncoder"}` once the speech model is warm; text questions work before that.

Generate the shared secret once and use it on both sides:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Put HTTPS in front with your reverse proxy (Caddy, nginx, the host's load balancer). If the proxy sets `X-Forwarded-For`, set `TRUST_PROXY_HEADERS=true` so rate limiting sees real clients.

### Calibrate before go-live

With the client-approved FAQ set loaded in WordPress and the test CSVs replaced with the approved test questions:

```bash
python eval/run_eval.py --kb exported_kb.json --matcher embedding --calibrate
```

Export `exported_kb.json` from `GET /wp-json/org-chatbot/v1/kb` (send the `X-Org-Chatbot-Key` header). Set `MATCH_THRESHOLD` to the recommended value, restart, then run the same script with `--service-url https://<service>` for end-to-end timing.

## 3. Install the WordPress plugin

1. Copy `wordpress-plugin/org-chatbot` to `wp-content/plugins/` and activate it on staging.
2. In `wp-config.php`:
   ```php
   define( 'ORG_CHATBOT_SHARED_SECRET', '<same value as WP_SHARED_SECRET>' );
   ```
   Do not write the secret in the handover note (NFR-MNT-04); store it in the Organization's password manager.
3. **Chatbot > Settings**: service URL, FAQ / Contact / Privacy Notice URLs, and the inquiry email for each concern (TBD-07). Save; the notice at the top should say "Service connected".
4. **FAQs**: enter the approved FAQ entries. Title = question, content = answer, "Other ways people ask this" = rephrasings (2-3 per entry improve matching noticeably), category = topic. Set each category's inquiry concern under FAQs > FAQ categories.
5. Put `[org_faq]` on the FAQ page if R1 did not already build one from these entries.
6. If the site sends a Content-Security-Policy, add the service origin:
   ```
   connect-src 'self' https://chatbot.example.org;
   ```
   The audio worklet loads from the site's own origin, so `script-src` needs no change.

## 4. Smoke checks after each deploy

- `/health` shows the expected FAQ count, matcher and `EBranchformerEncoder` in state `ready`.
- Ask one FAQ question by typing and one by voice on a phone and a desktop browser.
- Ask one out-of-scope question; the reply shows the right inquiry email, and it appears under **Chatbot > Unanswered questions** with any name or email masked.
- Edit an FAQ answer; the chatbot returns the new text within a minute without restarting anything (FR-23 AC1).
- Block the service domain in browser DevTools; the page still loads and the chat shows the Contact page and email (NFR-AVL-04).

Sources: [Hugging Face Spaces overview](https://huggingface.co/docs/hub/en/spaces-overview), [community thread on the CPU Basic change](https://discuss.huggingface.co/t/official-community-complaint-revert-free-cpu-basic-spaces-and-remove-anti-developer-sdk-restrictions/177703).

## 5. Google Cloud Run

When you finish, the chatbot service runs on Google Cloud Run. It starts when a visitor opens the chat, sleeps (and costs nothing) when nobody is chatting, and a spend cap stops it at $10 a month. Expect 1 to 2 hours the first time. At the traffic a club or organization FAQ usually sees, the monthly bill should be about $0.10 to $0.30, almost all of it image storage.

```
Visitor's browser ──(1) page + widget──────────────▶ WordPress site
       │                                                  ▲
       └──(2) question / recording (HTTPS, CORS)──▶ Cloud Run: org-faq-chatbot
                                                          │
                     (3) FAQ entries, unanswered log ─────┘  (shared secret header)
```

1. WordPress serves the page and the chat widget. It knows the Cloud Run address but never sends the shared secret to the browser.
2. The widget sends questions and recordings straight to Cloud Run. When the chat is opened, it wakes the service and shows "Starting up the chatbot…" while it starts.
3. The service fetches the FAQ from WordPress and records unanswered questions there. Both use the shared secret, which lives only in `wp-config.php` and Secret Manager.

| Part | Where it runs | What it does |
| --- | --- | --- |
| Chat widget (plugin 0.3.0) | Visitor's browser | Wakes the service when the chat opens, waits through a cold start, asks the questions |
| Org Chatbot plugin 0.3.0 | WordPress | Serves the widget, publishes the FAQ to the service, logs unanswered questions |
| `org-faq-chatbot` service | Cloud Run: 2 vCPU, 3 GiB, 0 to 1 instances | Loads the FAQ, transcribes voice with E-Branchformer, matches questions, answers |
| Spend cap and budget alert | Cloud Billing | Pauses Cloud Run at $10 a month; emails you about storage and build costs |

**Before you start:**

- [ ] Approval to put a card on a Google Cloud billing account (constraint C-10), even though the expected bill is cents.
- [ ] Admin access to WordPress, plus SFTP or your host's file manager, to copy the plugin folder and edit `wp-config.php`.
- [ ] A clone of this repository on your computer with plugin version 0.3.0 or later (the `Version:` line in `wordpress-plugin/org-chatbot/org-chatbot.php`). Step 6 copies the plugin from it.
- [ ] A browser. Every Google Cloud command runs in **Cloud Shell**, a terminal in the Google Cloud console that is already signed in, so you install nothing.

### Step 1: Create the Google Cloud project

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and sign in with an account the organization controls, not a member's personal Gmail, so access doesn't leave with one person.
2. Open the project picker at the top, choose **New project**, name it `Org FAQ chatbot`, and create it. Write down the **Project ID** it shows (for example `org-faq-chatbot-123456`).
3. Go to **Billing** and link the project to a billing account, creating one with the card if needed. If Google creates an organization resource for a new account, it starts with stricter "secure by default" policies ([Google Cloud docs](https://cloud.google.com/resource-manager/docs/secure-by-default-organizations)). Steps 3 and 5 account for them.
4. Click **Activate Cloud Shell** (`>_`, top right). A terminal opens at the bottom of the page.
5. Paste this block after replacing the values on the first three lines. Cloud Shell forgets them when it reconnects, so paste it again at the start of every session:

   ```bash
   PROJECT_ID=org-faq-chatbot-123456   # your Project ID
   REGION=asia-east1                   # see "Pick a region" below
   SITE=https://www.your-site.org      # your WordPress address, no trailing slash
   IMAGE=$REGION-docker.pkg.dev/$PROJECT_ID/chatbot/org-faq-chatbot:0.3.0
   gcloud config set project $PROJECT_ID
   ```
6. Switch on the services (about a minute):

   ```bash
   gcloud services enable run.googleapis.com artifactregistry.googleapis.com \
     cloudbuild.googleapis.com secretmanager.googleapis.com iam.googleapis.com
   ```
7. Get the code from the `cloud-run` branch, which holds the Cloud Run changes (`main` doesn't), and check you got it. Replace `your-org` with the GitHub account or organization that owns the repository:

   ```bash
   git clone --branch cloud-run https://github.com/your-org/chatbot-ieee.git && cd chatbot-ieee
   git branch --show-current
   ```

   It should print `cloud-run`. If it prints `main`, run `git switch cloud-run`.

**Pick a region** close to your visitors and your WordPress host: every question goes from the visitor to the service, and the service fetches the FAQ from WordPress. The free tier is counted at Tier 1 prices ([Cloud Run pricing](https://cloud.google.com/run/pricing)), so a Tier 1 region stretches it furthest. For example, for visitors in Southeast Asia, `asia-east1` (Taiwan) and `asia-southeast1` (Singapore) are the nearest; check the pricing page for which tier each is in today. Whatever you pick is where visitors' questions and recordings are processed, which matters for Step 8's paperwork.

### Step 2: Set the spending limits first

Before anything can cost money, create a **spend cap** that pauses Cloud Run at $10 a month, and a **budget alert** for everything else.

**Spend cap on Cloud Run** ([how spend caps work](https://docs.cloud.google.com/billing/docs/how-to/budgets-spend-caps)):

1. Go to **Billing → Budgets & alerts → Create budget**.
2. Choose **Spend cap enforcement** (not **Alerts only**) and name it `Chatbot Cloud Run cap`.
3. Under **Scope**, pick this project and the **Cloud Run** service. A cap covers exactly one project and one service.
4. Enter **$10** as the target amount. The time range is fixed to monthly.
5. Click **Finish**. Billing administrators and project owners get emails at 50%, 80% and 100% of the cap; these can't be changed.

Why $10: the cap counts gross costs at list price, before credits and discounts. Google doesn't say whether the free tier counts as a discount, so assume the cap sees your usage at full price. Typical use is about $4 a month at full price (see Costs), so a lower cap could pause the chatbot while your real bill is still $0. When the cap triggers, new requests to Cloud Run are paused (nothing is deleted) and visitors see the chatbot's offline message with your contact page and email, until the cap resets on the first of the next month or you lift it. Enforcement isn't instant, so a sudden spike can go slightly over, and the overage is billed.

**Alert for everything else:**

1. **Create budget** again, this time **Alerts only**, named `Chatbot account alert`.
2. Scope: this project, all services. Amount: **$5**. Keep the default email thresholds.
3. This covers image storage, builds and secrets, which the Cloud Run cap doesn't stop. Expect them to stay well under $1.

### Step 3: Build the container image

Google builds the image from `chatbot-service/Dockerfile` and stores it in your project, so you don't need Docker on your computer. The image contains CPU-only PyTorch and both models (about 3.9 GB unpacked), so nothing is downloaded when the service starts.

1. Create the image repository (once):

   ```bash
   gcloud artifacts repositories create chatbot --repository-format=docker \
     --location=$REGION --description="Org FAQ chatbot images"
   ```
2. Give the build account the three rights it needs. Newer projects no longer give it broad rights automatically, so builds fail with `PERMISSION_DENIED` without this:

   ```bash
   PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')
   BUILDER=$PROJECT_NUMBER-compute@developer.gserviceaccount.com
   for ROLE in roles/artifactregistry.writer roles/logging.logWriter roles/storage.objectViewer; do
     gcloud projects add-iam-policy-binding $PROJECT_ID --member=serviceAccount:$BUILDER \
       --role=$ROLE --condition=None -q > /dev/null
   done
   ```
3. From the `chatbot-ieee` folder, build and store the image. It downloads PyTorch, ESPnet and the models; allow up to an hour (it usually takes 10 to 20 minutes):

   ```bash
   gcloud builds submit chatbot-service --tag "$IMAGE" --timeout=3600s
   ```

   Builds run on the default `e2-standard-2` machine, which gets 2,500 free build-minutes a month ([Cloud Build pricing](https://cloud.google.com/build/pricing)).
4. Check the image is there:

   ```bash
   gcloud artifacts docker images list $REGION-docker.pkg.dev/$PROJECT_ID/chatbot --include-tags
   ```
5. To keep storage at cents, have old images deleted automatically. In the console, open **Artifact Registry → chatbot → Edit**. Under **Cleanup policies**, leave **Delete artifacts** selected (not **Dry run**), add these two policies, and save:

   - `delete-old`: **Conditional delete**, tag state **Any tag state**, older than `30d`.
   - `keep-latest-2`: **Keep most recent versions**, keep count `2`.

   You need both: a keep policy only protects images, so without the delete policy nothing is ever removed. Where they overlap, keep wins, so the 2 newest images stay however old they are. Changes take effect within about a day ([cleanup policies](https://docs.cloud.google.com/artifact-registry/docs/repositories/cleanup-policy)). Storage above the free 0.5 GB costs about $0.10 per GB per month ([Artifact Registry pricing](https://cloud.google.com/artifact-registry/pricing)).

### Step 4: Create the shared secret and the service's account

**4a. Shared secret.** Generate it and store it in Secret Manager:

```bash
SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
printf '%s' "$SECRET" | gcloud secrets create org-chatbot-shared-secret \
  --replication-policy=automatic --data-file=-
echo "$SECRET"   # copy it into the organization's password manager now: Step 6 needs it
```

**4b. The account the service runs as.** It can read that one secret and nothing else. The default account may have far broader rights:

```bash
gcloud iam service-accounts create chatbot-runtime --display-name="Chatbot service (runtime)"
gcloud secrets add-iam-policy-binding org-chatbot-shared-secret \
  --member=serviceAccount:chatbot-runtime@$PROJECT_ID.iam.gserviceaccount.com \
  --role=roles/secretmanager.secretAccessor
```

No key file is created for this account, and none is needed.

### Step 5: Deploy the service

1. Deploy with every setting at once:

   ```bash
   gcloud run deploy org-faq-chatbot --image="$IMAGE" --region=$REGION \
     --service-account=chatbot-runtime@$PROJECT_ID.iam.gserviceaccount.com \
     --port=8000 --cpu=2 --memory=3Gi --cpu-boost \
     --min-instances=0 --max-instances=1 --concurrency=20 --timeout=300 \
     --startup-probe=httpGet.path=/ready,httpGet.port=8000,initialDelaySeconds=0,failureThreshold=60,timeoutSeconds=4,periodSeconds=5 \
     --set-env-vars=WP_BASE_URL=$SITE,ALLOWED_ORIGINS=$SITE,TRUST_PROXY_HEADERS=true,REPORT_IN_REQUEST=true,HF_HUB_OFFLINE=1 \
     --set-secrets=WP_SHARED_SECRET=org-chatbot-shared-secret:latest \
     --no-invoker-iam-check
   ```

   If the site answers on two addresses (with and without `www`), list both in `ALLOWED_ORIGINS`. The comma would end the flag, so switch the separator to `@`: `--set-env-vars=^@^WP_BASE_URL=$SITE@ALLOWED_ORIGINS=https://your-site.org,https://www.your-site.org@TRUST_PROXY_HEADERS=true@REPORT_IN_REQUEST=true@HF_HUB_OFFLINE=1`.
2. Save the service's address for Step 6:

   ```bash
   URL=$(gcloud run services describe org-faq-chatbot --region=$REGION --format='value(status.url)'); echo $URL
   ```
3. Check that it starts. The first call wakes the service and can take a minute; the reply should show `"state":"ready"` and `"EBranchformerEncoder"` under `asr`, and `"entries"` above 0 once WordPress is connected (Step 6):

   ```bash
   curl -s $URL/health; echo
   ```
4. **Stop Google from keeping visitors' IP addresses.** Cloud Run writes a request log line for every request, with the visitor's IP address and browser, and keeps it for 30 days. The service itself never logs addresses ([privacy.md](privacy.md)), so exclude those lines:

   ```bash
   gcloud logging sinks update _Default \
     --add-exclusion='name=chatbot-request-logs,filter=resource.type="cloud_run_revision" AND log_id("run.googleapis.com/requests")'
   ```

   In the console this is **Logging → Log Router → _Default → Edit sink → Add exclusion**, with the same filter. The service's own log lines (startup, `reply … total_ms`) are kept. Request counts and status codes are still under **Cloud Run → Metrics**.

| Setting | Value | Why |
| --- | --- | --- |
| `--cpu` / `--memory` | 2 / 3Gi | Measured: about 1.3 GiB after loading, about 1.4 GiB after voice questions. 3 GiB leaves headroom; Step 7 checks the real peak |
| `--cpu-boost` | on | Twice the CPU during startup (and 10 s after), so the models load faster. The boosted CPU is billed ([CPU limits](https://docs.cloud.google.com/run/docs/configuring/cpu)) |
| `--min-instances` / `--max-instances` | 0 / 1 | Sleeps when idle, so idle time isn't billed. At most one instance ever runs, which caps the worst case |
| `--concurrency` | 20 | Typed questions run side by side; voice transcription is one at a time by design |
| `--startup-probe` | `/ready`, every 5 s, 60 tries | Visitors' requests wait until the FAQ, matcher and speech model are loaded (5 minutes at most; Cloud Run's limit is 10 minutes). Measured on a laptop: ready in about 31 s ([health checks](https://docs.cloud.google.com/run/docs/configuring/healthchecks)) |
| Billing | request-based (the default) | Billed only while starting up and handling requests, not while idle. Don't add `--no-cpu-throttling`: that switches to instance-based billing |
| `TRUST_PROXY_HEADERS` | `true` | Rate limits each visitor (20 questions a minute) by the address Cloud Run appends to `X-Forwarded-For` |
| `REPORT_IN_REQUEST` | `true` | Unanswered questions reach WordPress before CPU is throttled |
| `HF_HUB_OFFLINE` | `1` | The models come from the image; startup never waits on Hugging Face |
| `WP_SHARED_SECRET` | from Secret Manager | The secret never appears in the service settings or the image |
| `--no-invoker-iam-check` | | Visitors' browsers must reach the service directly. This is Google's recommended way to make a service public, and it works where an organization policy forbids `allUsers` ([public access](https://docs.cloud.google.com/run/docs/authenticating/public)) |

### Step 6: Connect WordPress

1. **Update the plugin by copying its folder.** With SFTP (for example FileZilla) or your host's file manager, copy the folder `wordpress-plugin/org-chatbot` from your local clone to `wp-content/plugins/` on the site, so it lands at `wp-content/plugins/org-chatbot/`. Overwrite the existing files when asked. Your settings and FAQ entries are kept, because they live in the database, not in the folder. Copy only that folder, not the rest of the repository. Then go to **Plugins** in WordPress: the plugin should show version 0.3.0. If it's new to the site, click **Activate**.
2. **Add the secret to `wp-config.php`**, above the line `/* That's all, stop editing! */`:

   ```php
   define( 'ORG_CHATBOT_SHARED_SECRET', 'PASTE-THE-SECRET-FROM-STEP-4a' );
   ```

   The `wp-config.php` value wins over anything saved in the **Shared secret** field under **Chatbot → Settings**. Leave that field empty: values saved there are stored in the database.
3. **Point the plugin at Cloud Run.** In **Chatbot → Settings**, set **Chatbot service URL** to the `URL` from Step 5 (it looks like `https://org-faq-chatbot-….run.app`), tick **The service sleeps when nobody is chatting**, and save. If the notice says the service is asleep or starting up, reload the page after a minute: the check has woken it. It should then say "Service connected" with your FAQ count.
4. **Content-Security-Policy.** If the site sends one (from a security plugin, the host, or Cloudflare), add the service to `connect-src`, for example `connect-src 'self' https://org-faq-chatbot-xxxxx.run.app;`.
5. **Firewalls and security plugins.** The service calls `GET /wp-json/org-chatbot/v1/kb` and `POST /wp-json/org-chatbot/v1/unanswered` from Google's addresses, which change. If you use a security plugin that blocks the REST API for logged-out callers, or a firewall such as Cloudflare's bot protection, allow `/wp-json/org-chatbot/v1/`. Both routes already refuse anyone without the shared secret.

### Step 7: Test that everything works

Run these in a private browser window, so you see the site as a visitor does.

- [ ] **Cold start:** wait at least 20 minutes after the last use (Cloud Run keeps an idle instance for up to 15). Open the chat and ask a typed question straight away. You should see "Starting up the chatbot…" and then the answer, never "not available". Write down how long it took: that's what visitors wait after a quiet period.
- [ ] **Follow-up:** ask a second question right away. It should answer in about a second.
- [ ] **The smoke checks in [section 4](#4-smoke-checks-after-each-deploy):** a typed and a spoken question on a phone and a desktop, an out-of-scope question that appears under **Chatbot → Unanswered questions** with details masked, an FAQ edit that shows within a minute, and the offline message when `run.app` is blocked in DevTools.

Then check speed, memory and startup in the console under **Cloud Run → org-faq-chatbot**:

| What | Where | Target | If it misses |
| --- | --- | --- | --- |
| Voice reply time | **Logs**: search `source=voice`, read `total_ms` on each `reply` line | 95% within 5,000 ms (proposed NFR-PERF-07); measured 2,200–2,700 ms on a laptop | `gcloud run services update org-faq-chatbot --region=$REGION --cpu=4` |
| Memory | **Metrics → Memory utilization** | Peak under 80% | Over 80%: raise `--memory=4Gi`. Under 50%: try `--memory=2Gi` |
| Startup time | **Metrics → Container startup latency** | Well under 300 s | Close to it: raise `--cpu`, or raise `failureThreshold` (up to 120 with `periodSeconds=5`) |
| Cold starts | **Metrics → Container instance count** | A few a day | Many more than visitors: check **Metrics → Request count** for a bot |
| Cost | **Billing → Reports**, filtered to this project | Cents | See Costs below |

### Step 8: Check the security

Run the commands in Cloud Shell with the Step 1 variables and `URL` set.

- [ ] **The secret guards the service's admin route.** Both should print `403`:

  ```bash
  curl -s -o /dev/null -w '%{http_code}\n' -X POST $URL/v1/kb/refresh
  curl -s -o /dev/null -w '%{http_code}\n' -X POST -H 'X-Org-Chatbot-Key: wrong' $URL/v1/kb/refresh
  ```
- [ ] **The secret guards WordPress's FAQ feed.** This should print `403`:

  ```bash
  curl -s -o /dev/null -w '%{http_code}\n' $SITE/wp-json/org-chatbot/v1/kb
  ```
- [ ] **Forged addresses don't dodge the rate limit.** This sends 22 questions, each with a different made-up first address. The last lines should be `429`:

  ```bash
  for i in $(seq 1 22); do curl -s -o /dev/null -w '%{http_code} ' -X POST -H 'Content-Type: application/json' \
    -H "X-Forwarded-For: 192.0.2.$i" -d '{"message":"hi"}' $URL/v1/chat; done; echo
  ```
- [ ] **Other websites can't use it from a browser.** This should print no `access-control-allow-origin` line:

  ```bash
  curl -s -D - -o /dev/null -X OPTIONS -H 'Origin: https://evil.example.com' \
    -H 'Access-Control-Request-Method: POST' $URL/v1/chat | grep -i access-control-allow-origin
  ```
- [ ] **No secret in the page.** View the source of any page and search for the first few characters of your secret. It must not appear. The `run.app` address does appear, by design.
- [ ] **No visitor addresses in the logs.** Ask a question on the site, wait a minute, then run this. It should print nothing (Step 5, item 4):

  ```bash
  gcloud logging read 'log_id("run.googleapis.com/requests")' --freshness=10m --limit=5
  ```
- [ ] **Only the right people can change the project.** In **IAM & Admin → IAM**, only the people who maintain the chatbot have roles. Keep at least two Owners.
- [ ] **Paperwork.** Add Google Cloud and your region to `docs/privacy.md` and the third-party service register (NFR-CMP-05): visitors' questions and recordings are processed there in memory and never stored, and their IP addresses aren't kept once Step 5, item 4 is done.

| Risk | What stops it |
| --- | --- |
| Someone reads the service address from the page and calls it directly | Nothing to steal: the service only answers FAQ questions. A script can make it work, but at most one instance runs, each address gets 20 questions a minute, and the $10 spend cap is the ceiling |
| A bot floods the chat | Same limits. If the cap triggers, the chatbot shows the offline message with contact details until the 1st, or until you lift the cap |
| Someone pretends to be WordPress | `/v1/kb/refresh` needs the shared secret, and the service only fetches the FAQ from `WP_BASE_URL` |
| Someone reads the FAQ feed or writes fake unanswered questions | Both WordPress routes need the shared secret |
| The service itself is compromised | Its account can read the one secret and nothing else |

**Why the service is public.** In this plugin, visitors' browsers talk to the service directly. Making the service private would need WordPress to relay every question and recording, and to sign each request with a Google key file kept on the web host. That relay would hold a PHP worker for the whole cold start, which many WordPress hosts cut off at 30 seconds. The shared secret never reaches the browser either way, and the limits above bound what a stranger can cost.

### Costs

Free each month, per billing account: 180,000 vCPU-seconds, 360,000 GiB-seconds and 2 million requests ([Cloud Run pricing](https://cloud.google.com/run/pricing)). With request-based billing you pay only while an instance starts and handles requests, not while it sits idle.

| Item | Estimate |
| --- | --- |
| One cold start | About 60 s of startup at 4 vCPU (boosted) plus 10 s of boost after it, so about 280 vCPU-seconds and 210 GiB-seconds. About $0.007 at list price |
| Free tier | About 600 cold starts a month (20 a day). Visitors within 15 minutes of each other share one start |
| Questions while warm | Typed questions take milliseconds of CPU and voice about 2 to 3 seconds, which is small next to cold starts |
| Image storage | The compressed image is likely 1.5 to 2 GB, so about $0.10 to $0.20 a month above the free 0.5 GB |
| Builds and the secret | Free: 2,500 build-minutes, 6 secret versions and 10,000 secret reads a month |
| Worst case | One instance busy all month would be over $100 at list price. The $10 cap stops it long before |

These are estimates from local measurements. Step 7's cost check gives the real figure.

### Day-to-day

Paste the Step 1 variable block into Cloud Shell first.

| Task | How |
| --- | --- |
| Edit the FAQ | Nothing to do: the service reloads within a minute. Saving an FAQ entry also wakes a sleeping service, which counts as one cold start |
| Release a new version | Change the tag at the end of `IMAGE` (for example `:0.3.1`), run Step 3's build, then `gcloud run deploy org-faq-chatbot --image="$IMAGE" --region=$REGION`. Other settings carry over. If the plugin changed too, copy its folder again as in Step 6, item 1 |
| Change a setting | `gcloud run services update org-faq-chatbot --region=$REGION --memory=4Gi` (or `--cpu=4`, `--max-instances=2`, …) |
| Pause the chatbot | See [Pause and resume the chatbot](#pause-and-resume-the-chatbot). Nothing is deleted, and visitors see the offline message |
| Test on your computer instead | See [Run the service on your computer instead](#run-the-service-on-your-computer-instead). Cloud Run keeps its settings |
| Change the shared secret | `printf '%s' "$NEW" \| gcloud secrets versions add org-chatbot-shared-secret --data-file=-`, then `gcloud run services update org-faq-chatbot --region=$REGION --update-secrets=WP_SHARED_SECRET=org-chatbot-shared-secret:latest`, then put the new value in `wp-config.php` straight away. In between, a running service keeps answering from the FAQ it has, but one that starts up then can't load the FAQ. Finally destroy the old version in **Secret Manager** |
| Watch costs | Cap emails come at 50%, 80% and 100% of $10. Check **Billing → Reports** once a month |
| The spend cap triggered | The chatbot shows its offline message until the 1st. To restore it sooner, find the cause in **Metrics** (request count) and **Logs**, then open the budget from the spend cap banner, click **Edit budget → Lift spend cap**, and confirm. Service can take up to an hour to return |
| People change | Keep at least two Owners on the project |

### Pause and resume the chatbot

To stop all Cloud Run use without deleting anything, make the service private. Google then refuses every request before it reaches the container, so no instance starts and CPU and memory cost nothing, even when bots call the address. Only image storage is still billed (see Costs). The service, its settings, the secret and the WordPress setup all stay.

Run these in Cloud Shell with the Step 1 variables and `URL` set.

1. **Pause:**

   ```bash
   gcloud run services update org-faq-chatbot --region=$REGION --invoker-iam-check
   ```

   Visitors still see the chat button, but a question gets the offline message with your contact page and email straight away. The notice in **Chatbot → Settings** shows an HTTP 403 error until you resume. To hide the chat button as well, untick **Show the chatbot on public pages** there.
2. **Check it's paused.** This prints `403` while paused and `200` while running:

   ```bash
   curl -s -o /dev/null -w '%{http_code}\n' $URL/health
   ```

3. **Resume:**

   ```bash
   gcloud run services update org-faq-chatbot --region=$REGION --no-invoker-iam-check
   ```

   If you hid the chat button, tick **Show the chatbot on public pages** again. The first question after resuming waits through a cold start, with "Starting up the chatbot…" shown.

### Run the service on your computer instead

Use this to test or demo the chatbot without Cloud Run, for example to try a change before releasing it. Cloud Run keeps all its settings, and switching back takes a minute.

The catch: only the browser on the computer running the service can reach it. Every other visitor sees the offline message until you switch back, so use the staging site or a time when nobody else needs the chatbot.

You need Docker Desktop with at least 3 GB of memory for Docker, a clone of the `cloud-run` branch, and WordPress already connected (Step 6), because the local service uses the same shared secret.

1. **Leave Cloud Run as it is.** With 0 minimum instances it sleeps and costs nothing once WordPress stops calling it. To also stop anyone else waking it, make it private in Cloud Shell, with the Step 1 variables set:

   ```bash
   gcloud run services update org-faq-chatbot --region=$REGION --invoker-iam-check
   ```

2. **Create the settings file.** In your clone, copy `chatbot-service/.env.example` to `chatbot-service/.env` and set these four lines. `.env` is in `.gitignore`, so the secret stays out of the repository.

   ```
   WP_BASE_URL=https://www.your-site.org
   WP_SHARED_SECRET=<the same value as ORG_CHATBOT_SHARED_SECRET in wp-config.php>
   ALLOWED_ORIGINS=https://www.your-site.org
   ALLOW_PRIVATE_NETWORK=true
   ```

   Use the site's address with `https://` and no trailing slash. `ALLOW_PRIVATE_NETWORK=true` lets a page from your public site call a service on your own computer; never set it on a server. Leave `TRUST_PROXY_HEADERS` and `REPORT_IN_REQUEST` at `false`: nothing sits in front of the service, and your computer doesn't throttle it after a reply.

3. **Build and start it** from the root of your clone. The first build downloads the models into the image and takes a while; later builds reuse most of it.

   ```bash
   docker build -t org-faq-chatbot:local chatbot-service
   docker run -d --name chatbot-local --env-file chatbot-service/.env -p 127.0.0.1:8000:8000 org-faq-chatbot:local
   ```

   After about a minute, open http://127.0.0.1:8000/health. It should show `"status":"ok"`, `"entries"` above 0, and `"state":"ready"` under `asr`. A `403` in `last_error` means `WP_SHARED_SECRET` differs from `wp-config.php`.

4. **Point WordPress at it.** Note the Cloud Run address first (Step 5's `URL`), so you can put it back. In **Chatbot → Settings**, set **Chatbot service URL** to `http://127.0.0.1:8000` (plain `http` is allowed only for local addresses), untick **The service sleeps when nobody is chatting**, and save.

   The notice at the top will say "Chatbot service unreachable". Ignore it: that check runs on the WordPress server, which can't see your computer. For the same reason, saving an FAQ entry doesn't reload the FAQ straight away; the service picks up changes within a minute.

5. **Test it** in Chrome or Edge on the same computer: ask a typed and a spoken question on the site. If the browser asks to let the site access devices on your local network, allow it. If the chat says "not available", look in DevTools' Console for a CORS error (check `ALLOWED_ORIGINS`) or a blocked local-network request.

**To switch back to Cloud Run:**

1. In **Chatbot → Settings**, put the `https://org-faq-chatbot-….run.app` address back, tick **The service sleeps when nobody is chatting**, and save. The notice can show the old result for a minute; reload, and it should say "Service connected".
2. If you made Cloud Run private in item 1, make it public again:

   ```bash
   gcloud run services update org-faq-chatbot --region=$REGION --no-invoker-iam-check
   ```

3. Stop the local copy:

   ```bash
   docker stop chatbot-local
   ```

   Next time, `docker start chatbot-local` starts it with the same settings. After changing `.env` or rebuilding, run `docker rm chatbot-local` and then item 3's `docker run` again.

### Troubleshooting

Most problems show up in **Cloud Run → org-faq-chatbot → Logs**, or in the WordPress PHP error log (with `WP_DEBUG_LOG` on, `wp-content/debug.log`).

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Build stops with `PERMISSION_DENIED` | The build account lacks rights | Step 3, item 2 |
| Build stops after 10 minutes | Default build time limit | Keep `--timeout=3600s` |
| Deploy refuses `--no-invoker-iam-check` (`FAILED_PRECONDITION`) | The organization policy `run.managed.requireInvokerIam` is enforced | Ask an organization admin to exempt this project. The plugin needs a public service |
| Deploy says the startup probe failed | Loading took over 300 s, or ran out of memory | Read Logs; raise `--cpu` or `--memory` |
| Chat always says "not available", never "Starting up" | The serverless box isn't ticked, the URL is wrong, or the browser is blocked | Check **Chatbot → Settings**; in DevTools' Console look for a CORS error (the site's address must be in `ALLOWED_ORIGINS` exactly, with `https://` and no trailing slash) or a Content-Security-Policy error (Step 6, item 4) |
| "Starting up" ends in "not available" | The service started but has no FAQ | `curl $URL/health`: `last_error` explains it. A `403` means the secret in `wp-config.php` differs from Secret Manager. A timeout or `ConnectError` means a firewall blocks Google (Step 6, item 5) |
| Voice says it's unavailable, typing works | The speech model failed to load | `curl $URL/health` shows the `asr` state and error; usually memory |
| An FAQ edit doesn't show | The service refreshes about once a minute | Wait a minute; if it persists, check `last_error` in `/health` |
| Settings page says the service is asleep | Normal when nobody has chatted recently | Reload after a minute |
| Some visitors get "not available" during a busy moment, with `429` under **Metrics → Request count** | More than 20 requests at once on the single instance | Raise `--max-instances=2` (the spend cap still applies) |
| Everything stopped mid-month | The spend cap triggered | See Day-to-day |

### Sources

Checked on 17 November 2026. Prices and defaults can change.

- [Cloud Run pricing](https://cloud.google.com/run/pricing)
- [Cloud Run CPU limits and startup CPU boost](https://docs.cloud.google.com/run/docs/configuring/cpu)
- [Cloud Run health checks (startup probes)](https://docs.cloud.google.com/run/docs/configuring/healthchecks)
- [Cloud Run: allowing public access](https://docs.cloud.google.com/run/docs/authenticating/public)
- [Spend cap budgets](https://docs.cloud.google.com/billing/docs/how-to/budgets-spend-caps)
- [Spend caps generally available (Google Cloud blog)](https://cloud.google.com/blog/topics/cost-management/google-cloud-spend-caps-now-generally-available)
- [Cloud Build pricing](https://cloud.google.com/build/pricing)
- [Artifact Registry pricing](https://cloud.google.com/artifact-registry/pricing)
- [Secret Manager pricing](https://cloud.google.com/secret-manager/pricing)
- [Secure-by-default organizations](https://cloud.google.com/resource-manager/docs/secure-by-default-organizations)
- [Community thread: Cloud Run and X-Forwarded-For](https://discuss.google.dev/t/cloud-run-which-client-ip-can-i-safely-use-for-rate-limiting/409611)
