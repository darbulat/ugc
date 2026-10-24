"""Readiness follows the producer's state without a latency assertion."""

import asyncio

import pytest

from tests.postgres_financial.legacy_confirmation_support import (
    finish_tasks,
    wait_for_signal,
)


@pytest.mark.asyncio
async def test_readiness_wait_accepts_signal_after_old_two_second_deadline():
    signal = asyncio.get_running_loop().create_future()
    release = asyncio.Event()

    async def produce():
        await asyncio.sleep(2.1)
        signal.set_result(123)
        await release.wait()

    producer = asyncio.create_task(produce())
    try:
        assert await wait_for_signal(signal, producer) == 123
        assert not producer.done()
        assert not signal.cancelled()
    finally:
        release.set()
        await finish_tasks(producer)


@pytest.mark.asyncio
async def test_readiness_wait_propagates_original_producer_exception():
    signal = asyncio.get_running_loop().create_future()
    error = RuntimeError("actual confirmation error")

    async def produce():
        raise error

    producer = asyncio.create_task(produce())
    try:
        with pytest.raises(RuntimeError) as raised:
            await wait_for_signal(signal, producer)
        assert raised.value is error
        assert not signal.done()
    finally:
        await finish_tasks(producer)


@pytest.mark.asyncio
async def test_readiness_wait_rejects_producer_return_without_signal():
    signal = asyncio.get_running_loop().create_future()

    async def produce():
        return "early result"

    producer = asyncio.create_task(produce())
    try:
        with pytest.raises(AssertionError, match="finished_before_boundary"):
            await wait_for_signal(signal, producer)
        assert not signal.done()
    finally:
        await finish_tasks(producer)


@pytest.mark.asyncio
async def test_readiness_wait_propagates_producer_cancellation():
    signal = asyncio.get_running_loop().create_future()
    producer = asyncio.create_task(asyncio.Event().wait())
    producer.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await wait_for_signal(signal, producer)
        assert not signal.done()
    finally:
        await finish_tasks(producer)


@pytest.mark.asyncio
async def test_readiness_signal_does_not_hide_same_turn_producer_exception():
    signal = asyncio.get_running_loop().create_future()
    error = RuntimeError("confirmation failed after signal")

    async def produce():
        signal.set_result(123)
        raise error

    producer = asyncio.create_task(produce())
    try:
        with pytest.raises(RuntimeError) as raised:
            await wait_for_signal(signal, producer)
        assert raised.value is error
    finally:
        await finish_tasks(producer)


@pytest.mark.asyncio
async def test_readiness_signal_does_not_accept_already_finished_producer():
    signal = asyncio.get_running_loop().create_future()

    async def produce():
        signal.set_result(123)

    producer = asyncio.create_task(produce())
    try:
        with pytest.raises(AssertionError, match="finished_before_boundary"):
            await wait_for_signal(signal, producer)
    finally:
        await finish_tasks(producer)


@pytest.mark.asyncio
async def test_cancelled_readiness_wait_preserves_signal_and_producer():
    signal = asyncio.get_running_loop().create_future()
    producer = asyncio.create_task(asyncio.Event().wait())
    waiter = asyncio.create_task(wait_for_signal(signal, producer))
    try:
        await asyncio.sleep(0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert not signal.done()
        assert not producer.done()
    finally:
        await finish_tasks(waiter, producer)
