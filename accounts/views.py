from django.shortcuts import render
from django.contrib.auth import authenticate, login
from rest_framework import status, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.authtoken.models import Token
from rest_framework.permissions import IsAuthenticated
from rest_framework.generics import DestroyAPIView, UpdateAPIView
from faker import Faker
from companies.models import Company

from .models import generate_unique_slug
from .serializers import UserCreateSerializer

from .permissions import IsStaffOrSuperuser
from .serializers import UserSerializer, UserUpdateSerializer, UserByEmailorSlugSerializer,UserInformationRoleSerializer,UserUpdateProfileWithPasswordSerializer,UserUpdateProfileWithOutPasswordSerializer
from .models import User
from rest_framework import status
from django.shortcuts import get_object_or_404
from django.contrib.auth.hashers import make_password
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import LimitOffsetPagination   
from rest_framework_simplejwt.tokens import RefreshToken
from django.forms.models import model_to_dict
import os
from email.message import EmailMessage
from django.utils import translation
from email.utils import formatdate
import smtplib, ssl
from rest_framework.exceptions import AuthenticationFailed


fake = Faker()


class UserRegistrationView(APIView):
    """
    Handle user registration. Requires authentication.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        Register a new user by validating and saving the data.
        Returns a 201 status on success or a 400 status on failure.
        """
        serializers = UserSerializer(data=request.data)
        if serializers.is_valid():
            serializers.save()
            return Response(serializers.data, status=status.HTTP_201_CREATED)
        return Response(serializers.errors, status=status.HTTP_400_BAD_REQUEST)


class TokenCheckView(APIView):
    """
    Check the validity of the token and return user information.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        headers = request.headers
        
        user = request.user
        token = Token.objects.get(user=user)
        return Response({
            'username': user.username,
            'is_admin': user.is_staff,
            'accessToken': token.key,
            'role': user.role
        })


class UserLoginView(ObtainAuthToken):
    """
    User login view that authenticates and returns a token.
    """
    def post(self, request, *args, **kwargs):
        login_input = request.data.get('username')
        password = request.data.get('password')
        user = User.objects.filter(email=login_input).first() or User.objects.filter(username=login_input).first()

        if user:
            user = authenticate(request, username=user.username, password=password)

        if user is not None:
            if user.is_active:
                login(request, user)
                token, created = Token.objects.get_or_create(user=user)
                if created:
                    token.delete()
                    token = Token.objects.create(user=user)

                response_data = {
                    'accessToken': token.key,
                    'username': user.username,
                    'role': getattr(user, 'role', None),
                    'passwordChanged': getattr(user, 'password_changed', None),
                    'uid': getattr(user, 'uid', None)
                }
                
                return Response(response_data)
            else:
                return Response({'message': 'User is inactive'}, status=status.HTTP_403_FORBIDDEN)
        else:
            return Response({'message': 'Invalid username or password'}, status=status.HTTP_401_UNAUTHORIZED)





class PasswordChangeView(APIView):
    """
    Allows an authenticated user to change their password.
    """
    permission_classes = [IsAuthenticated]
    def post(self, request):
        user = request.user
        new_password = request.data.get('password')
        
        if user and new_password:
            user.set_password(new_password)
            user.password_changed = True
            user.save()
            return Response({'message': 'Password changed successfully'}, status=status.HTTP_200_OK)
        return Response({'error': 'Invalid data'}, status=status.HTTP_400_BAD_REQUEST)

class CheckPasswordChanged(APIView):
    """
    Check if the user's password has been changed.
    """
    permission_classes = [IsAuthenticated]
    def post(self, request, *args, **kwargs):
        token_key = request.headers.get('Authorization').split(' ')[1]
        
        try:
            token = Token.objects.get(key=token_key)
            user = token.user
        except Token.DoesNotExist:
            return Response({'error': 'Invalid token'}, status=status.HTTP_400_BAD_REQUEST)
        

        return Response({'passwordChanged': user.password_changed, 'uid': user.uid}, status=status.HTTP_200_OK)

class UserLogoutView(APIView):
    """
    User logout view that invalidates the token.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        token =  Token.objects.get(key=request.auth.key)
        token.delete()
        return Response({'detail': 'Successfully logged out.'})
    


class VerifyTokenView(APIView):

    permission_classes = [IsAuthenticated]
    def get(self, request):
        try:
            token_key = request.auth.key
            token = Token.objects.get(key=token_key)
            return Response({'message': 'Token is valid'}, status=200)
        except Token.DoesNotExist:
            raise AuthenticationFailed('Invalid token.')


