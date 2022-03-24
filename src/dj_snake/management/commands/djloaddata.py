import os
import warnings
from collections import defaultdict

from django.core import serializers
from django.core.management.base import CommandError, CommandParser
from django.core.management.commands import loaddata
from django.core.management.utils import parse_apps_and_model_labels
from django.db import (
    DatabaseError, IntegrityError, connections, models, router, transaction
)


def group_objects_by_model(objects):
    """Group list of deserialized objects by object's model class"""
    grouped = defaultdict(list)
    for obj in objects:
        grouped[obj.object._meta.model].append(obj)
    return grouped


def topological_sort(dependency_graph):
    """
    Takes a dependency graph as a dictionary of node => dependencies.
    Yields node in topological order.
    """
    todo = dependency_graph.copy()
    while todo:
        current = {node for node, deps in todo.items() if not deps}

        if not current:
            raise ValueError(f"Cyclic dependency in graph: {todo}")

        yield from current

        # remove current from todo's nodes & dependencies
        todo = {
            node: (dependencies - current)
            for node, dependencies in todo.items()
            if node not in current
        }


def get_related_fields(model):
    """Get OneToMany relations of given model"""
    return [
        field for field in model._meta.fields if isinstance(field, models.ForeignKey)
    ]


def build_model_dependecy_graph(model_classes):
    """
    Build a dependency graph of models by inspecting model's field references
    with other models
    """

    def _get_dependencies(model):
        return {
            field.related_model for field in get_related_fields(model) if not field.null
        }

    graph = {}

    for model in model_classes:
        dependencies = _get_dependencies(model)
        graph[model] = dependencies
        # make sure all of our dependencies are included in the graph
        for dependency in dependencies:
            graph.setdefault(dependency, set())
    return graph


