from .base import *
from datetime import timedelta
import os
from dotenv import load_dotenv
load_dotenv()

DEBUG = True
STAGE = 'DEV'
SECRET_KEY = 'vr)rd0$p7@*j4-o5rzr!=l&^bwe$g_f51*dmtj6+!g4hoc%!p%'

URL_PROJECT = os.getenv('URL_PROJECT')
URL_BACKEND = os.getenv('URL_BACKEND')


ALLOWED_HOSTS = ["localhost:4200","localhost:8000", "localhost"]
CORS_ALLOWED_ORIGINS = [
    "http://localhost:4200",
    "http://localhost:8000",
]

EMAIL_HOST = os.getenv('EMAIL_HOST')
EMAIL_PORT = os.getenv('EMAIL_PORT')
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD')



DATABASES = {
   'default': {
       'ENGINE': 'django.contrib.gis.db.backends.postgis',
       'NAME': os.getenv('DB_NAME'),
       'USER': os.getenv('DB_USER'),
       'PASSWORD': os.getenv('DB_PASSWORD'),
       'HOST': os.getenv('DB_HOST'),
       'PORT': os.getenv('DB_PORT'),
   }
}


ELASTICSEARCH_DSL={
   'default': {
       'hosts': 'elastic:9200'
   },
}


SIMPLE_JWT = {
   'ACCESS_TOKEN_LIFETIME': timedelta(days=180),
   'REFRESH_TOKEN_LIFETIME': timedelta(days=190),
}




LOGGING = {
   'version': 1,
   'disable_existing_loggers': False,
   'handlers': {
       'file': {
           'level': 'WARNING',
           'class': 'logging.FileHandler',
           'filename': os.path.join(BASE_DIR, "backend",'debug.log'),
       },
       'console': {'class': 'logging.StreamHandler'}
   },
   'loggers': {
       'django': {
           'handlers': ['file'],
           'level': 'WARNING',
           'propagate': True,
       },
   }
}
