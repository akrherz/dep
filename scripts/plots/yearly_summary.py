import datetime
import cStringIO
import psycopg2
from shapely.wkb import loads
import numpy as np
import sys
from geopandas import read_postgis
import matplotlib
matplotlib.use('agg')
from pyiem.plot import MapPlot
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon
from matplotlib.collections import PatchCollection
import matplotlib.colors as mpcolors
import cartopy.crs as ccrs
import cartopy.feature as cfeature

V2NAME = {
    'avg_loss': 'Detachment',
    'qc_precip': 'Precipitation',
    'avg_delivery': 'Delivery',
    'avg_runoff': 'Runoff'}
V2MULTI = {
    'avg_loss': 4.463,
    'qc_precip': 1. / 25.4,
    'avg_delivery': 4.463,
    'avg_runoff': 1. / 25.4,
    }
V2UNITS = {
    'avg_loss': 'tons/acre',
    'qc_precip': 'inches',
    'avg_delivery': 'tons/acre',
    'avg_runoff': 'inches',
    }
V2RAMP = {
    'avg_loss': [0, 2.5, 5, 10, 20, 40, 60],
    'qc_precip': [15, 25, 35, 45, 55],
    'avg_delivery': [0, 2.5, 5, 10, 20, 40, 60],
    'avg_runoff': [0, 2.5, 5, 10, 15, 30],
    }

year = int(sys.argv[1])
v = sys.argv[2]
ts = datetime.date(year, 1, 1)
ts2 = datetime.date(year, 12, 31)
scenario = 0

# suggested for runoff and precip
if v in ['qc_precip', 'avg_runoff']:
    c = ['#ffffa6', '#9cf26d', '#76cc94', '#6399ba', '#5558a1']
# suggested for detachment
elif v in ['avg_loss']:
    c = ['#cbe3bb', '#c4ff4d', '#ffff4d', '#ffc44d', '#ff4d4d', '#c34dee']
# suggested for delivery
elif v in ['avg_delivery']:
    c = ['#ffffd2', '#ffff4d', '#ffe0a5', '#eeb74d', '#ba7c57', '#96504d']
cmap = mpcolors.ListedColormap(c, 'james')
cmap.set_under('white')
cmap.set_over('black')

pgconn = psycopg2.connect(database='idep', host='localhost', port=5555,
                          user='nobody')
cursor = pgconn.cursor()

title = "for %s" % (ts.strftime("%-d %B %Y"),)
if ts != ts2:
    title = "for period between %s and %s" % (ts.strftime("%-d %b %Y"),
                                              ts2.strftime("%-d %b %Y"))
m = MapPlot(axisbg='#EEEEEE', nologo=True, sector='iowa',
            nocaption=True,
            title='DEP %s %s' % (V2NAME[v], title),
            caption='Daily Erosion Project')

# Check that we have data for this date!
cursor.execute("""
    SELECT value from properties where key = 'last_date_0'
""")
lastts = datetime.datetime.strptime(cursor.fetchone()[0], '%Y-%m-%d')
floor = datetime.date(2007, 1, 1)
df = read_postgis("""
WITH data as (
  SELECT huc_12,
  sum("""+v+""")  as d from results_by_huc12
  WHERE scenario = %s and valid >= %s and valid <= %s
  GROUP by huc_12)

SELECT ST_Transform(simple_geom, 4326) as geo, coalesce(d.d, 0) as data
from huc12 i LEFT JOIN data d
ON (i.huc_12 = d.huc_12) WHERE i.scenario = %s and i.states ~* 'IA'
""", pgconn, params=(scenario, ts, ts2, scenario), geom_col='geo',
                  index_col=None)
df['data'] = df['data'] * V2MULTI[v]
if df['data'].max() < 0.01:
    bins = [0.01, 0.02, 0.03, 0.04, 0.05]
else:
    bins = V2RAMP[v]
norm = mpcolors.BoundaryNorm(bins, cmap.N)

patches = []
#m.ax.add_geometries(df['geo'], ccrs.PlateCarree())
for i, row in df.iterrows():
    c = cmap(norm([row['data'], ]))[0]
    arr = np.asarray(row['geo'].exterior)
    points = m.ax.projection.transform_points(ccrs.Geodetic(),
                                              arr[:, 0], arr[:, 1])
    p = Polygon(points[:, :2], fc=c, ec='k', zorder=2, lw=0.1)
    m.ax.add_patch(p)

#print len(patches)
#m.ax.add_collection(PatchCollection(patches, match_original=True))
m.drawcounties()
m.drawcities()
lbl = [round(_, 2) for _ in bins]
u = "%s, Avg: %.2f" % (V2UNITS[v], df['data'].mean())
m.draw_colorbar(bins, cmap, norm,
                clevlabels=lbl, title="%s :: %s" % (V2NAME[v], V2UNITS[v]))
plt.savefig('%s_%s.png' % (year, v))
