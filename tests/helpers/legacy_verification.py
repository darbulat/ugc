"""Explicit memory transaction fixture for legacy verification."""

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy

from ugc_bot.application.legacy_link_ports import LegacyMemoryTransaction
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryBloggerProfileRepository,
    InMemoryInstagramVerificationRepository,
    InMemoryUserRepository,
)
from ugc_bot.infrastructure.memory_social import InMemorySocialAccountRepository


class MemoryVerificationTransaction(LegacyMemoryTransaction):
    """Own these fixture adapters; all concurrent calls use this TM."""

    def __init__(self, users, profiles, codes=None, social=None):
        if not isinstance(users, InMemoryUserRepository) or not isinstance(
            profiles, InMemoryBloggerProfileRepository
        ):
            raise TypeError("explicit_memory_verification_adapters_required")
        if codes is not None and not isinstance(
            codes, InMemoryInstagramVerificationRepository
        ):
            raise TypeError("explicit_memory_verification_adapters_required")
        if social is not None and not isinstance(
            social, InMemorySocialAccountRepository
        ):
            raise TypeError("explicit_memory_verification_adapters_required")
        self.users, self.profiles, self.codes, self.social = (
            users,
            profiles,
            codes,
            social,
        )
        self._active = False
        self._lock = asyncio.Lock()

    @property
    def active(self):
        return self._active

    def contains(self, repository):
        return any(
            repository is item
            for item in (self.users, self.profiles, self.codes, self.social)
        )

    @asynccontextmanager
    async def transaction(self):
        async with self._lock:
            states = [
                self.users.users,
                self.users.telegram_index,
                self.users.max_index,
                self.profiles.profiles,
            ]
            if self.codes is not None:
                states.append(self.codes.codes)
            if self.social is not None:
                states.append(self.social.accounts)
            before = deepcopy(states)
            histories = (
                self.users.identity_history,
                self.profiles.identity_history,
            )
            history_before = deepcopy(histories)
            self._active = True
            try:
                yield self
            except BaseException:
                for state, saved in zip(states, before, strict=True):
                    state.clear()
                    state.update(saved)
                for history, saved in zip(
                    histories, history_before, strict=True
                ):
                    history._identity_observations[:] = (
                        saved._identity_observations
                    )
                    history._binding_observations[:] = (
                        saved._binding_observations
                    )
                    history._profile_seeds = saved._profile_seeds
                    history._binding_seeds = saved._binding_seeds
                    history._covered_from = saved._covered_from
                    history._registrations.clear()
                    history._registrations.update(saved._registrations)
                raise
            finally:
                self._active = False
