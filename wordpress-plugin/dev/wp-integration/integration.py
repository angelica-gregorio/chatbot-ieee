import os
import json, subprocess, time, urllib.request, urllib.error
S = os.environ["WP_TEST_DIR"]
HERE = os.path.dirname(os.path.abspath(__file__))
WP, SVC = "http://127.0.0.1:8090", "http://127.0.0.1:8000"
results = []
def req(url, data=None, headers=None, method=None):
    body = json.dumps(data).encode() if data is not None else None
    r = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", **(headers or {})}, method=method)
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")
def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
def php(script):
    return subprocess.run(["php", os.path.join(HERE, script)], capture_output=True, text=True).stdout.strip()

kb_url = WP + "/wp-json/org-chatbot/v1/kb"
code, _ = req(kb_url); check("KB endpoint rejects missing key", code == 403, code)
code, _ = req(kb_url, headers={"X-Org-Chatbot-Key": "wrong"}); check("KB endpoint rejects wrong key", code == 403, code)
code, kb = req(kb_url, headers={"X-Org-Chatbot-Key": "test-secret"})
titles = [e["question"] for e in kb["entries"]]
check("KB endpoint returns enabled entries only", code == 200 and len(kb["entries"]) == 12 and "What is the secret handshake?" not in titles, f"{len(kb['entries'])} entries")
check("Concerns without a valid email are not published", [c["key"] for c in kb["concerns"]] == ["general","events","membership","partnerships","media"], [c["key"] for c in kb["concerns"]])
member = next(e for e in kb["entries"] if e["question"] == "How do I become a member?")
check("Entry carries alt questions, concern, FAQ-page anchor, links", member["alt_questions"] and member["concern"] == "membership" and member["url"].endswith(f"/faq/#faq-{member['id']}") and member["links"], member["url"])

code, r = req(SVC + "/v1/chat", {"message": "How do I join your org?"})
check("Service answers from WordPress FAQ (post id)", r["type"] == "answer" and r["faq_id"] == member["id"], f"faq_id={r.get('faq_id')}")
code, r = req(SVC + "/v1/chat", {"message": "what is the secret handshake"})
check("Disabled FAQ entry is never answered", r["type"] == "fallback", r["type"])
code, r = req(SVC + "/v1/chat", {"message": "My name is Juan Dela Cruz, is parking free? juan@mail.com"})
check("Unmatched question gets fallback", r["type"] == "fallback", r["type"])
time.sleep(1.5)
code, _ = req(WP + "/wp-json/org-chatbot/v1/unanswered", {"question": "call me at 0917 123 4567 about sponsorship", "source": "voice"}, {"X-Org-Chatbot-Key": "test-secret"})
check("Unanswered endpoint accepts service reports", code == 201, code)
code, _ = req(WP + "/wp-json/org-chatbot/v1/unanswered", {"question": "x"}, {"X-Org-Chatbot-Key": "nope"})
check("Unanswered endpoint rejects wrong key", code == 403, code)
log = json.loads(php("read_log.php") or "[]")
texts = " | ".join(row["question"] for row in log)
check("Log stores redacted text only (service + WordPress redaction)", len(log) == 3 and "Juan" not in texts and "juan@" not in texts and "0917" not in texts and "[phone]" in texts, texts)
spoken = [row for row in log if row["question"].startswith("call me")]
check("Log counts spoken questions", spoken and spoken[0]["times_spoken"] in (1, "1"), spoken)

before = req(SVC + "/health")[1]["knowledge_base"]["version"]
php("edit_faq.php")
deadline, text = time.time() + 15, ""
while time.time() < deadline:
    text = req(SVC + "/v1/chat", {"message": "How do I become a member?"})[1].get("text", "")
    if text.startswith("Edited via WordPress"):
        break
    time.sleep(0.5)
after = req(SVC + "/health")[1]["knowledge_base"]["version"]
check("FR-23 AC1: edited answer live via refresh webhook, no redeploy (TTL=600 s)", text.startswith("Edited via WordPress") and before != after, f"{text!r}, kb {before}->{after}")

home = urllib.request.urlopen(WP + "/", timeout=10).read().decode()
check("Widget script and config printed on public pages", "chat-widget.js" in home and "orgChatbotConfig" in home and '"serviceUrl":"http:\\/\\/127.0.0.1:8000"' in home)
faq = urllib.request.urlopen(WP + "/faq/", timeout=10).read().decode()
check("[org_faq] renders <details> entries with anchors", f'id="faq-{member["id"]}"' in faq and "<details" in faq and "secret handshake" in faq)
for name, ok, detail in results:
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))
raise SystemExit(0 if all(ok for _, ok, _ in results) else 1)
