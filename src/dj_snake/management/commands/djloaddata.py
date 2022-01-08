import os
import warnings
from collections import defaultdict

from django.core import serializers
from django.core.management.base import CommandError
from django.core.management.commands import loaddata
from django.db import DatabaseError, IntegrityError, models, router


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
        current = {node for node, deps in todo.items() if len(deps) == 0}

        if not current:
            raise ValueError(f"Cyclic dependency in graph: {todo}")

        for node in current:
            yield node

        # remove current from todo's nodes & dependencies
        todo = {
            node: (dependencies - current) for node, dependencies in
            todo.items() if node not in current
        }


def build_model_dependecy_graph(model_classes):
    """
    Build a dependency graph of models by inspecting model's field references
    with other models
    """
    def _get_relations(model):
        dependant_models = set()
        for field in model._meta.fields:
            # Since OneToOneField is a sublass of ForeignKey
            # we can avoid checking it separately
            if isinstance(field, models.ForeignKey):
                dependant_models.add(field.related_model)
        return dependant_models

    graph = {}

    for model in model_classes:
        dependant_models = _get_relations(model)
        graph[model] = dependant_models
        # make sure all of our dependencies are included in the graph
        for dependant_model in dependant_models:
            graph.setdefault(dependant_model, set())
    return graph


class Command(loaddata.Command):
    help = (
        "Installs the named fixture(s) in the database while setting new primary key "
        "and preserving the relationships among all the objects"
    )

    def load_label(self, fixture_label):
        """Load fixtures files for a given label."""
        old_new_primary_key_map = defaultdict(dict)

        show_progress = self.verbosity >= 3
        for fixture_file, fixture_dir, fixture_name in self.find_fixtures(fixture_label):
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
                    ser_fmt, fixture, using=self.using, ignorenonexistent=self.ignore,
                    handle_forward_references=True,
                )

                model_to_object_mapping = group_objects_by_model(objects)
                graph = build_model_dependecy_graph(model_to_object_mapping.keys())
                topological_sorted_models = tuple(topological_sort(graph))

                for model in topological_sorted_models:
                    if model in model_to_object_mapping:
                        related_fields = [
                            field for field in model._meta.fields
                            if isinstance(field, models.ForeignKey)
                        ]
                        for obj in model_to_object_mapping[model]:
                            objects_in_fixture += 1
                            if (
                                obj.object._meta.app_config in self.excluded_apps
                                or type(obj.object) in self.excluded_models
                            ):
                                continue

                            if router.allow_migrate_model(self.using, obj.object.__class__):
                                loaded_objects_in_fixture += 1
                                self.models.add(obj.object.__class__)
                                old_pk = obj.object.pk
                                # set the primary key as None
                                obj.object.pk = None

                                # set the new primkary of foreignkey/onetoone field references
                                for field in related_fields:
                                    field_old_pk = getattr(obj.object, field.attname)
                                    field_new_pk = old_new_primary_key_map[field.related_model].get(field_old_pk)
                                    setattr(obj.object, field.attname, field_new_pk)

                                try:
                                    obj.save(using=self.using)
                                    if show_progress:
                                        self.stdout.write(
                                            '\rProcessed %i object(s).' % loaded_objects_in_fixture,
                                            ending=''
                                        )
                                # psycopg2 raises ValueError if data contains NULL chars.
                                except (DatabaseError, IntegrityError, ValueError) as e:
                                    e.args = ("Could not load %(app_label)s.%(object_name)s(pk=%(pk)s): %(error_msg)s" % {
                                        'app_label': obj.object._meta.app_label,
                                        'object_name': obj.object._meta.object_name,
                                        'pk': old_pk,
                                        'error_msg': e,
                                    },)
                                    raise
                                old_new_primary_key_map[model][old_pk] = obj.object.pk

                            if obj.deferred_fields:
                                self.objs_with_deferred_fields.append(obj)
                if objects and show_progress:
                    self.stdout.write('')  # add a newline after progress indicator
                self.loaded_object_count += loaded_objects_in_fixture
                self.fixture_object_count += objects_in_fixture
            except Exception as e:
                if not isinstance(e, CommandError):
                    e.args = ("Problem installing fixture '%s': %s" % (fixture_file, e),)
                raise
            finally:
                fixture.close()

            # Warn if the fixture we loaded contains 0 objects.
            if objects_in_fixture == 0:
                warnings.warn(
                    "No fixture data found for '%s'. (File format may be "
                    "invalid.)" % fixture_name,
                    RuntimeWarning
                )
