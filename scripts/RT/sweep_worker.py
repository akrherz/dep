"""We do work when jobs are placed in the queue."""

import shutil
import subprocess
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory

import click
import requests
from lxml import etree
from metpy.calc import wind_direction
from metpy.units import units
from pika.channel import Channel
from pydantic import ValidationError
from pyiem.util import logger

from dailyerosion.util import get_rabbitmqconn
from dailyerosion.workflows import QUEUES
from dailyerosion.workflows.sweeprun import SweepJobPayload, SweepJobResult
from dailyerosion.workflows.worker import sanitize_exe

LOG = logger()
MEMORY = {
    "runs": 0,
    "timestamp": time.time(),
}
IEMRE = "http://mesonet.agron.iastate.edu/iemre/hourly"
BINPATH = Path("/opt/dep/bin")


def drain(ch, delivery_tag, _payload):
    """NOOP to clear out the queue via a hackery"""
    cb = partial(ack_message, ch, delivery_tag)
    ch.connection.add_callback_threadsafe(cb)


def run_command(cmd: list[str], tempdir: str) -> bool:
    """Common command running logic."""
    with subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=tempdir
    ) as proc:
        (stdout, stderr) = proc.communicate()
        if proc.returncode != 0:
            LOG.error(
                "Command %s failed with %s\n%s",
                " ".join(cmd),
                stdout.decode("utf-8"),
                stderr.decode("utf-8"),
            )
            return False
    return True


def get_wind_obs(dt: date, lon: float, lat: float) -> list[float, list[float]]:
    """Get what we need from IEMRE."""
    # Hopefully the two decimal degrees results in some caching
    uri = f"{IEMRE}/{dt:%Y-%m-%d}/{lat:.2f}/{lon:.2f}/json"
    attempts = 0
    res = {"data": []}
    while attempts < 3:
        try:
            resp = requests.get(uri, timeout=30)
            resp.raise_for_status()
            res = resp.json()
            break
        except Exception as exp:
            print(uri)
            LOG.exception(exp)
        attempts += 1
        if attempts == 3:
            LOG.warning("Failed to get %s, returning 1s", uri)
            return [1.0] * 24
    hourly = []
    drct = 0
    maxvel = 0
    for entry in res["data"]:
        try:
            vel = (entry["uwnd_mps"] ** 2 + entry["vwnd_mps"] ** 2) ** 0.5
            if vel > maxvel:
                maxvel = vel
                drct = wind_direction(
                    entry["uwnd_mps"] * units("m/s"),
                    entry["vwnd_mps"] * units("m/s"),
                ).magnitude
        except Exception:
            vel = 1.0
        hourly.append(vel)
    for _i in range(len(hourly), 24):
        hourly.append(1.0)
    return drct, hourly


def run_sweep(tempdir: str, payload: SweepJobPayload) -> SweepJobResult | None:
    """Actually run wepp, really.

    Parameters
    ----------
    payload : SweepJobPayload
        Validated SWEEP job payload containing runfile content and executable.
    """
    # Build the SWEEP XML filepath
    basefn = (
        Path("/i")
        / f"{payload.scenario}"
        / "sweepin"
        / f"{payload.huc_12[:8]}"
        / f"{payload.huc_12[8:12]}"
        / f"{payload.huc_12}_{payload.fpath}"
    )
    # Get the wind information
    drct, windobs = get_wind_obs(payload.dt, payload.lon, payload.lat)
    # Load the XML
    tree = etree.parse(str(basefn) + ".sweep")
    # Update the XML with the provided content
    root = tree.getroot()
    # Update the hourly wind information found in the XML file at
    # sweepData/SCI_WindSpeeds/SCI_WindSpeed
    wind_nodes = root.findall("./SCI_WindSpeeds/SCI_WindSpeed")
    if len(wind_nodes) != 24:
        raise ValueError(
            f"Expected 24 SCI_WindSpeed nodes in {basefn}, found "
            f"{len(wind_nodes)}"
        )
    if len(windobs) != 24:
        raise ValueError(
            f"Expected 24 hourly wind values, found {len(windobs)}"
        )

    # Honor SCI_index if present so we always set the intended hour.
    wind_nodes = sorted(
        wind_nodes,
        key=lambda node: int(node.get("SCI_index", "0")),
    )
    for i, node in enumerate(wind_nodes):
        node.text = f"{windobs[i]:.14f}"

    # Copy in and update the references to various files
    shutil.copyfile(f"{basefn}.treat", f"{tempdir}/sweep.treat")
    shutil.copyfile(f"{basefn}.soilsurf", f"{tempdir}/sweep.soilsurf")
    sci_treat = root.find("./SCI_Subregions/SCI_Subregion/SCI_treat")
    sci_treat.text = "sweep.treat"
    sci_soilsurf = root.find("./SCI_Subregions/SCI_Subregion/SCI_soilsurf")
    sci_soilsurf.text = "sweep.soilsurf"

    # hacks again
    sci_ifc = root.find("./SCI_Subregions/SCI_Subregion/GUI_soilifc")
    sci_ifc.text = "sweep.ifc"
    shutil.copyfile(payload.ifcfile, f"{tempdir}/sweep.ifc")
    shutil.copyfile("/i/0/weps_test/erod.grdx", f"{tempdir}/erod.grdx")
    grdnode = root.find("./SCI_GridFile")
    grdnode.text = "erod.grdx"

    # Write out the XML file
    tree.write(
        f"{tempdir}/erod.sweep",
        encoding="ISO-8859-1",
        xml_declaration=True,
        doctype='<!DOCTYPE sweepData SYSTEM "sweep.dtd">',
        pretty_print=True,
    )

    # We are ready to run, gasp

    cmd = [
        sanitize_exe(BINPATH / payload.sweepexe),
        "-ierod.sweep",
        "-Erod",
    ]
    if not run_command(cmd, tempdir):
        return None
    with open(f"{tempdir}/erod.erod", encoding="utf-8") as fh:
        tokens = fh.read().strip().split()
        # total soil loss, saltation loss, suspension loss, PM10 loss
        erosion = float(tokens[0])
    return SweepJobResult(
        field_id=payload.field_id,
        dt=payload.dt,
        scenario=payload.scenario,
        erosion=erosion,
        max_wmps=max(windobs),
        avg_wmps=sum(windobs) / len(windobs),
        drct=drct,
    )


