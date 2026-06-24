"""Summarize Flowpath stats."""

import pandas as pd
from pyiem.database import get_dbconn


def main():
    """Go Main Go."""
    df = pd.read_csv("isbi.csv")
    dbconn = get_dbconn("dep")
    cursor = dbconn.cursor()
    for idx, row in df.iterrows():
        huc12 = f"{row['huc12Code']:012.0f}"
        cursor.execute(
            """
    SELECT count(*), max(avg_slope_ratio), max(max_slope_ratio),
    avg(avg_slope_ratio), avg(max_slope_ratio), stddev(avg_slope_ratio),
    stddev(max_slope_ratio) from flowpath p
    JOIN huc12 h on (p.huc12_id = h.huc12_id) where
    p.scenario_id = 0 and h.huc12_code = %s""",
            (huc12,),
        )
        data = cursor.fetchone()
        for i, col in enumerate(
            [
                "flowpath_count",
                "max_bulk_slope",
                "max_max_slope",
                "avg_bulk_slope",
                "avg_max_slope",
                "std_bulk_slope",
                "std_max_slope",
            ]
        ):
            df.at[idx, col] = data[i]

    df.to_csv("isbi.csv", index=False)


if __name__ == "__main__":
    main()
