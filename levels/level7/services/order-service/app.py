import os, json, time
from flask import Flask, request, jsonify
import psycopg
import pika

app = Flask(__name__)

DB_DSN = os.environ["DATABASE_URL"]
AMQP_URL = os.environ.get("AMQP_URL", "amqp://guest:guest@rabbitmq:5672/")

def publish(event: str, payload: dict):
    params = pika.URLParameters(AMQP_URL)
    for _ in range(20):
        try:
            conn = pika.BlockingConnection(params)
            ch = conn.channel()
            ch.queue_declare(queue="events", durable=True)
            body = json.dumps({"event": event, "payload": payload}, ensure_ascii=False).encode("utf-8")
            ch.basic_publish(exchange="", routing_key="events", body=body)
            conn.close()
            return
        except Exception:
            time.sleep(1)

@app.get("/health")
def health():
    return jsonify({"ok": True})

@app.post("/api/orders")
def create_order():
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    phone = (data.get("phone") or "").strip()
    items = data.get("items") or []

    if not name or not items:
        return jsonify({"error": "name/items required"}), 400

    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO orders (customer_name, phone) VALUES (%s, %s) RETURNING id", (name, phone))
            order_id = cur.fetchone()[0]

            for it in items:
                pid = int(it.get("product_id") or 0)
                qty = int(it.get("qty") or 1)
                cur.execute("SELECT price FROM products WHERE id=%s", (pid,))
                row = cur.fetchone()
                price = float(row[0]) if row else 0.0
                cur.execute(
                    "INSERT INTO order_items (order_id, product_id, qty, price) VALUES (%s, %s, %s, %s)",
                    (order_id, pid, qty, price),
                )

    publish("order.created", {"order_id": order_id, "customer_name": name})
    return jsonify({"order_id": order_id})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "7002")))
