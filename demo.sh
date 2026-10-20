#!/usr/bin/env bash
# Login, transfer, and check balances. Each call is a new connection, so the
# Service can send it to any of the app Pods. Watch "served_by" change while
# the token and balances stay consistent.
set -euo pipefail

URL="${URL:-http://$(minikube ip):30080}"
json() { python3 -c "import sys,json; print(json.load(sys.stdin)$1)"; }
show() { python3 -c "import sys,json; d=json.load(sys.stdin); p=d.pop('served_by'); d.pop('token',None); print(f'  served_by {p:<28} {d}')"; }

echo "== 1. Login as alice"
LOGIN=$(curl -s -X POST "$URL/login" -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":"alice123"}')
echo "$LOGIN" | show
TOKEN=$(echo "$LOGIN" | json "['token']")
AUTH="Authorization: Bearer $TOKEN"

echo; echo "== 2. Balance before (token from step 1 works on any Pod)"
for i in 1 2 3; do curl -s "$URL/balance" -H "$AUTH" | show; done

echo; echo "== 3. Transfer 2000 alice -> bob"
REQ_ID="demo-$(date +%s)"
curl -s -X POST "$URL/transfer" -H "$AUTH" -H 'Content-Type: application/json' \
  -d "{\"to\":\"bob\",\"amount\":2000,\"request_id\":\"$REQ_ID\"}" | show

echo; echo "== 4. Same request retried (e.g. client timeout) - applied only once, whichever Pod gets it"
for i in 1 2; do
  curl -s -X POST "$URL/transfer" -H "$AUTH" -H 'Content-Type: application/json' \
    -d "{\"to\":\"bob\",\"amount\":2000,\"request_id\":\"$REQ_ID\"}" | show
done

echo; echo "== 5. Balance after - same answer from every Pod"
for i in 1 2 3 4 5 6; do curl -s "$URL/balance" -H "$AUTH" | show; done
