from django.contrib.gis.db import models 
from django.contrib.auth.models import AbstractUser
import uuid
from companies.models import Company
from django.utils.safestring import mark_safe
from django.utils.crypto import get_random_string

class User(AbstractUser):
    ROLE_CHOICES = (
        ('administrator', 'Administrator'),
        ('staff', 'Staff'),
        ('user', 'User')
    )
    uid = models.UUIDField(primary_key=True, editable=False, default=uuid.uuid4)
    role = models.CharField(max_length=25, choices=ROLE_CHOICES, default='user')
    companies = models.ForeignKey(Company, on_delete=models.SET_NULL, null=True, blank=True, related_name='users')
    default_password = models.CharField(max_length=150, blank=True, default='')
    password_changed = models.BooleanField(default=False)
    slug = models.SlugField(max_length=15, unique=True, blank=True, null=True,help_text=mark_safe("<strong>Identifier of this user </strong>"))
    is_from_ldap = models.BooleanField(default=True, help_text=mark_safe("<strong> The user is from ldap </strong>"))
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='created_users')
    is_admin = models.BooleanField(default=False, null=True)
    

    def __str__(self) -> str:
        return self.username
    
    def company_name(self):
        entreprise = Company.objects.filter(pk=self.uid).first()
        if entreprise:
            return entreprise.name
        return None

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = generate_unique_slug()

        if self.is_superuser and self.is_staff:
            self.is_from_ldap = False

        super(User, self).save(*args, **kwargs)


def generate_unique_slug(length=9):
    """ A function to generate a 9 character slug and see if it has been used and contains naughty words."""
    slug = get_random_string(length)  # create one
    slug_is_wrong = True
    while slug_is_wrong:  # keep checking until we have a valid slug
        slug_is_wrong = False
        other_objs_with_slug = User.objects.filter(slug=slug)
        if len(other_objs_with_slug) > 0:
            # if any other objects have current slug
            slug_is_wrong = True
        if slug_is_wrong:
            # create another slug and check it again
            slug = get_random_string(9)
    return slug