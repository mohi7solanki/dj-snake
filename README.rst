========================
Dj-Snake
========================

.. image:: https://img.shields.io/github/workflow/status/mohi7solanki/dj-snake/CI/main?style=for-the-badge
   :target: https://github.com/mohi7solanki/dj-snake/actions?workflow=CI

Installing fixtures with django's ``loaddata`` command overrides objects with the same primary key.
While this is not a problem if you are installing the fixtures against a fresh DB with no data but in case you have
existing data then loading the fixture can be problematic as all the existing rows with the same primary key will be updated
with the new data from the fixture(s)
Using ``djloaddata`` to install fixture ensures that no existing rows will be touched and all the objects will only be inserted
while preserving all the relations between model objects.

Note: Currently ``djloaddata`` does not support circular or self-references but it will be added in the upcoming release.

Requirements
============

Python 3.6 to 3.10 supported.

Django 2.2 to 4.0 supported.

----


Installation
============

**First,** install with pip:

.. code-block:: bash

    python -m pip install dj-snake

**Second,** add the app to your ``INSTALLED_APPS`` setting:

.. code-block:: python

    INSTALLED_APPS = [
        ...,
        "dj_snake",
        ...,
    ]

The app adds a new management command named ``djloaddata``.


Usage
=====

.. code-block:: python

    python manage.py djloaddata fixture [fixture ...]
