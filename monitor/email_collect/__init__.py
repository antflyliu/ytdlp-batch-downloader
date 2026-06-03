"""Email collection and content pipeline boundary."""

__all__ = ["EmailCollectService"]


def __getattr__(name: str):
    if name == "EmailCollectService":
        from .service import EmailCollectService

        return EmailCollectService
    raise AttributeError(name)
