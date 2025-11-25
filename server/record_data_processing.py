import logging
import queue
import struct
import json
from typing import List, Dict, Optional
from datetime import datetime, timezone
from django.db.models import Q
from django.contrib.gis.geos import LineString
from rest_framework.response import Response
from rest_framework.exceptions import APIException
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import connection, transaction
from geopy.distance import geodesic

from devices.models import Device, Trajectory
from devices.serializers import TrajectoryRequestSerializer
from utils.convert import (
    create_geometry_from_points, 
    prepare_trajectory_properties, 
    json_serial,
    convert_timestamp_to_iso8601
)
from constants.device_info import (
    STATUS_OFF, STATUS_ON,
    PREVIOUS_STATUS_DEVICE, PREVIOUS_MODE_DEVICE,
    PROFESSIONAL_MODE, PRIVATE_MODE,
)
from .device_data_processing import process_tcp_data
import json

# Logging Configuration
logger = logging.getLogger(__name__)
MAX_DISTANCE_METERS = 5000

# Thread-safe queue for retrying failed records
data_queue = queue.Queue()

# Cache pour éviter les requêtes DB répétées
_device_cache = {}
_cache_lock = __import__('threading').Lock()

"""
See : https://wiki.teltonika-gps.com/view/Teltonika_AVL_Protocols
"""

def extract_records(avl_data: bytes, imei: str, num_records: int) -> List[Dict]:
    """
    Extracts multiple AVL records from the given Teltonika Codec8 TCP data packet.
    Optimized version with better error handling and performance.
    """
    offset = 2  # Skip Codec ID (1 byte) and Number of Records (1 byte)
    records = []
    
    # Pre-calculate minimum data size needed
    min_size_per_record = 24  # Base GPS data size
    
    for record_idx in range(num_records):
        try:
            # Ensure there's enough data left
            if len(avl_data) < offset + min_size_per_record:
                logger.warning(f"[{imei}] Insufficient data for record {record_idx + 1}/{num_records}")
                break

            # Extract timestamp (8 bytes, milliseconds since Unix epoch)
            timestamp_raw = int.from_bytes(avl_data[offset:offset + 8], byteorder="big")
            try:
                # Validation du timestamp (doit être raisonnable)
                if timestamp_raw < 1000000000000 or timestamp_raw > 9999999999999:
                    logger.warning(f"[{imei}] Invalid timestamp: {timestamp_raw}")
                    timestamp = None
                else:
                    timestamp = datetime.fromtimestamp(timestamp_raw / 1000, tz=timezone.utc)
            except (OverflowError, ValueError) as e:
                logger.warning(f"[{imei}] Timestamp conversion error: {e}")
                timestamp = None

            # Extract GPS and basic data
            priority = avl_data[offset + 8]
            longitude = struct.unpack(">i", avl_data[offset + 9:offset + 13])[0] / 10_000_000
            latitude = struct.unpack(">i", avl_data[offset + 13:offset + 17])[0] / 10_000_000
            altitude = struct.unpack(">h", avl_data[offset + 17:offset + 19])[0]
            angle = struct.unpack(">h", avl_data[offset + 19:offset + 21])[0]
            satellites = avl_data[offset + 21]
            speed = struct.unpack(">H", avl_data[offset + 22:offset + 24])[0]

            offset += 24  # Move offset to IO element section

            # Validation des coordonnées
            if not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
                logger.warning(f"[{imei}] Invalid coordinates: lat={latitude}, lng={longitude}")

            # Extract event ID (1 byte) and total IO element count (1 byte)
            if len(avl_data) < offset + 2:
                logger.warning(f"[{imei}] Insufficient data for IO elements")
                break
                
            event_id = avl_data[offset]
            offset += 2  # Skip event_id and total IO count

            io_elements = {}

            def extract_io_elements(num_elements: int, size: int) -> bool:
                """
                Extract IO elements of a specific size.
                Returns False if not enough data available.
                """
                nonlocal offset
                
                # Check if we have enough data
                required_size = num_elements * (1 + size)
                if len(avl_data) < offset + required_size:
                    logger.warning(f"[{imei}] Not enough data for {num_elements} IO elements of size {size}")
                    return False
                
                for _ in range(num_elements):
                    io_id = avl_data[offset]
                    io_value = int.from_bytes(avl_data[offset + 1:offset + 1 + size], byteorder="big")
                    io_elements[io_id] = io_value
                    offset += 1 + size
                    
                return True

            # Parse variable-length IO elements
            try:
                # 1-byte IO elements
                if len(avl_data) < offset + 1:
                    break
                num_1byte = avl_data[offset]
                offset += 1
                if not extract_io_elements(num_1byte, 1):
                    break

                # 2-byte IO elements
                if len(avl_data) < offset + 1:
                    break
                num_2byte = avl_data[offset]
                offset += 1
                if not extract_io_elements(num_2byte, 2):
                    break

                # 4-byte IO elements
                if len(avl_data) < offset + 1:
                    break
                num_4byte = avl_data[offset]
                offset += 1
                if not extract_io_elements(num_4byte, 4):
                    break

                # 8-byte IO elements
                if len(avl_data) < offset + 1:
                    break
                num_8byte = avl_data[offset]
                offset += 1
                if not extract_io_elements(num_8byte, 8):
                    break

            except IndexError as e:
                logger.error(f"[{imei}] Index error extracting IO elements: {e}")
                break

            # Append parsed record
            records.append({
                "imei": imei,
                "timestamp": timestamp,
                "priority": priority,
                "longitude": longitude,
                "latitude": latitude,
                "altitude": altitude,
                "angle": angle,
                "satellites": satellites,
                "speed": speed,
                "event_id": event_id,
                "io_elements": io_elements
            })
            
        except struct.error as e:
            logger.error(f"[{imei}] Struct unpacking error in record {record_idx + 1}: {e}")
            break
        except Exception as e:
            logger.error(f"[{imei}] Error extracting record {record_idx + 1}: {e}", exc_info=True)
            break

    logger.info(f"[{imei}] Successfully extracted {len(records)}/{num_records} records")
    try:
        records.sort(key=lambda r: r["timestamp"])
    except Exception as e:
        logger.warning(f"[{imei}] Unable to sort records: {e}")
    return records


