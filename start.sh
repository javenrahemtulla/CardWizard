#!/usr/bin/env bash
# Start Card Wizard on this computer (Mac / Linux). Data is stored in ./data.
# A password is required because the site may be reachable from the internet through a tunnel.
set -e
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is not installed. Get it from https://www.python.org/downloads/ and run this again."
  exit 1
fi

if [ ! -d .venv ]; then
  echo "First run: installing (this takes a few minutes and downloads a ~100 MB search model on first use)..."
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
. .venv/bin/activate
pip install -q -r requirements.txt

if [ -z "$SITE_PASSWORD" ]; then
  if [ -f .password ]; then
    SITE_PASSWORD="$(cat .password)"
  else
    printf "Choose a password for the site (people will need it to open it): "
    read -r SITE_PASSWORD
    [ -n "$SITE_PASSWORD" ] || { echo "A password is required."; exit 1; }
    printf "%s" "$SITE_PASSWORD" > .password
    chmod 600 .password
  fi
fi
export SITE_PASSWORD

PORT="${PORT:-8000}"
echo "Card Wizard is running at http://localhost:$PORT  (username: anything, password: the one you chose)"
echo "Press Ctrl+C to stop."
exec python -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT"
