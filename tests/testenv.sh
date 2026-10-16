#!/bin/bash
# Disposable test environment: a copy of the newest backup in database pos_test,
# a second API on 127.0.0.1:8015 and nginx serving the frontend on 127.0.0.1:8095.
# It serves the checkout it lives in, so a git worktree (e.g. /pos-dev) tests its own
# code while /pos stays live. The admin account's password is set to the one in tests/auth.py.
#   ./testenv.sh up     restore the latest dump and start everything
#   ./testenv.sh down   stop the API, remove the nginx site, drop pos_test
set -e

ROOT=$(cd "$(dirname "$0")/.." && pwd)
BACKEND=$ROOT/backend
SITE=/etc/nginx/sites-enabled/pos-test

stop_api() {
  for pid in $(ss -ltnp | grep ':8015 ' | grep -o 'pid=[0-9]*' | cut -d= -f2); do kill "$pid"; done
}

up() {
  stop_api
  local dump
  dump=$(ls -t /root/backups/pos/*.dump | head -1)
  echo "Restoring $dump"
  sudo -u postgres dropdb --if-exists pos_test
  sudo -u postgres createdb -O pos_user pos_test
  sudo -u postgres pg_restore -d pos_test --no-owner --role=pos_user < "$dump"

  local url
  url=$(grep DATABASE_URL "$BACKEND/.env" | cut -d= -f2- | sed 's#/pos_db$#/pos_test#')
  # The suites sign in as this admin (tests/auth.py, tests/auth.js); the test copy only.
  (cd "$BACKEND" && DATABASE_URL="$url" venv/bin/python -c \
    "import asyncio, manage; asyncio.run(manage.set_password('admin', 'test-admin-pass'))")
  (cd "$BACKEND" && DATABASE_URL="$url" setsid nohup venv/bin/uvicorn main:app --host 127.0.0.1 --port 8015 \
    > /tmp/pos-test.log 2>&1 < /dev/null &)

  cat > "$SITE" <<EOF
server {
    listen 127.0.0.1:8095;
    root $ROOT/frontend;
    index index.html;
    location /api/ { proxy_pass http://127.0.0.1:8015; }
    location / { try_files \$uri \$uri/ /index.html; add_header Cache-Control "no-store"; }
}
EOF
  nginx -t -q && systemctl reload nginx
  sleep 4
  [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8095/api/settings)" = 401 ] && echo "Test env up: http://127.0.0.1:8095 (log: /tmp/pos-test.log)"
}

down() {
  stop_api
  rm -f "$SITE"
  nginx -t -q && systemctl reload nginx
  sleep 1
  sudo -u postgres dropdb --if-exists pos_test
  echo "Test env removed"
}

case "$1" in
  up) up ;;
  down) down ;;
  *) echo "usage: $0 up|down"; exit 1 ;;
esac
