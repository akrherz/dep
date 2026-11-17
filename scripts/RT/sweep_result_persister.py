"""Persist the SWEEP results to a database."""

import json
import signal
import threading
import time
import traceback
from queue import Queue

from pika.exceptions import AMQPConnectionError
from pyiem.database import get_dbconnc

from dailyerosion.util import get_rabbitmqconn
from dailyerosion.workflows import QUEUES
from dailyerosion.workflows.sweeprun import SweepJobResult

RECONNECT_DELAY_SECONDS = 5


def _handle_sigterm(_signum, _frame):
    """Handle SIGTERM signal."""
    raise KeyboardInterrupt()


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
    signal.signal(signal.SIGTERM, _handle_sigterm)
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

    worker_thread = threading.Thread(target=db_worker, daemon=True)
    worker_thread.start()

    def callback(ch, method, _properties, body):
        """Run in a thread."""
        try:
            result = SweepJobResult(**json.loads(body))
            db_queue.put(result)
        except Exception as exp:
            print(f"Error processing message: {exp}")
        finally:
            ch.basic_ack(delivery_tag=method.delivery_tag)

    while True:
        connection = None
        channel = None
        try:
            connection, _config = get_rabbitmqconn()
            channel = connection.channel()
            channel.queue_declare(queue=QUEUES.SWEEP_RESULTS, durable=True)
            channel.basic_consume(
                queue=QUEUES.SWEEP_RESULTS, on_message_callback=callback
            )
            queue_name = QUEUES.SWEEP_RESULTS
            print(
                f"Waiting for messages in '{queue_name}'. "
                "Press Ctrl+C to exit."
            )
            channel.start_consuming()
        except KeyboardInterrupt:
            print("Exiting...")
            break
        except AMQPConnectionError as exp:
            print(
                "RabbitMQ connection lost: "
                f"{exp}. Reconnecting in {RECONNECT_DELAY_SECONDS}s...\n"
                f"{traceback.format_exc()}"
            )
            time.sleep(RECONNECT_DELAY_SECONDS)
        except Exception as exp:
            print(
                "Unexpected RabbitMQ consumer error: "
                f"{exp}. Reconnecting in {RECONNECT_DELAY_SECONDS}s..."
            )
            time.sleep(RECONNECT_DELAY_SECONDS)
        finally:
            if channel is not None and channel.is_open:
                channel.close()
            if connection is not None and connection.is_open:
                connection.close()

    db_queue.put(None)  # Stop db_worker
    worker_thread.join(timeout=5)
    if worker_thread.is_alive():
        print(
            "Warning: db_worker did not finish within timeout; "
            "some results may not have been persisted."
        )


if __name__ == "__main__":
    main()