def extract_records_extended(avl_data: bytes, imei: str, num_records: int) -> List[Dict]:
    """
    Extracts Codec 8 Extended records with improved error handling.
    """
    offset = 0
    records = []
    
    try:
        codec_id = avl_data[offset]
        offset += 1

        if codec_id != 0x8E:
            raise ValueError(f"Invalid Codec ID for Codec8 Extended: {hex(codec_id)}")

        record_count_1 = avl_data[offset]
        offset += 1

        if record_count_1 != num_records:
            logger.warning(f"[{imei}] Record count mismatch: expected {num_records}, got {record_count_1}")

        for record_idx in range(record_count_1):
            try:
                record = {
                    "imei": imei,
                    "io": {}
                }

                # Vérifier qu'on a assez de données pour un record minimum
                if len(avl_data) < offset + 28:  # Minimum: timestamp(8) + priority(1) + GPS(15) + event(2) + total_io(2)
                    logger.warning(f"[{imei}] Insufficient data for extended record {record_idx + 1}")
                    break

                # Timestamp (8 bytes)
                timestamp_raw = int.from_bytes(avl_data[offset:offset + 8], byteorder="big")
                record["timestamp"] = convert_timestamp_to_iso8601(timestamp_raw)
                offset += 8

                # Priority (1 byte)
                record["priority"] = avl_data[offset]
                offset += 1

                # GPS Element (15 bytes)
                longitude_raw = int.from_bytes(avl_data[offset:offset + 4], byteorder="big", signed=True)
                offset += 4
                record["longitude"] = longitude_raw / 10_000_000

                latitude_raw = int.from_bytes(avl_data[offset:offset + 4], byteorder="big", signed=True)
                offset += 4
                record["latitude"] = latitude_raw / 10_000_000

                record["altitude"] = int.from_bytes(avl_data[offset:offset + 2], byteorder="big")
                offset += 2

                record["angle"] = int.from_bytes(avl_data[offset:offset + 2], byteorder="big")
                offset += 2

                record["satellites"] = avl_data[offset]
                offset += 1

                record["speed"] = int.from_bytes(avl_data[offset:offset + 2], byteorder="big")
                offset += 2

                # Event IO ID (2 bytes)
                record["event_id"] = int.from_bytes(avl_data[offset:offset + 2], byteorder="big")
                offset += 2

                # Total IO (2 bytes)
                total_io = int.from_bytes(avl_data[offset:offset + 2], byteorder="big")
                offset += 2

                # Helper function to extract IO elements
                def extract_io_group(size_bytes: int) -> Dict:
                    """Extract IO elements of a specific size."""
                    nonlocal offset
                    
                    if len(avl_data) < offset + 2:
                        return {}
                        
                    count = int.from_bytes(avl_data[offset:offset + 2], byteorder="big")
                    offset += 2
                    
                    io_dict = {}
                    for _ in range(count):
                        # Vérifier qu'on a assez de données
                        required = 2 + size_bytes if size_bytes > 0 else 4  # Pour XB: 2 (id) + 2 (length)
                        if len(avl_data) < offset + required:
                            logger.warning(f"[{imei}] Insufficient data for IO element")
                            break
                            
                        io_id = int.from_bytes(avl_data[offset:offset + 2], byteorder="big")
                        offset += 2
                        
                        if size_bytes == -1:  # Variable length (XB)
                            length = int.from_bytes(avl_data[offset:offset + 2], byteorder="big")
                            offset += 2
                            if len(avl_data) < offset + length:
                                break
                            value = avl_data[offset:offset + length]
                            offset += length
                        else:
                            if len(avl_data) < offset + size_bytes:
                                break
                            value = int.from_bytes(avl_data[offset:offset + size_bytes], byteorder="big")
                            offset += size_bytes
                            
                        io_dict[io_id] = value
                        
                    return io_dict

                # Extract all IO groups
                record["io"]["1B"] = extract_io_group(1)
                record["io"]["2B"] = extract_io_group(2)
                record["io"]["4B"] = extract_io_group(4)
                record["io"]["8B"] = extract_io_group(8)
                record["io"]["XB"] = extract_io_group(-1)  # Variable length

                records.append(record)
                
            except Exception as e:
                logger.error(f"[{imei}] Error extracting extended record {record_idx + 1}: {e}", exc_info=True)
                break

        # Verify record count at end
        if len(avl_data) >= offset + 1:
            record_count_2 = avl_data[offset]
            if record_count_1 != record_count_2:
                logger.warning(f"[{imei}] Record count mismatch at end: {record_count_1} vs {record_count_2}")

    except Exception as e:
        logger.error(f"[{imei}] Error in extract_records_extended: {e}", exc_info=True)

    logger.info(f"[{imei}] Extracted {len(records)} extended records")

    try:
        records.sort(key=lambda r: r["timestamp"])
    except Exception as e:
        logger.warning(f"[{imei}] Unable to sort records: {e}")
    return records