class UserListView(APIView):
    """
    List users with LimitOffsetPagination.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        id_company = request.query_params.get('uid')

        if user and user.is_superuser and not id_company:
            users = User.objects.all().order_by('first_name')
        elif user and user.is_admin and not id_company:
            users = User.objects.exclude(is_superuser=True).order_by('first_name')
        elif user and id_company:
            users = User.objects.filter(companies_id=id_company).order_by('first_name')
        else:
            users = User.objects.none()

        paginator = LimitOffsetPagination()
        paginated_users = paginator.paginate_queryset(users, request)

        serializer = UserSerializer(paginated_users, many=True)
        return paginator.get_paginated_response(serializer.data)


class UserDeleteView(DestroyAPIView):
    """
    Mark a user as inactive (soft delete).
    """
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        uid = self.kwargs.get('uid')
        return get_object_or_404(User, uid=uid)
    
    def delete(self, request, *args, **kwargs):
        try:
            user = self.get_object()
            user.is_active = False
            user.save()
            return Response({"message": "User marked as inactive."}, status=status.HTTP_200_OK)
        except User.DoesNotExist:
            return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)
        
class UserRestoreView(DestroyAPIView):
    """
    Restore a previously inactive user.
    """
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        uid = self.kwargs.get('uid')
        return get_object_or_404(User, uid=uid)
    
    def delete(self, request, *args, **kwargs):
        try:
            user = self.get_object()
            user.is_active = True
            user.save()
            return Response({"message": "User marked as active."}, status=status.HTTP_200_OK)
        except Company.DoesNotExist:
            return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)
        

class UserUpdateView(UpdateAPIView):
    """
    Update user details.
    """
    permission_classes = [IsAuthenticated]
    queryset = User.objects.all()
    serializer_class = UserUpdateSerializer


    def get_object(self):
        uid = self.kwargs.get('uid')
        return User.objects.get(uid=uid)

    def put(self, request, *args, **kwargs):
        user = self.get_object()
        companies_id = request.data.get('companies')
        if companies_id:
            try:
                company = Company.objects.get(uid=companies_id)
            except Company.DoesNotExist:
                return Response({'errors': 'Company not found'}, status=status.HTTP_400_BAD_REQUEST)
            user.companies = company

        serializer = self.get_serializer(user, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        
        return Response({'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
    
    
    def post(self, request, *args, **kwargs):
        user = self.get_object()
        serializer = self.get_serializer(user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response({'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

class CreateRandomUserView(APIView):
    """
    View to create a random user and return the user data.
    """
    def post(self, request, *args, **kwargs):
        # Générer des données utilisateur aléatoires
        username = fake.user_name()
        password = fake.password()
        email = ""

        # Créer l'utilisateur
        user = User.objects.create_user(
            username=f'test.{username}',
            default_password=password,
            password=password,
            email=email,
            is_active=True,
            password_changed=False
        )

        # Sérialiser les données de l'utilisateur
        serializer = UserSerializer(user)
        
        # Envoyer les informations de l'utilisateur au frontend
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    

class CheckEmailExistsAPIView(APIView):
    """
    Check if an email is already registered.
    """
    permission_classes = [IsAuthenticated]
    def get(self, request, *args, **kwargs):
        email = request.query_params.get('email')
        if not email:
            return Response({"detail": "EMAIL parameter is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            user = User.objects.get(email=email)
            return Response({"exists": True, "user": UserSerializer(user).data}, status=status.HTTP_200_OK)
        except User.DoesNotExist:
            return Response({"exists": False}, status=status.HTTP_200_OK)
        

class CreateUserView(APIView):
    """
    View to create a user and return the user data.
    """
    permission_classes = [IsAuthenticated]
    def post(self, request, *args, **kwargs):
        first_name = request.data.get("first_name")
        last_name = request.data.get("last_name")
        email = request.data.get("email")
        entreprise_id = request.data.get("entreprise_id")
        status_user = request.data.get("status")

        if User.objects.filter(email=email).exists():
            return Response(
                {"error": "L'email est déjà utilisé."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            entreprise = Company.objects.get(uid=entreprise_id)
        except Company.DoesNotExist:
            return Response(
                {"error": "Entreprise non trouvée."},
                status=status.HTTP_400_BAD_REQUEST
            )

        user = User.objects.create_user(
            username=f"{first_name.lower()}.{last_name.lower()}",
            first_name=first_name,
            last_name=last_name,
            email=email,
            is_active=status_user
        )
        user.companies = entreprise 
        # Sérialiser les données de l'utilisateur
        serializer = UserSerializer(user)

        # Retourner les données de l'utilisateur créé
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    

class UserBySlug(APIView):
    """
    Retrieve a user by slug.    """
    def get(self, request, slug):
        user = get_object_or_404(User, slug=slug)
        serializer = UserByEmailorSlugSerializer(user)  # Sérialiser les données de l'utilisateur
        return Response(serializer.data, status=status.HTTP_200_OK)
    


class UpdateDefaultPassword(APIView):
    """
    Update a user's password to a new one.
    """
    def post(self, request, *args, **kwargs):
        email = request.data.get('username')
        password = request.data.get('password')

        if not email or not password:
            return Response(
                {"error": "Username and password are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response(
                {"error": "User not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        user.password = make_password(password)
        user.password_changed = True
        user.save()

        return Response(
            {"message": "Password updated successfully."},
            status=status.HTTP_200_OK
        )
    
class UserRole(APIView):
    """
    Retrieve a user role, including checking if the user is a superuser.
    """
    permission_classes = [IsAuthenticated]
    def get(self, request, slug):
        user = get_object_or_404(User)

        # Check if the user is a superuser
        user_role = {
            'is_superuser': user.is_superuser,  # True if user is a superuser, False otherwise
            'username': user.username,
            'email': user.email
        }

        return Response(user_role, status=status.HTTP_200_OK)


class UserInformationView(APIView):
    """
    Retrieve the information of the currently authenticated user.
    """
    def get(self, request):
        user = request.user  # Get the currently authenticated user
        token = Token.objects.get(user=user)
        serializer = UserInformationRoleSerializer(user)
        return Response(serializer.data, status=status.HTTP_200_OK)
    

class UserFmapInformationView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        admin_user = User.objects.filter(is_admin=True).first()
        serializer = UserInformationRoleSerializer(admin_user)
        return Response(serializer.data, status=status.HTTP_200_OK)
    

#à COrrigé
class UpdateTotalDeviceFmapView(APIView):
    permission_classes = [IsAuthenticated]

    def put(self, request):
        total_device = request.data.get("total_device")
        
        if total_device is None:
            return Response({"error": "total_device missing"}, status=400)

        admin_users = User.objects.filter(is_admin=True)
        if not admin_users.exists():
            return Response({"error": "No admin users found"}, status=404)

        for user in admin_users:
            user.total_device = total_device
            user.save()

        return Response({
            "success": True,
            "total_device": total_device,
            "updated_admins": admin_users.count()
        }, status=200)


class EditUserProfileWithPassword(APIView):
    """
    Update user details and password.
    """
    permission_classes = [IsAuthenticated]

    def get_object(self):
        uid = self.kwargs.get('uid')
        return User.objects.get(uid=uid)

    def put(self, request, *args, **kwargs):
        user = self.get_object()
        request.data["password"] = request.data.get('newPassword')

        update_password = request.data.get('update_password')

        # Check if the email exists
        new_email = request.data.get('email')
        if new_email and new_email != user.email:
            if User.objects.filter(email=new_email).exclude(uid=user.uid).exists():
                return Response({'errors': 'L\'email est déjà utilisé.'}, status=status.HTTP_400_BAD_REQUEST)

        if update_password:
            current_password = request.data.get('currentPassword')

            if not user.check_password(current_password):
                return Response({'errors': 'Mot de passe actuel incorrect.'}, status=status.HTTP_400_BAD_REQUEST)
            
            serializer = UserUpdateProfileWithPasswordSerializer(user, data=request.data, context={'request': request})
        else :
            serializer = UserUpdateProfileWithOutPasswordSerializer(user, data=request.data, context={'request': request})

        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)

        return Response({'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
    

class UserForgotPassword(APIView):
    def post(self, request, *args, **kwargs):
        email = request.data.get("email")
        if not email:
            return Response({"msg": "L'email est requis."}, status=status.HTTP_400_BAD_REQUEST)

        user = User.objects.filter(email=email, is_active=True).first()
        if not user:
            return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)

        slug = generate_unique_slug()
        user.slug = slug
        user.password_changed = False
        user.set_password(generate_unique_slug(9))
        user.save()

        return self._send_mail_reset_pass(email, slug)


    def _send_mail_reset_pass(self, email, slug):
        required_env_vars = ["URL_PROJECT", "EMAIL_HOST", "EMAIL_PORT", "EMAIL_HOST_USER", "EMAIL_HOST_PASSWORD"]
        env_values = {var: os.getenv(var) for var in required_env_vars}

        if not all(env_values.values()):
            return Response(
                {"msg": "Certains paramètres d'email sont manquants dans les variables d'environnement."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        language = translation.get_language().split("-")[0]
        subject = {"fr": "Mot de passe oublié", "en": "Forgot password"}.get(language, "Mot de passe oublié")

        template_path = f"templates/{language}/forgot_password.html"
        email_content = UserCreateSerializer._read_email_template(
            template_path, link=f"{env_values['URL_PROJECT']}/auth/login/{slug}"
        )

        msg = EmailMessage()
        msg["From"] = env_values["EMAIL_HOST_USER"]
        msg["To"] = email
        msg["Date"] = formatdate(localtime=True)
        msg["Subject"] = subject
        msg.set_content(email_content, subtype="html")

        try:
            with smtplib.SMTP(env_values["EMAIL_HOST"], int(env_values["EMAIL_PORT"])) as server:
                context = ssl.create_default_context()
                server.starttls(context=context)
                server.login(env_values["EMAIL_HOST_USER"], env_values["EMAIL_HOST_PASSWORD"])
                server.send_message(msg)
        except smtplib.SMTPException as e:
            return Response(
                {"msg": f"Impossible d'envoyer l'email : {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response({"msg": "Email envoyé avec succès."}, status=status.HTTP_200_OK)
