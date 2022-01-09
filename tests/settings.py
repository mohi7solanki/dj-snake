SECRET_KEY = "DO_YOU_KNOW_GODS_OF_DEATH_LOVES_APPLE"

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

USE_TZ = True
