class DirectoryNotFound(ValueError):
    status_code = 404
    """Requested directory entry does not exist."""


class DirectoryConflict(ValueError):
    status_code = 409
    """Mutation conflicts with an existing normalized entry."""
