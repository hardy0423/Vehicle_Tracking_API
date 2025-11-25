from django.db import models
from devices.models import Device
import uuid
from utils.alert_trigger import check_geofence_violation
from constants.speed_limits import SEVERITY_THRESHOLDS

# Create your models here.
class Event(models.Model):
    EVENT_TYPES = [
        ('speed_excess', 'Excès de vitesse'),
        ('geofence_breach', 'Violation de géofence'),
        ('device_offline', 'Appareil hors ligne'),
        ('battery_low', 'Batterie faible'),
        ('maintenance_due', 'Maintenance requise'),
        #other ...
    ]
    uid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device = models.ForeignKey(Device, on_delete=models.CASCADE)
    event_type = models.CharField(max_length=50, choices=EVENT_TYPES)
    timestamp = models.DateTimeField(auto_now_add=True)
    location = models.JSONField(null=True, blank=True)
    data = models.JSONField(null=True, blank=True)  
    
    class Meta:
        ordering = ['-timestamp']
        db_table = 'trackings_events'

        
    
    def __str__(self):
        return f"{self.get_event_type_display()} - Device: {self.device_id}"
    
    def determine_geofence_severity(self):
        if not self.data or 'distance' not in self.data:
            return 'medium'

        distance = self.data.get('distance', 0)

        if distance > 1000:
            return 'high'
        elif distance > 500:
            return 'medium'
        return 'low'
    
    def determine_speed_severity(self):
        if not self.data or 'excess' not in self.data:
            return 'medium'
        
        excess = self.data.get('excess', 0)
        if excess >= SEVERITY_THRESHOLDS['critical']:
            return 'critical'
        elif excess >= SEVERITY_THRESHOLDS['high']:
            return 'high'
        elif excess >= SEVERITY_THRESHOLDS['medium']:
            return 'medium'
        return 'low'