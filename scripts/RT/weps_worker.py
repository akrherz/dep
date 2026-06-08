"""We do work when jobs are placed in the queue.

Division of Labor
=================

 - Assemble WEPS inputs into a temp directory
 - We have a custom WEPS now that does not require erosion to output files.
 - run a current WEPS dev build like so: `weps -o<dd><mm><yyyy> -W1`
 - This generates a `saeros.in`, store it away for later SWEEP use
 - Then edit in the real wind and run SWEEP per the usual.

"""

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
from lxml import etree
from pika.channel import Channel
from pydantic import ValidationError
from pyiem.util import logger

from dailyerosion.util import get_rabbitmqconn
from dailyerosion.workflows import QUEUES
from dailyerosion.workflows.wepsrun import WEPSJobPayload
from dailyerosion.workflows.worker import sanitize_exe

LOG = logger()
MEMORY = {
    "runs": 0,
    "timestamp": time.time(),
}
BINPATH = Path("/opt/dep/bin")


def drain(ch, delivery_tag, _payload):
    """NOOP to clear out the queue via a hackery"""
    cb = partial(ack_message, ch, delivery_tag)
    ch.connection.add_callback_threadsafe(cb)


def run_command(cmd: list[str]) -> bool:
    """Common command running logic."""
    with subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
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


def process_erod(huc_12: str, fpath: int, tmpdir, simulation_day):
    """Manipulate and copy away stuff we need to run sweep."""
    saefile = Path(tmpdir) / f"saeros{simulation_day}" / "erod.sweep"
    # Read/parse the XML saefile
    tree = etree.parse(saefile)
    root = tree.getroot()
    sci_treat = root.find("./SCI_Subregions/SCI_Subregion/SCI_treat")
    sci_soilsurf = root.find("./SCI_Subregions/SCI_Subregion/SCI_soilsurf")

    savebase = (
        Path("/i/0/sweepin")
        / f"{huc_12[:8]}"
        / f"{huc_12[8:]}"
        / f"{huc_12}_{fpath}"
    )
    shutil.copyfile(saefile, f"{savebase}.sweep")
    shutil.copyfile(
        Path(tmpdir) / f"saeros{simulation_day}" / sci_treat.text,
        f"{savebase}.treat",
    )
    shutil.copyfile(
        Path(tmpdir) / f"saeros{simulation_day}" / sci_soilsurf.text,
        f"{savebase}.soilsurf",
    )


DAY1 = date(2007, 1, 1)


def generate_runfile(lon: float, lat: float):
    """Create the run file settings."""
    return f"""
#VERSION=1.05
#------------ WEPS SIMULATION RUN FILE ------------
# Note: Lines beginning with '#' are comment lines.
#       Lines beginning with '#   RFD' are comments used by the interface.
#
# --USER INFORMATION
#   RFD-UserName
Exercise 1
#   FarmId TractId FieldId runtypedisp RotationYears CycleCount
 |  |  | NRCS | 2 | 10
#   RFD-Site
FIPS:US-WI-097
#
# --SITE INFORMATION
#   Signed Latitude
+{lat}
#   Signed Longitude
{lon}
#   RFD-Elevation(meters)
337.99272
#   RFD-ClimateFlag|RFD-cligen.station
test1
#   RFD-WindFlag|RFD-windgen.station
test2
#
# --SIMULATION PERIOD
#   RFD-StartDate(day month year)
01 01 2007
#   RFD-EndDate(day month year)
31 12 2026
#   RFD-TimeSteps(per day)
24
#
# --RUN FILE FILENAMES (INPUT)
#   RFD-climate file
weps.cli
#   RFD-wind file
interpolated.win
#   RFD-sub-daily file
none
#   RFD-SoilFile
Bearden_I119A_70_SICL.ifc
#   RFD-ManageFile
weps.man
#
# --WEPS OUTPUT OPTIONS
#   RFD-OutputFile
null
#   RFD-ReportForm
0 0 0 0 0 0
#   RFD-OutputPeriod
2
#   RFD-SubmodelOutput
0 1 0 0 0 0
#   RFD-DebugOutput
0 0 0 0 0 0
#
# --SIMULATION REGION INFORMATION
#   RFD-RegionAngle(degrees clockwise from North)
0.0
#   Origin coordinates of simulation region (meters)
0.0  0.0
#    RFD-XLength(meters)  RFD-YLength(meters)
714.08  714.08
#   RFD-Scales(place holder line - needed for older versions of WEPS)
5.5 5.5
#
#   RFD-AccNo
1
#   Accounting region coordinates (meters)
    0.0  0.0
714.08  714.08
#
#   RFD-SubregionNo
1
#   Subregion region coordinates (meters)
0.0  0.0
714.08  714.08
#   RFD-AverageSlope(ratio m/m)
-1
#   RFD-BarrierNo
0
0.0 0.0
0.0 0.0
none
0.0
0.0
0.0
#
# --CIRCULAR FIELD INFORMATION
# Note: These fields are not used by the weps simulation.
#       The shape and radius values are used by the user
#       interface to approximate a rectangular field.  They
#       are included here so the reports can display the
#       correct field shape.
#
#   RFD-Shape
circle
#   RFD-Radius
402.87
#   RFD-WaterErosionLoss
0.00
#   RFD-SoilRockFragments
-1
#---------- END OF SIMULATION RUN FILE ------------
"""


