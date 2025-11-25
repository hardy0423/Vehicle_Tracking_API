from rest_framework import serializers
from .models import Notification

class NotificationSerializer(serializers.ModelSerializer):

    class Meta:
        model = Notification
        fields = ['uid', 'user', 'alert', 'message', 'notification_type', 'created_at', 'read']
