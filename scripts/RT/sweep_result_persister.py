"""Persist the SWEEP results to a database."""

import json
import threading
from queue import Queue

from pyiem.database import get_dbconnc

from dailyerosion.util import get_rabbitmqconn
from dailyerosion.workflows.sweeprun import SweepJobResult

RABBITMQ_QUEUE = "sweep_results"


# Placeholder for database persistence


def persist_to_database(cursor, result: SweepJobResult):
    """Insert the result into the database."""
    cursor.execute(
        """
    insert into field_wind_erosion_results (field_id, scenario_id,
    valid, erosion_kgm2, avg_wind_speed_mps, max_wind_speed_mps, drct) values
    (%s,%s,%s,%s,%s,%s,%s)
    """,
        (
            result.field_id,
            result.scenario,
            result.dt,
            result.erosion,
            result.avg_wmps,
            result.max_wmps,
            result.drct,
        ),
    )


def main():
    """Go Main Go."""
    connection, _config = get_rabbitmqconn()
    channel = connection.channel()
    channel.queue_declare(queue=RABBITMQ_QUEUE, durable=True)

    db_queue = Queue()

    def db_worker():
        """Run in a thread."""
        conn, cursor = get_dbconnc("dep")
        while True:
            result = db_queue.get()
            if result is None:
                break
            try:
                persist_to_database(cursor, result)
                conn.commit()
            except Exception as exp:
                print(f"Error persisting to database: {exp}, reconnecting")
                conn, cursor = get_dbconnc("dep")
            db_queue.task_done()

    threading.Thread(target=db_worker, daemon=True).start()

    def callback(ch, method, _properties, body):
        """Run in a thread."""
        try:
            result = SweepJobResult(**json.loads(body))
            db_queue.put(result)
        except Exception as exp:
            print(f"Error processing message: {exp}")
        finally:
            ch.basic_ack(delivery_tag=method.delivery_tag)

    channel.basic_consume(queue=RABBITMQ_QUEUE, on_message_callback=callback)
    print(f"Waiting for messages in '{RABBITMQ_QUEUE}'. Press Ctrl+C to exit.")
    try:
        channel.start_consuming()
    except KeyboardInterrupt:
        print("Exiting...")
        channel.stop_consuming()
        db_queue.put(None)  # Stop db_worker
    connection.close()


if __name__ == "__main__":
    main()
