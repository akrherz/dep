"""Enqueue WEPS jobs we want run.

The goal here is to run WEPS for "today" and generate the necessary SWEEP input
files with realistic values to run the model after DEP/WEPP runs.  We are
threading an ugly neddle here.

Division of Labor
=================

 - Enqueue WEPS jobs to rabbitmq for `weps_worker.py` to deal with

"""

import time
from datetime import datetime

import click
import httpx
import pandas as pd
import pika
from enqueue_wepp_jobs import GRAPH_HUC12
from pyiem.database import get_sqlalchemy_conn, sql_helper
from pyiem.iemre import get_gid
from pyiem.util import logger

from dailyerosion.util import get_rabbitmqconn
from dailyerosion.workflows import QUEUES
from dailyerosion.workflows.wepsrun import WEPSJobPayload

LOG = logger()


@click.command()
@click.option(
    "--date",
    "-d",
    required=False,
    type=click.DateTime(),
    help="Date to run for when for_sweep is set.",
)
@click.option("-s", "--scenario", type=int, help="Scenario ID", default=0)
@click.option("--myhucs", help="Specify file of HUC12s to filter job.")
@click.option("--queue", help="RabbitMQ destination", default=QUEUES.WEPS)
@click.option(
    "--for_sweep", is_flag=True, help="Is this job to bootstrap SWEEP runs."
)
def main(
    date: datetime | None,
    scenario: int,
    myhucs: str | None,
    queue: str,
    for_sweep: bool,
):
    """Go main Go."""
    # First, do some checking that args make sense.
    if date is None and for_sweep:
        LOG.error("Must specify --date when --for_sweep is set")
        return
    if date is not None and not for_sweep:
        LOG.error("--date is only used when --for_sweep is set")
        return
    if myhucs:
        LOG.warning("Using %s to filter job submission", myhucs)
        with open(myhucs, encoding="ascii") as fh:
            myhucs = [s.strip() for s in fh]

    # We are making an assumption below about filtering corn/soybean fields
    dt = datetime.now().date() if date is None else date.date()
    with get_sqlalchemy_conn("idep") as conn:
        fieldsdf = pd.read_sql(
            sql_helper(
                """
    with data as (
        select o.field_id,
        row_number() over (partition by field_id ORDER by fpath asc),
        substr(o.landuse, :charat, 1) as crop, f.fpath, h.huc_12,
        st_pointn(st_transform(o.geom, 4326), 1) as pt, c.filepath as clifile
        from flowpath_ofes o, flowpaths f, huc12 h, climate_files c
        where o.flowpath = f.fid and f.huc_12 = h.huc_12 and
        (h.states ~* 'MN' or h.huc_12 = ANY(:graphhucs))
        and f.scenario = 0 and o.ofe = 1 and f.climate_file_id = c.id)
    select field_id, fpath, huc_12, st_x(pt) as lon, st_y(pt) as lat, crop,
    clifile from data
    where row_number = 1 and crop in ('C', 'B') {huclimit}
        """,
                huclimit=" and huc_12 = ANY(:hucs)" if myhucs else "",
            ),
            conn,
            params={
                "graphhucs": GRAPH_HUC12,
                "hucs": myhucs,
                "charat": dt.year - 2007 + 1,
            },
        )
    if fieldsdf.empty:
        LOG.warning("No fields found with query, exiting")
        return
    totaljobs = len(fieldsdf.index)
    connection, rabbit_config = get_rabbitmqconn()
    channel = connection.channel()
    # Declare queue as durable (survives broker restart)
    # This is idempotent - safe to declare multiple times
    channel.queue_declare(queue=queue, durable=True)
    sts = datetime.now()
    windfile = ""

    for row in fieldsdf.itertuples():
        if not for_sweep:
            gid = f"{get_gid(row.lon, row.lat):06.0f}"
            windfile = f"/i/0/wind/{gid[:3]}/{gid}.win"
        payload = WEPSJobPayload(
            wepsexe="weps_dep",
            for_sweep=for_sweep,
            windfile=windfile,
            manfile=(
                f"/i/0/weps_man/{row.huc_12[:8]}/{row.huc_12[8:]}/"
                f"{row.huc_12}_{row.fpath}.man"
            ),
            field_id=row.field_id,
            fpath=row.fpath,
            huc_12=row.huc_12,
            clifile=row.clifile,
            dt=dt,
            scenario=scenario,
            lon=row.lon,
            lat=row.lat,
        )
        # Publish to default exchange ("") with routing_key=queue name
        # This directly routes the message to the named queue
        channel.basic_publish(
            exchange="",  # Default exchange (nameless exchange)
            routing_key=queue,  # Queue name to route to
            body=payload.model_dump_json(),
            properties=pika.BasicProperties(
                # Message survives broker restart
                delivery_mode=pika.DeliveryMode.Persistent,
            ),
        )
    # Wait a few seconds for the dust to settle
    time.sleep(10)
    connection.close()
    percentile = 1.0001
    while True:
        now = datetime.now()
        req = httpx.get(
            f"http://{rabbit_config['host']}:15672/api/queues/%2F/{queue}",
            auth=(rabbit_config["user"], rabbit_config["password"]),
            timeout=60,
        )
        queueinfo = req.json()
        # jobs either ready or unawked
        jobsleft = queueinfo["messages_persistent"]
        done = totaljobs - jobsleft
        if (jobsleft / float(totaljobs)) < percentile:
            LOG.warning(
                "%6i/%s [%.3f /s]",
                jobsleft,
                totaljobs,
                done / (now - sts).total_seconds(),
            )
            percentile -= 0.1
        if (now - sts).total_seconds() > 36000:
            LOG.error("ERROR, 10 Hour Job Limit Hit")
            break
        if jobsleft == 0:
            LOG.warning("Done!")
            break
        time.sleep(30)


if __name__ == "__main__":
    main()
