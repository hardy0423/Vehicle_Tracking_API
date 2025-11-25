from django.urls import path
from .views import  ClassifiedTileView, InterventionZoneDelete, InterventionZoneRetrieve, ZoneListView, ZoneCreateView

urlpatterns = [
    path('get-all/', ZoneListView.as_view(), name='zone-list'),
    path('create/', ZoneCreateView.as_view(), name='zone-create'),
    path('at-zone/tiles/<int:z>/<int:x>/<int:y>', ClassifiedTileView.as_view(), name='zone_tiles'),
    path('at-zone/tiles/<uuid:zone_id>/<int:z>/<int:x>/<int:y>', ClassifiedTileView.as_view(), name='zone_tiles'),
    path('get/<uuid:uid>/', InterventionZoneRetrieve.as_view(), name='zone-retrieve'),


    #Uncomment this code if we want to add the functionality to delete a polygon in the database 
    # path('delete/<uuid:uid>/', InterventionZoneDelete.as_view(), name='zone-delete'),
]




