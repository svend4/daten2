import os, json, time, uuid
from flask import Flask, request, jsonify
import psycopg
import pika

app = Flask(__name__)

DB_DSN = os.environ["DATABASE_URL"]
AMQP_URL = os.environ.get("RABBITMQ_URL") or os.environ.get("AMQP_URL", "amqp://guest:guest@rabbitmq:5672/")

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
    email = (data.get("email") or "").strip()
    address = (data.get("address") or "").strip()
    items = data.get("items") or []

    if not name or not items:
        return jsonify({"error": "name/items required"}), 400

    order_number = uuid.uuid4().hex
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            # Позиции с серверными ценами и снимком названия
            priced = []
            subtotal = 0.0
            for it in items:
                pid = int(it.get("product_id") or 0)
                qty = int(it.get("quantity") or it.get("qty") or 1)
                if qty < 1:
                    continue
                cur.execute("SELECT name, price FROM products WHERE id=%s", (pid,))
                row = cur.fetchone()
                if not row:
                    continue
                pname, price = row[0], float(row[1])
                line_total = price * qty
                subtotal += line_total
                priced.append((pid, pname, qty, price, line_total))

            if not priced:
                return jsonify({"error": "no valid items"}), 400

            cur.execute(
                "INSERT INTO customers (name, phone, email, address) VALUES (%s, %s, %s, %s) RETURNING id",
                (name, phone, email, address),
            )
            customer_id = cur.fetchone()[0]

            cur.execute(
                """INSERT INTO orders
                   (order_number, customer_id, subtotal, total_amount, delivery_address, status, payment_status)
                   VALUES (%s, %s, %s, %s, %s, 'new', 'pending') RETURNING id""",
                (order_number, customer_id, subtotal, subtotal, address),
            )
            order_id = cur.fetchone()[0]

            for pid, pname, qty, price, line_total in priced:
                cur.execute(
                    """INSERT INTO order_items
                       (order_id, product_id, product_name, quantity, unit_price, line_total)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (order_id, pid, pname, qty, price, line_total),
                )
                cur.execute("UPDATE products SET stock = stock - %s WHERE id=%s", (qty, pid))

            cur.execute(
                "INSERT INTO order_status_history (order_id, status, note) VALUES (%s, 'new', 'Заказ создан')",
                (order_id,),
            )

    publish("order.created", {"order_number": order_number, "customer_name": name})
    return jsonify({"order_number": order_number, "total": subtotal}), 201

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "7002")))
