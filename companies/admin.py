from django.contrib import admin
from companies.models import Country
from import_export import resources
from import_export.admin import ExportActionModelAdmin, ImportMixin

# Register your models here.
class CountryResource(resources.ModelResource):
    class Meta:
        model = Country
        fields = ('name', 'alpha2_code', 'alpha3_code', 'numeric_code')
        import_id_fields = ('alpha2_code',)
        
@admin.register(Country)
class CountryAdmin(ImportMixin, ExportActionModelAdmin, admin.ModelAdmin):
    resource_class = CountryResource
    list_display =  ('name', 'alpha2_code', 'alpha3_code', 'numeric_code')
    search_fields = ('name', 'alpha2_code', 'alpha3_code', 'numeric_code')