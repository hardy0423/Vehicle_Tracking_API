from rest_framework import serializers
from .models import InterventionZone

class ZoneSerializer(serializers.ModelSerializer):
    nameZone = serializers.CharField(source='name')
    class Meta:
        model = InterventionZone
        fields = ['uid', 'nameZone','geom']
    
    def create(self, validated_data):
        return InterventionZone.objects.create(**validated_data)