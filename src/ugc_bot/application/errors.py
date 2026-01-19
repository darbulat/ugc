"""Application-specific exceptions."""


class UserNotFoundError(RuntimeError):
    """Raised when a user cannot be found."""


class BloggerRegistrationError(ValueError):
    """Raised when blogger registration data is invalid."""


class AdvertiserRegistrationError(ValueError):
    """Raised when advertiser registration data is invalid."""


class OrderCreationError(ValueError):
    """Raised when order creation data is invalid."""
