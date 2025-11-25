from django.db import models
from accounts.models import User
from trackings.alerts.models import Alert
import uuid

class Notification(models.Model):
    CRITIQUE = 'Critique'
    ELEVE = 'Élevé'
    MOYEN = 'Moyen'
    FAIBLE = 'Faible'

    NOTIFICATION_TYPES = [
        (CRITIQUE, 'Critique'),
        (ELEVE, 'Élevé'),
        (MOYEN, 'Moyen'),
        (FAIBLE, 'Faible'),
    ]

    uid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    alert = models.ForeignKey(Alert, on_delete=models.CASCADE, null=True, blank=True)
    message = models.TextField()
    notification_type = models.CharField(
        max_length=20,
        choices=NOTIFICATION_TYPES,
        default=FAIBLE
    )
    created_at = models.DateTimeField(auto_now_add=True)
    read = models.BooleanField(default=False)


    class Meta:
        ordering = ['-created_at']
        db_table = 'trackings_notifications' 


    def __str__(self):
        return f"Notification for {self.user.username}: {self.message}" 