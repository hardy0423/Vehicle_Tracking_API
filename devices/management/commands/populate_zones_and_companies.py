from django.core.management.base import BaseCommand
from django.contrib.gis.geos import Polygon
from companies.models import Company, Country
from map.models import InterventionZone
import uuid


class Command(BaseCommand):
    help = "Populate the InterventionZone and Company tables with initial data"

    def handle(self, *args, **kwargs):
        try:
            country, created = Country.objects.get_or_create(
                alpha2_code='FR',
                defaults={
                    'name': 'France',
                    'alpha3_code': 'FRA', 
                    'numeric_code': 250,
                    'is_active': True
                }
            )
            self.stdout.write(
                self.style.SUCCESS(f"Country {'created' if created else 'retrieved'} successfully: {country.name}")
            )
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error handling Country: {str(e)}"))
            return

        try:
            polygon_coords = [
                (2.512742622890727, 51.200238995279165),
                (-5.837730371299443, 48.5109879594454),
                (-1.5761063961887203, 42.912140714094505),
                (3.058820122569614, 42.1133636032078),
                (7.534674735807215, 45.303214077854506),
                (8.332365931920947, 49.051360793108785),
                (2.5697281575696422, 51.282007479536645),
                (2.512742622890727, 51.200238995279165)
            ]
            
            geom = Polygon(polygon_coords, srid=4326)

            intervention_zone, created = InterventionZone.objects.get_or_create(
                name="France",
                defaults={
                    'uid': uuid.uuid4(),
                    'geom': geom,
                    'default_zone': True
                }
            )
            
            if created:
                self.stdout.write(self.style.SUCCESS("InterventionZone 'France' created successfully."))
            else:
                self.stdout.write(self.style.WARNING("InterventionZone 'France' already exists."))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error creating InterventionZone: {str(e)}"))
            return

        try:
            company, created = Company.objects.get_or_create(
                name="VISION CONNECT",
                defaults={
                    'uid': uuid.uuid4(),
                    'region': "France (Europe)",
                    'adress': "3 Grange Tascher 45210 FERRIERES-EN-GATINAIS",
                    'country': country,
                    'email': "contact@vision-connect.fr",
                    'nbr_device': 50,
                    'default_company': True,
                    'is_actif': True
                }
            )
            
            if created:
                self.stdout.write(self.style.SUCCESS("Company 'Vision Connect' created successfully."))
            else:
                self.stdout.write(self.style.WARNING("Company 'Vision Connect' already exists."))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error creating Company: {str(e)}"))