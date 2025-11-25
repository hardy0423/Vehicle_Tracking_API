from .views import (CheckIMEIExistsAPIView, DeviceDelete, DeviceListAPIView, DeviceLocationAPIView, DeviceRetrieve,UserDeviceIntervetionListView,DeviceRetrieveByImei,CheckDeviceNumberAPIView,DeviceCreateAPIView,IntervetionZoneByIdView,DeviceRestoreView,
    DeviceTypeListView, DeviceUpdate,SpeedLimitView, ServerListView, UserDeviceCompanyListView, TrajectoryMVTView, CreateTrajectoryView, DevicePrivateAPIView, DeviceCompanyRetrieveView, DevicePositionRetriever, GetDevicesByUserCompanyView, DeviceCommandView) 
from django.urls import path
urlpatterns = [
    # ---- Create / Update / Delete ----
    path('create/', DeviceCreateAPIView.as_view(), name='device-create'),
    path('create-trajectory/', CreateTrajectoryView.as_view(), name='trajectory-create'),  # Test Local
    path('delete/<uuid:uid>/', DeviceDelete.as_view(), name='device-delete'),
    path('restore/<uuid:uid>/', DeviceRestoreView.as_view(), name='company-restore'),
    path('update/<uuid:uid>/', DeviceUpdate.as_view(), name='device-update'),

    # ---- Retrieve / Get by ID or IMEI ----
    path('get/<uuid:uid>/', DeviceRetrieve.as_view(), name='device-retrieve'),
    path('get/<str:imei>/', DeviceRetrieveByImei.as_view(), name='deviceImei-retrieve'),
    path('get-device-user/', GetDevicesByUserCompanyView.as_view(), name='device-by-user'),
    path('get-position/<uuid:uid>/', DevicePositionRetriever.as_view(), name='device-position-retrieve'),

    # ---- Device Lists ----
    path('list/', DeviceListAPIView.as_view(), name='device-list'),
    path('types/', DeviceTypeListView.as_view(), name='device-types'),
    path('servers/', ServerListView.as_view(), name='device-servers'),

    # ---- Companies / Zones ----
    path('companies/', UserDeviceCompanyListView.as_view(), name='device-companies'),
    path('companies/<uuid:uid>/', DeviceCompanyRetrieveView.as_view(), name='device-companies'),
    path('zone/', UserDeviceIntervetionListView.as_view(), name='device-companies'),
    path('intervention-zone/<uuid:uid>/', IntervetionZoneByIdView.as_view(), name='zone-intervention'),

    # ---- Location / Itinerary ----
    path('location/', DeviceLocationAPIView.as_view(), name='device-location'),
    path('itinerary/<uuid:device_id>/<str:date_trajectory>/<int:z>/<int:x>/<int:y>', TrajectoryMVTView.as_view(), name='device-itinerary-mvt'),

    # ---- Commands / Settings ----
    path('command/<uuid:uid>/', DeviceCommandView.as_view(), name='engine-immobilizer'),
    path('private-mode/', DevicePrivateAPIView.as_view(), name='device-private'),
    path('speed-limit/<uuid:uid>/', SpeedLimitView.as_view(), name='speed-limit'),

    path('check-imei/', CheckIMEIExistsAPIView.as_view(), name='check-imei'),
    path('checkt-device-number/', CheckDeviceNumberAPIView.as_view(), name='check-device'),
]


