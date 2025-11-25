# Standard library imports
import logging
from pyproj import Proj, Transformer

# 2Third-party library imports
import requests

#  Django-specific imports
from django.http import Http404, HttpResponse, JsonResponse
from django.db.models import F
from django.db.models.functions import Cast
from django.db.models import TextField, JSONField
from django.contrib.gis.geos import Polygon, LineString, Point
from django.contrib.gis.db.models.functions import AsGeoJSON
from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import TokenAuthentication
from django.contrib.gis.geos import LineString as GEOSLineString
from django.shortcuts import get_object_or_404
from django.db.models.expressions import RawSQL
from datetime import datetime
import struct
from utils.codec12 import create_codec12_command
from utils.parser import DeviceResponseParser
import concurrent.futures
import asyncio
import socket
import re
from rest_framework.exceptions import PermissionDenied, NotFound
from django.utils.decorators import method_decorator

# Imports from internal apps (your project-specific models and serializers)
from companies.serializers import CompanySerializer
from companies.models import Company
from .serializers import DeviceSerializer, ServerDeviceSerializer, TypeDeviceSerializer, DeviceDataSerializer, TrajectoryPropertiesSerializer, TrajectoryRequestSerializer, LocationSerializer
from .models import Device, Server, TypeDevice, Trajectory
from map.models import InterventionZone
from map.serializers import ZoneSerializer
from vectortiles.views import MVTView
from vectortiles import VectorLayer
from vectortiles import settings as app_settings
from rest_framework.authtoken.models import Token
from utils.convert import json_serial, prepare_trajectory_properties, create_geometry_from_points
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from server.device_data_processing import process_tcp_data
from django.views.decorators.csrf import csrf_exempt
from asgiref.sync import sync_to_async
from constants.device_info import (
    STATUS_OFF,
    STATUS_ON,
    PREVIOUS_STATUS_DEVICE,
    PREVIOUS_MODE_DEVICE,
    PROFESSIONAL_MODE,
    PRIVATE_MODE,
)


from rest_framework.pagination import LimitOffsetPagination   
from server.tcp_communication_server import TCPConnectionHandler


logger = logging.getLogger(__name__)

wgs84 = Proj(init="epsg:4326")
web_mercator = Proj(init="epsg:3857")


