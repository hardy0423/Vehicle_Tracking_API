from rest_framework import serializers
from .models import Company, Country
class CountrySerializer(serializers.ModelSerializer):
    class Meta:
        model = Country
        fields = '__all__'

class CompanyWithCountrySerializer(serializers.ModelSerializer):
    country = CountrySerializer()
 
    class Meta:
        model = Company
        fields = ['uid', 'name', 'region','email', 'country', 'adress', 'nbr_device', 'is_actif', 'created_by', 'logo', 'default_company']        

class CompanySerializer(serializers.ModelSerializer):
    country = serializers.PrimaryKeyRelatedField(queryset=Country.objects.all())
 
    class Meta:
        model = Company
        fields = ['uid', 'name', 'region','email', 'country', 'adress', 'nbr_device', 'is_actif', 'created_by', 'logo', 'default_company']

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        add_device_access = self.context.get('add_device_access', False)

        if add_device_access:
            representation['device_access'] = 'Access granted'

        return representation
    
    def create(self, validated_data):
        return Company.objects.create(**validated_data)
    
    def update(self, instance, validated_data):
        instance.name = validated_data.get('name', instance.name)
        instance.email = validated_data.get('email', instance.email)
        instance.region = validated_data.get('region', instance.region)
        instance.adress = validated_data.get('adress', instance.adress)
        instance.country = validated_data.get('country', instance.country)
        instance.nbr_device = validated_data.get('nbr_device', instance.nbr_device)
        instance.save()
        return instance
