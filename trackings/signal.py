import logging
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db.models.signals import post_save
from django.dispatch import receiver
from devices.models import Trajectory
from trackings.alerts.models import Alert
from trackings.events.models import Event
from trackings.notifications.models import Notification
from utils.alert_trigger import check_geofence_violation, check_speed_violation
import os
import smtplib, ssl
from django.utils import translation
from email.message import EmailMessage
from accounts.serializers import UserCreateSerializer
from constants.device_info import PROFESSIONAL_MODE

logger = logging.getLogger(__name__)

@receiver(post_save, sender=Trajectory)
def check_trajectory_geofence(sender, instance, created, **kwargs):
    """
    Check for geofence violations when a trajectory is created or updated with an end time.

    Parameters:
        sender (Model): The model class that sent the signal.
        instance (Trajectory): The trajectory instance being saved.
        created (bool): Whether this is a new trajectory instance.
    """
    if created or instance.end_time:
        last_point = instance.geom[-1]

        location = {
            'latitude': last_point[1],
            'longitude': last_point[0]
        }

        device_mode = instance.last_position.get('device_mode')

        violation = check_geofence_violation(location, instance.device.zone)

        if violation['violation'] and device_mode == PROFESSIONAL_MODE:
            Event.objects.create(
                device=instance.device,
                event_type='geofence_breach',
                location=location,
                data={
                    'distance': violation['distance'],
                    'trajectory_id': str(instance.uid)
                }
            )

@receiver(post_save, sender=Trajectory)
def check_trajectory_speed(sender, instance, created, **kwargs):
    """
    Check for speed violations on a trajectory and create an event if a violation is detected.

    Parameters:
        sender (Model): The model class that sent the signal.
        instance (Trajectory): The trajectory instance being saved.
        created (bool): Whether this is a new trajectory instance.
    """
    try:
        if not (created or instance.end_time):
            return

        if not instance.properties or 'trajectory' not in instance.properties:
            logger.warning(f"Trajectory {instance.uid} missing required properties")
            return

        trajectories = instance.properties['trajectory']
        if not trajectories:
            return

        last_point = trajectories[-1]

        if 'location' not in last_point or 'speed' not in last_point:
            logger.warning("Trajectory point missing required data")
            return

        speed_limit = instance.device.speed_limit

        if speed_limit != 0:
            violation = check_speed_violation(
                speed=last_point['speed'],
                speed_limit=speed_limit
            )

            if violation['violation'] and last_point['mode'] == PROFESSIONAL_MODE:
                Event.objects.create(
                    device=instance.device,
                    event_type='speed_excess',
                    location={
                        'latitude': last_point['location']['lat'],
                        'longitude': last_point['location']['lng']
                    },
                    data={
                        'speed': violation['speed'],
                        'speed_limit': violation['speed_limit'],
                        'excess': violation['excess'],
                        'severity': violation['severity'],
                        'trajectory_id': str(instance.uid)
                    }
                )

    except Exception as e:
        logger.error(f"Error checking speed violation: {str(e)}", exc_info=True)

@receiver(post_save, sender=Event)
def create_alert_for_event(sender, instance, created, **kwargs):
    """
    Creates an alert for specific event types when an event is generated.
    """
    logger.info(f"Event saved: UID={instance.uid}, Created={created}, Type={instance.event_type}")

    if created:
        try:
            if instance.event_type == 'geofence_breach':
                severity = instance.determine_geofence_severity()
                alert = Alert.objects.create(event=instance, severity=severity, status='pending')
                logger.info(f"Geofence breach alert created: UID={alert.uid}, Severity={severity}")

            elif instance.event_type == 'speed_excess':
                severity = instance.determine_speed_severity()
                alert = Alert.objects.create(event=instance, severity=severity, status='pending')
                logger.info(f"Speed excess alert created: UID={alert.uid}, Severity={severity}")

        except Exception as e:
            logger.error(f"Error creating alert for event {instance.uid}: {e}", exc_info=True)

@receiver(post_save, sender=Alert)
def alert_created(sender, instance, created, **kwargs):
    """
    Creates user notifications when an alert is generated.
    """
    logger.info(f"Alert saved: UID={instance.uid}, Created={created}, Severity={instance.severity}")

    if created:
        try:
            users = instance.event.device.company_manager.users.all()
            device_name = instance.event.device.name

            for user in users:
                notification = Notification.objects.create(
                    user=user,
                    alert=instance,
                    message=(
                        f"{instance.event.get_event_type_display()} - "
                        f"{instance.get_severity_display()} "
                        f"(Appareil: {device_name})"
                    ),
                    notification_type= f"{instance.get_severity_display()}"
                )
                logger.info(f"Notification created: UID={notification.uid} for User={user.uid}")

            # send_alert_email_to_users(users, instance, device_name)

        except Exception as e:
            logger.error(f"Error creating notification for alert {instance.uid}: {e}", exc_info=True)

@receiver(post_save, sender=Notification)
def notification_created(sender, instance, created, **kwargs):
    """
    Sends a WebSocket notification when a new notification is created.
    """
    logger.info(f"Notification saved: UID={instance.uid}, Created={created}, Type={instance.notification_type}")

    if created:
        try:
            channel_layer = get_channel_layer()
            user_uid = instance.user.uid
            logger.info(f"Sending WebSocket notification to User={user_uid}")

            async_to_sync(channel_layer.group_send)(
                f"notifications_{user_uid}",
                {
                    "type": "notification_message",
                    "message": {
                        "uid": str(instance.uid),
                        "message": instance.message,
                        "notification_type": instance.notification_type,
                        "created_at": instance.created_at.isoformat(),
                        "alert_id": str(instance.alert.uid) if instance.alert else None
                    }
                }
            )

            logger.info(f"WebSocket notification sent successfully for Notification={instance.uid}")

        except Exception as e:
            logger.error(f"Error sending WebSocket notification for Notification {instance.uid}: {e}", exc_info=True)


def send_alert_email_to_users(users, alert, device_name):
    """
    Sends an email to all users of the company regarding an alert.
    """
    EMAIL_HOST = os.getenv('EMAIL_HOST')
    EMAIL_PORT = int(os.getenv('EMAIL_PORT'))
    EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER')
    EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD')

    if not all([EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD]):
        raise ValueError("Some email parameters are missing in the environment variables.")
    
    language = translation.get_language().split('-')[0] 

    subject = {
        "fr": f"[{alert.get_severity_display()}] Alerte sur l'appareil {device_name}",
        "en": f"[{alert.get_severity_display()}] Alert on device {device_name}",
    }.get(language, f"[{alert.get_severity_display()}] Alert on device {device_name}")


    alert_date = alert.created_at.strftime("%Y-%m-%d %H:%M:%S")

    template_path = f"templates/{language}/notification.html"

    email_content = UserCreateSerializer._read_email_template(
            template_path, event_type=alert.event.get_event_type_display(),severity=alert.get_severity_display(), device_name=device_name, alert_date=alert_date
    )

    for user in users:
        try:
            msg = EmailMessage()
            msg['From'] = EMAIL_HOST_USER
            msg['To'] = user.email
            msg['Subject'] = subject
            msg.set_content(email_content, subtype='html')

            with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as server:
                context_ssl = ssl.create_default_context()
                server.starttls(context=context_ssl)
                server.login(EMAIL_HOST_USER, EMAIL_HOST_PASSWORD)
                server.sendmail(EMAIL_HOST_USER, user.email, msg.as_string())
        except Exception as e:
            logger.error(f"Error sending email to {user.email}: {e}")



