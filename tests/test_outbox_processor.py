"""Tests for outbox processor."""

import asyncio

import pytest
from unittest.mock import AsyncMock, Mock

from ugc_bot.outbox_processor import OutboxProcessor


class TestOutboxProcessor:
    """Test outbox processor."""

    @pytest.mark.asyncio
    async def test_start_stop(self) -> None:
        """Processor starts and stops correctly."""

        outbox_publisher = Mock()
        kafka_publisher = Mock()

        processor = OutboxProcessor(
            outbox_publisher=outbox_publisher,
            kafka_publisher=kafka_publisher,
            poll_interval=0.1,
            max_retries=3,
        )

        # Start processor
        await processor.start()
        assert processor._running

        # Stop processor
        await processor.stop()
        assert not processor._running

    @pytest.mark.asyncio
    async def test_process_once(self) -> None:
        """Process once executes processing."""

        outbox_publisher = Mock()
        outbox_publisher.process_pending_events = AsyncMock()
        kafka_publisher = Mock()

        processor = OutboxProcessor(
            outbox_publisher=outbox_publisher,
            kafka_publisher=kafka_publisher,
            poll_interval=0.1,
            max_retries=3,
        )

        await processor.process_once()

        # Verify processing was called
        outbox_publisher.process_pending_events.assert_called_once_with(
            kafka_publisher, 3
        )

    @pytest.mark.asyncio
    async def test_background_processing(self) -> None:
        """Background processing loop works correctly."""

        outbox_publisher = Mock()
        outbox_publisher.process_pending_events = AsyncMock()
        kafka_publisher = Mock()

        processor = OutboxProcessor(
            outbox_publisher=outbox_publisher,
            kafka_publisher=kafka_publisher,
            poll_interval=0.01,  # Very short interval
            max_retries=3,
        )

        # Start processor
        await processor.start()

        # Wait a bit for processing to happen multiple times
        await asyncio.sleep(0.03)

        # Stop processor
        await processor.stop()

        # Verify processing was called at least once
        assert outbox_publisher.process_pending_events.call_count >= 1

    @pytest.mark.asyncio
    async def test_start_idempotent(self) -> None:
        """Starting processor twice is idempotent."""

        outbox_publisher = Mock()
        kafka_publisher = Mock()

        processor = OutboxProcessor(
            outbox_publisher=outbox_publisher,
            kafka_publisher=kafka_publisher,
            poll_interval=0.1,
            max_retries=3,
        )

        # Start processor twice
        await processor.start()
        assert processor._running
        assert processor._task is not None
        first_task = processor._task

        await processor.start()  # Should not create new task
        assert processor._running
        assert processor._task == first_task  # Same task

        await processor.stop()

    @pytest.mark.asyncio
    async def test_stop_idempotent(self) -> None:
        """Stopping processor twice is idempotent."""

        outbox_publisher = Mock()
        kafka_publisher = Mock()

        processor = OutboxProcessor(
            outbox_publisher=outbox_publisher,
            kafka_publisher=kafka_publisher,
            poll_interval=0.1,
            max_retries=3,
        )

        await processor.start()
        assert processor._running

        # Stop processor twice
        await processor.stop()
        assert not processor._running

        await processor.stop()  # Should not raise error
        assert not processor._running

    @pytest.mark.asyncio
    async def test_process_loop_handles_exceptions(self) -> None:
        """Processing loop handles exceptions gracefully."""

        outbox_publisher = Mock()
        kafka_publisher = Mock()

        # Make process_pending_events raise an exception
        outbox_publisher.process_pending_events.side_effect = Exception("Test error")

        processor = OutboxProcessor(
            outbox_publisher=outbox_publisher,
            kafka_publisher=kafka_publisher,
            poll_interval=0.01,  # Very short interval
            max_retries=3,
        )

        # Start processor
        await processor.start()

        # Wait a bit for processing to attempt
        await asyncio.sleep(0.02)

        # Stop processor
        await processor.stop()

        # Verify processing was attempted (even though it failed)
        assert outbox_publisher.process_pending_events.call_count >= 1
        assert not processor._running


