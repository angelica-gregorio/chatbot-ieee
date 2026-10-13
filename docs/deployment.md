# Deployment

Follow NFR-SAF-02: every step below goes to **staging first**, passes the smoke checks, and is logged before it reaches production.

## 1. Choose where the service runs

The service is a standard Docker container. It needs a public HTTPS address the visitor's browser can reach, outbound access to the WordPress site, and enough CPU for the speech model (101M parameters, padded to 30 s of audio per question).

| Option | Notes |
| --- | --- |
| Organization or school server / VM | Usually the cheapest; put it behind the existing reverse proxy for HTTPS |
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
