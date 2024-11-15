"""
ARCHES - a program developed to inventory and manage immovable cultural heritage.
Copyright (C) 2013 J. Paul Getty Trust and World Monuments Fund

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as
published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program. If not, see <http://www.gnu.org/licenses/>.
"""

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User
from django.db import connection, models, transaction
from arches.app.models.graph import Graph
from arches.app.models.models import Node, Widget


class Command(BaseCommand):
    """
    Commands for adding arches test users

    """

    # Silence system checks since this command is the cure for
    # one of the system checks (arches.E004)
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument(
            "-o",
            "--operation",
            nargs="?",
            choices=[
                "publish",
                "create_editable_future_graphs",
                "migrate_string_nodes_to_nonlocalized",
            ],
            help="""
            Operation Type
                'publish' publishes resource models indicated using the --graphs arg.
                'create_editable_future_graphs' creates an editable_future_graph for resource models indicated using the --graphs arg.

                Operations apply to all resource models if a --graphs value is not provided,
            """,
        )
        parser.add_argument(
            "-g",
            "--graphs",
            action="store",
            dest="graphs",
            default=False,
            help="A comma separated list of graphids to which an operation will be applied.",
        )
        parser.add_argument(
            "-n",
            "--nodes",
            action="store",
            dest="nodes",
            default=False,
            help="A comma separated list of node aliases to which an operation will be applied.",
        )
        parser.add_argument(
            "-u",
            "--username",
            action="store",
            dest="username",
            default="admin",
            help="A username required for the publication of graphs.",
        )
        parser.add_argument(
            "--update",
            action="store_true",
            dest="update",
            help="This will update PublishedGraph instances without creating a new GraphPublication.",
        )
        parser.add_argument(
            "-ui",
            "--update_instances",
            action="store_true",
            dest="update_instances",
            help="Do you want to assign new graph publication ids to all corresponding resource instances?",
        )

    def handle(self, *args, **options):
        if options["graphs"]:
            self.graphs = [
                Graph(graphid.strip()) for graphid in options["graphs"].split(",")
            ]
        else:
            self.graphs = Graph.objects.filter(isresource=True).exclude(
                source_identifier__isnull=False
            )

        self.update_instances = True if options["update_instances"] else False
        self.update = True if options["update"] else False

        if options["operation"] == "publish":
            self.publish(options["username"])

        if options["operation"] == "create_editable_future_graphs":
            self.create_editable_future_graphs()

        if options["operation"] == "migrate_string_nodes_to_nonlocalized":
            source_graphids = [graph.graphid for graph in self.graphs]
            self.future_graphs = Graph.objects.filter(
                source_identifier__in=source_graphids
            )

            if options["nodes"]:
                node_aliases = [alias.strip() for alias in options["nodes"].split(",")]
                self.nodes = Node.objects.filter(
                    graph__in=[graph.pk for graph in self.future_graphs],
                    alias__in=node_aliases,
                    datatype="string",
                ).prefetch_related("cardxnodexwidget_set")
            else:
                raise CommandError("No node aliases provided.")

            self.migrate_string_nodes_to_nonlocalized()

    def create_editable_future_graphs(self):
        print("\nBEGIN Create editable_future_graphs...")

        with transaction.atomic():
            for graph in self.graphs:
                print("\nCreating editable_future_graph for %s..." % graph.name)
                graph.create_editable_future_graph()

                print(
                    "%s has been updated! Creating a new publication for %s."
                    % (graph.name, graph.name)
                )
                graph.publish()

            print("\nEND Create editable_future_graphs. Success!")

    def publish(self, username):
        user = User.objects.get(username=username)

        if self.update:
            print("\nUpdating Publications...")
        else:
            print("\nPublishing ...")

        graphids = []
        for graph in self.graphs:
            if not graph.source_identifier_id:
                graphids.append(str(graph.pk))

                print(graph.name)

                if self.update:
                    if graph.publication_id:
                        graph.update_published_graphs()
                else:
                    if not graph.publication_id:
                        graph.publish(user)

            graphids.append(str(graph.pk))
        if self.update_instances:
            graphids = tuple(graphids)
            with connection.cursor() as cursor:
                cursor.execute(
                    "update resource_instances r set graphpublicationid = publicationid from graphs g where r.graphid = g.graphid and g.graphid in %s;",
                    (graphids,),
                )

    def migrate_string_nodes_to_nonlocalized(self):
        NON_LOCALIZED_STRING_WIDGET = Widget.objects.get(
            name="non-localized-text-widget"
        )

        with transaction.atomic():
            for node in self.nodes:
                node.datatype = "non-localized-string"
                node.full_clean()
                node.save()

                cross_records = node.cardxnodexwidget_set.annotate(
                    updated_config=models.F("config")
                )

                for cross_record in cross_records:
                    cross_record.config = {}
                    cross_record.save()

                    original_default_value = cross_record.updated_config.get(
                        "defaultValue", None
                    )
                    if original_default_value:
                        new_default_value = original_default_value["en"]["value"]
                        cross_record.updated_config["defaultValue"] = new_default_value

                    original_widgth = cross_record.updated_config.get("width", None)
                    if original_widgth:
                        reformatted_width = original_widgth.replace("%", "") + "%"
                        cross_record.updated_config["width"] = reformatted_width

                    cross_record.config = cross_record.updated_config
                    cross_record.widget = NON_LOCALIZED_STRING_WIDGET
                    cross_record.full_clean()
                    cross_record.save()

        # Refetch updated future graphs (and their updated nodes on the graph proxy model instance)
        future_graphs = Graph.objects.filter(
            pk__in=[future_graph.pk for future_graph in self.future_graphs]
        )
        for future_graph in future_graphs:
            source_graph = Graph.objects.get(pk=future_graph.source_identifier_id)
            updated_source_graph = source_graph.update_from_editable_future_graph(
                editable_future_graph=future_graph
            )
            editable_future_graph = updated_source_graph.create_editable_future_graph()
            updated_source_graph.publish(
                notes="Migrated selected string nodes to non-localized string nodes"
            )

            self.stdout.write(
                "The following nodes for the {0} graph have been successfully migrated to non-localized string datatype: {1}".format(
                    updated_source_graph.name,
                    ", ".join([node.alias for node in self.nodes]),
                )
            )