def run_weps(payload: WEPSJobPayload) -> None:
    """Actually run WEPS, really.

    Parameters
    ----------
    payload : WEPSJobPayload
        Validated SWEEP job payload containing runfile content and executable.
    """
    simulation_day = (payload.dt - DAY1).days + 1
    with TemporaryDirectory() as tmpdir:
        runfile = generate_runfile(payload.lon, payload.lat)
        with open(Path(tmpdir) / "weps.run", "w") as fh:
            fh.write(runfile)
        shutil.copyfile(payload.clifile, Path(tmpdir) / "weps.cli")
        # We bring in a wind file that is all zeros, hopefully this works
        # without messing up the soil state.
        if payload.for_sweep:
            payload.windfile = "/i/0/wind/zeros.win"

        shutil.copyfile(payload.windfile, Path(tmpdir) / "interpolated.win")
        shutil.copyfile(payload.manfile, Path(tmpdir) / "weps.man")

        # we are left with the hardcoded soil :/
        for hack in [
            "Bearden_I119A_70_SICL.ifc",
        ]:
            shutil.copyfile(f"/i/0/weps_test/{hack}", Path(tmpdir) / hack)
        cmd = [
            sanitize_exe(BINPATH / payload.wepsexe),
            "-c0",  # no soil conditioning output
            "-E1",  # Run WEPS erosion, needs to be on always for -o to work
            "-e0",  # Don't create all sweep files
            "-H0",  # No heartbeat output
            "-i3",  # temp debuggin
            "-I2",  # Run the given management cycles, TODO
            "-n0",  # Don't create new input files
            f"-o{payload.dt:%d%m%Y}",  # Generate SWEEP input on this date
            f"-P{tmpdir}",  # Path to files
            "-t0",  # No confidence interval reported
            "-T0",  # No deep furrow effect
            "-W1",  # simple runoff method, perf
            "-u0",  # No resurfacing of buried roots, perf opt?
        ]
        try:
            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if not payload.for_sweep:
                plotfn = Path(tmpdir) / "plot.out"
                savefn = (
                    Path("/i/0/weps")
                    / payload.huc_12[:8]
                    / payload.huc_12[8:]
                    / f"{payload.huc_12}_{payload.fpath}.out"
                )
                savefn.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(plotfn, savefn)
        except subprocess.CalledProcessError as exp:
            LOG.error("WEPS command failed: %s", " ".join(exp.cmd))
            LOG.error("Return code: %s", exp.returncode)
            LOG.error("STDOUT: %s", exp.stdout)
            LOG.error("STDERR: %s", exp.stderr)
            return
        if payload.for_sweep:
            process_erod(payload.huc_12, payload.fpath, tmpdir, simulation_day)


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
        job = WEPSJobPayload.model_validate_json(payload)
        run_weps(job)

    except ValidationError as exp:
        # Invalid payload structure - log the validation errors
        LOG.error("Invalid payload format: %s", exp)
        LOG.error("Raw payload: %s", payload[:200])  # Log first 200 chars
    except Exception as exp:
        LOG.error("run_weps exception: %s", exp)
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
    "--queue", default=QUEUES.WEPS, help="Queue name to consume from"
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
