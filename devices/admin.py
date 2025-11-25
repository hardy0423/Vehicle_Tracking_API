from django.contrib import admin
from import_export import resources
from import_export.admin import ExportActionModelAdmin, ImportMixin

from devices.models import Server, TypeDevice, Device
from companies.models import Company
from map.models import InterventionZone

# Register your models here.
class TypeDeviceResource(resources.ModelResource):
    class Meta:
        model = TypeDevice
        fields = ('uid', 'product', 'name', 'value', 'status', 'port')
        import_id_fields = ('uid',)

class ServerResource(resources.ModelResource):
    class Meta:
        model = Server
        fields = ('uid', 'ip_address', 'hostname', 'port')
        import_id_fields = ('uid',)

@admin.register(TypeDevice)
class TypeDeviceAdmin(ImportMixin, ExportActionModelAdmin, admin.ModelAdmin):
    resource_class = TypeDeviceResource
    list_display = ('uid', 'product', 'name', 'value', 'status', 'port')
    search_fields = ('name', 'product', 'value')
    list_editable = ('status', 'port')


@admin.register(Server)
class ServerAdmin(ImportMixin, ExportActionModelAdmin, admin.ModelAdmin):
    resource_class = ServerResource
    list_display = ('uid', 'ip_address', 'hostname', 'port')
    search_fields = ('ip_address', 'hostname')
    list_editable = ('port',)


admin.site.register(Company)
admin.site.register(Device)
admin.site.register(InterventionZone)


