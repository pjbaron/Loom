"""Data models for the nested package."""


class BaseModel:
    """Base class for all models."""

    def validate(self) -> bool:
        """Validate the model. Override in subclasses."""
        return True


class User(BaseModel):
    """Represents a user in the system."""

    def __init__(self, name: str, email: str):
        """Initialize a user with name and email."""
        self.name = name
        self.email = email

    def validate(self) -> bool:
        """Validate user has required fields."""
        return bool(self.name and self.email)
