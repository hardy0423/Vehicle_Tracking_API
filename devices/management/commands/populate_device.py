import json
import os
from django.core.management.base import BaseCommand
from devices.models import TypeDevice
import uuid

class Command(BaseCommand):
    help = "Insert device types into the database from device.json"

    def handle(self, *args, **options):
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        json_path = os.path.join(base_dir, '..', 'data', 'device.json')

        try:
            with open(json_path, 'r') as file:
                device_data = json.load(file)
        except FileNotFoundError:
            self.stderr.write(self.style.ERROR(f"device.json not found at {json_path}"))
            return

        for item in device_data:
            TypeDevice.objects.create(
                uid=uuid.uuid4(),
                product=item.get('product', ''),
                name=item.get('name', ''),
                value=item.get('value', ''),
                port=str(item.get('port', ''))
            )

        self.stdout.write(self.style.SUCCESS('Devices inserted successfully.'))