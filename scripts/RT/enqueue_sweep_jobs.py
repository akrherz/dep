"""Generate DEP SWEEP jobs to be run."""

import time
from datetime import datetime
from pathlib import Path

import click
import httpx
import pandas as pd
import pika
from enqueue_wepp_jobs import GRAPH_HUC12
from pyiem.database import get_sqlalchemy_conn, sql_helper
from pyiem.util import logger
from sqlalchemy.engine import Connection

from dailyerosion.util import get_rabbitmqconn
from dailyerosion.workflows import QUEUES
from dailyerosion.workflows.sweeprun import SweepJobPayload

LOG = logger()


def clean_database(conn: Connection, dt, hucs):
    """Remove current entries."""
    res = conn.execute(
        sql_helper("""
    delete from field_wind_erosion_results r USING fields f
    WHERE r.valid = :dt and r.field_id = f.field_id and f.huc12 = ANY(:hucs)
    and f.scenario = 0
                   """),
        {"dt": dt, "hucs": hucs},
    )
    loglvl = LOG.info if res.rowcount == 0 else LOG.warning
    loglvl("Removed %s previous field_wind_erosion_results", res.rowcount)
    conn.commit()


@click.command()
@click.option(
    "--date",
    "-d",
    required=True,
    type=click.DateTime(),
    help="Date to run for",
)
@click.option("-s", "--scenario", type=int, help="Scenario ID", default=0)
@click.option("--myhucs", help="Specify file of HUC12s to filter job.")
@click.option("--queue", help="RabbitMQ destination", default=QUEUES.SWEEP)
def main(date: datetime, scenario: int, myhucs: str | None, queue: str):
    """Go main Go."""
    dt = date.date()
    if myhucs:
        LOG.warning("Using %s to filter job submission", myhucs)
        with open(myhucs, encoding="ascii") as fh:
            myhucs = [s.strip() for s in fh]

    with get_sqlalchemy_conn("dep") as conn:
        fieldsdf = pd.read_sql(
            sql_helper(
                """
    with data as (
        select o.field_id,
        row_number() over (partition by field_id ORDER by huc12_fpath_num asc),
        substr(f.landuse, :charat, 1) as crop, f.huc12_fpath_num, h.huc12_code,
        st_pointn(st_transform(o.geom, 4326), 1) as pt, g.mukey
        from flowpath_ofe o
        JOIN flowpath f on (o.flowpath_id = f.flowpath_id)
        JOIN huc12 h on (f.huc12_id = h.huc12_id)
        JOIN gssurgo g on (o.gssurgo_id = g.gssurgo_id)
        where (h.states ~* 'MN' or h.huc12_code = ANY(:graphhucs))
        and f.scenario_id = 0 and o.ofe = 1)
    select field_id, huc12_fpath_num, huc12_code, st_x(pt) as lon,
    st_y(pt) as lat, crop, mukey
    from data
    where row_number = 1 and crop in ('C', 'B') {huclimit}
        """,
                huclimit=" and h.huc12_code = ANY(:hucs)" if myhucs else "",
            ),
            conn,
            params={
                "graphhucs": GRAPH_HUC12,
                "hucs": myhucs,
                "charat": dt.year - 2007 + 1,
            },
        )
        # Remove current entries, only for HUC12s of interest!
        clean_database(conn, dt, fieldsdf["huc12_code"].unique().tolist())
    totaljobs = len(fieldsdf.index)
    connection, rabbit_config = get_rabbitmqconn()
    channel = connection.channel()
    # Declare queue as durable (survives broker restart)
    # This is idempotent - safe to declare multiple times
    channel.queue_declare(queue=queue, durable=True)
    sts = datetime.now()

    for row in fieldsdf.itertuples():
        ifcfile = Path(f"/i/0/weps_soil_fy2024/{row.mukey}.ifc")
        if not ifcfile.exists():
            ifcfile = Path("/i/0/weps_test/Bearden_I119A_70_SICL.ifc")
        payload = SweepJobPayload(
            sweepexe="sweep_dep",
            field_id=row.field_id,
            fpath=row.huc12_fpath_num,
            ifcfile=str(ifcfile),
            huc_12=row.huc12_code,
            crop=row.crop,
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