class TestRunProcessor:
    """Test run_processor function."""

    @pytest.mark.asyncio
    async def test_run_processor_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """run_processor successfully starts and runs processor."""

        # Mock config
        mock_config = Mock()
        mock_config.log_level = "INFO"
        mock_config.kafka_enabled = True
        mock_config.kafka_bootstrap_servers = "localhost:9092"
        mock_config.kafka_topic = "test-topic"
        mock_config.database_url = "sqlite://"

        # Mock outbox publisher
        mock_outbox_publisher = Mock()

        # Mock Kafka publisher
        mock_kafka_publisher = Mock()

        # Mock processor with async methods
        mock_processor = Mock(spec=OutboxProcessor)
        mock_processor._running = False
        mock_processor._task = None

        async def mock_start():
            mock_processor._running = True

        async def mock_stop():
            mock_processor._running = False

        mock_processor.start = Mock(side_effect=mock_start)
        mock_processor.stop = Mock(side_effect=mock_stop)

        # Track processor creation
        processor_created = False

        def mock_processor_init(*args, **kwargs):
            nonlocal processor_created
            processor_created = True
            return mock_processor

        # Patch all dependencies
        monkeypatch.setattr("ugc_bot.outbox_processor.load_config", lambda: mock_config)
        monkeypatch.setattr("ugc_bot.outbox_processor.configure_logging", Mock())
        fake_container = Mock()
        fake_container.build_outbox_deps.return_value = (
            mock_outbox_publisher,
            mock_kafka_publisher,
        )
        monkeypatch.setattr(
            "ugc_bot.outbox_processor.Container",
            lambda _: fake_container,
        )
        monkeypatch.setattr(
            "ugc_bot.outbox_processor.OutboxProcessor", mock_processor_init
        )

        # Mock asyncio.sleep to break the infinite loop
        sleep_count = 0
        original_sleep = asyncio.sleep

        async def mock_sleep(delay):
            nonlocal sleep_count
            sleep_count += 1
            if sleep_count > 2:  # Break after a few iterations
                raise KeyboardInterrupt()
            await original_sleep(0.001)

        monkeypatch.setattr("asyncio.sleep", mock_sleep)

        # Import and run
        from ugc_bot.outbox_processor import run_processor

        # Should handle KeyboardInterrupt gracefully
        await run_processor()

        # Verify processor was created and started
        assert processor_created
        mock_processor.start.assert_called_once()
        mock_processor.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_processor_kafka_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """run_processor exits early when Kafka is disabled."""

        mock_config = Mock()
        mock_config.log = Mock()
        mock_config.log.log_level = "INFO"
        mock_config.db = Mock()
        mock_config.db.database_url = "sqlite://"

        mock_logger = Mock()

        fake_container = Mock()
        fake_container.build_outbox_deps.return_value = (Mock(), None)

        monkeypatch.setattr("ugc_bot.outbox_processor.load_config", lambda: mock_config)
        monkeypatch.setattr("ugc_bot.outbox_processor.configure_logging", Mock())
        monkeypatch.setattr(
            "ugc_bot.outbox_processor.Container",
            lambda _: fake_container,
        )

        from ugc_bot.outbox_processor import run_processor

        monkeypatch.setattr("ugc_bot.outbox_processor.logger", mock_logger)

        await run_processor()

        mock_logger.error.assert_called_once()
        error_call = mock_logger.error.call_args[0][0]
        assert "Kafka is disabled" in error_call

    @pytest.mark.asyncio
    async def test_run_processor_missing_database_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """run_processor exits early when database URL is missing."""

        mock_config = Mock()
        mock_config.log = Mock()
        mock_config.log.log_level = "INFO"
        mock_config.db = Mock()
        mock_config.db.database_url = ""

        mock_logger = Mock()

        monkeypatch.setattr("ugc_bot.outbox_processor.load_config", lambda: mock_config)
        monkeypatch.setattr("ugc_bot.outbox_processor.configure_logging", Mock())

        from ugc_bot.outbox_processor import run_processor

        monkeypatch.setattr("ugc_bot.outbox_processor.logger", mock_logger)

        await run_processor()

        mock_logger.error.assert_called_once()
        error_call = mock_logger.error.call_args[0][0]
        assert "DATABASE_URL is required" in error_call

    @pytest.mark.asyncio
    async def test_run_processor_handles_keyboard_interrupt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """run_processor handles KeyboardInterrupt gracefully."""

        mock_config = Mock()
        mock_config.log = Mock()
        mock_config.log.log_level = "INFO"
        mock_config.db = Mock()
        mock_config.db.database_url = "sqlite://"

        mock_outbox_publisher = Mock()
        mock_kafka_publisher = Mock()
        mock_logger = Mock()

        mock_processor = Mock(spec=OutboxProcessor)
        mock_processor._running = False
        mock_processor._task = None

        async def mock_start():
            mock_processor._running = True

        async def mock_stop():
            mock_processor._running = False

        mock_processor.start = Mock(side_effect=mock_start)
        mock_processor.stop = Mock(side_effect=mock_stop)

        fake_container = Mock()
        fake_container.build_outbox_deps.return_value = (
            mock_outbox_publisher,
            mock_kafka_publisher,
        )

        monkeypatch.setattr("ugc_bot.outbox_processor.load_config", lambda: mock_config)
        monkeypatch.setattr("ugc_bot.outbox_processor.configure_logging", Mock())
        monkeypatch.setattr(
            "ugc_bot.outbox_processor.Container",
            lambda _: fake_container,
        )
        monkeypatch.setattr(
            "ugc_bot.outbox_processor.OutboxProcessor",
            lambda *args, **kwargs: mock_processor,
        )

        sleep_count = 0
        original_sleep = asyncio.sleep

        async def mock_sleep(delay):
            nonlocal sleep_count
            sleep_count += 1
            if sleep_count == 1:
                raise KeyboardInterrupt()
            await original_sleep(0.001)

        monkeypatch.setattr("asyncio.sleep", mock_sleep)

        from ugc_bot.outbox_processor import run_processor

        monkeypatch.setattr("ugc_bot.outbox_processor.logger", mock_logger)

        await run_processor()

        mock_logger.info.assert_called()
        info_calls = [str(call) for call in mock_logger.info.call_args_list]
        assert any("Shutting down" in str(call) for call in info_calls)

        mock_processor.start.assert_called_once()
        mock_processor.stop.assert_called_once()


class TestMain:
    """Test main function."""

    def test_main_calls_run_processor(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """main function calls run_processor via asyncio.run."""

        run_processor_called = False
        asyncio_run_called = False
        coro_passed = None

        async def mock_run_processor():
            nonlocal run_processor_called
            run_processor_called = True

        def mock_asyncio_run(coro):
            nonlocal asyncio_run_called, coro_passed
            asyncio_run_called = True
            coro_passed = coro
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(coro)
            finally:
                loop.close()

        # Patch run_processor and asyncio.run
        monkeypatch.setattr(
            "ugc_bot.outbox_processor.run_processor", mock_run_processor
        )
        monkeypatch.setattr("asyncio.run", mock_asyncio_run)

        # Import and call main
        from ugc_bot.outbox_processor import main

        main()

        # Verify asyncio.run was called with run_processor coroutine
        assert asyncio_run_called
        assert coro_passed is not None
        # Verify run_processor was called (it's called when creating the coroutine)
        # The coroutine is created when passed to asyncio.run
