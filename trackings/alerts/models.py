from django.db import models
from trackings.events.models import Event
import uuid

class Alert(models.Model):
    SEVERITY_LEVELS = [
        ('low', 'Faible'),
        ('medium', 'Moyen'),
        ('high', 'Élevé'),
        ('critical', 'Critique'),
    ]

    STATUS_CHOICES = [
        ('pending', 'En attente'),
        ('acknowledged', 'Reconnu'),
        ('resolved', 'Résolu'),
        ('dismissed', 'Ignoré'),
    ]
    uid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, null=True, blank=True)
    severity = models.CharField(max_length=20, choices=SEVERITY_LEVELS, default='low')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    
    class Meta:
        ordering = ['-created_at']
        db_table = 'trackings_alerts' 
    
    def __str__(self):
        return f"Alert: {self.event.get_event_type_display()} - {self.get_severity_display()}"
    