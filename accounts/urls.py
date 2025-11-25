from django.urls import path
from .views import CheckPasswordChanged, UserDeleteView, UserLoginView, UserLogoutView, TokenCheckView,UserListView, UserUpdateView,CheckEmailExistsAPIView, UserBySlug, UpdateDefaultPassword, UserRole, UserInformationView, UserRestoreView, EditUserProfileWithPassword, UserForgotPassword, VerifyTokenView,UserFmapInformationView

urlpatterns = [
    # -------- AUTHENTICATION --------
    path('login/', UserLoginView.as_view(), name='user-login'),
    path('logout/', UserLogoutView.as_view(), name='user-logout'),
    path('token/', TokenCheckView.as_view(), name='token-check'),
    path('token-verify/', VerifyTokenView.as_view(), name='token-verify'),
    path('forgot-password/', UserForgotPassword.as_view(), name="forgot-password"),
    path('check-password-change/', CheckPasswordChanged.as_view(), name='password-change'),
    path('default-password-change/', UpdateDefaultPassword.as_view(), name='password-update'),

    # -------- USER CRUD --------
    path('lists/', UserListView.as_view(), name='user-list'),
    path('get/', UserInformationView.as_view(), name='user-get'),
    path('get-fmap/', UserFmapInformationView.as_view(), name='user-fmap-get'),
    path('update/<uuid:uid>/', UserUpdateView.as_view(), name='user-update'),
    path('update-profile/<uuid:uid>/', EditUserProfileWithPassword.as_view(), name='user-edit-profile'),
    path('delete/<uuid:uid>/', UserDeleteView.as_view(), name='user-delete'),
    path('restore/<uuid:uid>/', UserRestoreView.as_view(), name='user-restore'),

    # -------- VALIDATIONS & CHECKS --------
    path('check-email/', CheckEmailExistsAPIView.as_view(), name='check-email'),

    # -------- OTHER --------
    path("user-by-slug/<str:slug>", UserBySlug.as_view()),
    path("user-role/", UserRole.as_view()),
]
