import ee
import folium
import pandas as pd
# Import datetime
from datetime import datetime
import datetime as dt
import json
import geopandas as gpd
from definitions import *


# add area field to fields
def addArea(feature):
    return feature.set({'area_sqm': feature.geometry().area()})


def add_cloudProbability(s2, s2c):
    s2_sysindex_list = s2.aggregate_array('system:index')
    s2c_sysindex_list = s2c.aggregate_array('system:index')
    # create list of system:index values in s2 that are NOT in s2c
    s2_sysindex_list_noMatch = s2_sysindex_list.removeAll(s2c_sysindex_list)
    # filter s2 into two imgColls:
    s2_sys_ind_match = s2.filter(
        ee.Filter.inList("system:index", s2c_sysindex_list))
    s2_sys_ind_NoMatch = s2.filter(ee.Filter.inList(
        "system:index", s2_sysindex_list_noMatch))
    # Join the cloud probability collection to the TOA reflectance collection.
    withCloudProbability_yes_s2c = indexJoin(
        s2_sys_ind_match, s2c, 'cloud_probability')
    # apply constant cloud probability raster = 0
    withCloudProbability_no_s2c = s2_sys_ind_NoMatch.map(
        addNoCloudProb).filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 30))
    # merge two imgColls
    withCloudProbability = withCloudProbability_yes_s2c.merge(
        withCloudProbability_no_s2c)
    return withCloudProbability


# ** Cloud masking
# Define a function to join the two collections on their 'system:index'
# property. The 'propName' parameter is the name of the property that
# references the joined image.
def indexJoin(colA, colB, propName):
    primary = colA
    secondary = colB
    condition = ee.Filter.equals(
        leftField='system:index', rightField='system:index')
    joined = ee.ImageCollection(ee.Join.saveFirst(
        propName).apply(primary, secondary, condition))

  # Merge the bands of the joined image.
    return joined.map(lambda image: image.addBands(ee.Image(image.get(propName))))


def buildMaskFunction(cloudProb):
    def applyCloudMask(img):
        # Define clouds as pixels having greater than the given cloud probability.
        cloud = img.select('probability').gt(ee.Image(cloudProb))
        # Apply the cloud mask to the image and return it.
        return img.updateMask(cloud.Not())
    return applyCloudMask

# Define a function to add a cloud probability band with constant raster = 0
# use for sentinel-2 images with no corresponding cloud-probability (s2c) image


def addNoCloudProb(image):
    image = image.addBands(ee.Image(0).rename('probability'))
    return image


def cloud_free_function(image):
    pixels_cloudFree = image.select('probability').lte(
        50).rename('cloud_free_binary')
    pixels_all = image.select('probability').lte(100).rename('pixel_count')
    return image.addBands(pixels_cloudFree).addBands(pixels_all)


def mosaicByDate(imcol):
  # imcol: An image collection
  # returns: An image collection
    imlist = imcol.toList(imcol.size())
    unique_dates = imlist.map(lambda im: ee.Image(
        im).date().format("YYYY-MM-dd")).distinct()

    def inner_function(d):
        d = ee.Date(d)
        im = imcol.filterDate(d, d.advance(1, "day")).mosaic()
        return im.set(
            "system:time_start", d.millis(),
            "system:id", d.format("YYYY-MM-dd"))
    mosaic_imlist = unique_dates.map(inner_function)

    return ee.ImageCollection(mosaic_imlist)


def addNDWIThresh(image):
    ndwi = image.normalizedDifference(['B8', 'B11']).rename('NDWI')
    thresh = ndwi.gt(thresh_val).rename('threshold')
    return image.addBands([ndwi, thresh])


def fix(area):
    def reduceRegionsSum(image):
        collection = area
        reducer = ee.Reducer.sum()
        scale = 10
        sum_cloudfree = image.reduceRegions(collection, reducer, scale)
  # add date field to each feature with image date
        return sum_cloudfree.map(lambda feature: feature.set('Date', image.date().format('YYYY-MM-dd')))
    return reduceRegionsSum


def addPctCloudFree(feature):
    return feature.set({'Pct_CloudFree': ee.Number(feature.get('cloud_free_binary')).divide(ee.Number(feature.get('pixel_count')))})

# Sumarize the mean value of the NDWI value, the threshold layer (i.e. the % of the polygon that is above the threshold )
# reduce regions MEAN


def fix2(fields):
    def reduceRegionsMean(image):
        collection = fields
        reducer = ee.Reducer.mean()
        scale = 30
        mean_NDWI_threshold = image.reduceRegions(collection, reducer, scale)
  # add date field to each feature with image date # set geometry to null
        return mean_NDWI_threshold.map(lambda feature: feature.set('Date', image.date().format('YYYY-MM-dd')).setGeometry(None))
    return reduceRegionsMean

# Define a method for displaying Earth Engine image tiles on a folium map.


