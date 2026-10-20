"""Tiny banking API used to show that it does not matter which Pod serves a request.

Nothing is kept in Pod memory:
  - login state lives in a signed JWT (any Pod can verify it with the shared secret)
  - balances live in PostgreSQL (every Pod talks to the same DB Service)
Every response includes "served_by" so you can see which Pod answered.
"""
import os
import socket
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import psycopg2
from flask import Flask, jsonify, request

POD = os.environ.get("POD_NAME", socket.gethostname())
JWT_SECRET = os.environ["JWT_SECRET"]
DB = dict(
    host=os.environ.get("DB_HOST", "bank-db"),
    dbname=os.environ.get("DB_NAME", "bank"),
    user=os.environ.get("DB_USER", "bank"),
    password=os.environ["DB_PASSWORD"],
)

app = Flask(__name__)


def db():
    return psycopg2.connect(**DB)


def reply(body, status=200):
    return jsonify({"served_by": POD, **body}), status


def current_user():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    try:
        return jwt.decode(auth[7:], JWT_SECRET, algorithms=["HS256"])["sub"]
    except jwt.InvalidTokenError:
        return None


@app.get("/healthz")
def healthz():
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1")
    return reply({"ok": True})


@app.post("/login")
def login():
    data = request.get_json(force=True)
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT password FROM users WHERE username = %s", (data.get("username"),))
        row = cur.fetchone()
    if not row or row[0] != data.get("password"):  # plain-text passwords: demo only
        return reply({"error": "invalid credentials"}, 401)
    token = jwt.encode(
        {"sub": data["username"], "exp": datetime.now(timezone.utc) + timedelta(minutes=30)},
        JWT_SECRET,
        algorithm="HS256",
    )
    return reply({"user": data["username"], "token": token})


@app.get("/balance")
def balance():
    user = current_user()
    if not user:
        return reply({"error": "not logged in"}, 401)
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT balance FROM accounts WHERE owner = %s", (user,))
        (bal,) = cur.fetchone()
    return reply({"user": user, "balance": bal})


@app.post("/transfer")
def transfer():
    user = current_user()
    if not user:
        return reply({"error": "not logged in"}, 401)
    data = request.get_json(force=True)
    to, amount = data.get("to"), int(data.get("amount", 0))
    request_id = data.get("request_id") or str(uuid.uuid4())
    if amount <= 0 or to == user:
        return reply({"error": "invalid transfer"}, 400)

    conn = db()
    try:
        with conn, conn.cursor() as cur:  # one DB transaction: commit on success, rollback on error
            # Idempotency: the same request_id is only ever applied once, whichever Pod gets it.
            cur.execute(
                "INSERT INTO transfers (request_id, from_owner, to_owner, amount) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT (request_id) DO NOTHING",
                (request_id, user, to, amount),
            )
            if cur.rowcount == 0:
                return reply({"request_id": request_id, "status": "duplicate, already applied"})

            # Lock both rows (in a fixed order) so concurrent transfers on other Pods wait.
            cur.execute(
                "SELECT owner, balance FROM accounts WHERE owner IN (%s, %s) ORDER BY owner FOR UPDATE",
                (user, to),
            )
            balances = dict(cur.fetchall())
            if to not in balances:
                conn.rollback()
                return reply({"error": "unknown recipient"}, 400)
            if balances[user] < amount:
                conn.rollback()
                return reply({"error": "insufficient funds"}, 400)

            cur.execute("UPDATE accounts SET balance = balance - %s WHERE owner = %s", (amount, user))
            cur.execute("UPDATE accounts SET balance = balance + %s WHERE owner = %s", (amount, to))
        return reply({"request_id": request_id, "status": "ok", "from": user, "to": to, "amount": amount})
    finally:
        conn.close()
