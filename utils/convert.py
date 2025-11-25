
from datetime import datetime, date,timezone
from pyproj import Proj, Transformer
from django.contrib.gis.geos import LineString as GEOSLineString, Point
import logging

MAX_JUMP_METERS = 1000


logger = logging.getLogger(__name__)
def convert_datetime_to_iso(data):
    """
        Recursively converts datetime objects in the dictionary to ISO 8601 strings.
    """
    if isinstance(data, dict):
        return {key: convert_datetime_to_iso(value) for key, value in data.items()}
    elif isinstance(data, list):
        return [convert_datetime_to_iso(item) for item in data]
    elif isinstance(data, datetime):
        return data.isoformat()  # Convertir datetime en ISO 8601
    return data



def prepare_trajectory_properties(trajectory_data, list_trajectory_data):
        """
            Prepares trajectory properties from the received data.
            Converts datetime objects to ISO 8601 strings.
        """
        trajectory_data = convert_datetime_to_iso(trajectory_data)


        list_trajectory_data.append(trajectory_data['points'][0])

        return {
            'trajectory': list_trajectory_data,
        }

    
def json_serial(obj):
        """JSON serializer for objects not serializable by default json code"""
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        raise TypeError ("Type %s not serializable" % type(obj))


# def create_geometry_from_points(points, trajectory_geom, should_continue_geometry): # à verifier
#     """
#     Creates or updates a LineString geometry from a new point.
#     If only one point is available, returns a LineString with two identical points.
#     """
#     cumulative_coords = []
#     transformer = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)

#     if not points or len(points) != 1:
#         raise ValueError("The 'points' list must contain exactly one element.")

#     current_point = points[0]
#     current_coords = transformer.transform(
#         current_point['location']['lng'],
#         current_point['location']['lat']
#     )

#     if should_continue_geometry and trajectory_geom and len(trajectory_geom.coords) > 0:
#         cumulative_coords.extend(trajectory_geom.coords)

#     cumulative_coords.append(current_coords)

#     # Si un seul point, le dupliquer pour former une LineString valide
#     if len(cumulative_coords) == 1:
#         cumulative_coords.append(current_coords)

#     return GEOSLineString(cumulative_coords)

def create_geometry_from_points(points, trajectory_geom, should_continue_geometry):
    """
    Crée ou met à jour une géométrie LineString à partir d'un point GPS.
    Si un seul point est disponible, retourne une LineString avec deux points identiques.
    Évite les "vols d'oiseau" en vérifiant la distance avec le dernier point.
    
    Args:
        points (list): Liste contenant exactement un point avec 'lat' et 'lng'.
        trajectory_geom (GEOSLineString): Géométrie existante à continuer.
        should_continue_geometry (bool): True si on veut continuer l'ancienne géométrie.
    
    Returns:
        GEOSLineString: Nouvelle géométrie.
    """
    if not points or len(points) != 1:
        raise ValueError("La liste 'points' doit contenir exactement un élément.")

    transformer = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
    current_point = points[0]
    current_coords = transformer.transform(
        current_point['location']['lng'],
        current_point['location']['lat']
    )

    cumulative_coords = []

    # Si on continue la géométrie existante, vérifier qu'elle existe
    if should_continue_geometry and trajectory_geom and len(trajectory_geom.coords) > 0:
        last_coords = trajectory_geom.coords[-1]
        last_point = Point(last_coords)
        new_point = Point(current_coords)

        # Vérifie la distance entre le dernier point et le nouveau
        if last_point.distance(new_point) < MAX_JUMP_METERS:
            cumulative_coords.extend(trajectory_geom.coords)
        else:
            logger.warning(
                f"Jump too large, starting new segment: "
                f"{last_coords} -> {current_coords}"
            )

    # Ajout du nouveau point
    cumulative_coords.append(current_coords)

    # Si un seul point, le dupliquer pour créer une LineString valide
    if len(cumulative_coords) == 1:
        cumulative_coords.append(current_coords)

    return GEOSLineString(cumulative_coords)


def convert_timestamp_to_iso8601(timestamp_ms):
    timestamp_sec = timestamp_ms / 1000
    dt_object = datetime.fromtimestamp(timestamp_sec, timezone.utc)
    return dt_object.isoformat()