from django.contrib.gis.db import models 
import uuid
from django.utils.timezone import now

class Country(models.Model):
    name = models.CharField(max_length=100)
    alpha2_code = models.CharField(max_length=2, unique=True)
    alpha3_code = models.CharField(max_length=3, unique=True)
    numeric_code = models.IntegerField()

    def __str__(self):
        return self.name

class Company(models.Model):
    uid = models.UUIDField(primary_key=True, editable=False, default=uuid.uuid4)
    name = models.CharField(max_length=150, blank=False, null=False)
    email = models.CharField(max_length=150, null=True, unique=True)    
    region = models.CharField(max_length=150,blank=True, null=True)
    adress = models.CharField(max_length=250,blank=True, null=True)
    country = models.ForeignKey('Country', on_delete=models.SET_NULL, null=True, blank=True)
    is_actif = models.BooleanField(default=True)
    logo = models.ImageField(upload_to="company_logos/", blank=True, null=True)
    nbr_device = models.PositiveIntegerField(
        default=0,
        null=False,
        blank=False,
    )
    default_company = models.BooleanField(default=False)

    created_by = models.ForeignKey(
        'accounts.User', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True
    )

    deleted_at = models.DateTimeField(null=True, blank=True) 

    def __str__(self) -> str:
        return self.name

    def delete(self, *args, **kwargs):
        """
        Override the delete method to set deleted_at instead of deleting the object.
        """
        self.deleted_at = now()
        self.save()
    
    @property
    def is_deleted(self):
        """Check if the object is soft-deleted."""
        return self.deleted_at is not None
