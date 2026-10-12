#!/usr/bin/env bash
# Ship HEAD to the VPS and rebuild. Usage: VPS_HOST=1.2.3.4 [VPS_USER=debian] [VPS_DIR=horilla-hr] scripts/deploy.sh
set -euo pipefail
: "${VPS_HOST:?set VPS_HOST}"
U="${VPS_USER:-debian}" D="${VPS_DIR:-horilla-hr}"
# .env and docker-compose.vps.yml live only on the server and are not in git, so tar -x never touches them.
git archive HEAD | ssh "$U@$VPS_HOST" "mkdir -p $D && tar -x -C $D"
ssh "$U@$VPS_HOST" "cd $D && docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.vps.yml up -d --build web scheduler mcp && docker image prune -f"
