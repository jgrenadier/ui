import json
import re

import pandas as pd
from sqlalchemy import create_engine

import numpy as np
import holoviews as hv
import geoviews as gv
import datashader as ds
import dask.dataframe as dd
from cartopy import crs
import requests

from bokeh.models import WMTSTileSource, TextInput, Select
from bokeh.plotting import curdoc
from bokeh.layouts import layout
from holoviews.operation.datashader import datashade

# Get renderer and set global display options
renderer = hv.renderer('bokeh').instance(mode='server')
hv.opts("RGB [width=1200 height=682 xaxis=None yaxis=None show_grid=False]")
hv.opts("Polygons (fill_color=None line_width=1.5) [apply_ranges=False tools=['tap']]")
hv.opts("Points [apply_ranges=False] WMTS (alpha=0.5)")

# Load census data
df = dd.io.parquet.read_parquet('data/census.snappy.parq').persist()
census_points = gv.Points(df, kdims=['easting', 'northing'], vdims=['race'])

# Declare colormapping
color_key = {'w':'white',  'b':'green', 'a':'red',   'h':'orange',   'o':'saddlebrown'}
races     = {'w':'White', 'b':'Black', 'a':'Asian', 'h':'Hispanic', 'o':'Other'}
color_points = hv.NdOverlay({races[k]: gv.Points([0,0], crs=crs.PlateCarree())(style=dict(color=v))
                             for k, v in color_key.items()})

# Apply datashading to census data
x_range, y_range = ((-13884029.0, -7453303.5), (2818291.5, 6335972.0)) # Continental USA
shade_defaults = dict(x_range=x_range, y_range=y_range, x_sampling=10, y_sampling=10, width=1200, height=682,
                      color_key=color_key, aggregator=ds.count_cat('race'),)
shaded = datashade(census_points, **shade_defaults)

shapefile = {'state_house': 'cb_2016_48_sldl_500k',
             'state_senate': 'cb_2016_48_sldu_500k',
             'us_house': 'cb_2015_us_cd114_5m',
}

def load_district_shapefile(id):
    shape_path = 'data/{0}/{0}.shp'.format(shapefile[id])
    districts = gv.Shape.from_shapefile(shape_path, crs=crs.PlateCarree())
    districts = gv.operation.project_shape(districts)
    districts = hv.Polygons([gv.util.geom_to_array(dist.data) for dist in districts])
    return districts

# Define tile source
tile_url = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{Z}/{Y}/{X}.jpg'
tiles = gv.WMTS(WMTSTileSource(url=tile_url))


DIVISION_ID_RE = {
    'state_house': re.compile(r'ocd-division/country:us/state:[a-z]{2}/sldl:([0-9]+)'),
    'state_senate': re.compile(r'ocd-division/country:us/state:[a-z]{2}/sldu:([0-9]+)'),
    'us_house': re.compile(r'ocd-division/country:us/state:[a-z]{2}/cd:([0-9]+)'),
    'county': re.compile(r'ocd-division/country:us/state:[a-z]{2}/county:[^\/]+/council_district:([0-9]+)'),
    'city_council': re.compile(r'ocd-division/country:us/state:[a-z]{2}/place:[^\/]+/council_district:([0-9]+)'),
}


engine = create_engine('mysql+mysqlconnector://atxhackathon:atxhackathon@atxhackathon.chs2sgrlmnkn.us-east-1.rds.amazonaws.com:3306/atxhackathon', echo=False)
cnx = engine.raw_connection()
vtd_data = pd.read_sql('SELECT * FROM vtd2016preselection', cnx)


def address_latlon_lookup(address, api_key):
    json_response = requests.get(
        'https://maps.googleapis.com/maps/api/geocode/json?address={address}&key={api_key}'.format(
            address=address, api_key=api_key))
    # TODO: error handling for not found addresses
    #  result comes out looking like {"lat" : 30.2280933, "lng" : -97.8503729}
    location = json.loads(json_response)['results'][0]['geometry']['location']
    return location['lat'], location['lng']


def get_district_boundaries(district_id):
    pass



def address_district_lookup(address, district_type, api_key):
    json_response = requests.get(
        'https://www.googleapis.com/civicinfo/v2/representatives?address={address}&key={api_key}'.format(
            address=address, api_key=api_key)
    )
    # TODO: error handling for not found addresses
    divisions = json.loads(json_response)['divisions']
    for key in divisions:
        match = DIVISION_ID_RE[district_type].match(key)
        if match:
            district = match.group(1)
    # TODO: error handling for no matching RE (maybe due to different state expression)
    return district

# Define valid function for FunctionHandler
# when deploying as script, simply attach to curdoc
def modify_doc(doc):
    def set_bounds(attr, old, new):
        """Upon specification of an address, or change of district type, re-zoom to show
        the district applicable to the address provided"""
        pass

    def district_type_update(attr, old, new):
        """Choose between state_house, state_senate, US house districts to display"""
        pass

    def set_district_on_click():
        """Update any data in tables shown to user (perhaps in mouse-over)

        This could also be selected numerically, for people who know their district by number
        """
        pass

    address_input = TextInput(title='Address')
    address_input.on_change('value', set_bounds)
    district_type = Select(title='District type', options=[
        ('us_house', "US House"),
        ('state_house', "State House"),
        ('state_senate', "State Senate"),
    ], value='us_house')
    address_input.on_change('value', district_type_update)

    def get_plot():
        # Combine the holoviews plot and widgets in a layout
        return tiles * shaded * color_points * load_district_shapefile(district_type.value)

    # Create HoloViews plot and attach the document
    hvplot = get_plot()
    plot = layout([
    [renderer.get_plot(hvplot, doc).state],
    [address_input, district_type]], sizing_mode='fixed')

    doc.add_root(plot)
    return doc

doc = modify_doc(curdoc())
