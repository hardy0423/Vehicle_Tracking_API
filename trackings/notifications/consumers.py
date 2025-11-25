import json
import logging
from datetime import datetime
from uuid import UUID
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.contrib.auth.models import AnonymousUser
from rest_framework.authtoken.models import Token

from .models import Notification



logger = logging.getLogger(__name__)

class NotificationConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer to handle real-time notifications for authenticated users.
    """

    async def connect(self):
        """
        Handles WebSocket connection with silent rejection for invalid tokens.
        """
        try:
            token = self.get_token_from_query()
            if not token:
                await self.close()
                return

            user = await self.get_user_from_token(token)
            if not user or not user.is_authenticated:
                await self.close()
                return

            self.user = user
            self.room_group_name = f"notifications_{self.user.uid}"
            
            await self.channel_layer.group_add(
                self.room_group_name,
                self.channel_name
            )
            await self.accept()
            await self.send_unread_notifications()

        except Exception as e:
            logger.debug(f"Connection error: {str(e)}")
            await self.close()

    async def disconnect(self, close_code):
        """
        Handles WebSocket disconnection.
        Removes the user from the notification group.
        """
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )

    async def receive(self, text_data):
        """
        Handles messages received from the WebSocket client.
        Currently supports marking notifications as read.
        """
        data = json.loads(text_data)
        logger.debug(f"Received data: {data}")

        if data.get('type') == 'mark_read':
            await self.mark_notification_read(data.get('notification_id'))

    async def notification_message(self, event):
        """
        Sends a notification message to the WebSocket client.
        """
        await self.send(text_data=json.dumps({
            'type': 'notification',
            'message': event['message']
        }))

    async def send_unread_notifications(self):
        """
        Sends all unread notifications to the WebSocket client.
        """
        try:
            logger.debug("Sending unread notifications")
            notifications = await self.get_unread_notifications()
            if notifications:
                await self.send(text_data=json.dumps({
                    'type': 'unread_notifications',
                    'notifications': notifications
                }))
        except Notification.DoesNotExist:
            logger.debug("Notification does not exist")
            pass

    @database_sync_to_async
    def mark_notification_read(self, notification_id):
        """
        Marks a notification as read in the database.
        """
        try:
            logger.debug("Marking notification as read")
            notification = Notification.objects.get(
                uid=notification_id,
                user=self.user
            )
            notification.read = True
            notification.save()
            #notification.delete()
        except Notification.DoesNotExist:
            logger.debug("Notification does not exist")
            pass

    @database_sync_to_async
    def get_unread_notifications(self):
        """
        Retrieves all unread notifications for the authenticated user.
        Formats the notification data to be sent to the client.
        """
        unread_notifications = list(Notification.objects.filter(
            user=self.user,
            read=False
        ).values('uid', 'message', 'notification_type', 'created_at'))

        for notification in unread_notifications:
            if isinstance(notification['uid'], UUID):
                notification['uid'] = str(notification['uid'])
            if isinstance(notification['created_at'], datetime):
                notification['created_at'] = notification['created_at'].strftime('%Y-%m-%dT%H:%M:%S.%fZ')

        return unread_notifications


    def get_token_from_query(self):
        try:
            query_string = self.scope.get("query_string", b"").decode("utf-8")
            params = parse_qs(query_string)
            return params.get('token', [None])[0]
        except:
            return None

    @database_sync_to_async
    def get_user_from_token(self, token):
        """
        Authenticates a user based on the provided token.
        Returns an AnonymousUser if the token is invalid or not found.
        """
        try:
            token_obj = Token.objects.get(key=token)
            return token_obj.user
        except Token.DoesNotExist:
            return AnonymousUser()