def send_records_to_api(records: List[Dict], codec_id: int):
    """
    Optimized batch processing of AVL records.
    Handles all records in a single transaction with caching.
    """
    if not records:
        logger.debug("No records to process")
        return

    imei = records[0].get("imei", "unknown")
    logger.info(f"[{imei}] Processing {len(records)} records (Codec: {hex(codec_id)})")

    success_count = 0
    failed_records = []

    try:
        # Convert all records once
        json_batch = [json.dumps(r, default=str) for r in records]

        # Single transaction for the whole batch
        with transaction.atomic():
            responses = save_data_batch(json_batch, codec_id)

        for idx, resp in enumerate(responses):
            if resp.status_code in [200, 201]:
                success_count += 1
            else:
                failed_records.append(records[idx])

        if failed_records:
            logger.warning(f"[{imei}] {len(failed_records)} records failed")

        logger.info(f"[{imei}] Done: {success_count} success, {len(failed_records)} failed")

    except Exception as e:
        logger.error(f"[{imei}] Fatal error in send_records_to_api: {e}", exc_info=True)

    finally:
        connection.close()

def save_data_batch(records_json: List[str], codec_id: int) -> List[Response]:
    """
    Process multiple records efficiently in one DB transaction.
    """
    responses = []
    device_cache = {}

    for record_json in records_json:
        try:
            tcp_data = process_tcp_data(record_json, codec_id)
            serializer = TrajectoryRequestSerializer(data=tcp_data)

            if not serializer.is_valid():
                logger.error(f"Invalid data: {serializer.errors}")
                responses.append(Response({"error": serializer.errors}, status=400))
                continue

            data = serializer.validated_data
            device_id = data.get("device_id")

            # Check cache
            device = device_cache.get(device_id)
            if not device:
                device = get_cached_device(device_id)
                if not device:
                    responses.append(Response({"error": "Device not found"}, status=404))
                    continue
                device_cache[device_id] = device

            # Process the trajectory
            resp = process_trajectory_data(device, data)
            responses.append(resp)

        except Exception as e:
            logger.error(f"Error processing record batch: {e}", exc_info=True)
            responses.append(Response({"error": str(e)}, status=500))

    return responses


