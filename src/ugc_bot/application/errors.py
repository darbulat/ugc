"""Application-specific exceptions."""


class UserNotFoundError(RuntimeError):
    """Raised when a user cannot be found."""


class BloggerRegistrationError(ValueError):
    """Raised when blogger registration data is invalid."""


class AdvertiserRegistrationError(ValueError):
    """Raised when advertiser registration data is invalid."""


class OrderCreationError(ValueError):
    """Raised when order creation data is invalid."""


class InteractionNotFoundError(ValueError):
    """Raised when an interaction cannot be found."""


class InteractionError(ValueError):
    """Raised when interaction state or action is invalid."""


class ComplaintAlreadyExistsError(ValueError):
    """Raised when user already filed a complaint for the order."""


class ComplaintNotFoundError(ValueError):
    """Raised when a complaint cannot be found."""
