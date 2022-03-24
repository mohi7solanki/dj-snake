from django.db import models


class Base(models.Model):
    name = models.CharField(max_length=64, unique=True)

    class Meta:
        abstract = True

    def __str__(self):
        return self.name


class Author(Base):
    favourite_publisher = models.ForeignKey(
        "testapp.Publisher", on_delete=models.CASCADE, null=True
    )


class Book(Base):
    author = models.ForeignKey(Author, on_delete=models.CASCADE)


class Publisher(Base):
    favourite_book = models.ForeignKey(Book, on_delete=models.CASCADE)


class Person(Base):
    friend = models.ForeignKey("self", null=True, on_delete=models.CASCADE)
