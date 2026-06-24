"""Place jobs into our DEP queue!"""

import os
import time
from datetime import date, datetime

import click
import httpx
import pandas as pd
import pika
from pyiem.database import get_sqlalchemy_conn, sql_helper
from pyiem.util import logger

from dailyerosion.util import get_rabbitmqconn
from dailyerosion.workflows import QUEUES
from dailyerosion.workflows.wepprun import (
    WeppJobPayload,
    WeppRunConfig,
    build_runfile,
)

YEARS = date.today().year - 2006
# suboptimal hardcode at the moment...
WEPPEXE = "wepp_dep"

# These are legacy HUC12s that required a graph file to be generated from
# WEPP.  The WEPS/Sweep workflow no longer requires it, but this list is
# useful for definining non-MN HUC12s to test.
GRAPH_HUC12 = (
    "090201081101 090201081102 090201060605 102702040203 101500041202 "
    "090203010403 070200070501 070102050503 090203030703 090203030702 "
    "090203030304 090201081002 070102020203 070200080101 101702040106"
    "070400080203 090203040601 070400080803 070200090907 070200020303 "
    "090203110206 070200110603"
).split()


@click.command()
@click.option("-s", "--scenario", type=int, help="Scenario ID", default=0)
@click.option(
    "--runerrors", is_flag=True, help="Run previous runs that errored."
)
@click.option("--myhucs", help="Specify file of HUC12s to filter job.")
@click.option("--queue", help="RabbitMQ destination", default=QUEUES.WEPP)
def main(scenario: int, runerrors: bool, myhucs: str | None, queue: str):
    """Go main Go."""
    log = logger()
    if myhucs:
        log.warning("Using %s to filter job submission", myhucs)
        with open(myhucs, encoding="ascii") as fh:
            myhucs = [s.strip() for s in fh]

    with get_sqlalchemy_conn("dep") as conn:
        # Figure out the source of flowpaths
        res = conn.execute(
            sql_helper(
                """
    SELECT flowpath_scenario from scenario where scenario_id = :scenario
    """
            ),
            {"scenario": scenario},
        )
        flscenario = res.fetchone()[0]

        flowpathdf = pd.read_sql(
            sql_helper(
                """
        SELECT huc12_code, huc12_fpath_num, filepath, ofe_count, irrigated
        from flowpath p
        JOIN climate_file c on (p.climate_file_id = c.climate_file_id)
        JOIN huc12 h on (p.huc12_id = h.huc12_id)
        where p.scenario_id = :flscenario {huclimit}
        """,
                huclimit=" and h.huc12_code = ANY(:hucs)" if myhucs else "",
            ),
            conn,
            params={"flscenario": flscenario, "hucs": myhucs},
        )
    totaljobs = len(flowpathdf.index)
    connection, rabbit_config = get_rabbitmqconn()
    channel = connection.channel()
    # Declare queue as durable (survives broker restart)
    # This is idempotent - safe to declare multiple times
    channel.queue_declare(queue=queue, durable=True)
    sts = datetime.now()

    weppconfig = WeppRunConfig(years=YEARS)

    for row in flowpathdf.itertuples():
        errfn = (
            f"/i/0/error/{row.huc12_code[:8]}/{row.huc12_code[8:]}"
            f"/{row.huc12_code}_{row.huc12_fpath_num}.error"
        )
        if runerrors:
            if not os.path.isfile(errfn):
                continue
            os.unlink(errfn)

        payload = WeppJobPayload(
            errorfn=errfn,
            wepprun=build_runfile(
                weppconfig,
                f"/i/{scenario}/{{prefix}}/"
                f"{row.huc12_code[:8]}/{row.huc12_code[8:]}/"
                f"{row.huc12_code}_{row.huc12_fpath_num}.{{prefix}}",
                f"/i/{scenario}/{{prefix}}/"
                f"{row.huc12_code[:8]}/{row.huc12_code[8:]}/"
                f"{row.huc12_code}_{row.huc12_fpath_num}.{{prefix}}",
                row.filepath,
                f"/i/{scenario}/irrigation/ofe{row.ofe_count}.txt",
            ),
            weppexe=WEPPEXE,
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
            log.warning(
                "%6i/%s [%.3f /s]",
                jobsleft,
                totaljobs,
                done / (now - sts).total_seconds(),
            )
            percentile -= 0.1
        if (now - sts).total_seconds() > 36000:
            log.error("ERROR, 10 Hour Job Limit Hit")
            break
        if jobsleft == 0:
            log.warning("Done!")
            break
        time.sleep(30)


if __name__ == "__main__":
    main()
