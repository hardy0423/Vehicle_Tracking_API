from django.core.management.base import BaseCommand
from companies.models import Country
import pycountry

class Command(BaseCommand):
    help = "Populate the Country table using pycountry"

    def handle(self, *args, **kwargs):
        for country in pycountry.countries:
            Country.objects.get_or_create(
                name=country.name,
                alpha2_code=country.alpha_2,
                alpha3_code=country.alpha_3,
                numeric_code=int(country.numeric)
            )
        self.stdout.write(self.style.SUCCESS("Countries populated successfully."))