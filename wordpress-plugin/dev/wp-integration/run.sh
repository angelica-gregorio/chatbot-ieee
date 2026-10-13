#!/usr/bin/env bash
# Integration test of the plugin on a real, throwaway WordPress site.
#
# Downloads WordPress and the official SQLite database driver (no MySQL needed),
# installs the plugin, enters the sample FAQ as real FAQ posts, starts the
# chatbot service against the site, and runs:
#   integration.py  - REST endpoints, shared secret, disabled entries, redacted
#                     log, FR-23 AC1 refresh webhook, widget and [org_faq] output
#   admin_e2e.py    - headless Chromium: widget on the front page, admin log,
#                     "Create FAQ entry", Chatbot box, deletes, settings save
# and fails if the plugin logs any PHP notice or warning.
#
# Needs: git, PHP 8.1+ with pdo_sqlite, the service venv (chatbot-service/.venv),
# and Playwright with Chromium for python3.
#
# Usage: wordpress-plugin/dev/wp-integration/run.sh
#        WP_TEST_DIR=/tmp/wp-test WP_VERSION=7.1.3 wordpress-plugin/dev/wp-integration/run.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HERE/../../.." && pwd)"
export REPO_ROOT
export WP_TEST_DIR="${WP_TEST_DIR:-$(mktemp -d)}"
WP_VERSION="${WP_VERSION:-7.1.3}"
SQLITE_VERSION="${SQLITE_VERSION:-v3.1.0}"
SERVICE_PYTHON="${SERVICE_PYTHON:-$REPO_ROOT/chatbot-service/.venv/bin/python}"

echo "Test site: $WP_TEST_DIR (WordPress $WP_VERSION, SQLite driver $SQLITE_VERSION)"
mkdir -p "$WP_TEST_DIR"
cd "$WP_TEST_DIR"
[ -d site ] || git clone -q --depth 1 --branch "$WP_VERSION" https://github.com/WordPress/WordPress.git site
[ -d sqlite ] || git clone -q --depth 1 --branch "$SQLITE_VERSION" https://github.com/WordPress/sqlite-database-integration.git sqlite

rm -rf site/wp-content/plugins/sqlite-database-integration site/wp-content/plugins/org-chatbot site/wp-content/database
cp -rL sqlite/packages/plugin-sqlite-database-integration site/wp-content/plugins/sqlite-database-integration
cp site/wp-content/plugins/sqlite-database-integration/db.copy site/wp-content/db.php
cp -r "$REPO_ROOT/wordpress-plugin/org-chatbot" site/wp-content/plugins/org-chatbot
cp "$HERE/wp-config.php" site/wp-config.php

php "$HERE/install.php" 2>/dev/null
php "$HERE/activate.php" 2>/dev/null
: > site/wp-content/debug.log
php "$HERE/setup.php" 2>/dev/null

PHP_CLI_SERVER_WORKERS=4 php -S 127.0.0.1:8090 -t "$WP_TEST_DIR/site" "$HERE/router.php" > "$WP_TEST_DIR/php-server.log" 2>&1 &
PHP_PID=$!
(
  cd "$REPO_ROOT/chatbot-service"
  WP_BASE_URL=http://127.0.0.1:8090 WP_SHARED_SECRET=test-secret MATCHER=lexical ASR_ENABLED=false \
  ALLOWED_ORIGINS=http://127.0.0.1:8090 KB_TTL_SECONDS=600 \
  exec "$SERVICE_PYTHON" -m uvicorn app.main:app_factory --factory --host 127.0.0.1 --port 8000 --no-access-log
) > "$WP_TEST_DIR/service.log" 2>&1 &
SERVICE_PID=$!
trap 'kill $PHP_PID $SERVICE_PID 2>/dev/null || true' EXIT

for _ in $(seq 1 60); do
  curl -sf http://127.0.0.1:8090/ >/dev/null && curl -sf http://127.0.0.1:8000/health >/dev/null && break
  sleep 0.5
done

status=0
python3 "$HERE/integration.py" || status=1
python3 "$HERE/admin_e2e.py" || status=1

if grep -qi "org-chatbot\|org_chatbot" site/wp-content/debug.log; then
  echo "FAIL PHP notices or warnings from the plugin:"; grep -i "org-chatbot\|org_chatbot" site/wp-content/debug.log | head
  status=1
else
  echo "PASS No PHP notices or warnings from the plugin"
fi
echo "Screenshots and logs: $WP_TEST_DIR"
exit $status