class DeviceListAPIView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request, *args, **kwargs):
        user = request.user
        id_company = request.query_params.get('uid')
        filter_active = request.query_params.get('active')

        if not id_company:
            return Response(
                {'error': 'Missing company ID (uid).'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if user.is_superuser or getattr(user, 'is_admin', False):
            devices = Device.objects.filter(company_manager_id=id_company)
        elif hasattr(user, 'companies_id') and user.companies_id:
            devices = Device.objects.filter(company_manager_id=user.companies_id)
        else:
            raise PermissionDenied('Unauthorized or no associated companies.')

        if filter_active is None or filter_active.lower() == 'true':
            devices = devices.filter(is_actif=True)
        elif filter_active.lower() == 'false':
            devices = devices.filter(is_actif=False)

        # Ajout du tri par nom ici
        devices = devices.select_related('company_manager').order_by('name')

        paginator = LimitOffsetPagination()
        paginated_devices = paginator.paginate_queryset(devices, request)

        serializer = DeviceSerializer(paginated_devices, many=True)
        return paginator.get_paginated_response(serializer.data)




class DeviceCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get_object(self, uid):
        try:
            return Company.objects.get(uid=uid)
        except Company.DoesNotExist:
            raise Http404

    def post(self, request, *args, **kwargs):
        intervention_zone_id = request.data.get('zone', {}).get('zoneId')

        if intervention_zone_id:
                try:
                    zone_instance = InterventionZone.objects.get(pk=intervention_zone_id)
                except InterventionZone.DoesNotExist:
                    return Response({'error': 'Zone with the provided ID does not exist'}, status=status.HTTP_404_NOT_FOUND)
        else :
            intervention_zone = request.data.get('zone', {})
            if not intervention_zone:
                return Response({'error': 'Intervention zone is required'}, status=status.HTTP_400_BAD_REQUEST)
            
            # Extract and transform geometry
            geojson_geometry = intervention_zone.get('geometry', {})
            geojson_properties = intervention_zone.get('properties', {})
            coordinates = geojson_geometry.get("coordinates", [])
            # Validate geometry presence
            if not coordinates:
                return Response({'error': 'Coordinates are missing'}, status=status.HTTP_400_BAD_REQUEST)

            # Transform coordinates from WGS84 to Web Mercator
            transformer = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
            coords_web_mercator = [[transformer.transform(lon, lat) for lon, lat in coordinates[0]]]
            # Prepare zone data for serialization
            zone_data = {
                'nameZone': geojson_properties.get("nameZone"),
                'geom': Polygon(coords_web_mercator[0])
            }

            # Serialize and validate the zone
            zone_serializer = ZoneSerializer(data=zone_data)
            if not zone_serializer.is_valid():
                return Response(zone_serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            
            # Save the intervention zone and retrieve the instance
            zone_instance = zone_serializer.save()
        
        # # Serialize and validate device data
        device_data = request.data.get('device', {})
        type_uid = device_data.get('type', {})
        if type_uid:
            device_data['type'] = type_uid
        # # Extract the company_manager UID if it exists
        company_manager_uid = device_data.get('company_manager', {})
        try:
            zone_instance = InterventionZone.objects.get(pk=intervention_zone_id)
        except InterventionZone.DoesNotExist:
            pass

        if company_manager_uid:
            device_data['company_manager'] = company_manager_uid

        device_serializer = DeviceDataSerializer(data=device_data)
        if device_serializer.is_valid():
            # Save the device and associate it with the company and zone
            device_instance = device_serializer.save(zone=zone_instance)
            return Response(device_serializer.data, status=status.HTTP_201_CREATED)
        return Response(device_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class UserDeviceCompanyListView(APIView):
    """
    API View to list the companies associated with the authenticated user.
    
    - GET: Returns the list of active companies associated with the user.
        - Admins and superusers can access all companies.
        - Regular users can only access companies they are linked to.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        if user.is_superuser or user.is_admin:
            companies = Company.objects.filter(is_actif=True).order_by('name')
        elif hasattr(user, 'companies_id') and user.companies_id:
            companies = Company.objects.filter(uid=user.companies_id,is_actif=True )
        else:
            return Response(
                {'error': 'Unauthorized or no associated companies'},
                status=status.HTTP_403_FORBIDDEN
            )
        serializer = CompanySerializer(companies, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class DeviceTypeListView(APIView):
    """
    API View to retrieve all device types.
    
    - GET: Lists all available device types that are currently active.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        types = TypeDevice.objects.filter(status=True)
        serializer = TypeDeviceSerializer(types, many=True)
        return Response(serializer.data)

class ServerListView(APIView):
    """
    API View to retrieve all servers.
    
    - GET: Lists all active servers.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        servers = Server.objects.filter(status=True)
        serializer = ServerDeviceSerializer(servers, many=True)
        return Response(serializer.data)

class DeviceRetrieve(APIView):
    """
    API View to retrieve details of a specific device.
    
    - GET: Fetches the details of a device based on its unique ID (UID).
        - The device must be associated with a company the user belongs to.
    """
    def get(self, request, *args, **kwargs):
        uid = kwargs.get('uid')

        if not uid:
            return Response(
                {'error': 'Device UID is required.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Try to retrieve the device
        try:
            device = Device.objects.get(uid=uid)
        except Device.DoesNotExist:
            raise NotFound("Device not found.")
        
        # Check if the device belongs to a company associated with the user
        if not self._is_user_authorized_to_view_device(request.user, device):
            raise PermissionDenied("You do not have permission to access this device.")

        # If device is found and authorized, serialize it
        serializer = DeviceSerializer(device)
        return Response(serializer.data)

    def _is_user_authorized_to_view_device(self, user, device):
        """
        Check if the user is authorized to view the device.
        """
        # Superuser or admin can access any device
        if user.is_superuser or getattr(user, 'is_admin', False):
            return True
        
        # If the user is associated with a company, check if the device belongs to that company
        if hasattr(user, 'companies_id') and user.companies_id:
            return device.company_manager_id == user.companies_id
        
        # For any other case, the user is not authorized
        return False


class DeviceUpdate(APIView):
    """
    API View to update an existing device.
    
    - PUT: Updates the device details, including intervention zone association and device attributes.
        - The device can be updated by users associated with the device's company.
    """
    permission_classes = [IsAuthenticated]

    def put(self, request, *args, **kwargs):
        uid = kwargs.get('uid')

        # Fetch the device to update
        try:
            device_instance = Device.objects.get(uid=uid)
        except Device.DoesNotExist:
            return Response({'error': 'Device not found'}, status=status.HTTP_404_NOT_FOUND)

        # Handle zone data
        intervention_zone_id = request.data.get('zone', {}).get('zoneId')
        if intervention_zone_id:
            try:
                zone_instance = InterventionZone.objects.get(pk=intervention_zone_id)
            except InterventionZone.DoesNotExist:
                return Response({'error': 'Zone with the provided ID does not exist'}, status=status.HTTP_404_NOT_FOUND)
        else:
            # Process new polygon data if no zoneId is provided
            intervention_zone = request.data.get('zone', {})
            if not intervention_zone:
                return Response({'error': 'Intervention zone is required'}, status=status.HTTP_400_BAD_REQUEST)

            geojson_geometry = intervention_zone.get('geometry', {})
            geojson_properties = intervention_zone.get('properties', {})
            coordinates = geojson_geometry.get("coordinates", [])

            if not coordinates:
                return Response({'error': 'Coordinates are missing'}, status=status.HTTP_400_BAD_REQUEST)

            transformer = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
            coords_web_mercator = [[transformer.transform(lon, lat) for lon, lat in coordinates[0]]]

            zone_data = {
                'nameZone': geojson_properties.get("nameZone"),
                'geom': Polygon(coords_web_mercator[0])
            }

            zone_serializer = ZoneSerializer(data=zone_data)
            if not zone_serializer.is_valid():
                return Response(zone_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            zone_instance = zone_serializer.save()

        # Update device data
        device_data = request.data.get('device', {})
        type_uid = device_data.get('type', {})
        if type_uid:
            device_data['type'] = type_uid

        company_manager_uid = device_data.get('company_manager', {})
        if company_manager_uid:
            device_data['company_manager'] = company_manager_uid


        # # Serialize and update the device instance
        device_serializer = DeviceDataSerializer(device_instance, data=device_data, partial=True)
        if device_serializer.is_valid():
            device_instance = device_serializer.save(zone=zone_instance)
            return Response(device_serializer.data, status=status.HTTP_200_OK)
        return Response(device_serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class DeviceDelete(APIView):
    """
    API View to deactivate and delete a device.
    
    - DELETE: Marks a device as inactive and deletes it from the system.
        - Only users with access to the company managing the device can deactivate it.
    """
    permission_classes = [IsAuthenticated]

    def delete(self, request, *args, **kwargs):
        uid = kwargs.get('uid')
        if not uid:
            return Response({'error': 'Device UID is required'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            # Récupérer et désactiver l'appareil
            device = Device.objects.get(uid=uid)
            device.is_actif = False
            device.delete()
            device.save()
            return Response({'message': "L'appareil a été désactivé avec succès."}, status=status.HTTP_204_NO_CONTENT)
        except Device.DoesNotExist:
            raise Http404("Appareil non trouvé.")


class DeviceLocationAPIView(APIView):
    """
    API View to retrieve the location of a device based on its IMEI.
    """
    permission_classes = [IsAuthenticated]
    def post(self, request):
        imei = request.data.get('device_imei')

        if not imei:
            return Response({"error": "IMEI is required"}, status=status.HTTP_400_BAD_REQUEST)
        url = 'https://api.closeguardtechnology.com/v1/396slbHG7506Rlglhglbfj7/deviceinfo'
        headers = {
            'Api-Token': '3853925hxnsvdebdyh36s',
            'Request-Id': '123456789',
            'content-type': 'application/x-www-form-urlencoded'
        }
        data = {'device_imei': imei}

        try:
            response = requests.post(url, headers=headers, data=data)

            if response.status_code != 200:
                return Response({"error": "Failed to fetch data from external API"}, status=response.status_code)

            try:
                device_info = response.json()
            except ValueError:
                return Response({"error": "Invalid JSON response from API"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            if device_info.get('status') == 'success':
                return Response(device_info.get('data', {}), status=status.HTTP_200_OK)
            else:
                return Response({"error": device_info.get('message', 'Unknown error')}, status=status.HTTP_404_NOT_FOUND)

        except requests.exceptions.RequestException as e:
            return Response({"error": f"Request failed: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class CheckIMEIExistsAPIView(APIView):
    """
    API View to check if a device with a specific IMEI exists.
    
    - GET: Checks whether a device with the provided IMEI exists in the system.
    """
    permission_classes = [IsAuthenticated]
    def get(self, request, *args, **kwargs):
        imei = request.query_params.get('imei')
        if not imei:
            return Response({"detail": "IMEI parameter is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            device = Device.objects.get(imei=imei)
            return Response({"exists": True, "device": DeviceSerializer(device).data}, status=status.HTTP_200_OK)
        except Device.DoesNotExist:
            return Response({"exists": False}, status=status.HTTP_200_OK)
        


class UserDeviceIntervetionListView(APIView):
    """
    API View to list interventions related to the user's devices.
    
    - GET: Fetches a list of interventions associated with the user's devices.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        try:
            user = request.user
        except Token.DoesNotExist:
            return Response({'error': 'Invalid token'}, status=status.HTTP_400_BAD_REQUEST)
        except IndexError:
            return Response({'error': 'Invalid Authorization header format'}, status=status.HTTP_400_BAD_REQUEST)
        
        # # Récupérer les entreprises associées à l'utilisateur
        # companies = Company.objects.filter(user=user)
        # serializer = CompanySerializer(companies, many=True)
        return Response()
    

class DeviceRetrieveByImei(APIView):
    """
    API View to retrieve a device by its IMEI.
    
    - GET: Fetches the details of a device using its IMEI number, ensuring the device is associated with the user's company.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        imei = kwargs.get('imei')

        # Ensure the device belongs to the user's company
        user = request.user
        list_companies = Company.objects.filter(users=user)

        if not list_companies.exists():
            return Response({'error': 'User is not associated with any company'}, status=status.HTTP_403_FORBIDDEN)

        try:
            # Retrieve the device using IMEI and check if it belongs to the user's company
            device = Device.objects.get(imei=imei, company_manager__in=list_companies)
        except Device.DoesNotExist:
            raise Http404("Device not found")
        
        # Serialize the device data
        serializer = DeviceSerializer(device)
        return Response(serializer.data)
    



class CheckDeviceNumberAPIView(APIView):
    """
    API View to check the number of devices associated with the authenticated user.
    
    - GET: Returns the total number of devices managed by the user or their company.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        
        # # Récupérer les entreprises associées à l'utilisateur
        # companies = Company.objects.filter(user=user)
        # serializer = CompanySerializer(companies, many=True)
        return Response()
    
class CreateTrajectoryView(APIView):
    STATUS_OFF = STATUS_OFF
    PREVIOUS_STATUS_DEVICE = PREVIOUS_STATUS_DEVICE
    STATUS_ON = STATUS_ON
    PROFESSIONAL_MODE = PROFESSIONAL_MODE
    PRIVATE_MODE = PRIVATE_MODE
    PREVIOUS_MODE_DEVICE = PREVIOUS_MODE_DEVICE

    def post(self, request):
        """
        Handles POST requests for creating or updating device trajectories.

        This function processes the incoming trajectory data for a specific device,
        checks the current and previous status, updates an existing trajectory if necessary,
        or creates a new trajectory entry in the database.
        """
        new_trajectory_data = []
        new_geom_data = LineString()
        trajectory_points = []
        trajectory_geom = LineString()
        try:
            serializer = TrajectoryRequestSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            data = serializer.validated_data

            trajectory_data = data['trajectories']
            if not trajectory_data or not trajectory_data[0]['points']:
                    return Response({'error': 'Invalid trajectory data'}, status=status.HTTP_400_BAD_REQUEST)

            first_point = trajectory_data[0]['points'][0]
            device_mode = first_point.get('mode')

            device_status = first_point.get('status')
            device_id = data.get('device_id')
            vehicle_speed = first_point.get('speed')
            trajectory_date = first_point.get('timestamp')
            current_date_trajectory = trajectory_date.date()
            device = get_object_or_404(Device, uid=device_id)

            
            device_data = first_point.get('location')
            device_data['name'] = device.name
            device_data['device_mode'] = device_mode
            device_data['status'] = device_status

            # Validate device status
            if device_status not in [self.STATUS_ON, self.STATUS_OFF]:
                return Response({'error': f"Invalid status: {device_status}. Status must be 'On' or 'Off'."}, status=status.HTTP_400_BAD_REQUEST)
            

            last_trajectory = self.get_last_trajectory(device)

            self.send_device_status_update(device, device_status,vehicle_speed, device_data)

            if last_trajectory:
                if not self.should_save_data(trajectory_data, last_trajectory):
                    return Response({'message': 'Position unchanged, no need to save'}, status=status.HTTP_200_OK)

                trajectory_device = Trajectory.objects.get(uid=last_trajectory.uid)
                trajectory_points = trajectory_device.properties.get('trajectory', [])
                trajectory_geom = trajectory_device.geom

                if trajectory_points:
                    last_trajectory_point = trajectory_points[-1]
                    self.PREVIOUS_STATUS_DEVICE = last_trajectory_point.get('status')
                    self.PREVIOUS_MODE_DEVICE = last_trajectory_point.get('mode')

            previous_date_trajectory = last_trajectory.end_time.date() if last_trajectory else None

            # Update the existing trajectory if the previous mode was private
            if self.PREVIOUS_MODE_DEVICE == self.PRIVATE_MODE:
                trajectory_geom = [] 
                trajectory_points = [] 

            mode_changed_to_private = self.PREVIOUS_MODE_DEVICE == self.PROFESSIONAL_MODE and device_mode == self.PRIVATE_MODE
            status_was_off = self.PREVIOUS_STATUS_DEVICE == self.STATUS_OFF
            new_date_detected = previous_date_trajectory and current_date_trajectory > previous_date_trajectory
            should_start_new_trajectory = mode_changed_to_private or status_was_off or new_date_detected
            device_is_private_mode = device_mode == self.PRIVATE_MODE
            # Check if we need to start a new trajectory or update the existing one
            if status_was_off or device_is_private_mode:
                # Prepare properties and geometry for the trajectory
                properties = prepare_trajectory_properties(trajectory_data[0], new_trajectory_data)
                geom_data = create_geometry_from_points(
                    trajectory_data[0]['points'], new_geom_data, not should_start_new_trajectory
                )
                if should_start_new_trajectory:
                    try:
                        Trajectory.objects.create(
                            device=device,
                            geom=geom_data,
                            properties=properties,
                            start_time=json_serial(data['start_time']),
                            end_time=json_serial(data['end_time']),
                            last_position = device_data
                        )
                    except Exception as e:
                        print(f"An error occurred: {e}")
                        raise
                else:
                    # Update the existing trajectory
                    last_trajectory.geom = geom_data
                    last_trajectory.properties = properties
                    last_trajectory.end_time = data['end_time']
                    last_trajectory.last_position = device_data
                    last_trajectory.save()
            else:
                # Prepare properties and geometry for the updated trajectory
                properties = prepare_trajectory_properties(trajectory_data[0], trajectory_points)
                geom_data = create_geometry_from_points(
                    trajectory_data[0]['points'], trajectory_geom, True
                )
                
                # Save the updates to the last trajectory
                last_trajectory.geom = geom_data
                last_trajectory.properties = properties
                last_trajectory.end_time = data['end_time']
                last_trajectory.last_position = device_data
                last_trajectory.save()

            return Response({'message': 'Trajectory successfully recorded'}, status=status.HTTP_201_CREATED)
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            return Response({'error': 'An unexpected error occurred'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def get_last_trajectory(self, device):
        return Trajectory.objects.filter(device=device).order_by('-end_time').first()
        
    def send_device_status_update(self, device, status,vehicle_speed, position=None):
        """
        Updates the device status and sends a WebSocket notification.
        """
        try:
            if device.status != status:  # Avoid unnecessary saves
                device.status = status
                device.save(update_fields=["status"])

            # Send WebSocket update
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                "device_status_updates",
                {
                    "type": "send_device_status",
                    "device_id": str(device.uid),  # Assuming `uid` is the primary key
                    "status": status,
                    "position": position,
                    "speed":vehicle_speed,
                    "immatriculation":device.car_name
                },
            )
            logger.info(f"Sent device status update for {device.uid}: {status}")

        except Exception as e:
            logger.error(f"Failed to send WebSocket update for {device.uid}: {e}", exc_info=True)
        
    def should_save_data(self, trajectory_data, last_trajectory):
        """
        Checks if the new trajectory data should be saved.
        - Prevents saving if both lat/lng are 0.
        - Prevents unnecessary writes if the position doesn't change.
        """
        if not trajectory_data or not trajectory_data[0]['points']:
            return False 

        current_point = trajectory_data[0]['points'][0]
        current_lat = current_point['location']['lat']
        current_lng = current_point['location']['lng']

        if current_lat == 0 and current_lng == 0:
            return False

        last_lat = last_trajectory.last_position['lat']
        last_lng = last_trajectory.last_position['lng']

        return not (current_lat == last_lat and current_lng == last_lng)


class TrajectoryTileView(VectorLayer):
    """
    A view to represent trajectory data as a vector tile layer.
    """
    model = Trajectory
    id = "trajectory"
    tile_fields = ('device', 'properties_data', 'end_time', 'start_time')
    geom_field = "geom"

    def get_queryset(self):
        device_id = getattr(self, "device_id", None)
        date_trajectory = getattr(self, "date_trajectory", None)

        queryset = Trajectory.objects.all()
        if device_id and date_trajectory:
            queryset = queryset.filter(
                device__uid=device_id,
                end_time__date=date_trajectory
            )


        return queryset.annotate(
            properties_data=Cast("properties", TextField())
        )

    
    def serialize(self, obj):
        trajectory_serialize = TrajectoryPropertiesSerializer(obj)
        return trajectory_serialize.data 



class TrajectoryMVTView(MVTView):
    """
       MVTView handles one or more vector layers defined in the layer_classes attribute.
    """
    layer_classes = [TrajectoryTileView]

    def get(self, request, *args, **kwargs):
        device_id = kwargs.get("device_id")
        date_trajectory = kwargs.get("date_trajectory")
        
        for layer_class in self.layer_classes:
            layer_class.device_id = device_id
            layer_class.date_trajectory = date_trajectory

        try:
            response = super().get(request, *args, **kwargs)
        except Exception as e:
            print(f"An error occurred: {e}")
            raise
        return response


class DevicePrivateAPIView(APIView):

    def post(self, request):
        device_id = request.data.get('device_id')
        is_private_mode = request.data.get('is_private')  # True for private, False for pro
        
        if device_id is None or is_private_mode is None:
            return Response({"error": "device_id and is_private must be provided."}, status=status.HTTP_400_BAD_REQUEST)

        device = get_object_or_404(Device, uid=device_id)
        if not is_private_mode:
            device.is_pro_mode = True
        else:
            device.is_pro_mode = False
        device.is_private_mode = is_private_mode
        
        device.save()

        return Response({
            'message': f"Device mode updated to {'private' if is_private_mode else 'pro'}.",
            'device_id': device.uid,
            'is_private_mode': device.is_private_mode
        }, status=status.HTTP_200_OK)

class DeviceCompanyRetrieveView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request, *args, **kwargs):
        uid = kwargs.get('uid')
        if not uid:
            return Response({'error': 'Device UID is required'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            company = Company.objects.get(uid=uid)
        except Device.DoesNotExist:
            raise Http404("company not found")
        
        serializer = CompanySerializer(company)
        return Response(serializer.data)

class DevicePositionRetriever(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        uid = kwargs.get('uid')
        date_trajectory = request.query_params.get('date')

        if not uid:
            return Response({'error': 'Device UID is required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            filter_params = {'device__uid': uid}
            if date_trajectory:
                filter_params['end_time__date'] = date_trajectory

            last_trajectory = (
                Trajectory.objects
                .filter(**filter_params)
                .order_by('-end_time')
                .first()
            )

            if not last_trajectory:
                return Response({'error': 'No trajectory found for the device'}, status=status.HTTP_404_NOT_FOUND)

            # Vérifier la présence d'une position
            last_position = last_trajectory.last_position
            if not last_position:
                return Response({'error': 'No position data found for the device'}, status=status.HTTP_404_NOT_FOUND)

            # Sérialiser et retourner les données
            serializer = LocationSerializer(last_position)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({'error': f'An unexpected error occurred: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        

class GetDevicesByUserCompanyView(APIView):
    """
    Retrieve the devices associated with the company of the currently authenticated user.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        if user.is_superuser or user.is_admin:
            devices = Device.objects.filter(trajectories__isnull=False).distinct()
        else:
            devices = Device.objects.filter(company_manager=user.companies, is_actif=True)
        if not devices.exists():
            return Response({"detail": "No devices found for the current user."}, status=status.HTTP_404_NOT_FOUND)

        serializer = DeviceSerializer(devices, many=True)

        return Response(serializer.data, status=status.HTTP_200_OK)
    
class SpeedLimitView(APIView):
    """
    API endpoint to set a speed limit on the vehicle.
    """
    def post(self, request, *args, **kwargs):
        uid = kwargs.get("uid")
        speed_limit = request.data.get("speed_limit")

        if not speed_limit or not isinstance(speed_limit, int) or speed_limit <= 0:
            return JsonResponse({'status': 'error', 'message': 'Invalid speed limit'}, status=400)

        try:
            device = Device.objects.get(uid=uid)

            device.speed_limit = speed_limit
            device.save()

            return JsonResponse({
                'status': 'success',
                'message': f'Speed limit set to {speed_limit} km/h'
            })

        except Device.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'Device not found'}, status=404)

        except Exception as e:
            return JsonResponse({'status': 'error', 'message': f'Internal server error: {str(e)}'}, status=500)
        
class DeviceCommandView(APIView):
    """
    API View to send commands to a device and process the response.
    See https://wiki.teltonika-gps.com/view/Template:FMB_SMS/GPRS_Commands
    """

    def post(self, request, *args, **kwargs):
        """
        Handles POST requests to send a command to a specific device.

        - Retrieves the device using the provided `uid`
        - Sends the command using the TCP connection handler
        - Parses the response to update the engine lock state if applicable
        - Returns a JSON response with the result
        """
        device_uid = kwargs.get("uid")

        try:
            device = Device.objects.get(uid=device_uid)
            command = request.data.get("command")

            if not command:
                return JsonResponse({'status': 'error', 'message': 'Command is required'}, status=400)

            if command.startswith(("setigndigout", "setdigout")):
                if device.status == 'On':
                    return JsonResponse({
                        'status': 'error',
                        'message': "Impossible d'exécuter la commande : le véhicule est en marche."
                    }, status=409)


            # Create the appropriate Codec12 command based on command type
            if command.startswith("setigndigout"):
                # codec12_command = self.create_setdigout_command(command)
                codec12_command = self.create_setigndigout_command(command)
            elif command.startswith("setparam"):
                codec12_command = self.create_setparam_command(command)
            else:
                codec12_command = create_codec12_command(command)

            # Send the command to the device through the TCP connection
            response = TCPConnectionHandler.send_command_to_device(device.imei, codec12_command, timeout=15)

            if response:
                self.response_validation(command, response, device)

                # Parse the device response
                parsed_response = DeviceResponseParser.parse_response(command, response)
                return JsonResponse({
                    'status': 'success',
                    'message': 'Command sent successfully',
                    'response': parsed_response
                })

            else:
                return JsonResponse({'status': 'error', 'message': "Appareil non connecté ou délai d'attente dépassé"}, status=404)

        except Device.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'Appareil introuvable'}, status=404)

        except socket.timeout:
            return JsonResponse({'status': 'error', 'message': "Temps d'attente dépassé. L'appareil n'a pas répondu à temps."}, status=504)

        except Exception as e:
            return JsonResponse({'status': 'error', 'message': f'Erreur interne du serveur : {str(e)}'}, status=500)


    
    def response_validation(self, command, response, device):
        """
        View https://wiki.teltonika-gps.com/view/FMC130_SMS/GPRS_Commands
        """

        patterns = {
            "setigndigout": r'DOUT1:',
            "getinfo": r'RTC:',
            "getstatus": r'Data Link:',
            "ggps": r'D:'
        }

        if command.startswith("setigndigout"):
            print("RESPONSE ", response)
            match = re.search(patterns["setigndigout"], response)
            if match:
                dout1_value = match.group(1)
                device.engine_lock = dout1_value == "0"  # 0 = Locked
                device.save()
            else:
                return JsonResponse(
                    {'status': 'error', 'message': 'Erreur lors de l\'envoi de la commande anti-démarrage'},
                    status=400
                )

        for key in ["getinfo", "getstatus", "ggps"]:
            if command.startswith(key):
                if not re.search(patterns[key], response):
                    error_messages = {
                        "getinfo": "Erreur lors de la récupération des informations de l'appareil",
                        "getstatus": "Erreur lors de la récupération du statut",
                        "ggps": "Erreur lors de la récupération de la position du dispositif"
                    }
                    print(f"ERREUR {key.upper()}")
                    return JsonResponse(
                        {'status': 'error', 'message': error_messages[key]},
                        status=400
                    )

    def create_setdigout_command(self, command):
        """
        Generates the 'setdigout' command with the given parameters.
        
        Expected command format:
        "setdigout DOUT1 DOUT2 timeoutY1 timeoutY2 speedZ1 speedZ2"

        
        """
        parts = command.split()
        if len(parts) != 7:
            raise ValueError("Invalid command format. Expected format: 'setdigout DOUT1 DOUT2 timeoutY1 timeoutY2 speedZ1 speedZ2'")

        
        dout1 = parts[1]
        dout2 = parts[2]
        timeoutY1 = parts[3]
        timeoutY2 = parts[4]
        speedZ1 = parts[5]
        speedZ2 = parts[6]
        # Format the command string according to the 'setdigout' syntax
        command = f"setdigout {dout1} {dout2} {timeoutY1} {timeoutY2} {speedZ1} {speedZ2}"
        
        # Remove extra spaces and generate the Codec12 command
        return create_codec12_command(command.strip())
    

    def create_setigndigout_command(self, command):
        """
        Generates the 'setigndigout' command with the given parameters.
        
        Expected command format:
        "setigndigout DOUT1 DOUT2 DOUT3 timeoutX timeoutY timeoutZ"
        
        Where:
        - DOUT1, DOUT2, DOUT3: 0=OFF, 1=ON, ?=Ignore
        - timeoutX, timeoutY, timeoutZ: timeout values in seconds for each DOUT
        
        Example: "setigndigout 1 ? ? 0 0 0" - Active DOUT1 seulement, timeouts infinis
        """
        parts = command.split()
        if len(parts) != 7:
            raise ValueError("Invalid command format. Expected format: 'setigndigout DOUT1 DOUT2 DOUT3 timeoutX timeoutY timeoutZ'")

        dout1 = parts[1]
        dout2 = parts[2] 
        dout3 = parts[3]
        timeoutX = parts[4]
        timeoutY = parts[5]
        timeoutZ = parts[6]
        
        # Format the command string according to the 'setigndigout' syntax
        command = f"setigndigout {dout1} {dout2} {dout3} {timeoutX} {timeoutY} {timeoutZ}"
        
        # Remove extra spaces and generate the Codec12 command
        return create_codec12_command(command.strip())

    
    def create_setparam_command(self, command):
        """
        Generates the 'setparam' command with the given parameters.
        
        Example usage:
        "setparam 11104:80" - Sets parameter 11104 to value 80.
        """
        return create_codec12_command(command.strip())

class IntervetionZoneByIdView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        intervention_zone_id = kwargs.get('uid')

        if not intervention_zone_id:
            return Response(
                {'error': 'Intervention Zone UID is required.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            zone = InterventionZone.objects.get(pk=intervention_zone_id)
        except InterventionZone.DoesNotExist:
            return Response(
                {'error': 'Intervention Zone not found.'},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = ZoneSerializer(zone)
        return Response(serializer.data, status=status.HTTP_200_OK)
    

class DeviceRestoreView(APIView):
    permission_classes = [IsAuthenticated]

    def get_object(self, uid):
        try:
            return Device.objects.get(uid=uid)
        except Device.DoesNotExist:
            raise Http404

    def delete(self, request, uid):
        device = self.get_object(uid)
        company = device.company_manager
        active_device_count = Device.objects.filter(company_manager=company, is_actif=True).count()
        if active_device_count >= company.nbr_device:
            return Response(
                {"error": "Le nombre maximal d'appareils actifs pour votre entreprise a été atteint."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        
        device.is_actif = True
        device.deleted_at = None
        device.save()

        return Response({"message": "L'appareil a été restauré avec succès."}, status=status.HTTP_200_OK)