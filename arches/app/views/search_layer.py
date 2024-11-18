import math
from django.views import View

from django.core.cache import caches
from arches.app.models.system_settings import settings
from django.utils.translation import gettext as _

from arches.app.search.search_engine_factory import SearchEngineFactory
from arches.app.search.elasticsearch_dsl_builder import (
    Query,
    Bool,
    GeoShape,
    Nested,
    GeoTileGridAgg,
    NestedAgg,
    Aggregation,
)

# from django.db import connection
from django.http import Http404, HttpResponse
from arches.app.utils.betterJSONSerializer import JSONDeserializer
from pprint import pprint

# from django.contrib.gis.geos import Polygon
from datetime import datetime, timedelta
from time import time
import mercantile
import mapbox_vector_tile

ZOOM_THRESHOLD = 14
EXTENT = 4096


class SearchLayer(View):
    def get(self, request, zoom, x, y):
        start = time()
        print(f"ZOOM: {zoom}")
        searchid = request.GET.get("searchid", None)
        if not searchid:
            print("NO SEARCHID FOUND ON REQUEST")
            raise Http404(_("Missing 'searchid' query parameter."))

        EARTHCIRCUM = 40075016.6856
        PIXELSPERTILE = 256
        cache = caches["default"]
        pit_id = cache.get(searchid + "_pit")
        query_dsl = cache.get(searchid + "_dsl")
        # pprint(query_dsl)
        # {"pit_id": pit_id, "dsl": query.dsl}
        if pit_id is None or query_dsl is None:
            print(f"no resourceids found in cache for searchid: {searchid}")
            raise Http404(_("Missing resourceids from search cache."))

        se = SearchEngineFactory().create()
        query_dsl = JSONDeserializer().deserialize(query_dsl, indent=4)
        new_query = Query(se, limit=0)
        new_query.prepare()
        new_query.dsl = query_dsl
        # spatial_query = Bool()
        # if int(y) == 203:
        #     print("\n\n\nwhats my new query\n\n\n")
        #     pprint(new_query.__str__())
        tile_x = int(x)
        tile_y = int(y)
        tile_z = int(zoom)
        tile_bounds = mercantile.bounds(tile_x, tile_y, tile_z)
        bbox = (
            tile_bounds.west,
            tile_bounds.south,
            tile_bounds.east,
            tile_bounds.north,
        )
        geo_bbox_query = {
            "geo_bounding_box": {
                "points.point": {
                    "top_left": {"lat": tile_bounds.north, "lon": tile_bounds.west},
                    "bottom_right": {"lat": tile_bounds.south, "lon": tile_bounds.east},
                }
            }
        }

        if int(zoom) < ZOOM_THRESHOLD:

            geotile_agg = GeoTileGridAgg(
                precision=int(zoom), field="points.point", size=10000
            )
            centroid_agg = Aggregation(
                type="geo_centroid", name="centroid", field="points.point"
            )
            geotile_agg.add_aggregation(centroid_agg)
            nested_agg = NestedAgg(path="points", name="geo_aggs")
            nested_agg.add_aggregation(geotile_agg)

            # Build the filter aggregation
            geo_filter_agg = Aggregation(
                type="filter",
                name="geo_filter",
                filter=Nested(path="points", query=geo_bbox_query).dsl,
            )

            # Add the geotile_grid aggregation under the filter aggregation
            geo_filter_agg.add_aggregation(geotile_agg)

            # Update the nested aggregation
            nested_agg = NestedAgg(path="points", name="geo_aggs")
            nested_agg.add_aggregation(geo_filter_agg)
            new_query.add_aggregation(nested_agg)

            # pit doesn't allow scroll context or index
            new_query.dsl["source_includes"] = []
            new_query.dsl["size"] = 0
            # if int(y) == 203:
            #     pprint(new_query.dsl)
            results = se.es.search(
                pit={"id": pit_id, "keep_alive": "2m"}, _source=False, **new_query.dsl
            )
            elapsed = time() - start
            # print(
            #     "_______Time to finish search_layer search 1 (total: {0}) = {1}".format(results["hits"]["total"]["value"], timedelta(seconds=elapsed))
            # )
            # print("search done")
            # print(results["hits"]["total"])
            # pprint(results)
            features = []
            buckets = results["aggregations"]["geo_aggs"]["geo_filter"]["zoomed_grid"][
                "buckets"
            ]
            # print(f"Number of buckets: {len(buckets)}")

            for bucket in buckets:
                centroid = bucket["centroid"]["location"]
                lon = centroid["lon"]
                lat = centroid["lat"]
                doc_count = bucket["doc_count"]
                # px, py = lnglat_to_tile_px(lon, lat, tile_x, tile_y, tile_z, EXTENT)

                feature = {
                    "geometry": {"type": "Point", "coordinates": [lon, lat]},
                    "properties": {"count": doc_count},
                }

                features.append(feature)

            layers = [
                {
                    "name": "clusters",  # Layer name
                    "features": features,
                    "version": 2,
                    "extent": EXTENT,
                }
            ]
        else:
            # Fetch individual features
            # Add the spatial filter to the query
            points_spatial_query = Nested(path="points", query=geo_bbox_query)
            # new_query.add_query(spatial_query)

            geometries_spatial_query = Nested(path="geometries", query=geo_bbox_query)
            spatial_bool_query = Bool()
            spatial_bool_query.should(points_spatial_query)
            spatial_bool_query.should(geometries_spatial_query)
            new_query.add_query(spatial_bool_query)

            new_query.dsl["size"] = 10000

            new_query.include("points.point")
            new_query.include("geometries.geom")
            # new_query.include("resourceinstanceid")
            # Add other fields if needed

            # Execute the search
            results = se.es.search(
                pit={"id": pit_id, "keep_alive": "2m"}, **new_query.dsl
            )

            # Process the hits to generate features
            features = []
            point_features = []
            geometry_features = []

            for hit in results["hits"]["hits"]:
                source = hit["_source"]
                resource_id = hit.get("_id")

                # Handle points
                points = source.get("points", [])
                for point in points:
                    point_geom = point.get("point")
                    if point_geom:
                        lon = point_geom.get("lon")
                        lat = point_geom.get("lat")
                        if lon and lat:
                            feature = {
                                "geometry": {
                                    "type": "Point",
                                    "coordinates": [lon, lat],
                                },
                                "properties": {
                                    "resourceinstanceid": resource_id,
                                    "count": 1,
                                },
                            }
                            point_features.append(feature)
                geometries = source.get("geometries", [])
                for geometry in geometries:
                    geom = geometry.get("geom")
                    if geom:
                        geom_type = geom.get("type")
                        coordinates = geom.get("coordinates")
                        if coordinates:
                            feature = {
                                "geometry": {
                                    "type": geom_type,
                                    "coordinates": coordinates,
                                },
                                "properties": {"resourceinstanceid": resource_id},
                            }
                            pprint(feature)
                            geometry_features.append(feature)

            # Build layers
            layers = []

            if point_features:
                point_layer = {
                    "name": "points",
                    "features": point_features,
                    "version": 2,
                    "extent": EXTENT,
                }
                layers.append(point_layer)

            if geometry_features:
                geometry_layer = {
                    "name": "geometries",
                    "features": geometry_features,
                    "version": 2,
                    "extent": EXTENT,
                }
                layers.append(geometry_layer)

        tile = mapbox_vector_tile.encode(
            layers, quantize_bounds=bbox, y_coord_down=True, extents=EXTENT
        )
        return HttpResponse(tile, content_type="application/vnd.mapbox-vector-tile")


def create_searchlayer_mvt_cache_key(searchid_hash, zoom, x, y, user):
    return f"searchlayer_mvt_{searchid_hash}_{zoom}_{x}_{y}_{user}"
