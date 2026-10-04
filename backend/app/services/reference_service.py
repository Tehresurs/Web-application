"""Reference operations shared by API and future matching consumers."""
from app.repositories import subobjects, value_aliases
from app.repositories.directory_errors import DirectoryNotFound


def require_subobject(subobject_id):
    item = subobjects.get_subobject(subobject_id)
    if item is None:
        raise DirectoryNotFound("Подобъект не найден")
    return item


def require_value_alias(alias_id):
    item = value_aliases.get_value_alias(alias_id)
    if item is None:
        raise DirectoryNotFound("Соответствие не найдено")
    return item
