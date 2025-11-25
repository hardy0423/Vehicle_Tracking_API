from rest_framework import serializers

from companies.serializers import CompanySerializer
from .models import User
import uuid
from django.db import transaction
from companies.models import Company
from django.conf import settings
from email.message import EmailMessage
from email.utils import formatdate
import os
import smtplib, ssl
from django.utils import translation

class UserSerializer(serializers.ModelSerializer):
    companies = CompanySerializer()
    slug = serializers.CharField(read_only=True)
    is_staff = serializers.BooleanField(read_only=True)
    is_superuser = serializers.BooleanField()
    class Meta:
        model = User
        fields = ['uid','username', 'email', 'last_name', 'is_from_ldap','slug','first_name', 'is_active', 'is_staff', 'is_superuser', 'date_joined', 'role', 'password','default_password', 'companies', 'password_changed', 'created_by', 'is_admin']
        extra_kwargs = {'password': {'write_only': True}}



class UserUpdateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False)
    companies = serializers.PrimaryKeyRelatedField(
        queryset=Company.objects.all(), required=False
    )
    class Meta:
        model = User
        fields = ['email', 'first_name', 'last_name', 'is_active', 'is_staff', 'is_superuser', 'companies','password']

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        if password:
            instance.set_password(password)
            instance.password_changed = True
        instance.username = validated_data.get('username', instance.username)
        instance.email = validated_data.get('email', instance.email)
        instance.first_name = validated_data.get('first_name', instance.first_name)
        instance.last_name = validated_data.get('last_name', instance.last_name)
        instance.is_active = validated_data.get('is_active', instance.is_active)
        instance.is_staff = validated_data.get('is_staff', instance.is_staff)
        instance.is_superuser = validated_data.get('is_superuser', instance.is_superuser)
        instance.password_changed = validated_data.get('password_changed', instance.password_changed)
        instance.role = validated_data.get('role', instance.role)
        instance.save()
        return instance
    


