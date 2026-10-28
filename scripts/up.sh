#!/usr/bin/env bash
# Start the local Chatwoot, make its account, admin and API token the first time, and write them to .env.
# Every secret is generated here and stays in the git-ignored files docker/.env and .env; none is printed.
set -euo pipefail
cd "$(dirname "$0")/.."
dc() { docker compose -f docker/compose.yml --env-file docker/.env "$@"; }
rnd() { openssl rand -hex 16; }

if [ ! -f docker/.env ]; then
  pg=$(rnd); rd=$(rnd)
  cat > docker/.env <<ENV
SECRET_KEY_BASE=$(openssl rand -hex 64)
FRONTEND_URL=http://localhost:3010
FORCE_SSL=false
ENABLE_ACCOUNT_SIGNUP=false
REDIS_URL=redis://:$rd@redis:6379
REDIS_PASSWORD=$rd
POSTGRES_HOST=postgres
POSTGRES_USERNAME=postgres
POSTGRES_PASSWORD=$pg
RAILS_ENV=production
RAILS_LOG_TO_STDOUT=true
LOG_LEVEL=warn
ACTIVE_STORAGE_SERVICE=local
MAILER_SENDER_EMAIL=Harbor Trading <support@harbor-trading.example>
ADMIN_PASSWORD=$(rnd)Aa1!
ENV
  dc up -d postgres redis
  sleep 8
  dc run --rm rails bundle exec rails db:chatwoot_prepare >/dev/null
fi

dc up -d
echo "waiting for Chatwoot…"
for _ in $(seq 1 120); do
  curl -fsS -o /dev/null http://127.0.0.1:3010/api 2>/dev/null && break
  sleep 3
done

if ! grep -q '^CHATWOOT_TOKEN=' .env 2>/dev/null; then
  pw=$(grep '^ADMIN_PASSWORD=' docker/.env | cut -d= -f2-)
  out=$(dc exec -T -e ADMIN_PASSWORD="$pw" rails bundle exec rails r "$(cat scripts/setup.rb)" | tail -2)
  token=$(echo "$out" | sed -n 's/^TOKEN=//p'); account=$(echo "$out" | sed -n 's/^ACCOUNT=//p')
  [ -n "$token" ] && [ -n "$account" ] || { echo "could not create the API token" >&2; exit 1; }
  { echo "CHATWOOT_URL=http://127.0.0.1:3010"; echo "CHATWOOT_ACCOUNT=$account"; echo "CHATWOOT_TOKEN=$token"; } >> .env
  echo "account, admin and API token created (in docker/.env and .env)"
fi
echo "Chatwoot is up at http://localhost:3010"