def default_serializer(obj):
    """Serializes datetime objects to ISO format."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, bytes):
        return obj.hex()
    raise TypeError(f"Type {type(obj)} not serializable")


def handle_api_failure(record: Dict):
    """Fallback mechanism: enqueue failed records."""
    try:
        data_queue.put(record, block=False)
        logger.debug(f"Record queued for retry: {record.get('imei')}")
    except queue.Full:
        logger.error("Retry queue is full, dropping record")


def get_cached_device(device_id: str) -> Optional[Device]:
    """
    Get device from cache or DB.
    CRITICAL OPTIMIZATION: Évite les requêtes DB répétées.
    """
    with _cache_lock:
        if device_id in _device_cache:
            return _device_cache[device_id]
    
    try:
        device = Device.objects.select_related('company_manager').get(uid=device_id)
        
        with _cache_lock:
            _device_cache[device_id] = device
            
        return device
    except Device.DoesNotExist:
        return None


def invalidate_device_cache(device_id: str):
    """Invalidate device cache entry."""
    with _cache_lock:
        _device_cache.pop(device_id, None)


def process_trajectory_data(device, data) -> Response:
    """
    Main optimized trajectory logic.
    Handles trajectory creation or update for a single device.
    """
    trajectory_data = data.get("trajectories", [])
    if not trajectory_data or not trajectory_data[0].get("points"):
        return Response({"error": "Empty trajectory data"}, status=400)

    points = trajectory_data[0]["points"]
    points.sort(key=lambda p: p["timestamp"])

    first_point = points[0]
    mode = first_point.get("mode")
    status = first_point.get("status")
    speed = first_point.get("speed", 0)
    timestamp = first_point.get("timestamp")
    current_date = timestamp.date() if timestamp else None

    # Location validation
    location = first_point.get("location", {})
    lat, lng = location.get("lat"), location.get("lng")
    if not lat or not lng or lat == 0 or lng == 0:
        return Response({"message": "Invalid coordinates"}, status=200)

    address = location.get("city")

    # Update live status
    update_device_status_and_speed(device, status, speed, address)

    # On démarre une transaction atomique pour s'assurer que toutes les opérations sur la trajectoire
    # soient effectuées de manière sécurisée et cohérente.
    with transaction.atomic():

        # On récupère la dernière trajectoire du device, triée par end_time décroissant
        # select_for_update(lock) pour verrouiller la ligne si quelqu'un d'autre y accède.
        last_traj = (
            Trajectory.objects.filter(device=device)
            .select_for_update(skip_locked=True)
            .order_by("-end_time")
            .first()
        )

        # On initialise les variables du contexte précédent :
        # - prev_date : date de fin de la dernière trajectoire
        # - prev_props : propriétés de la dernière trajectoire (points, status, mode…)
        # - prev_geom : géométrie de la dernière trajectoire
        prev_date = last_traj.end_time.date() if last_traj else None
        prev_props = last_traj.properties.get("trajectory", []) if last_traj else []
        prev_geom = last_traj.geom if last_traj else LineString()

        # On récupère les derniers états connus :
        # - prev_status : statut du véhicule (ON/OFF)
        # - prev_mode : mode de conduite (professionnel, privé…)
        # - prev_speed : dernière vitesse
        prev_status = prev_props[-1].get("status") if prev_props else STATUS_OFF
        prev_mode = prev_props[-1].get("mode") if prev_props else PROFESSIONAL_MODE
        prev_speed = prev_props[-1].get("speed", 0)

        # Vérifie si c'est un nouveau jour pour créer une nouvelle trajectoire
        new_day = prev_date and current_date and current_date > prev_date

        # Vérifie si les données reçues sont suffisamment différentes pour être sauvegardées
        unchanged = not should_save_data(trajectory_data, last_traj)

        # Si pas de changement significatif et pas de nouveau jour => on ne fait rien
        if unchanged and not new_day:
            logger.debug(f"[{device.imei}] No significant change")
            return Response({"message": "No change"}, status=200)

        # Si le mode actuel est privé, on ne sauvegarde pas la trajectoire
        if mode == PRIVATE_MODE:
            logger.info(f"[{device.imei}] Private mode – no save")
            return Response({"message": "Private mode"}, status=200)

        # On décide si on doit créer une nouvelle trajectoire :
        # - aucune trajectoire précédente
        # - le mode précédent était privé
        # - véhicule arrêté et vitesse 0
        # - nouveau jour
        new_traj_needed = (
            not last_traj
            or prev_mode == PRIVATE_MODE
            or (prev_status == STATUS_OFF and float(prev_speed) == 0)
            or new_day
        )

        # Prépare les propriétés de la trajectoire :
        # si nouvelle trajectoire => on part d'une liste vide, sinon on continue les anciennes propriétés
        props = prepare_trajectory_properties(
            trajectory_data[0],
            [] if new_traj_needed else prev_props
        )

        # Crée la géométrie (ligne) à partir des points reçus
        # continue l'ancienne géométrie si ce n'est pas une nouvelle trajectoire
        geom = create_geometry_from_points(
            trajectory_data[0]["points"],
            LineString() if new_traj_needed else prev_geom,  # ← Changement ici
            should_continue_geometry=not new_traj_needed
        )

        # Création d'une nouvelle trajectoire si nécessaire
        if new_traj_needed:
            Trajectory.objects.create(
                device=device,
                geom=geom,
                properties=props,
                start_time=json_serial(data["start_time"]),
                end_time=json_serial(data["end_time"]),
                last_position=location,
            )
            logger.info(f"[{device.imei}] New trajectory created")
            return Response({"message": "New trajectory created"}, status=201)

        # Sinon, mise à jour de la dernière trajectoire existante
        last_traj.geom = geom
        last_traj.properties = props
        last_traj.end_time = data["end_time"]
        last_traj.last_position = location
        last_traj.save(update_fields=["geom", "properties", "end_time", "last_position"])

        logger.debug(f"[{device.imei}] Trajectory updated")
        return Response({"message": "Trajectory updated"}, status=200)




def save_data_response_avant_modification(record_json: str, codec_id: int):
    """
    Main trajectory logic: validates, processes, and updates DB entries.
    OPTIMIZED: Reduced DB queries, better transaction handling.
    """
    try:
        # Parse TCP data
        tcp_data = process_tcp_data(record_json, codec_id)
        print("TCP Data:", tcp_data)  # Debugging line
        
        serializer = TrajectoryRequestSerializer(data=tcp_data)
        if not serializer.is_valid():
            logger.error(f"Invalid trajectory data: {serializer.errors}")
            return Response({'error': serializer.errors}, status=400)

        data = serializer.validated_data
        trajectory_data = data.get('trajectories', [])
        
        if not trajectory_data or not trajectory_data[0].get('points'):
            return Response({'error': 'Empty or invalid trajectory data'}, status=400)

        points = trajectory_data[0]['points']
        points.sort(key=lambda p: p['timestamp'])
        trajectory_data[0]['points'] = points

        first_point = points[0]
        device_mode = first_point.get('mode')
        device_status = first_point.get('status')
        device_id = data.get('device_id')
        timestamp = first_point.get('timestamp')
        current_date = timestamp.date() if timestamp else None
        vehicle_speed = first_point.get('speed', 0)

        speed_limit = data.get('parameters', {}).get('speed_limit')
        

        # OPTIMIZATION: Use cache
        device = get_cached_device(device_id)
        
        if not device:
            logger.error(f"Device not found: {device_id}")
            return Response({'error': 'Device not found'}, status=404)

        # Validation du statut
        if device_status not in [STATUS_ON, STATUS_OFF]:
            logger.warning(f"Invalid device status: {device_status}")
            return Response({'error': 'Invalid device status'}, status=400)
        
        device_status = STATUS_OFF if vehicle_speed == 0 and device_status == STATUS_OFF else STATUS_ON


        device_position = {
            **first_point.get('location', {}), 
            "name": device.name, 
            "device_mode": device_mode, 
            "status": device_status
        }

        address = device_position.get("city")

        # Validation des coordonnées
        lat = device_position.get('lat', 0)
        lng = device_position.get('lng', 0)
        if lat in [0, 0.0, None] or lng in [0, 0.0, None]:
            logger.debug(f"[{device.imei}] Invalid coordinates, skipping")
            return Response({'message': 'Invalid coordinates'}, status=200)

        # Update device status (this also handles WebSocket broadcast)
        update_device_status_and_speed(device, device_status, vehicle_speed, address, speed_limit, device_position)

        # OPTIMIZATION: Use select_for_update to avoid race conditions
        with transaction.atomic():
            last_trajectory = (
                Trajectory.objects
                .filter(device=device)
                .select_for_update(skip_locked=True)
                .order_by('-end_time')
                .first()
            )

            previous_date = last_trajectory.end_time.date() if last_trajectory else None
            trajectory_points = last_trajectory.properties.get('trajectory', []) if last_trajectory else []
            trajectory_geom = last_trajectory.geom if last_trajectory else LineString()

            previous_status = trajectory_points[-1].get('status') if trajectory_points else PREVIOUS_STATUS_DEVICE
            previous_mode = trajectory_points[-1].get('mode') if trajectory_points else PREVIOUS_MODE_DEVICE
            previous_speed = trajectory_points[-1].get('speed') if trajectory_points else 0
            try:
                previous_speed = float(previous_speed)
            except (TypeError, ValueError):
                previous_speed = 0.0    

            # Reset trajectory if switching from private mode
            if previous_mode == PRIVATE_MODE:
                trajectory_points = []
                trajectory_geom = LineString()

            new_day = previous_date and current_date and current_date > previous_date
            unchanged = not should_save_data(trajectory_data, last_trajectory)

            if unchanged and not new_day:
                logger.debug(f"[{device.imei}] No significant change detected")
                return Response({'message': 'No significant change'}, status=200)

            is_private = device_mode == PRIVATE_MODE
            switched_to_private = previous_mode == PROFESSIONAL_MODE and is_private
            status_was_off = previous_status == STATUS_OFF and previous_speed == 0
            new_trajectory_needed = not last_trajectory or switched_to_private or status_was_off or new_day

            if is_private:
                logger.info(f"[{device.imei}] Vehicle in PRIVATE mode — no trajectory will be saved.")
                return Response({'message': 'Private mode: trajectory not recorded'}, status=200)

            properties = prepare_trajectory_properties(
                trajectory_data[0], 
                trajectory_points if not new_trajectory_needed else []
            )

            should_continue_geometry = (
                not new_trajectory_needed and 
                (previous_status == STATUS_ON or previous_speed > 0)
            )
            
            geom_data = create_geometry_from_points(
                trajectory_data[0]['points'], 
                trajectory_geom,
                should_continue_geometry
            )

            if new_trajectory_needed:
                Trajectory.objects.create(
                    device=device,
                    geom=geom_data,
                    properties=properties,
                    start_time=json_serial(data['start_time']),
                    end_time=json_serial(data['end_time']),
                    last_position=device_position,
                )
                logger.info(f"[{device.imei}] New trajectory created")
                return Response({'message': 'New trajectory created'}, status=201)
            
            if not last_trajectory:
                logger.error(f"[{device.imei}] No trajectory to update")
                return Response({'error': 'No existing trajectory to update'}, status=400)

            # Update existing trajectory
            last_trajectory.geom = geom_data
            last_trajectory.properties = properties
            last_trajectory.end_time = data['end_time']
            last_trajectory.last_position = device_position
            last_trajectory.save(update_fields=['geom', 'properties', 'end_time', 'last_position'])

            logger.debug(f"[{device.imei}] Trajectory updated")
            return Response({'message': 'Trajectory updated'}, status=200)

    except Device.DoesNotExist:
        logger.error("Device not found")
        return Response({'error': 'Device not found'}, status=404)
        
    except Exception as e:
        logger.error(f"Processing error: {e}", exc_info=True)
        return Response({'error': 'Internal server error'}, status=500)
        
    finally:
        # CRITICAL: Always close DB connection
        try:
            connection.close()
        except:
            pass


def update_device_status_and_speed(device: Device, status: str, speed: float,  address: str, speed_limit: Optional[int], position: Optional[Dict] = None):
    """
    Updates device status and speed limit in DB and broadcasts via WebSocket.
    OPTIMIZED: Only save if actually changed, batch field updates.
    """
    try:
        # Validation de la position
        if position:
            lat = position.get("lat")
            lng = position.get("lng")

            if not lat or not lng or lat == 0 or lng == 0:
                logger.debug(f"[{device.imei}] Invalid position, skipping update")
                return


        updated_fields = []

        # Check if status changed
        if device.status != status:
            device.status = status
            updated_fields.append("status")

        # Check if speed limit changed
        if speed_limit is not None:
            try:
                speed_limit = int(speed_limit)
                if speed_limit > 0 and device.speed_limit != speed_limit:
                    device.speed_limit = speed_limit
                    updated_fields.append("speed_limit")
            except (ValueError, TypeError):
                logger.debug(f"[{device.imei}] Invalid speed limit: {speed_limit}")

        # OPTIMIZATION: Only save if there are changes
        if updated_fields:
            device.save(update_fields=updated_fields)
            logger.debug(f"[{device.imei}] Updated fields: {updated_fields}")
            
            # Invalidate cache after update
            invalidate_device_cache(str(device.uid))

        # Broadcast via WebSocket (non-blocking)
        try:
            company_name = device.company_manager.name if device.company_manager else None

            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                "device_status_updates",
                {
                    "type": "send_device_status",
                    "device_id": str(device.uid),
                    "status": status,
                    "position": position,
                    "speed": speed,
                    "companyName": company_name,
                    "immatriculation":device.car_name,
                    "address": address
                },
            )
        except Exception as ws_error:
            logger.warning(f"[{device.imei}] WebSocket broadcast failed: {ws_error}")

    except Exception as e:
        logger.error(f"[{device.imei}] Error updating device: {e}", exc_info=True)


def should_save_data(trajectory_data: List[Dict], last_trajectory: Optional[Trajectory]) -> bool:
    """
    Returns True if the location or status changed significantly.
    Optimized logic with coordinate validation and distance check
    to avoid invalid GPS points or 'bird-flight' jumps.
    """
    if not trajectory_data or not trajectory_data[0].get('points'):
        return False

    current = trajectory_data[0]['points'][0]
    current_location = current.get('location', {})
    
    lat = current_location.get('lat', 0)
    lng = current_location.get('lng', 0)

    # Ignore invalid coordinates
    if not (-90 <= lat <= 90 and -180 <= lng <= 180) or (lat == 0 and lng == 0):
        return False

    # No previous trajectory = always save
    if not last_trajectory:
        return True

    last = last_trajectory.last_position or {}
    last_lat = last.get('lat')
    last_lng = last.get('lng')

    # If both OFF, don't save
    # if last.get('status') == STATUS_OFF and current.get('status') == STATUS_OFF:
    #     return False

    # Vérification de distance pour éviter le "bird-flight"
    if last_lat is not None and last_lng is not None:
        dist_m = geodesic((last_lat, last_lng), (lat, lng)).meters
        if dist_m > MAX_DISTANCE_METERS:
            return False  # saut GPS improbable

    # Check if anything changed
    location_changed = (lat != last_lat or lng != last_lng)
    status_changed = current.get('status') != last.get('status')

    return location_changed or status_changed