def send_result(ch: Channel, payload: str):
    """Send to RabbitMQ, back on the main thread."""
    ch.basic_publish(
        exchange="",
        routing_key="sweep_results",
        body=payload,
    )


def run(ch: Channel, delivery_tag, payload):
    """Actually run wepp for this event.

    Parameters
    ----------
    ch : pika.channel.Channel
        The RabbitMQ channel.
    delivery_tag : int
        The message delivery tag for acknowledgment.
    payload : bytes
        The raw message payload from RabbitMQ.
    """
    # We should be fully within a thread at this point...
    try:
        # Parse and validate the payload using Pydantic model
        job = SweepJobPayload.model_validate_json(payload)
        with TemporaryDirectory() as tempdir:
            result = run_sweep(tempdir, job)
        if result is not None:
            cb = partial(send_result, ch, result.model_dump_json())
            ch.connection.add_callback_threadsafe(cb)

    except ValidationError as exp:
        # Invalid payload structure - log the validation errors
        LOG.error("Invalid payload format: %s", exp)
        LOG.error("Raw payload: %s", payload[:200])  # Log first 200 chars
    except Exception as exp:
        LOG.error("run_sweep exception: %s", exp)
        LOG.error("Traceback: %s", traceback.format_exc())

    cb = partial(ack_message, ch, delivery_tag)
    ch.connection.add_callback_threadsafe(cb)


def ack_message(ch: Channel, delivery_tag):
    """Note that `ch` must be the same pika channel instance via which
    the message being ACKed was retrieved (AMQP protocol constraint).
    """
    if ch.is_open:
        ch.basic_ack(delivery_tag)
    else:
        # Channel is already closed, so we can't ACK this message;
        # log and/or do something that makes sense for your app in this case.
        pass
    MEMORY["runs"] += 1


def run_consumer(queue: str, jobfunc, executor, prefetch_count: int):
    """Our main runloop."""
    LOG.info("Starting queue_worker for queue: %s", queue)

    conn, _config = get_rabbitmqconn()
    channel = conn.channel()
    # Declare queue as durable (must match producer)
    # This is idempotent - safe to declare multiple times
    channel.queue_declare(queue, durable=True)
    # Limit unacknowledged messages to prevent overwhelming worker
    channel.basic_qos(prefetch_count=prefetch_count)

    def proxy(mychannel, method, _props, payload):
        """Wrapper around jobfunc."""
        delivery_tag = method.delivery_tag
        executor.submit(jobfunc, mychannel, delivery_tag, payload)

    # Consume from queue with manual acknowledgment for reliability
    channel.basic_consume(queue, proxy, auto_ack=False)
    # blocks
    channel.start_consuming()


def print_timing():
    """Print timing information."""
    while True:
        time.sleep(300)
        runs = MEMORY["runs"]
        dt = time.time() - MEMORY["timestamp"]
        rate = runs / dt
        MEMORY["runs"] = 0
        MEMORY["timestamp"] = time.time()
        if runs == 0:
            continue
        LOG.info("%s runs over %.3fs for %.3f r/s", runs, dt, rate)


@click.command()
@click.option("--workers", type=int, required=True)
@click.option("--drainme", is_flag=True)
@click.option(
    "--queue", default=QUEUES.SWEEP, help="Queue name to consume from"
)
@click.option(
    "--prefetch-count",
    type=int,
    help="Maximum unacknowledged jobs to reserve per worker process",
)
def main(
    workers: int,
    drainme: bool,
    queue: str,
    prefetch_count: int | None,
):
    """Go main Go."""
    jobfunc = run if not drainme else drain
    if prefetch_count is None:
        prefetch_count = workers
    # Start a thread to print timing every 300 seconds
    threading.Thread(target=print_timing, daemon=True).start()
    while True:
        # Start a threadpool executor that is associated with a rabbitmq
        # connection.  Run until something bad happens, then start again!
        try:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                run_consumer(queue, jobfunc, executor, prefetch_count)
            LOG.warning("run_consumer exited cleanly, sleeping 30 seconds")
            time.sleep(30)
        except KeyboardInterrupt:
            LOG.critical("Exiting due to keyboard interrupt")
            break
        except Exception as exp:
            LOG.error("Exception %s, sleeping 30", exp)
            traceback.print_exc()
            time.sleep(30)


if __name__ == "__main__":
    main()
