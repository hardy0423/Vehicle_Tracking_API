from django.shortcuts import render
from django.shortcuts import get_object_or_404
from rest_framework import status, generics
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from vectortiles.views import MVTView
from .models import InterventionZone
from django.http import Http404
from rest_framework.views import APIView

from .permissions import IsStaffOrSuperuser
from .serializers import ZoneSerializer
from vectortiles import VectorLayer
import logging
from pyproj import Proj, transform
from django.contrib.gis.geos import Polygon
from devices.models import Device
from django.db import models


logger = logging.getLogger(__name__)
wgs84 = Proj(init="epsg:4326")
web_mercator = Proj(init="epsg:3857")
class ZoneListView(generics.ListAPIView):
    """API endpoint to list intervention zones for a company's devices.
    
    Retrieves all intervention zones associated with devices belonging to a specific company (by UID).
    Includes default zones if no device-specific zones exist.
    
    Permissions:
        - User must be authenticated.
    
    Query Parameters:
        uid (str): Company UID (required).
    
    Returns:
        Response: Serialized list of InterventionZone objects.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = ZoneSerializer

    def get(self, request):
        id_company = request.query_params.get('uid')
        if not id_company:
            return Response({"detail": "Company UID is required."}, status=status.HTTP_400_BAD_REQUEST)
        
        devices = Device.objects.filter(company_manager_id=id_company)
        zone_intervention_ids = devices.values_list('zone_id', flat=True).distinct()

        if zone_intervention_ids:
            intervention_zones = InterventionZone.objects.filter(models.Q(uid__in=zone_intervention_ids) | models.Q(default_zone=True))
        else:
            intervention_zones = InterventionZone.objects.filter(default_zone=True)

        serializer = self.get_serializer(intervention_zones, many=True)
        return Response(serializer.data)
    
class ZoneCreateView(generics.CreateAPIView):
    """API endpoint to create a new intervention zone.
    
    Accepts GeoJSON geometry, converts it to Web Mercator (EPSG:3857), 
    and saves the zone to the database.
    
    Permissions:
        - User must be authenticated.
    
    Request Body:
        - geometry (GeoJSON): Polygon coordinates in EPSG:4326 (WGS84).
        - properties (dict): Zone metadata (e.g., `nameZone`).
    
    Returns:
        Response: Serialized created zone or validation errors.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = ZoneSerializer

    def post(self, request):
        data = request.data.copy()
        data['nameZone'] = data.get('properties', {}).get('nameZone', None)
        geojson_geometry = data.get('geometry', None)
        geom_wkt = geojson_geometry["coordinates"]

        coords_web_mercator = [
            [(transform(Proj(init='epsg:4326'), Proj(init='epsg:3857'), lon, lat)) for lon, lat in geom_wkt[0]]
        ]
        data['geom'] = Polygon(coords_web_mercator[0])
        
        serializer = self.get_serializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    

class ZoneIntervetionTileView(VectorLayer):
    """Vector tile layer for intervention zones.
    
    Serves intervention zones as Mapbox Vector Tiles (MVT) for map rendering.
    Supports filtering by zone_id if provided.
    """
    model = InterventionZone
    id = "intervention_zones"
    tile_fields = (
        "name",
        "default_zone",
    )
    
    geom_field = "geom"

    def get_queryset(self):
        zone_id = getattr(self, "zone_id", None)
        queryset = InterventionZone.objects.all()
        if zone_id != None:
            queryset = queryset.filter(uid=zone_id)
        return queryset

class ClassifiedTileView(MVTView):
    """API endpoint to serve vector tiles for intervention zones.
    
    Dynamically configures the tile layer based on the requested zone_id.
    
    URL Parameters:
        zone_id (str, optional): Filters tiles to a specific zone.
    """
    layer_classes = [ZoneIntervetionTileView]

    def get(self, request, *args, **kwargs):
        """Handles GET requests, injecting zone_id into layer classes."""
        zone_id = kwargs.get("zone_id")
        for layer_class in self.layer_classes:
            layer_class.zone_id = zone_id
        return super().get(request, *args, **kwargs)
    

class InterventionZoneDelete(APIView):
    """API endpoint to delete an intervention zone by UID.
    
    Permissions:
        - User must be authenticated and staff/superuser.
    
    URL Parameters:
        uid (str): Zone UID to delete.
    
    Returns:
        Response: 204 (success) or 404 (zone not found).
    """
    permission_classes = [IsAuthenticated, IsStaffOrSuperuser]

    def delete(self, request, *args, **kwargs):
        uid = kwargs.get('uid')
        try:
            intervention_zone = InterventionZone.objects.get(uid=uid)
            intervention_zone.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except InterventionZone.DoesNotExist:
            return Response({"error": "Intervention Zone not found"}, status=status.HTTP_404_NOT_FOUND)


class InterventionZoneRetrieve(APIView):
    """API endpoint to retrieve details of a single intervention zone.
    
    Permissions:
        - User must be authenticated and staff/superuser.
    
    URL Parameters:
        uid (str): Zone UID to fetch.
    
    Headers:
        Authorization: Bearer token (required).
    
    Returns:
        Response: Serialized zone data or 404 if not found.
    """
    permission_classes = [IsAuthenticated, IsStaffOrSuperuser]

    def get(self, request, *args, **kwargs):
        uid = kwargs.get('uid')
        token_key = request.headers.get('Authorization')
        if not token_key:
            return Response({'error': 'Authorization header missing'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            intervention_zone = InterventionZone.objects.get(uid=uid)
        except InterventionZone.DoesNotExist:
            raise Http404("Intervention Zone not found")
        
        serializer = ZoneSerializer(intervention_zone)
        return Response(serializer.data)