class UserCreateSerializer(serializers.ModelSerializer):
    companies = serializers.CharField(write_only=True, allow_null=True, required=False)

    class Meta:
        model = User
        fields = ['email', 'first_name', 'last_name', 'companies', 'is_from_ldap', 'is_admin']

    def create(self, validated_data):
        validated_data['username'] = validated_data['email']
        validated_data['is_from_ldap'] = False
        creator = self.context['request'].user

        return self._perform_create(validated_data, creator)

    def _perform_create(self, validated_data, creator):
        with transaction.atomic():
            is_admin = validated_data.get('is_admin', False)
            user = self._create_user(validated_data, creator)

            try:
                company = self._get_company(validated_data.get('companies'))
                if is_admin:
                    user.is_admin = True
                    user.companies = company
                    user.role="administrator"
                    user.companies
                    user.save()
                    self._send_email_admin(user.email, user.slug)
                else:
                    user.companies = company
                    user.save()
                    self._send_email(user.email,user.slug,company.name)
            except Exception as e:
                raise serializers.ValidationError({
                    "email": [f"Une erreur est survenue lors de l'envoi du mail : {str(e)}"]
                })

        return user

    def _create_user(self, validated_data, creator):
        return User.objects.create_user(
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', ''),
            email=validated_data.get('email'),
            username=validated_data.get('email'),
            created_by=creator
        )

    def _get_company(self, company_id):
        """ Récupère une entreprise en vérifiant son existence. """
        try:
            return Company.objects.get(uid=company_id)
        except Company.DoesNotExist:
            raise serializers.ValidationError({
                "companies": ["L'entreprise spécifiée est introuvable."]
            })
    
    @staticmethod
    def _read_email_template(template_path, **kwargs):
        try:
            with open(template_path, 'r', encoding='utf-8') as file:
                content = file.read()
            
            for key, value in kwargs.items():
                content = content.replace(f"{{{{{key}}}}}", value)
            
            return content
        
        except FileNotFoundError:
            raise Exception(f"Template file not found: {template_path}")
        except Exception as e:
            raise Exception(f"Error reading or processing the template: {str(e)}")


    def _send_email(self, email, slug, company_name):
        """ Send an email to the new user """
        URL_PROJECT = os.getenv('URL_PROJECT')
        EMAIL_HOST = os.getenv('EMAIL_HOST')
        EMAIL_PORT = os.getenv('EMAIL_PORT')
        EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER')
        EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD')

        if not all([URL_PROJECT, EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD]):
            raise ValueError("Certains paramètres d'email sont manquants dans les variables d'environnement.")


        language = translation.get_language().split('-')[0] 

        subject = {
            "fr": f"Votre nouveau compte sur l'entreprise {company_name}",
            "en": f"Your new account on {company_name}",
        }.get(language, f"Votre nouveau compte sur l'entreprise {company_name}")

        template_path = f"templates/{language}/user_email.html"
        email_content = UserCreateSerializer._read_email_template(
            template_path, link=f"{URL_PROJECT}/auth/login/{slug}", company_name=company_name
        )

        try:
            msg = EmailMessage()
            msg['From'] = EMAIL_HOST_USER
            msg['To'] = email
            msg['Subject'] = subject  # Utilisation du sujet dynamique
            msg.set_content(email_content, subtype='html')

            with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as server:
                context = ssl.create_default_context()
                server.starttls(context=context)
                server.login(EMAIL_HOST_USER, EMAIL_HOST_PASSWORD)
                server.sendmail(EMAIL_HOST_USER, email, msg.as_string())

        except Exception as e:
            raise Exception(f"Une erreur est survenue lors de l'envoi du mail: {str(e)}")

    def _send_email_admin(self, email, slug):
        """ Send an email to the new user administrator """
        
        URL_PROJECT = os.getenv('URL_PROJECT')
        EMAIL_HOST = os.getenv('EMAIL_HOST')
        EMAIL_PORT = os.getenv('EMAIL_PORT')
        EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER')
        EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD')

        if not all([URL_PROJECT, EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD]):
            raise ValueError("Certains paramètres d'email sont manquants dans les variables d'environnement.")

        language = translation.get_language().split('-')[0]

        subject = {
            "fr": "Activation de votre compte administrateur",
            "en": "Administrator account activation",
        }.get(language, "Administrator account activation") 

        template_path = f"templates/{language}/admin_email.html"
        email_content = UserCreateSerializer._read_email_template(
            template_path, link=f"{URL_PROJECT}/auth/login/{slug}"
        )

        try:
            msg = EmailMessage()
            msg['From'] = EMAIL_HOST_USER
            msg['To'] = email
            msg['Subject'] = subject 
            msg.set_content(email_content, subtype='html')

            with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as server:
                context = ssl.create_default_context()
                server.starttls(context=context)
                server.login(EMAIL_HOST_USER, EMAIL_HOST_PASSWORD)
                server.sendmail(EMAIL_HOST_USER, email, msg.as_string())

        except Exception as e:
            raise Exception(f"Une erreur est survenue lors de l'envoi du mail : {str(e)}")
        

class UserByEmailorSlugSerializer(serializers.ModelSerializer):
    """ Serializer for getting user by email or slug """
    username = serializers.CharField(read_only=True)
    first_name = serializers.CharField(read_only=True)
    last_name = serializers.CharField(read_only=True)
    email = serializers.CharField(read_only=True)
    is_staff = serializers.BooleanField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    is_from_ldap = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = [
            'uid',
            'is_superuser',
            'username',
            'first_name',
            'last_name',
            'email',
            'is_staff',
            'is_active',
            'slug',
            'is_from_ldap',
            'password_changed'
        ]



class UserInformationRoleSerializer(serializers.ModelSerializer):
    companies = CompanySerializer()
    class Meta:
        model = User
        fields = ['uid','username', 'email', 'last_name','slug','first_name', 'is_active', 'is_staff', 'is_superuser', 'date_joined', 'role', 'password','default_password', 'password_changed', 'created_by', 'is_admin','companies']
        extra_kwargs = {'password': {'write_only': True}}



class UserUpdateProfileWithPasswordSerializer(serializers.ModelSerializer):
    currentPassword = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'currentPassword', 'password']

    def validate_current_password(self, value):
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError("Le mot de passe actuel est incorrect.")
        return value

    def update(self, instance, validated_data):
        password = validated_data.get('password')
        if password:
            instance.set_password(password)
        
        instance.first_name = validated_data.get('first_name', instance.first_name)
        instance.last_name = validated_data.get('last_name', instance.last_name)
        instance.email = validated_data.get('email', instance.email)
        
        instance.save()
        return instance
    

class UserUpdateProfileWithOutPasswordSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email',]
