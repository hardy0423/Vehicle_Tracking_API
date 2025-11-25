import uuid
from django.contrib.gis.db import models

class InterventionZone(models.Model):
    uid = models.UUIDField(primary_key=True, editable=False, default=uuid.uuid4)
    name = models.CharField(max_length=80, blank=True,default='Zone')
    geom = models.PolygonField(srid=3857, blank=True, null=True)
    default_zone = models.BooleanField(default=False) 

    class Meta:
        db_table = 'interventionzone'