def add_ee_layer(self, ee_object, vis_params, name):

    try:
        # display ee.Image()
        if isinstance(ee_object, ee.image.Image):
            map_id_dict = ee.Image(ee_object).getMapId(vis_params)
            folium.raster_layers.TileLayer(
                tiles=map_id_dict['tile_fetcher'].url_format,
                attr='Google Earth Engine',
                name=name,
                overlay=True,
                control=True
            ).add_to(self)
        # display ee.ImageCollection()
        elif isinstance(ee_object, ee.imagecollection.ImageCollection):
            ee_object_new = ee_object.mosaic()
            map_id_dict = ee.Image(ee_object_new).getMapId(vis_params)
            folium.raster_layers.TileLayer(
                tiles=map_id_dict['tile_fetcher'].url_format,
                attr='Google Earth Engine',
                name=name,
                overlay=True,
                control=True
            ).add_to(self)
        # display ee.Geometry()
        elif isinstance(ee_object, ee.geometry.Geometry):
            folium.GeoJson(
                data=ee_object.getInfo(),
                name=name,
                overlay=True,
                control=True
            ).add_to(self)
        # display ee.FeatureCollection()
        elif isinstance(ee_object, ee.featurecollection.FeatureCollection):
            ee_object_new = ee.Image().paint(ee_object, 0, 2)
            map_id_dict = ee.Image(ee_object_new).getMapId(vis_params)
            folium.raster_layers.TileLayer(
                tiles=map_id_dict['tile_fetcher'].url_format,
                attr='Google Earth Engine',
                name=name,
                overlay=True,
                control=True
            ).add_to(self)

    except:
        print("Could not display {}".format(name))


def to_dataframe(table, columns):
    nested_list = table.reduceColumns(
        ee.Reducer.toList(len(columns)), columns).values().get(0)
    data = nested_list.getInfo()
    return pd.DataFrame(data, columns=columns)


def standardize_names(df, standard_name, old_name):
    if standard_name in df.columns:
        print("{} exists".format(standard_name))
    else:
        df[standard_name] = df[old_name]
        df = df.drop([old_name], axis=1)
    return df


def table_combine(table1, table2, columns1, columns2, stat_list):
    # combine two tables
    df1 = to_dataframe(table1, columns1)
    df2 = to_dataframe(table2, columns2)
    # Convert to starndardized column names
    df1 = standardize_names(df1, "Bid_ID", columns1[0])
    df1 = standardize_names(df1, "Field_ID", columns1[1])
    df2 = standardize_names(df2, "Bid_ID", columns1[0])
    df2 = standardize_names(df2, "Field_ID", columns1[1])
    df = pd.merge(df1, df2, on=['Bid_ID', 'Field_ID', 'Date'], how='left')
    # selete the enrolled fields and drop the non-enrolled ones
    df = df.loc[df.Status.isin(stat_list)]
    df['Date'] = pd.to_datetime(df['Date'])
    df['pct_flood'] = df['threshold']
    df['Source'] = 'Sentinel 2'
    df['Unique_ID'] = df['Bid_ID'] + "_" + df['Field_ID']
    # replace the percentage flooded with Nan if below cloud_free_tresh
    df.loc[df['Pct_CloudFree'] < cloud_free_thresh, 'pct_flood'] = pd.NA
    # add in no data to ensure all weeks are include
    df_date = pd.date_range(start=df.Date.min(),
                            end=df.Date.max()).to_frame(name="Date")
    df_date["Unique_ID"] = df.iloc[0]['Unique_ID']
    df_date["Source"] = df.iloc[0]['Source']
    df = pd.concat([df, df_date]).reset_index()
    return df


def add_all_dates(df):
    # remove rows with lots of clouds
    df = df.loc[df.Pct_CloudFree > cloud_free_thresh].copy()
    # add in no data to ensure all weeks are include
    df_date = pd.date_range(start=df.Date.min(),
                            end=df.Date.max()).to_frame(name="Date")
    df_date["Unique_ID"] = df.iloc[0]['Unique_ID']
    df_date["Source"] = df.iloc[0]['Source']
    df = pd.concat([df, df_date]).reset_index()
    return df


def pivot_table(df):
    df['Week_start'] = df['Date'] - pd.to_timedelta(6, unit='d')
    df_week = (df.groupby([pd.Grouper(key='Week_start', freq='W-SUN'), 'Unique_ID', 'Source'])
               .agg({'pct_flood': 'mean'})
               .reset_index()
               .rename(columns={'pct_flood': 'Mean_field_flood_pct', })
               )
    df_week['Week_start'] = df_week['Week_start'].dt.strftime('%Y-%m-%d')
    df_pivot = df_week.pivot_table(index=['Unique_ID', 'Source'], columns='Week_start',
                                   values='Mean_field_flood_pct', dropna=False).reset_index()
    df_pivot = df_pivot.dropna(
        how='all', subset=df_pivot.columns.values.tolist()[2:])
    df_pivot['Bid_ID'] = df_pivot['Unique_ID'].str.split('_', n=1, expand=True)[
        0]
    df_pivot['Field_ID'] = df_pivot['Unique_ID'].str.split('_', n=1, expand=True)[
        1]
    df_pivot.drop(['Unique_ID', ], axis=1, inplace=True)
    return df_pivot

