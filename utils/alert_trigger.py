from typing import Dict, Any
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import D
from constants.speed_limits import SEVERITY_THRESHOLDS
from typing import Dict, Any
import logging
import math

logger = logging.getLogger(__name__)

def is_point_in_geofence(point: Dict[str, float], geofence_polygon) -> bool:
    """
    Vérifie si un point est dans une zone d'intervention
    """
    point_obj = Point(point['longitude'], point['latitude'])
    return geofence_polygon.contains(point_obj)

def check_geofence_violation(device_location: Dict[str, Any], intervention_zone) -> Dict[str, Any]:
    """
    Checks if a device has violated its geofence by leaving its designated intervention zone.
    This function determines if the device's location is inside the specified intervention zone (a polygon).
    If the device is outside the zone, it calculates the distance to the nearest point on the boundary of the zone.
    """
    logger.info("Checking geofence violation for device location: %s", device_location)

    if not device_location or not intervention_zone:
        logger.warning("Missing device location or intervention zone. No violation detected.")
        return {'violation': False, 'distance': 0}

    point = Point(device_location['longitude'], device_location['latitude'])
    logger.debug("Device point created: %s", point)

    if not intervention_zone.geom:
        logger.error("Intervention zone has no valid geometry.")
        return {'violation': False, 'distance': 0}

    # Check if the device is inside the intervention zone
    is_in_zone = is_point_in_geofence(device_location, intervention_zone.geom)
    logger.info("Device is inside geofence: %s", is_in_zone)

    if not is_in_zone:
        distance = point.distance(intervention_zone.geom.boundary)
        logger.warning("Raw distance calculated: %s", distance)

        if math.isinf(distance) or math.isnan(distance):
            logger.error("Invalid distance calculated: %s. Setting to 0.", distance)
            distance = 0

        logger.warning("Geofence violation detected! Distance to boundary: %f meters", distance)
        return {'violation': True, 'distance': distance}

    logger.info("No geofence violation detected.")
    return {'violation': False, 'distance': 0}

def determine_speed_severity(excess: float) -> str:
        """
        Determines the severity of the speeding violation
        """
        if excess >= SEVERITY_THRESHOLDS['critical']:
            return 'critical'
        elif excess >= SEVERITY_THRESHOLDS['high']:
            return 'high'
        elif excess >= SEVERITY_THRESHOLDS['medium']:
            return 'medium'
        return 'low'

def check_speed_violation(
        speed: float,
        speed_limit: float
    ) -> Dict[str, Any]:
    """
    Checks if a speed violation occurs by comparing the actual speed
    with the defined speed limit.
    """

    if speed is None or speed_limit is None:
        return {'violation': False, 'severity': None, 'excess': 0, 'speed': None, 'speed_limit': None}
    
    speed = float(speed)
    speed_limit = float(speed_limit)

    if speed_limit == 0:
        return {
            'violation': False,
            'severity': None,
            'excess': 0,
            'speed': speed,
            'speed_limit': speed_limit
        }

    if speed <= speed_limit:
        return {
            'violation': False,
            'severity': None,
            'excess': 0,
            'speed': speed,
            'speed_limit': speed_limit
        }

    excess = speed - speed_limit
    severity = determine_speed_severity(excess)

    return {
        'violation': True,
        'severity': severity,
        'excess': excess,
        'speed': speed,
        'speed_limit': speed_limit
    }
