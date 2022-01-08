SECRET_KEY = "NOTASECRET"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    },
}

TIME_ZONE = "UTC"

INSTALLED_APPS = [
    "dj_snake",
]
