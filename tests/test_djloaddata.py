import tempfile
from io import StringIO

import pytest
from django.core.management import call_command

from tests.testapp import models


@pytest.mark.django_db
def test_djloaddata_command():
    """Test djloaddata command"""
    author_drake = models.Author.objects.create(name="Drake")
    book = models.Book.objects.create(name="Drake's Book", author=author_drake)
    out = StringIO()
    call_command("dumpdata", stdout=out)

    author_drake.name = "Daft Punk"
    author_drake.save()
    book.name = "Punk's Book"
    book.save()

    with tempfile.NamedTemporaryFile(suffix='.json') as fixture:
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
