"""StreamHost application package."""


def create_app():
    """Lazily import and instantiate the FastAPI application."""

    from app.main import create_app as _create_app  # local import to avoid eager deps

    return _create_app()


__all__ = ["create_app"]
