# Python 3.12, Django 6.x — minimal settings for running tests in a library

SECRET_KEY = "test-secret-key"
DEBUG = True

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
]  # Add your app labels here if needed, e.g. ["django_tasks_gcp"]

MIDDLEWARE = []  # Not needed for tests unless your code requires it

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

USE_TZ = True
TIME_ZONE = "UTC"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
