from django.contrib.gis.db import models 
from django.contrib.gis.geos import Point
import uuid
from companies.models import Company
from django.core.validators import MaxValueValidator, MinValueValidator
from map.models import InterventionZone
from django.utils.timezone import now
from django.contrib.postgres.fields import JSONField


class TypeDevice(models.Model):
    uid = models.UUIDField(primary_key=True, editable=False, default=uuid.uuid4, unique=True)
    product = models.CharField(max_length=150, default='')
    name = models.CharField(max_length=150)
    value = models.CharField(max_length=150, default='')
    status = models.BooleanField(default=False)
    port = models.CharField(max_length=7, default='')

    def __str__(self) -> str:
        return self.name

class Server(models.Model):
    uid = models.UUIDField(primary_key=True, editable=False, default=uuid.uuid4)
    ip_address = models.GenericIPAddressField()
    hostname = models.CharField(max_length=150, blank=True, null=True)
    port = models.PositiveIntegerField(default=0, validators=[MinValueValidator(0), MaxValueValidator(65535)])
    status = models.BooleanField(default=True)
    def __str__(self):
        return f"{self.hostname} ({self.ip_address})"


class Device(models.Model):
    STATUS_CHOICES = [
        ('On', 'On'),
        ('Off', 'Off'),
    ]

    uid = models.UUIDField(primary_key=True, editable=False, default=uuid.uuid4)
    imei = models.CharField(max_length=150, unique=True)
    name = models.CharField(max_length=150, blank=True, null=True)
    sim_number = models.CharField(max_length=20, blank=True, null=True)
    is_device_addable = models.BooleanField(default=False)
    status = models.CharField(
        max_length=3,
        blank=True,
        null=True,
        choices=STATUS_CHOICES,
        default='Off'
    )
    type = models.ForeignKey(TypeDevice, on_delete=models.SET_NULL, null=True, related_name='devices')
    company_manager = models.ForeignKey(Company, on_delete=models.SET_NULL, null=True, related_name='devices')
    #servers = models.ManyToManyField(Server, related_name='devices', blank=True)
    zone = models.ForeignKey(InterventionZone, on_delete=models.CASCADE, null=True, related_name='devices')
    is_actif = models.BooleanField(default=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    is_private_mode = models.BooleanField(default=False)
    is_pro_mode = models.BooleanField(default=False)
    speed_limit = models.FloatField(default=0.0)
    car_name = models.CharField(max_length=150, blank=True, null=True)  # immatriculation

    #to be checked
    ip_address = models.GenericIPAddressField(default='192.000.1.100')
    port = models.IntegerField(default=00000)
    engine_lock=models.BooleanField(default=False) 

    def __str__(self) -> str:
        return self.name

    def delete(self, *args, **kwargs):
        """
        Override the delete method to set deleted_at instead of deleting the object.
        """
        self.deleted_at = now()
        self.save()

    def restore(self):
        """
        Restore a soft-deleted object by setting deleted_at to None.
        """
        self.deleted_at = None
        self.save()
    
    @property
    def is_deleted(self):
        """Check if the object is soft-deleted."""
        return self.deleted_at is not None


class Trajectory(models.Model):
    uid = models.UUIDField(primary_key=True, editable=False, default=uuid.uuid4)
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name='trajectories')
    geom = models.LineStringField(srid=3857)
    properties = models.JSONField(blank=True, null=True)  # Liste d'attributs associés à chaque point
    start_time = models.DateTimeField(auto_now_add=True)  
    end_time = models.DateTimeField(null=True, blank=True) 
    last_position = models.JSONField(blank=True, null=True)


    class Meta:
        ordering = ['-start_time']

    # def __str__(self):
    #     return f"Trajectory for {self.device.uid} starting at {self.start_time}"

class Status(models.Model):
    STATUS_CHOICES = (
        ('0', 'Power Supply OK'),
        ('1', 'Power Supply Failure'),
        ('2', 'Battery OK'),
        ('3', 'Low Battery'),
        ('4', 'GPS Signal Acquired'),
        ('5', 'GPS Signal Lost'),
        ('6', 'No Movement Detected'),
        ('7', 'Movement Detected'),
        ('8', 'Vibration Detected'),
        ('9', 'Input Off'),
        ('10', 'Input On'),
        ('11', 'Over Speed Detected'),
        ('12', 'Ignition Off'),
        ('13', 'Ignition On'),
        ('14', 'Entering Geofence'),
        ('15', 'Exiting Geofence'),
        ('16', 'Communication OK'),
        ('17', 'Communication Failure'),
    )
    uid = models.UUIDField(primary_key=True, editable=False, default=uuid.uuid4)
    code = models.CharField(max_length=10, choices=STATUS_CHOICES, unique=True)
    description = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return f"{self.code} - {self.description}"

class DeviceData(models.Model):
    uid = models.UUIDField(primary_key=True, editable=False, default=uuid.uuid4)
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name='data')
    timestamp = models.DateTimeField()
    latitude = models.FloatField()
    longitude = models.FloatField()
    speed = models.FloatField()
    battery_status = models.CharField(max_length=10, choices=Status.STATUS_CHOICES)
    gps_status = models.CharField(max_length=10, choices=Status.STATUS_CHOICES)
    accelerometer_status = models.CharField(max_length=10, choices=Status.STATUS_CHOICES)
    digital_input_status = models.CharField(max_length=10, choices=Status.STATUS_CHOICES)
    analog_input_status = models.FloatField(blank=True, null=True)
    geofence_status = models.CharField(max_length=10, choices=Status.STATUS_CHOICES)
    communication_status = models.CharField(max_length=10, choices=Status.STATUS_CHOICES)
    ignition_status = models.CharField(max_length=10, choices=Status.STATUS_CHOICES)

    def __str__(self):
        return f"Device {self.device.imei} at {self.timestamp}"
