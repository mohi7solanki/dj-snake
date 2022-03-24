import json
import tempfile
from io import StringIO

import pytest
from django.core.management import call_command
from django.db import IntegrityError, transaction

from tests.testapp import models


@pytest.mark.django_db
def test_djloaddata_command_acyclic():
    """Test djloaddata command with data containing no cyclic relationships"""
    author_drake = models.Author.objects.create(name="Drake")
    book = models.Book.objects.create(name="Drake's Book", author=author_drake)
    out = StringIO()
    call_command("dumpdata", stdout=out)

    author_drake.name = "Daft Punk"
    author_drake.save()
    book.name = "Punk's Book"
    book.save()

    with tempfile.NamedTemporaryFile(suffix=".json") as fixture:
        fixture.write(out.getvalue().encode("utf-8"))
        fixture.seek(0)
        call_command("djloaddata", fixture.name)

    # Check new objects are being created
    assert models.Author.objects.count() == 2
    assert models.Book.objects.count() == 2

    # Check if the relationship between the author and the book
    # is preserved
    punk, drake = models.Author.objects.order_by("pk")
    punk_book, drake_book = models.Book.objects.order_by("pk")
    assert punk_book.author == punk
    assert drake_book.author == drake


@pytest.mark.django_db
def test_djloaddata_command_cyclic():
    """Test djloaddata command with data containing cyclic relationships"""
    author_karma = models.Author.objects.create(name="karma")
    karma_book = models.Book.objects.create(name="karma's Book", author=author_karma)
    kalamkaar = models.Publisher.objects.create(
        name="Kalamkaar", favourite_book=karma_book
    )
    author_karma.favourite_publisher = kalamkaar
    author_karma.save()
    # create a person, ensure this doesn't get overidden
    models.Person.objects.create(name="First person")
    fixture_data = [
        {
            "model": "testapp.author",
            "pk": 1,
            "fields": {"name": "KR$NA", "favourite_publisher": 1},
        },
        {
            "model": "testapp.book",
            "pk": 1,
            "fields": {"name": "KR$NA's Book", "author": 1},
        },
        {
            "model": "testapp.publisher",
            "pk": 1,
            "fields": {"name": "Kalamkaar Youtube", "favourite_book": 1},
        },
        {
            "model": "testapp.person",
            "pk": 1,
            "fields": {"name": "Second person", "friend": 2},
        },
        {
            "model": "testapp.person",
            "pk": 2,
            "fields": {"name": "Third person", "friend": 1},
        },
    ]

    with tempfile.NamedTemporaryFile(suffix=".json") as fixture:
        fixture.write(json.dumps(fixture_data).encode("utf-8"))
        fixture.seek(0)
        call_command("djloaddata", fixture.name)

    karma_book.refresh_from_db()
    assert karma_book.author == author_karma
    kalamkaar.refresh_from_db()
    assert kalamkaar.favourite_book == karma_book
    author_karma.refresh_from_db()
    assert author_karma.favourite_publisher == kalamkaar

    author_krsna = models.Author.objects.get(name="KR$NA")
    book_krsna = models.Book.objects.get(name="KR$NA's Book")
    kalamkaar_youtube = models.Publisher.objects.get(name="Kalamkaar Youtube")
    assert book_krsna.author == author_krsna
    assert kalamkaar_youtube.favourite_book == book_krsna
    assert author_krsna.favourite_publisher == kalamkaar_youtube

    assert models.Person.objects.filter(pk=1, name="First person").exists()
    second_person = models.Person.objects.get(name="Second person")
    third_person = models.Person.objects.get(name="Third person")
    assert second_person.friend == third_person
    assert third_person.friend == second_person


@pytest.mark.django_db(transaction=True)
def test_djloaddata_command_ignore_conflicting_arguement():
    fixture_data = [
        {
            "model": "testapp.author",
            "pk": 1,
            "fields": {"name": "KR$NA", "favourite_publisher": 1},
        },
        {
            "model": "testapp.book",
            "pk": 1,
            "fields": {"name": "KR$NA's Book", "author": 1},
        },
        {
            "model": "testapp.publisher",
            "pk": 1,
            "fields": {"name": "Kalamkaar Youtube", "favourite_book": 1},
        },
    ]
    assert models.Author.objects.count() == 0
    with tempfile.NamedTemporaryFile(suffix=".json") as fixture:
        fixture.write(json.dumps(fixture_data).encode("utf-8"))
        fixture.seek(0)
        call_command("djloaddata", fixture.name)
        with pytest.raises(IntegrityError):
            call_command("djloaddata", fixture.name)
    author = models.Author.objects.get(name="KR$NA")
    assert models.Book.objects.get(name="KR$NA's Book").author == author
    fixture_data = [
        {
            "model": "testapp.author",
            "pk": 1,
            "fields": {"name": "KR$NA", "favourite_publisher": 1},
        },
        {
            "model": "testapp.book",
            "pk": 1,
            "fields": {"name": "KR$NA and Karma's Book", "author": 1},
        },
    ]
    with tempfile.NamedTemporaryFile(suffix=".json") as fixture:
        fixture.write(json.dumps(fixture_data).encode("utf-8"))
        fixture.seek(0)
        call_command("djloaddata", fixture.name, ignoreconflicting=True)
    assert models.Book.objects.get(name="KR$NA and Karma's Book").author == author
