import os, json, time
import pika

AMQP_URL = os.environ.get("AMQP_URL", "amqp://guest:guest@rabbitmq:5672/")

def main():
    params = pika.URLParameters(AMQP_URL)
    while True:
        try:
            conn = pika.BlockingConnection(params)
            ch = conn.channel()
            ch.queue_declare(queue="events", durable=True)

            def callback(ch, method, properties, body):
                msg = json.loads(body.decode("utf-8"))
                print("NOTIFY:", msg)
                ch.basic_ack(delivery_tag=method.delivery_tag)

            ch.basic_qos(prefetch_count=5)
            ch.basic_consume(queue="events", on_message_callback=callback)
            print("notification-service listening on queue=events")
            ch.start_consuming()
        except Exception as e:
            print("retry:", e)
            time.sleep(2)

if __name__ == "__main__":
    main()
