from django.db import models


class UUID4(models.Func):
    function = "uuid_generate_v4"
    arity = 0
    output_field = models.UUIDField()


class JSONBPathQueryArray(models.Func):
    function = "JSONB_PATH_QUERY_ARRAY"
    arity = 2
    output_fields = models.JSONField()
