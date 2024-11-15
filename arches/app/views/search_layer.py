from django.views import View

# from django.http import JsonResponse
import json
from django.core.cache import caches
from arches.app.models.system_settings import settings
from django.utils.translation import gettext as _

# from arches.app.search.search_engine_factory import SearchEngineFactory
from django.db import connection
from django.http import Http404, HttpResponse


class SearchLayer(View):
    def get(self, request, zoom, x, y):
        # se = SearchEngineFactory().create()
        searchid = request.GET.get("searchid", None)
        if not searchid:
            raise Http404(_("Missing 'searchid' query parameter."))
        EARTHCIRCUM = 40075016.6856
        PIXELSPERTILE = 256
        cache = caches["default"]
        resource_ids = cache.get(searchid)
        if resource_ids:
            resource_ids = json.loads(resource_ids)
        else:
            print(f"no resourceids found in cache for searchid: {searchid}")
            raise Http404(_("Missing resourceids from search cache."))

        search_geom_count = 0
        cache_key = create_searchlayer_mvt_cache_key(searchid, zoom, x, y, request.user)
        tile = cache.get(cache_key)
        if tile is None:
            with connection.cursor() as cursor:
                if len(resource_ids) == 0:
                    resource_ids.append(
                        "10000000-0000-0000-0000-000000000001"
                    )  # This must have a uuid that will never be a resource id.
                resource_ids = tuple(resource_ids)

                if int(zoom) < 14:
                    arc = EARTHCIRCUM / ((1 << int(zoom)) * PIXELSPERTILE)
                    distance = arc * float(1000)
                    min_points = 3
                    distance = (
                        settings.CLUSTER_DISTANCE_MAX
                        if distance > settings.CLUSTER_DISTANCE_MAX
                        else distance
                    )

                    count_query = """
                    SELECT count(*) FROM geojson_geometries
                    WHERE
                    ST_Intersects(geom, TileBBox(%s, %s, %s, 3857))
                    AND
                    resourceinstanceid in %s
                    """

                    # get the count of matching geometries
                    cursor.execute(
                        count_query,
                        [
                            zoom,
                            x,
                            y,
                            resource_ids,
                        ],
                    )
                    search_geom_count = cursor.fetchone()[0]

                    if search_geom_count >= min_points:
                        cursor.execute(
                            """WITH clusters(tileid, resourceinstanceid, nodeid, geom, cid)
                            AS (
                                SELECT m.*,
                                ST_ClusterDBSCAN(geom, eps := %s, minpoints := %s) over () AS cid
                                FROM (
                                    SELECT tileid,
                                        resourceinstanceid,
                                        nodeid,
                                        geom
                                    FROM geojson_geometries
                                    WHERE 
                                    ST_Intersects(geom, TileBBox(%s, %s, %s, 3857))
                                    AND
                                    resourceinstanceid in %s
                                ) m
                            )
                            SELECT ST_AsMVT(
                                tile,
                                'search_layer',
                                4096,
                                'geom',
                                'id'
                            ) FROM (
                                SELECT resourceinstanceid::text,
                                    row_number() over () as id,
                                    1 as point_count,
                                    ST_AsMVTGeom(
                                        geom,
                                        TileBBox(%s, %s, %s, 3857)
                                    ) AS geom,
                                    '' AS extent
                                FROM clusters
                                WHERE cid is NULL
                                UNION
                                SELECT NULL as resourceinstanceid,
                                    row_number() over () as id,
                                    count(*) as point_count,
                                    ST_AsMVTGeom(
                                        ST_Centroid(
                                            ST_Collect(geom)
                                        ),
                                        TileBBox(%s, %s, %s, 3857)
                                    ) AS geom,
                                    ST_AsGeoJSON(
                                        ST_Extent(geom)
                                    ) AS extent
                                FROM clusters
                                WHERE cid IS NOT NULL
                                GROUP BY cid
                            ) as tile;""",
                            [
                                distance,
                                min_points,
                                zoom,
                                x,
                                y,
                                resource_ids,
                                zoom,
                                x,
                                y,
                                zoom,
                                x,
                                y,
                            ],
                        )
                    elif search_geom_count:
                        cursor.execute(
                            """SELECT ST_AsMVT(tile, 'search_layer', 4096, 'geom', 'id') FROM (SELECT tileid,
                                id,
                                resourceinstanceid,
                                nodeid,
                                featureid::text AS featureid,
                                ST_AsMVTGeom(
                                    geom,
                                    TileBBox(%s, %s, %s, 3857)
                                ) AS geom,
                                1 AS point_count
                            FROM geojson_geometries
                            WHERE resourceinstanceid in %s and (geom && ST_TileEnvelope(%s, %s, %s))) AS tile;""",
                            [zoom, x, y, resource_ids, zoom, x, y],
                        )
                    else:
                        tile = ""

                    cursor.execute(
                        """SELECT ST_AsMVT(tile, 'search_layer', 4096, 'geom', 'id') FROM (SELECT tileid,
                            id,
                            resourceinstanceid,
                            nodeid,
                            featureid::text AS featureid,
                            ST_AsMVTGeom(
                                geom,
                                TileBBox(%s, %s, %s, 3857)
                            ) AS geom,
                            1 AS point_count
                        FROM geojson_geometries
                        WHERE resourceinstanceid in %s and (geom && ST_TileEnvelope(%s, %s, %s))) AS tile;""",
                        [zoom, x, y, resource_ids, zoom, x, y],
                    )
                tile = bytes(cursor.fetchone()[0]) if tile is None else tile
                cache.set(cache_key, tile, settings.TILE_CACHE_TIMEOUT)

        return HttpResponse(tile, content_type="application/x-protobuf")


def create_searchlayer_mvt_cache_key(searchid_hash, zoom, x, y, user):
    return f"searchlayer_mvt_{searchid_hash}_{zoom}_{x}_{y}_{user}"
