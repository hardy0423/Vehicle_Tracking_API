from channels.generic.websocket import AsyncWebsocketConsumer
import json
from constants.device_info import (
    STATUS_OFF, STATUS_ON
)

class DeviceStatusConsumer(AsyncWebsocketConsumer):
    """
    A WebSocket consumer that handles real-time updates for device statuses.
    Tracks the status and position of devices and sends updates to connected clients.
    """
    previous_statuses = {}

    async def connect(self):
        """
        Handles WebSocket connection setup.
        Adds the client to the "device_status_updates" group.
        """
        self.group_name = "device_status_updates"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        """
        Handles WebSocket disconnection.
        Removes the client from the "device_status_updates" group.
        """
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data):
        """
        Handles incoming WebSocket messages (if needed).
        Currently, no action is taken on received messages.
        """
        pass  # You can add logic here if the client sends messages to the server

    async def send_device_status(self, event):
        """
        Sends device status and position updates to the connected client.
        Only sends updates if the status has changed since the last update.

        Args:
            event (dict): A dictionary containing the device ID, status, and optional position.
        """
        device_id = event["device_id"]
        current_position = event.get("position")
        current_speed = event.get("speed")
        companyName = event.get("companyName")
        immatriculation = event.get("immatriculation")
        address = event.get("address")
        if current_speed == 0 and event["status"] == STATUS_OFF:
            current_status = STATUS_OFF
        else:
            current_status = STATUS_ON

        message = {
            "device_id": device_id,
            "position": current_position,
            "speed": current_speed,
            "companyName": companyName,
            "car_name": immatriculation,
            'address': address
        }

        # Only send the status if it has changed
        if device_id not in self.previous_statuses or self.previous_statuses[device_id] != current_status:
            self.previous_statuses[device_id] = current_status  # Update the last known status
            message["status"] = current_status

        # Send the message to the client
        await self.send(text_data=json.dumps(message))