class Command(loaddata.Command):
    help = (
        "Installs the named fixture(s) in the database while setting new primary key "
        "and preserving the relationships among all the objects"
    )

    def add_arguments(self, parser: CommandParser) -> None:
        super().add_arguments(parser)
        parser.add_argument(
            "--ignoreconflicting",
            "-ic",
            action="store_true",
            dest="ignore_conflicting",
            help="Ignore rows that fails with IntegrityError.",
        )

    def handle(self, *fixture_labels, **options):
        self.ignore = options["ignore"]
        self.using = options["database"]
        self.app_label = options["app_label"]
        self.verbosity = options["verbosity"]
        self.excluded_models, self.excluded_apps = parse_apps_and_model_labels(
            options["exclude"]
        )
        self.format = options["format"]
        self.ignore_conflicting = options["ignore_conflicting"]

        with transaction.atomic(using=self.using):
            self.loaddata(fixture_labels)

        # Close the DB connection -- unless we're still in a transaction. This
        # is required as a workaround for an edge case in MySQL: if the same
        # connection is used to create tables, load data, and query, the query
        # can return incorrect results. See Django #7572, MySQL #37735.
        if transaction.get_autocommit(self.using):
            connections[self.using].close()

    def load_label(self, fixture_label: str) -> None:
        """Load fixtures files for a given label."""
        self.old_new_primary_key_map = defaultdict(dict)
        self.obj_with_nullable_fk = set()

        show_progress = self.verbosity >= 3
        for fixture_file, fixture_dir, fixture_name in self.find_fixtures(
            fixture_label
        ):
            _, ser_fmt, cmp_fmt = self.parse_name(os.path.basename(fixture_file))
            open_method, mode = self.compression_formats[cmp_fmt]
            fixture = open_method(fixture_file, mode)
            try:
                self.fixture_count += 1
                objects_in_fixture = 0
                loaded_objects_in_fixture = 0
                if self.verbosity >= 2:
                    self.stdout.write(
                        "Installing %s fixture '%s' from %s."
                        % (ser_fmt, fixture_name, loaddata.humanize(fixture_dir))
                    )

                objects = serializers.deserialize(
                    ser_fmt,
                    fixture,
                    using=self.using,
                    ignorenonexistent=self.ignore,
                    handle_forward_references=True,
                )

                model_to_object_mapping = group_objects_by_model(objects)
                graph = build_model_dependecy_graph(model_to_object_mapping.keys())

                for model in topological_sort(graph):
                    if model not in model_to_object_mapping:
                        continue
                    related_fields = get_related_fields(model)
                    for obj in model_to_object_mapping[model]:
                        objects_in_fixture += 1
                        if self.save_obj(obj, model, related_fields):
                            loaded_objects_in_fixture += 1
                            if show_progress:
                                self.stdout.write(
                                    "\rProcessed %i object(s)."
                                    % loaded_objects_in_fixture,
                                    ending="",
                                )

                for obj in self.obj_with_nullable_fk:
                    model = obj.object._meta.model
                    nullable_related_fields = [
                        field for field in get_related_fields(model) if field.null
                    ]
                    for field in nullable_related_fields:

                        field_old_pk = getattr(obj.object, field.attname)
                        field_new_pk = self.old_new_primary_key_map[
                            field.related_model
                        ].get(field_old_pk)

                        setattr(obj.object, field.attname, field_new_pk)
                        try:
                            obj.save(using=self.using)
                        # psycopg2 raises ValueError if data contains NULL chars.
                        except (DatabaseError, IntegrityError, ValueError) as e:
                            e.args = (
                                "Could not load %(app_label)s.%(object_name)s(pk=%(pk)s): %(error_msg)s"
                                % {
                                    "app_label": obj.object._meta.app_label,
                                    "object_name": obj.object._meta.object_name,
                                    "pk": obj.object.pk,
                                    "error_msg": e,
                                },
                            )
                            raise

                if objects and show_progress:
                    self.stdout.write("")  # add a newline after progress indicator
                self.loaded_object_count += loaded_objects_in_fixture
                self.fixture_object_count += objects_in_fixture
            except Exception as e:
                if not isinstance(e, CommandError):
                    e.args = (
                        "Problem installing fixture '%s': %s" % (fixture_file, e),
                    )
                raise
            finally:
                fixture.close()

            # Warn if the fixture we loaded contains 0 objects.
            if objects_in_fixture == 0:
                warnings.warn(
                    "No fixture data found for '%s'. (File format may be "
                    "invalid.)" % fixture_name,
                    RuntimeWarning,
                )

    def save_obj(self, obj, model, related_fields):
        if (
            obj.object._meta.app_config in self.excluded_apps
            or type(obj.object) in self.excluded_models
        ):
            return False
        saved = False
        if router.allow_migrate_model(self.using, obj.object.__class__):
            saved = True
            self.models.add(obj.object.__class__)
            old_pk = obj.object.pk
            # set the primary key as None
            obj.object.pk = None

            # set the new primary of foreignkey/onetoone field references
            for field in related_fields:
                field_old_pk = getattr(obj.object, field.attname)
                if field_old_pk and field.null:
                    self.obj_with_nullable_fk.add(obj)
                    continue  # avoid setting None value
                field_new_pk = self.old_new_primary_key_map[field.related_model].get(
                    field_old_pk
                )
                setattr(obj.object, field.attname, field_new_pk)

            @transaction.atomic
            def _try_save(obj):
                try:
                    obj.save(using=self.using)
                # psycopg2 raises ValueError if data contains NULL chars.
                except (DatabaseError, IntegrityError, ValueError) as e:
                    if isinstance(e, IntegrityError) and self.ignore_conflicting:
                        # Ensure we save the same old primary key in the
                        # old_new_primary_key_map dictionary
                        obj.object.pk = old_pk
                        return
                    e.args = (
                        "Could not load %(app_label)s.%(object_name)s(pk=%(pk)s): %(error_msg)s"
                        % {
                            "app_label": obj.object._meta.app_label,
                            "object_name": obj.object._meta.object_name,
                            "pk": old_pk,
                            "error_msg": e,
                        },
                    )
                    raise

            _try_save(obj)
            self.old_new_primary_key_map[model][old_pk] = obj.object.pk

        if obj.deferred_fields:
            self.objs_with_deferred_fields.append(obj)
        return saved
