import os
from playwright.sync_api import sync_playwright, expect
S = os.environ["WP_TEST_DIR"]
HERE = os.path.dirname(os.path.abspath(__file__))
WP = "http://127.0.0.1:8090"
results = []
def check(name, fn):
    try:
        results.append((name, True, fn() or ""))
    except Exception as e:
        results.append((name, False, str(e).splitlines()[0][:200]))
with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    def widget_on_wp():
        page.goto(WP + "/")
        page.locator(".org-chatbot__launcher").click()
        page.locator("#org-chatbot-input").fill("Where is the sign-up form for events?")
        page.keyboard.press("Enter")
        expect(page.locator(".org-chatbot__msg--bot:not(.is-pending)").nth(1)).to_contain_text("registration form on that page")
        page.screenshot(path=f"{S}/wp-front.png")
    check("Widget on the real WordPress front page answers (CORS ok)", widget_on_wp)

    def login():
        page.goto(WP + "/wp-login.php")
        page.fill("#user_login", "admin"); page.fill("#user_pass", "local-test-pass-123")
        page.click("#wp-submit"); page.wait_for_url("**/wp-admin/**")
    check("Admin login", login)

    def log_screen():
        page.goto(WP + "/wp-admin/admin.php?page=org-chatbot")
        expect(page.locator("h1")).to_have_text("Unanswered questions")
        rows = page.locator("table.wp-list-table tbody tr")
        expect(rows).to_have_count(3)
        expect(page.locator("table.wp-list-table")).to_contain_text("[name]")
        page.screenshot(path=f"{S}/wp-log.png", full_page=True)
        return f"{rows.count()} rows"
    check("Unanswered log screen lists redacted questions", log_screen)

    def create_faq_prefill():
        link = page.locator("table.wp-list-table tbody tr").filter(has_text="secret handshake").get_by_role("link", name="Create FAQ entry")
        href = link.get_attribute("href")
        page.goto(WP + "/wp-admin/" + href.split("/wp-admin/")[-1] if "/wp-admin/" in href else href)
        page.wait_for_timeout(4000)
        title = page.evaluate("() => (window.wp && wp.data) ? wp.data.select('core/editor').getEditedPostAttribute('title') : document.title")
        assert "secret handshake" in title, title
        return title
    check("'Create FAQ entry' pre-fills the question as the title", create_faq_prefill)

    def chatbot_box():
        expect(page.locator("#org-chatbot")).to_be_attached(timeout=15000)
        assert page.locator("textarea[name='org_chatbot_alt_questions']").count() == 1
    check("FAQ editor shows the Chatbot box", chatbot_box)

    def delete_row():
        page.goto(WP + "/wp-admin/admin.php?page=org-chatbot")
        page.locator("table.wp-list-table tbody tr").filter(has_text="secret handshake").locator("button[name='org_chatbot_delete']").click(force=True)
        page.wait_for_url("**page=org-chatbot**")
        expect(page.locator("table.wp-list-table tbody tr")).to_have_count(2)
    check("Row delete works (nonce-protected POST)", delete_row)

    def bulk_delete():
        page.locator("table.wp-list-table tbody tr").first.locator("input[name='ids[]']").check()
        page.select_option("#org-chatbot-bulk", "delete")
        page.get_by_role("button", name="Apply").click()
        page.wait_for_url("**page=org-chatbot**")
        expect(page.locator("table.wp-list-table tbody tr")).to_have_count(1)
    check("Bulk delete works (no clash with admin-post action)", bulk_delete)

    def settings_screen():
        page.goto(WP + "/wp-admin/admin.php?page=org-chatbot-settings")
        expect(page.locator(".notice")).to_contain_text("Service connected: 12 FAQ entries loaded, lexical matcher")
        expect(page.locator("text=Set by ORG_CHATBOT_SHARED_SECRET in wp-config.php.")).to_be_visible()
        page.screenshot(path=f"{S}/wp-settings.png", full_page=True)
    check("Settings screen shows live service status", settings_screen)

    def settings_save():
        page.fill("input[name='org_chatbot_settings[concerns][4][keywords]'], textarea[name='org_chatbot_settings[concerns][4][keywords]']", "media, press, journalist, interview, photographer")
        page.fill("#ocb-service", "http://chatbot.example.org")
        page.locator("#submit").click()
        page.wait_for_load_state()
        expect(page.locator("#setting-error-service_url")).to_be_visible()
        page.fill("#ocb-service", "http://127.0.0.1:8000")
        page.locator("#submit").click()
        page.wait_for_load_state()
        expect(page.locator("textarea[name='org_chatbot_settings[concerns][4][keywords]']")).to_have_value("media, press, journalist, interview, photographer")
        expect(page.locator("textarea[name='org_chatbot_settings[concerns][1][links]']")).to_have_value("Events | https://example.org/events/")
    check("Settings form saves; plain-http public URL rejected; links survive", settings_save)

    results.append(("No JavaScript errors", not errors, "; ".join(errors)[:200]))
    b.close()
for n, ok, d in results:
    print(("PASS " if ok else "FAIL ") + n + (f"  [{d}]" if d else ""))
raise SystemExit(0 if all(ok for _, ok, _ in results) else 1)
