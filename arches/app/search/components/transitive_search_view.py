from arches.app.search.components.standard_search_view import StandardSearchView
from arches.app.search.elasticsearch_dsl_builder import Bool, Query, Terms, Nested
from arches.app.utils.betterJSONSerializer import JSONDeserializer

from arches.app.models.system_settings import settings
from arches.app.models.models import GraphModel
from arches.app.search.mappings import RESOURCES_INDEX
from arches.app.search.search_engine_factory import SearchEngineFactory
from arches.app.utils.string_utils import get_str_kwarg_as_bool
from django.utils.translation import gettext as _
from arches.app.utils.permission_backend import get_resource_types_by_perm

from typing import Dict, Tuple

from arches.app.search.components.base import SearchFilterFactory
from arches.app.views.search import (
    append_instance_permission_filter_dsl,
    get_permitted_nodegroups,
    get_provisional_type,
)

import logging

logger = logging.getLogger(__name__)


class TransitiveSearchView(StandardSearchView):

    def view_data(self):
        return {
            "resources": list(
                GraphModel.objects.filter(
                    graphid__in=get_resource_types_by_perm(
                        self.request.user, "read_nodegroup"
                    )
                )
            )
        }

    def create_query_dict(self, query_dict):
        # check that all searchview required linkedSearchFilters are present
        # query_dict[self.searchview_component.componentname] = True
        for linked_filter in self.searchview_component.config["linkedSearchFilters"]:
            if (
                linked_filter.get("required", False)
                and linked_filter["componentname"] not in query_dict
            ):
                query_dict[linked_filter["componentname"]] = {}
        return self.sort_query_dict(query_dict)

    def append_dsl(self, search_query_object, **kwargs):
        querystring_params = kwargs.get("querystring", "[]")
        search_query_object["query"].include("fromrelations")
        search_query_object["query"].include("torelations_graphids")
        search_query_object["query"].exclude("tiles")
        transitive_graph_filter = Bool()

        graphids = JSONDeserializer().deserialize(querystring_params)
        if len(graphids) > 0:
            transitive_graph_filter.should(
                Nested(
                    path="fromrelations",
                    query=Terms(field="fromrelations.graphid", terms=graphids),
                )
            )
            transitive_graph_filter.should(
                Terms(  # checks for docs with at least one matching graphid
                    field="torelations_graphids", terms=graphids
                )
            )
            transitive_graph_filter.minimum_should_match = 1

            search_query_object["query"].add_query(transitive_graph_filter)

    def execute_query(self, search_query_object, response_object, **kwargs):
        resourceinstanceid = kwargs.get("resourceinstanceid", None)
        if resourceinstanceid is None:
            limit = 10000
            results = search_query_object["query"].search(
                index=RESOURCES_INDEX, limit=limit, scroll="1m"
            )

            scroll_id = results["_scroll_id"]
            scroll_size = results["hits"]["total"]["value"]
            total_results = results["hits"]["total"]["value"]

            while scroll_size > 0:
                page = search_query_object["query"].se.es.scroll(
                    scroll_id=scroll_id, scroll="1m"
                )
                scroll_size = len(page["hits"]["hits"])
                results["hits"]["hits"] += page["hits"]["hits"]
        else:
            results = search_query_object["query"].search(
                index=RESOURCES_INDEX, id=resourceinstanceid
            )
            total_results = 1

        if results is not None:
            if "hits" not in results:
                if "docs" in results:
                    results = {"hits": {"hits": results["docs"]}}
                else:
                    results = {
                        "hits": {"hits": [results], "total": {"value": total_results}}
                    }

        response_object["results"] = results

    def execute_followup_query(self, search_query_object, response_object, **kwargs):
        ids_query = Bool()
        ids_query.filter(
            Terms(
                field="resourceinstanceid",
                terms=[
                    hit["_id"] for hit in response_object["results"]["hits"]["hits"]
                ],
            )
        )
        search_query_object["query"].add_query(ids_query)
        search_query_object["query"].include("relations")
        load_tiles = get_str_kwarg_as_bool("tiles", self.request.GET)
        if load_tiles:
            search_query_object["query"].include("tiles")
        search_query_object["query"].include("graph_id")
        search_query_object["query"].include("root_ontology_class")
        search_query_object["query"].include("resourceinstanceid")
        search_query_object["query"].include("points")
        search_query_object["query"].include("geometries")
        search_query_object["query"].include("displayname")
        search_query_object["query"].include("displaydescription")
        search_query_object["query"].include("map_popup")
        search_query_object["query"].include("provisional_resource")
        search_query_object["query"].include("permissions")

        results = None
        for_export = get_str_kwarg_as_bool("export", self.request.GET)
        pages = self.request.GET.get("pages", None)
        total = int(self.request.GET.get("total", "0"))
        dsl = search_query_object["query"]
        if for_export or pages:
            results = dsl.search(index=RESOURCES_INDEX, scroll="1m")
            scroll_id = results["_scroll_id"]
            if not pages:
                if total <= settings.SEARCH_EXPORT_LIMIT:
                    pages = (total // settings.SEARCH_RESULT_LIMIT) + 1
                else:
                    pages = (
                        int(
                            settings.SEARCH_EXPORT_LIMIT // settings.SEARCH_RESULT_LIMIT
                        )
                        - 1
                    )
            for page in range(int(pages)):
                results_scrolled = dsl.se.es.scroll(scroll_id=scroll_id, scroll="1m")
                results["hits"]["hits"] += results_scrolled["hits"]["hits"]

        if results is not None:
            if "hits" not in results:
                if "docs" in results:
                    results = {"hits": {"hits": results["docs"]}}
                else:
                    results = {"hits": {"hits": [results]}}

                results["hits"]["total"] = {"value": len(results["hits"]["hits"])}

        response_object["results"] = results

    def handle_search_results_query(
        self,
        search_filter_factory: SearchFilterFactory,
        returnDsl: bool,
    ) -> Tuple[Dict, Dict]:
        se = SearchEngineFactory().create()
        search_query_object = {"query": Query(se)}
        response_object = {"results": None}
        sorted_query_obj = search_filter_factory.create_search_query_dict(
            list(self.request.GET.items()) + list(self.request.POST.items())
        )
        permitted_nodegroups = get_permitted_nodegroups(self.request.user)
        include_provisional = get_provisional_type(self.request)
        try:
            for filter_type, querystring in list(sorted_query_obj.items()):
                search_filter = search_filter_factory.get_filter(filter_type)
                if search_filter:
                    search_filter.append_dsl(
                        search_query_object,
                        permitted_nodegroups=permitted_nodegroups,
                        include_provisional=include_provisional,
                        querystring=querystring,
                    )
            append_instance_permission_filter_dsl(self.request, search_query_object)
        except Exception as err:
            logger.exception(err)
            message = {
                "message": _("Error: {0}. Search failed.").format(str(err)),
            }
            raise Exception(message)

        if returnDsl:
            return response_object, search_query_object

        for filter_type, querystring in list(sorted_query_obj.items()):
            search_filter = search_filter_factory.get_filter(filter_type)
            if search_filter:
                search_filter.execute_query(search_query_object, response_object)

        search_query_object["query"] = Query(SearchEngineFactory().create())
        # need to re-apply paging-filter and sorting append_dsl
        for filter_type, querystring in list(sorted_query_obj.items()):
            search_filter = search_filter_factory.get_filter(filter_type)
            if search_filter and filter_type in ["paging-filter", "sort-results"]:
                search_filter.append_dsl(
                    search_query_object,
                    permitted_nodegroups=permitted_nodegroups,
                    include_provisional=include_provisional,
                    querystring=querystring,
                )

        self.execute_followup_query(search_query_object, response_object)
        if response_object["results"] is not None:
            # allow filters to modify the results
            for filter_type, querystring in list(sorted_query_obj.items()):
                search_filter = search_filter_factory.get_filter(filter_type)
                if search_filter:
                    search_filter.post_search_hook(
                        search_query_object,
                        response_object,
                        permitted_nodegroups=permitted_nodegroups,
                    )

            search_query_object.pop("query")
            # ensure that if a search filter modified the query in some way
            # that the modification is set on the response_object
            for key, value in list(search_query_object.items()):
                if key not in response_object:
                    response_object[key] = value

        return response_object, search_query_object
