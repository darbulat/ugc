"""Application-specific exceptions."""


class UserNotFoundError(RuntimeError):
    """Raised when a user cannot be found."""


class BloggerRegistrationError(ValueError):
    """Raised when blogger registration data is invalid."""


class AdvertiserRegistrationError(ValueError):
    """Raised when advertiser registration data is invalid."""


class OrderCreationError(ValueError):
    """Raised when order creation data is invalid."""


class OrderNotFoundError(OrderCreationError):
    """Raised when an order cannot be found."""


class OrderNotActiveError(OrderCreationError):
    """Raised when an order is not in ACTIVE status."""


class InteractionNotFoundError(ValueError):
    """Raised when an interaction cannot be found."""


class InteractionError(ValueError):
    """Raised when interaction state or action is invalid."""


class ComplaintAlreadyExistsError(ValueError):
    """Raised when user already filed a complaint for the order."""


class ComplaintNotFoundError(ValueError):
    """Raised when a complaint cannot be found."""


class ManagerUserNotFoundError(ValueError):
    """Raised when a Telegram user for manager assignment is not found."""

    def __init__(self, telegram_username: str) -> None:
        self.telegram_username = telegram_username
        super().__init__(f"User with Telegram @{telegram_username} not found")


class ScrapeCreatorsAPIError(RuntimeError):
    """ScrapeCreators API error (e.g. 402 out of credits)."""

    def __init__(
        self,
        message: str,
        status_code: int,
        response_text: str = "",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text


class InstagramUserNotFoundError(RuntimeError):
    """Instagram API error 9010: account deleted or changed."""

    def __init__(self, instagram_user_id: str) -> None:
        self.instagram_user_id = instagram_user_id
        super().__init__(f"No matching Instagram user: {instagram_user_id}")


class RatingAlreadyExistsError(ValueError):
    """Raised when a rating already exists for this blogger+order pair."""


class InvalidRatingScoreError(ValueError):
    """Raised when score is outside the allowed range 1-5."""
