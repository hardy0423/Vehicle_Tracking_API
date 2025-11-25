# backend/company/views.py
from django.http import Http404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from accounts.models import User
from .permissions import IsStaffOrSuperuser, IsAdminOrSuperuser
from .models import Company, Country
from .serializers import CompanySerializer, CountrySerializer, CompanyWithCountrySerializer
from django.db.models import Sum
from rest_framework.authentication import TokenAuthentication
from rest_framework.pagination import LimitOffsetPagination   
import uuid
from django.core.files.base import ContentFile
import base64
from devices.models import Device
from trackings.notifications.models import Notification
from trackings.notifications.serializers import NotificationSerializer
from django.shortcuts import get_object_or_404

class CountryListCreate(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        countries = Country.objects.all()
        serializer = CountrySerializer(countries, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = CountrySerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class CompanyList(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        user = request.user
        id_company = request.query_params.get('uid')

        if user and id_company:
            companies = Company.objects.filter(uid=id_company)
        elif hasattr(user, 'companies_id') and user.companies_id and (not user.is_admin and not user.is_superuser):
            companies = Company.objects.filter(uid=user.companies_id)
        elif user:
            companies = Company.objects.all().order_by('name')
        else:
            return Response(
                {'error': 'Unauthorized or no associated companies'},
                status=status.HTTP_403_FORBIDDEN
            )

        paginator = LimitOffsetPagination()
        paginated_companies = paginator.paginate_queryset(companies, request)

        serializer = CompanyWithCountrySerializer(paginated_companies, many=True)
        return paginator.get_paginated_response(serializer.data)
    

class CompanyCreate(APIView):
    permission_classes = [IsAdminOrSuperuser]

    def post(self, request):
        self.check_permissions(request)
        data = request.data.copy()
        data['created_by'] = request.user.uid
        serializer = CompanySerializer(data=data)
        
        if serializer.is_valid():
            company = serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)



class CountryDetail(APIView):
    permission_classes = [IsAuthenticated]

    def get_object(self, alpha2_code):
        try:
            return Country.objects.get(alpha2_code=alpha2_code)
        except Country.DoesNotExist:
            raise Http404

    def get(self, request, alpha2_code):
        country = self.get_object(alpha2_code)
        serializer = CountrySerializer(country)
        return Response(serializer.data)

    def put(self, request, alpha2_code):
        country = self.get_object(alpha2_code)
        serializer = CountrySerializer(country, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, alpha2_code):
        country = self.get_object(alpha2_code)
        country.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    
class CompanyDetail(APIView):
    permission_classes = [IsAuthenticated]

    def get_object(self, uid):
        try:
            return Company.objects.get(uid=uid)
        except Company.DoesNotExist:
            raise Http404

    def get(self, request, uid):
        company = self.get_object(uid)
        serializer = CompanySerializer(company)
        return Response(serializer.data)

    def put(self, request, uid):
        user = request.user

        company = self.get_object(uid)

        if user.companies is not None : 
            if user.companies != company :
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        serializer = CompanySerializer(company, data=request.data)

        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, uid):
        self.permission_classes = [IsAdminOrSuperuser]
        self.check_permissions(request) 
        try:
            company = self.get_object(uid)
            company.is_actif = False
            company.nbr_device = 0
            company.delete()
            company.save()

            devices = Device.objects.filter(company_manager=company)
            devices.update(is_actif=False)

            users = User.objects.filter(companies=company)
            users.update(is_active=False)
            Notification.objects.filter(user__in=users).update(read=True)


            return Response({"message": "Company marked as inactive."}, status=status.HTTP_200_OK)
        except Company.DoesNotExist:
            return Response({"error": "Company not found."}, status=status.HTTP_404_NOT_FOUND)


class CompanyRestoreDetail(APIView):
    permission_classes = [IsAuthenticated, IsAdminOrSuperuser]

    def get_object(self, uid):
        try:
            return Company.objects.get(uid=uid)
        except Company.DoesNotExist:
            raise Http404

    def delete(self, request, uid):
        try:
            company = self.get_object(uid)
            company.is_actif = True
            company.save()

            return Response({"message": "Company marked as actvice."}, status=status.HTTP_200_OK)
        except Company.DoesNotExist:
            return Response({"error": "Company not found."}, status=status.HTTP_404_NOT_FOUND)



class CheckEmailExistsAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        email = request.query_params.get('email')
        if not email:
            return Response({"detail": "EMAIL parameter is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            company = Company.objects.get(email=email)
            return Response({"exists": True, "user": CompanySerializer(company).data}, status=status.HTTP_200_OK)
        except Company.DoesNotExist:
            return Response({"exists": False}, status=status.HTTP_200_OK)

class CheckDeviceNumber(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        user = request.user
        number = request.query_params.get('number')
        email_company = request.query_params.get('email')
        try:
            number = int(number)
            if number <= 0:
                return Response(
                    {"valid": False, "message": "The number of devices must be greater than zero."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        except (ValueError, TypeError):
            return Response(
                {"valid": False, "message": "Invalid 'number' parameter."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        company_query = Company.objects.filter(is_actif=True, default_company=False)
        if email_company:
            company_query = company_query.exclude(email=email_company)

        used_devices = company_query.aggregate(total=Sum('nbr_device'))['total'] or 0

        default_company = get_object_or_404(Company, default_company=True)
        total_available_devices = default_company.nbr_device - used_devices

        if number > total_available_devices:
            return Response(
                {
                    "valid": False,
                    "message": "The number of devices exceeds the available limit.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not company_query.exists() and number > default_company.nbr_device:
            return Response(
                {
                    "valid": False,
                    "message": "The number of devices exceeds the maximum allowed by the platform.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {"valid": True, "message": "Device number is valid."},
            status=status.HTTP_200_OK,
        )

class CompanyAddLogo(APIView):
    permission_classes = [IsAuthenticated]

    def get_object(self, uid):
        try:
            return Company.objects.get(uid=uid)
        except Company.DoesNotExist:
            raise Http404

    def post(self, request, *args, **kwargs):
        company_uid = kwargs.get("uid")
        image_logo = request.data.get("image")

        if not image_logo:
            return Response({"error": "Aucune image fournie"}, status=status.HTTP_400_BAD_REQUEST)
        company = self.get_object(company_uid)

        try:
            format, imgstr = image_logo.split(';base64,')
            ext = format.split('/')[-1] 
            file_name = f"company_logo_{uuid.uuid4()}.{ext}"
            company.logo.save(file_name, ContentFile(base64.b64decode(imgstr)), save=True)
            return Response({"message": "Image enregistrée avec succès"}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": f"Erreur lors de l'enregistrement de l'image: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        

class NotificationList(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, uid):
        user = request.user

        if not Company.objects.filter(uid=uid, users=user).exists() and not (user.is_admin or user.is_superuser):
            return Response({'detail': 'Unauthorized access to this company\'s notifications.'}, status=403)

        if user.is_admin or user.is_superuser:
            try:
                company = Company.objects.get(uid=uid)
            except Company.DoesNotExist:
                return Response({'detail': 'Company not found.'}, status=404)

            first_user = User.objects.filter(companies=company).order_by('created_at').first()
            if not first_user:
                return Response({'detail': 'No user found in this company.'}, status=404)

            notifications = Notification.objects.filter(user=first_user)
        else:
            notifications = Notification.objects.filter(user=user)

        paginator = LimitOffsetPagination()
        paginated_notifications = paginator.paginate_queryset(notifications, request)
        serializer = NotificationSerializer(paginated_notifications, many=True)
        return paginator.get_paginated_response(serializer.data)



class UpdateTotalDeviceFmapView(APIView):
    permission_classes = [IsAuthenticated]

    def put(self, request):
        total_device = request.data.get("total_device")

        if total_device is None:
            return Response({"error": "total_device missing"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            total_device = int(total_device)
            if total_device < 0:
                return Response({"error": "total_device must be a positive integer"}, status=status.HTTP_400_BAD_REQUEST)
        except (ValueError, TypeError):
            return Response({"error": "Invalid total_device format"}, status=status.HTTP_400_BAD_REQUEST)

        default_company = get_object_or_404(Company, default_company=True)
        default_company.nbr_device = total_device
        default_company.save()

        return Response({
            "success": True,
            "message": "Total device updated for the default company",
            "company": default_company.name,
            "total_device": total_device
        }, status=status.HTTP_200_OK)