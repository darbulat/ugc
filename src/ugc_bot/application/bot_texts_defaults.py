"""Application-layer re-export of DEFAULT_TEXTS.

The canonical source lives in ``bot.texts.defaults`` (4 000+ lines of
UI copy).  This thin module lets *application* services import the dict
without reaching into the presentation layer, keeping the dependency
arrow ``application → domain`` clean.

Bot / scheduler / test code may keep importing from
``ugc_bot.bot.texts.defaults`` directly — that is fine for callers that
already depend on the bot package.
"""

from ugc_bot.bot.texts.defaults import DEFAULT_TEXTS

__all__ = ["DEFAULT_TEXTS"]