def fields_to_df_d(fields):
    '''
    extract start and end dates information from fields
    '''
    df = gpd.read_file(json.dumps(fields.getInfo()))
    df_d = df[['BidID', 'FieldID', 'Status', 'EndDate', 'StartDate']]
    columns = df_d.columns
    df_d = standardize_names(df_d, 'Bid_ID', columns[0])
    df_d = standardize_names(df_d, 'Field_ID', columns[1])
    df_d['EndDT'] = df_d['EndDate'].apply(lambda x : datetime.fromtimestamp(x/1000).strftime('%Y-%m-%d'))
    df_d['StartDT'] = df_d['StartDate'].apply(lambda x : datetime.fromtimestamp(x/1000).strftime('%Y-%m-%d'))
    return df_d

def add_flood_dates(df_d, df, stat_list):
    '''
    add plannded flooding start and end time to the pivoted table
    '''
    df_d['Flood Start'] = pd.to_datetime(df_d['StartDT'])
    df_d['Flood End'] = pd.to_datetime(df_d['EndDT'])
    df_d = df_d[['Bid_ID', 'Field_ID', 'Status', 'Flood Start', 'Flood End']]
    df_pivot = pd.merge(df, df_d, on=['Bid_ID', 'Field_ID'], how='left')
    df_pivot = df_pivot.loc[df_pivot.Status.isin(stat_list)]
  # print("Selected status values: {}".format(stat_list))
  # print("All status values: {}".format(df_d['Status'].unique().tolist()))
    df_pivot = df_pivot.drop(['Status'], axis=1)
    col_num = -4
  # Change the order of the columns
    cols = df_pivot.columns.tolist()
    cols = cols[col_num:] + cols[:col_num]
    df_pivot = df_pivot[cols]
    df_pivot['Flood Start'] = df_pivot['Flood Start'].astype(str)
    df_pivot['Flood End'] = df_pivot['Flood End'].astype(str)
    return df_pivot


def no_flood_dates(df):
    cols = df.columns.tolist()
    cols = cols[-2:] + cols[:-2]
    df = df[cols]
    return df


def cloud_free_percent(df, start):
    # Check the number of cloud free records in the last seven days
    # Calculate the start and end dates of last week and two weeks ago
    start_last = dt.datetime.strptime(start, '%Y-%m-%d').date()
    end_last = start_last + dt.timedelta(days=6)
    start_last2 = start_last - dt.timedelta(days=7)
    # Create a boolean mask indicating which rows meet both conditions
    df['Date_obj'] = df['Date'].dt.date
    last_week = df[(df['Date_obj'] <= end_last) & (df['Date_obj'] >= start_last)].groupby(
        ['Unique_ID']).agg({'Pct_CloudFree': 'max'})
    two_week_ago = df[(df['Date_obj'] < start_last) & (
        df['Date_obj'] >= start_last2)].groupby(['Unique_ID']).agg({'Pct_CloudFree': 'max'})
    mask_last_week = (last_week > cloud_free_thresh)
    mask_2_week = (two_week_ago > cloud_free_thresh)
    num = len(df.Unique_ID.unique())
    # Count the number of rows that meet the conditions
    percent = mask_last_week.sum()/len(last_week)
    mask = mask_last_week.sum()
    mask2 = mask_2_week.sum()
    if len(two_week_ago) == 0:
        percent2 = 0
    else:
        percent2 = mask_2_week.sum()/len(two_week_ago)
    # print(num, percent[0], percent2[0])
    return num, percent[0], percent2[0], mask[0], mask2[0]


def watch_list(df, start):
    columns = df.columns[0:4].values.tolist()
    columns.append(start)
    print(columns)
    # print(start)
    in_flood = df[columns].copy()
    in_flood['Flood Start'] = pd.to_datetime(in_flood['Flood Start'])
    in_flood['Flood End'] = pd.to_datetime(in_flood['Flood End'])
    in_flood = in_flood[(in_flood[start] <= 0.33) &
                        (in_flood['Flood Start'] <= pd.to_datetime(start)) &
                        (in_flood['Flood End'] > pd.to_datetime(start))].sort_values(by=in_flood.columns[-1])
    in_flood[start] = in_flood[start]*100
    watch = in_flood[in_flood.iloc[:, -1].notna()]
    watch['Flood Start'] = watch['Flood Start'].astype(str)
    watch['Flood End'] = watch['Flood End'].astype(str)
    watch[start] = watch[start].astype(int)
    watch = watch.rename(columns={start: 'Flooding Percentage, %'})
    # return watch with format percentage
    return watch
