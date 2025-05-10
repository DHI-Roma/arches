import logging
import uuid
from arches.app.models.resource import Resource
from arches.app.models.tile import Tile
from arches.app.models.models import IIIFManifest, EditLog, WorkflowHistory
from arches.app.utils.index_database import (
    index_resources_by_transaction,
    optimize_resource_iteration,
)
from django.db import transaction, DatabaseError

# Get an instance of a logger
logger = logging.getLogger(__name__)


# Given a transaction ID, reverse (delete or update) tiles and resources created/updated during the transaction
def reverse_edit_log_entries(transaction_id):
    revserse_operation_transactionid = str(uuid.uuid4())

    transaction_changes = EditLog.objects.filter(transactionid=transaction_id)

    resource_create_changes = transaction_changes.filter(edittype="create")
    tile_edit_changes = transaction_changes.filter(edittype="tile edit")
    tile_create_changes = transaction_changes.filter(edittype="tile create")

    number_of_db_changes = (
        resource_create_changes.count()
        + tile_edit_changes.count()
        + tile_create_changes.count()
    )

    created_resources_query_set = Resource.objects.filter(
        resourceinstanceid__in=resource_create_changes.values_list(
            "resourceinstanceid", flat=True
        )
    )

    try:
        with transaction.atomic():
            for resource in optimize_resource_iteration(
                created_resources_query_set, chunk_size=2000
            ):
                resource.delete(
                    fetch_relations=False,
                    transaction_id=revserse_operation_transactionid,
                )

            for tile in Tile.objects.filter(
                tileid__in=tile_create_changes.values_list("tileinstanceid", flat=True)
            ):
                tile.delete(
                    recalculate_descriptors=False,
                    transaction_id=revserse_operation_transactionid,
                )

            for tile in Tile.objects.filter(
                tileid__in=tile_edit_changes.values_list("tileinstanceid", flat=True)
            ):
                tile.data = tile_edit_changes.get(
                    tileinstanceid=str(tile.tileid)
                ).oldvalue
                tile.save(
                    index=False,
                    recalculate_descriptors=False,
                    transaction_id=revserse_operation_transactionid,
                )
        if tile_edit_changes.count() > 0:
            index_resources_by_transaction(
                transaction_id,
                recalculate_descriptors=True,
            )

    except DatabaseError:
        logger.error("Error connecting to database")
        number_of_db_changes = 0

    return number_of_db_changes


def delete_manifests(transaction_id):
    number_of_db_changes = 0
    try:
        with transaction.atomic():
            transaction_changes = IIIFManifest.objects.filter(
                transactionid=transaction_id
            )
            for obj in transaction_changes:
                obj.delete()
                number_of_db_changes += 1
    except DatabaseError:
        logger.error("Error connecting to database")

    return number_of_db_changes


def delete_workflow_histories(transaction_id):
    number_of_db_changes = 0
    with transaction.atomic():
        # Should have already checked that the user created the transaction.
        qs = WorkflowHistory.objects.filter(workflowid=transaction_id)
        number_of_db_changes = qs.count()
        qs.delete()

    return number_of_db_changes
