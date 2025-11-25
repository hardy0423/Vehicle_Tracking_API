from django.urls import path
from .views import CompanyList,CompanyCreate, CompanyDetail, CountryDetail, CountryListCreate, CheckEmailExistsAPIView, CheckDeviceNumber, CompanyRestoreDetail,CompanyAddLogo, NotificationList, UpdateTotalDeviceFmapView

urlpatterns = [
    # --- Company CRUD ---
    path('list/', CompanyList.as_view(), name='company-list'),
    path('create/', CompanyCreate.as_view(), name='company-create'),
    path('get/<uuid:uid>/', CompanyDetail.as_view(), name='company-get'),
    path('update/<uuid:uid>/', CompanyDetail.as_view(), name='company-update'),
    path('delete/<uuid:uid>/', CompanyDetail.as_view(), name='company-delete'),
    path('restore/<uuid:uid>/', CompanyRestoreDetail.as_view(), name='company-restore'),

    # --- Company Specific Actions ---
    path('add-image/<uuid:uid>/', CompanyAddLogo.as_view(), name='add-image'),
    path('notification-list/<uuid:uid>/', NotificationList.as_view(), name='notification-list'),
    path('update-device-fmap/', UpdateTotalDeviceFmapView.as_view(), name='update-total-device'),

    # --- Country Management ---
    path('countries/', CountryListCreate.as_view(), name='country-list-create'),
    path('countries/<str:alpha2_code>/', CountryDetail.as_view(), name='country-detail'),

    # --- Validation / Checks ---
    path('check-email/', CheckEmailExistsAPIView.as_view(), name='check-email'),
    path('check-device-number/', CheckDeviceNumber.as_view(), name='check-device-number'),
]


