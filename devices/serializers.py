from rest_framework import serializers
from .models import Device, Server, TypeDevice, Trajectory
from map.views import ZoneSerializer
from companies.views import CompanySerializer


class TypeDeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = TypeDevice
        fields = ['uid', 'product','value','port', 'name', 'status']


class DeviceSerializer(serializers.ModelSerializer):
    zone = ZoneSerializer()
    company_manager = CompanySerializer()
    type= TypeDeviceSerializer()
    is_device_addable = serializers.SerializerMethodField()
    class Meta:
        model = Device
        fields = ['uid', 'type', 'imei', 'name', 'car_name', 'sim_number', 'status', 'company_manager', 'zone', 'is_actif', 'is_device_addable', 'speed_limit', 'ip_address', 'port', 'engine_lock']
    
    def get_is_device_addable(self, obj):
        total_device_company = obj.company_manager.nbr_device
        device_in_use = Device.objects.filter(company_manager=obj.company_manager, is_actif=True).count()
        return device_in_use < total_device_company


class ServerDeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Server
        fields = ['uid', 'ip_address', 'hostname', 'port', 'status']



class DeviceDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = Device
        fields = ['uid', 'type', 'imei', 'name', 'sim_number', 'company_manager', 'zone', 'car_name']

class TrajectoryPropertiesSerializer(serializers.ModelSerializer):
    properties = serializers.JSONField(read_only=True, allow_null=True)
    test_json_field = serializers.JSONField()
    class Meta:
        model = Trajectory
        fields = ['properties', 'device', 'geom', 'start_time', 'end_time', 'test_json_field']

class LocationSerializer(serializers.Serializer):
    lat = serializers.FloatField()
    lng = serializers.FloatField()
    city = serializers.CharField(max_length=255)
    status = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        max_length=255
    )

class PointSerializer(serializers.Serializer):
    status = serializers.CharField()
    location = LocationSerializer()
    timestamp = serializers.DateTimeField()
    speed = serializers.CharField()
    mode = serializers.CharField()

class TrajectoryDataSerializer(serializers.Serializer):
    points = PointSerializer(many=True)


class ParametersSerializer(serializers.Serializer):
    speed_limit = serializers.FloatField() 
    #other parameters

class TrajectoryRequestSerializer(serializers.Serializer):
    device_id = serializers.UUIDField()
    start_time = serializers.DateTimeField()
    end_time = serializers.DateTimeField()
    trajectories = TrajectoryDataSerializer(many=True)
    parameters = ParametersSerializer()


