#!/usr/bin/env bash
# One-time setup of the chatbot service on macOS or Linux.
#
#   ./setup.sh          everything: packages, PyTorch (CPU) and the speech + embedding models
#   ./setup.sh --light  tests and widget work only, no models
#
# Models go to the Hugging Face cache (~/.cache/huggingface). Safe to run again.
set -euo pipefail

service="$(cd "$(dirname "$0")" && pwd)/chatbot-service"
venv="$service/.venv"
python="$venv/bin/python"

supported() {
  "$@" -c 'import sys; sys.exit(0 if sys.version_info[:2] in ((3, 12), (3, 13)) else 1)' 2>/dev/null
}

if [ -x "$python" ] && ! supported "$python"; then
  echo "chatbot-service/.venv uses an unsupported Python version. Delete it and run ./setup.sh again." >&2
  exit 1
fi

if [ ! -x "$python" ]; then
  # ESPnet supports Python 3.12 and 3.13 only (not 3.11, not 3.14).
  base=""
  for candidate in python3.13 python3.12 python3; do
    if command -v "$candidate" >/dev/null && supported "$candidate"; then base="$candidate"; break; fi
  done
  if [ -z "$base" ]; then
    echo "Python 3.12 or 3.13 is required. Install it (python.org, Homebrew or your package manager) and run ./setup.sh again." >&2
    exit 1
  fi
  echo "Creating chatbot-service/.venv with $base"
  "$base" -m venv "$venv"
fi

"$python" -m pip install --upgrade pip
"$python" -m pip install -r "$service/requirements-dev.txt"

if [ "${1:-}" != "--light" ]; then
  # CPU-only PyTorch first, so pip does not pull the much larger CUDA build.
  "$python" -m pip install --index-url https://download.pytorch.org/whl/cpu "torch==2.11.*" "torchaudio==2.11.*"
  "$python" -m pip install -r "$service/requirements-ml.txt"
  (cd "$service" && "$python" scripts/download_models.py)
fi

echo
echo "Setup complete. Next:"
echo "  cd chatbot-service && . .venv/bin/activate"
echo "  pytest"
if [ "${1:-}" = "--light" ]; then
  echo '  python scripts/dev_server.py --fake-asr "how can i volunteer"'
else
  echo "  python scripts/dev_server.py"
fi
