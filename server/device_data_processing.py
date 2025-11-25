from django.shortcuts import get_object_or_404
from datetime import datetime, timezone
from devices.models import Device
import logging
import math
import json
import asyncio
import aiohttp
# Constants for device status and modes
PROFESSIONAL_MODE = "Professional"
PRIVATE_MODE = "Private"
DEVICE_ON = "On"
DEVICE_OFF = "Off"

# Logging configuration
logger = logging.getLogger(__name__)

"""
See https://wiki.teltonika-gps.com/view/FMC130_Teltonika_Data_Sending_Parameters_ID
"""

# IO element keys as constants
IO_ELEMENTS_SPEED_LIMIT = '1116' #MaxRoadSpeed
IO_ELEMENT_IGNITION = '239'  # Ignition
IO_ELEMENT_MOVEMENT = '240'  # Movement
IO_ELEMENTS_MODE = '250' #The element 250 - Trip refers to the status of a journey or trip for the vehicle.

class TcpDataProcessingError(Exception):
    """Custom exception for handling TCP data processing errors."""
    pass


def clean_invalid_data(data):
    """
    Cleans invalid data (like Infinity, -Infinity, or NaN) before saving to the database.
    """
    if isinstance(data, (float, int)):
        if math.isinf(data) or math.isnan(data):
            return None
    return data

def flatten_io_elements(io_extended: dict) -> dict:
    """
    Converts categorized IO elements (by size) into a flat dictionary.

    Args:
        io_extended (dict): IO elements categorized by '1B', '2B', etc.
    """
    flat_io = {}
    for size_group, elements in io_extended.items():
        flat_io.update({str(k): v for k, v in elements.items()})
    return flat_io


async def get_address(lat, lon):
    url = (
        f"https://data.geopf.fr/geocodage/reverse?"
        f"lon={lon}&lat={lat}&index=address&limit=1&returntruegeometry=false&type=street"
    )

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    features = data.get("features")
                    if features and len(features) > 0:
                        return features[0]["properties"]["label"]
        return "Adresse non trouvée"
    except Exception as e:
        logger.warning(f"Error fetching address for ({lat}, {lon}): {e}")
        return "Adresse non trouvée"


def process_tcp_data(tcp_data, codec_id):
    """
    Processes incoming TCP data from the device and returns structured data.
    
    Args:
        tcp_data (str or dict): JSON string or dict from the device (TCP).
        codec_id (int): Codec type (e.g., 8 for Codec8, 142 for Codec8 Extended).

    Returns:
        dict: Processed data for saving.
    """
    try:
        if isinstance(tcp_data, str):
            tcp_data = json.loads(tcp_data)

        imei = tcp_data.get("imei")
        timestamp = tcp_data.get("timestamp")
        longitude = clean_invalid_data(tcp_data.get("longitude"))
        latitude = clean_invalid_data(tcp_data.get("latitude"))
        speed = clean_invalid_data(tcp_data.get("speed"))
        altitude = clean_invalid_data(tcp_data.get("altitude"))
        angle = clean_invalid_data(tcp_data.get("angle"))
        satellites = tcp_data.get("satellites")
        event_id = tcp_data.get("event_id")

        # Codec-based IO element extraction
        if codec_id == 8: #Codec8 standard
            io_elements = tcp_data.get("io_elements", {})
        elif codec_id == 142:  #extended codec
            io_raw = tcp_data.get("io", {})
            io_elements = flatten_io_elements(io_raw)
        else:
            raise TcpDataProcessingError(f"Unsupported codec ID: {codec_id}")

        start_time = timestamp
        end_time = start_time  # Same as start time for this scenario

        # Retrieve device object based on IMEI
        device = get_object_or_404(Device, imei=imei)
        device_id = device.uid
        # Get the device status, mode, and speed limit
        device_status = check_device_status(io_elements)
        device_mode = check_device_mode(io_elements)
        speed_limit = get_speed_limit(io_elements)

        address = None
        try:
            address = asyncio.run(get_address(latitude, longitude))
        except Exception as e:
            logger.warning(f"[{device.imei}] Failed to fetch address: {e}")

        # Build trajectory point
        trajectory_point = {
            "status": device_status,
            "location": {
                "lat": latitude,
                "lng": longitude,
                "city": address
            },
            "speed": str(speed),
            "mode": device_mode,

            "timestamp": start_time
        }

        trajectory = {
            "points": [trajectory_point]
        }

        processed_data = {
            "device_id": device_id,
            "start_time": start_time,
            "end_time": end_time,
            "trajectories": [trajectory],
            "parameters": {"speed_limit": speed_limit}
        }

        return processed_data

    except Exception as e:
        logger.error(f"Failed to process TCP data: {e}")
        raise TcpDataProcessingError(f"Failed to process TCP data: {e}")


def check_device_status(io_elements):
    """
    Checks the status of the device (on/off) based on IO elements.
    
    Args:
        io_elements (dict): The input/output elements containing device data.

    Rules:
        - 239: Ignition
            0 = Off, 1 = On
        - 240: Movement
            0 = Off, 1 = On
    """
    ignition = get_io_element_value(io_elements, IO_ELEMENT_IGNITION)
    movement = get_io_element_value(io_elements, IO_ELEMENT_MOVEMENT)

    # Si le véhicule a l’allumage ou le mouvement activé, on le considère comme "ON"
    if ignition == 1 or movement == 1:
        return DEVICE_ON
    else:
        return DEVICE_OFF


def check_device_mode(io_elements):
    """
    Checks the mode of the device (Private/Professional) based on IO elements.
    
    Args:
        io_elements (dict): The input/output elements containing device data.

    0 – trip stop
    1 – trip start
    From 01.00.24 fw version available with BT app new values:
    2 – Business Status
    3 – Private Status
    4-9 – Custom Statuses

    """
    movement_source = get_io_element_value(io_elements, IO_ELEMENTS_MODE)
    if movement_source == 3:
        return PRIVATE_MODE
    elif movement_source == 0:
        return PROFESSIONAL_MODE
    return PROFESSIONAL_MODE
    

def get_speed_limit(io_elements):
    """
    Retrieves the speed limit from the IO elements.
    
    Args:
        io_elements (dict): The input/output elements containing device data.
    
    Returns:
        int: Speed limit if available, else 0.
    """
    speed_limit = get_io_element_value(io_elements, IO_ELEMENTS_SPEED_LIMIT, default=0)
    
    return speed_limit


def get_io_element_value(io_elements, key, default=None):
    """
    Retrieves the value of a specific IO element from the device data.
    
    Args:
        io_elements (dict): The IO elements dictionary.
        key (int): The key of the IO element to retrieve.
        default: The default value if the key does not exist.
    
    Returns:
        The value of the IO element or the default value.
    """
    return io_elements.get(key, default)
