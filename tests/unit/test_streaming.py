"""
Tests for streaming functionality.

Issue #8: Phase 3.1 Performance Optimization
"""

import asyncio
import json
import time
from types import SimpleNamespace

import pytest

from app.streaming import (
    QueryStreamer,
    StreamEvent,
    StreamEventType,
    create_sse_response,
    heartbeat_generator,
    stream_results,
)


async def collect_events(generator) -> list[StreamEvent]:
    """Collect all events from an async generator."""
    return [event async for event in generator]


class TestStreamEventType:
    """Tests for StreamEventType enum."""

    def test_event_types_exist(self) -> None:
        """Test that all expected event types exist."""
        assert StreamEventType.QUERY_START.value == "query_start"
        assert StreamEventType.QUERY_PROGRESS.value == "query_progress"
        assert StreamEventType.QUERY_COMPLETE.value == "query_complete"
        assert StreamEventType.QUERY_ERROR.value == "query_error"
        assert StreamEventType.REASONING_STEP.value == "reasoning_step"
        assert StreamEventType.SQL_GENERATED.value == "sql_generated"
        assert StreamEventType.RESULT_BATCH.value == "result_batch"
        assert StreamEventType.RESULT_COMPLETE.value == "result_complete"
        assert StreamEventType.HEARTBEAT.value == "heartbeat"


class TestStreamEvent:
    """Tests for StreamEvent dataclass."""

    def test_event_creation(self) -> None:
        """Test creating a stream event."""
        event = StreamEvent(
            event_type=StreamEventType.QUERY_START,
            data={"query": "test", "database_id": "db1"},
        )

        assert event.event_type == StreamEventType.QUERY_START
        assert event.data["query"] == "test"

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        timestamp = time.time()
        event = StreamEvent(
            event_type=StreamEventType.SQL_GENERATED,
            data={"sql": "SELECT 1"},
            timestamp=timestamp,
        )

        result = event.to_dict()
        assert result["event"] == "sql_generated"
        assert result["data"]["sql"] == "SELECT 1"
        assert result["timestamp"] == timestamp

    def test_to_json(self) -> None:
        """Test conversion to JSON."""
        event = StreamEvent(
            event_type=StreamEventType.QUERY_PROGRESS,
            data={"progress": 0.5},
            timestamp=1234567890.0,
        )

        json_str = event.to_json()
        parsed = json.loads(json_str)

        assert parsed["event"] == "query_progress"
        assert parsed["data"]["progress"] == 0.5
        assert parsed["timestamp"] == 1234567890.0

    def test_auto_timestamp(self) -> None:
        """Test automatic timestamp generation."""
        before = time.time()
        event = StreamEvent(
            event_type=StreamEventType.HEARTBEAT,
            data={},
        )
        after = time.time()

        result = event.to_dict()
        # Add small tolerance for timing precision
        assert before - 0.001 <= result["timestamp"] <= after + 0.001


class TestQueryStreamer:
    """Tests for QueryStreamer class."""

    @pytest.fixture
    def streamer(self) -> QueryStreamer:
        """Create a query streamer for testing."""
        return QueryStreamer(batch_size=10, heartbeat_interval=1.0)

    def test_streamer_initialization(self) -> None:
        """Test streamer initialization."""
        streamer = QueryStreamer(batch_size=50, heartbeat_interval=5.0)
        assert streamer._batch_size == 50
        assert streamer._heartbeat_interval == 5.0

    def test_default_initialization(self) -> None:
        """Test default initialization values."""
        streamer = QueryStreamer()
        assert streamer._batch_size == 100
        assert streamer._heartbeat_interval == 15.0


class TestQueryStreamerExecution:
    """Tests for streaming execution paths."""

    @pytest.mark.asyncio
    async def test_stream_execution_legacy_batches_results(self) -> None:
        """Test legacy execution streams batched results without regeneration."""
        from db.executor import QueryResult

        streamer = QueryStreamer(batch_size=2)
        query_result = QueryResult(
            success=True,
            sql="SELECT 1",
            rows=[{"id": 1}, {"id": 2}, {"id": 3}],
            row_count=3,
        )

        class StubEngine:
            def __init__(self) -> None:
                self.called_with: tuple[str, str, int] | None = None

            async def execute_sql(
                self,
                sql: str,
                database_id: str,
                max_rows: int,
            ) -> QueryResult:
                self.called_with = (sql, database_id, max_rows)
                return query_result

            async def generate_sql(self, *args, **kwargs) -> None:
                raise AssertionError("generate_sql should not be called")

        engine = StubEngine()

        events = await collect_events(
            streamer._stream_execution_legacy(engine, "SELECT 1", "db1", max_rows=5)
        )

        assert engine.called_with == ("SELECT 1", "db1", 5)
        assert events[0].event_type == StreamEventType.QUERY_PROGRESS
        batch_events = [event for event in events if event.event_type == StreamEventType.RESULT_BATCH]
        assert len(batch_events) == 2
        assert events[-1].event_type == StreamEventType.RESULT_COMPLETE

    @pytest.mark.asyncio
    async def test_stream_execution_legacy_emits_error(self) -> None:
        """Test legacy execution surfaces execution failures."""
        from db.executor import QueryResult

        streamer = QueryStreamer(batch_size=2)
        query_result = QueryResult(
            success=False,
            sql="SELECT 1",
            rows=[],
            row_count=0,
            error="Execution failed",
        )

        class StubEngine:
            async def execute_sql(
                self,
                sql: str,
                database_id: str,
                max_rows: int,
            ) -> QueryResult:
                return query_result

        events = await collect_events(
            streamer._stream_execution_legacy(StubEngine(), "SELECT 1", "db1", max_rows=5)
        )

        assert events[-1].event_type == StreamEventType.QUERY_ERROR
        assert all(event.event_type != StreamEventType.RESULT_COMPLETE for event in events)

    @pytest.mark.asyncio
    async def test_stream_execution_legacy_exception(self) -> None:
        """Test legacy execution handles raised exceptions."""
        streamer = QueryStreamer()

        class StubEngine:
            async def execute_sql(self, **kwargs) -> None:
                raise RuntimeError("boom")

        events = await collect_events(
            streamer._stream_execution_legacy(StubEngine(), "SELECT 1", "db1", max_rows=5)
        )

        assert events[-1].event_type == StreamEventType.QUERY_ERROR
        assert events[-1].data["stage"] == "execution"

    @pytest.mark.asyncio
    async def test_stream_query_missing_sql_emits_error(self, monkeypatch) -> None:
        """Test stream_query emits error when SQL generation is empty."""
        streamer = QueryStreamer()

        settings = SimpleNamespace(
            agent=SimpleNamespace(enabled=False, use_legacy_fallback=False)
        )
        monkeypatch.setattr("app.streaming.get_settings", lambda: settings)

        class StubEngine:
            async def generate_sql(self, **kwargs) -> SimpleNamespace:
                return SimpleNamespace(sql="", confidence=0.0, reasoning_trace=[])

            async def execute_sql(self, **kwargs) -> None:
                raise AssertionError("execute_sql should not be called")

        async def fake_get_engine() -> StubEngine:
            return StubEngine()

        monkeypatch.setattr(
            "app.text2sql_engine.get_text2sql_engine",
            fake_get_engine,
        )

        events = await collect_events(
            streamer.stream_query(
                natural_query="Show users",
                database_id="db1",
                execute=True,
            )
        )

        assert events[-1].event_type == StreamEventType.QUERY_ERROR
        assert all(event.event_type != StreamEventType.RESULT_COMPLETE for event in events)

    @pytest.mark.asyncio
    async def test_stream_query_executes_legacy_sql(self, monkeypatch) -> None:
        """Test stream_query executes generated SQL via legacy executor."""
        from db.executor import QueryResult

        streamer = QueryStreamer(batch_size=5)

        settings = SimpleNamespace(
            agent=SimpleNamespace(enabled=False, use_legacy_fallback=False)
        )
        monkeypatch.setattr("app.streaming.get_settings", lambda: settings)

        class StubEngine:
            def __init__(self) -> None:
                self.generate_calls = 0
                self.execute_calls = 0

            async def generate_sql(self, **kwargs) -> SimpleNamespace:
                self.generate_calls += 1
                return SimpleNamespace(
                    sql="SELECT 1",
                    confidence=0.9,
                    reasoning_trace=[],
                )

            async def execute_sql(self, **kwargs) -> QueryResult:
                self.execute_calls += 1
                return QueryResult(
                    success=True,
                    sql="SELECT 1",
                    rows=[{"id": 1}],
                    row_count=1,
                )

        engine = StubEngine()

        async def fake_get_engine() -> StubEngine:
            return engine

        monkeypatch.setattr(
            "app.text2sql_engine.get_text2sql_engine",
            fake_get_engine,
        )

        events = await collect_events(
            streamer.stream_query(
                natural_query="Show users",
                database_id="db1",
                execute=True,
            )
        )

        assert engine.generate_calls == 1
        assert engine.execute_calls == 1
        assert any(event.event_type == StreamEventType.RESULT_COMPLETE for event in events)

    @pytest.mark.asyncio
    async def test_stream_query_skips_execution_when_disabled(self, monkeypatch) -> None:
        """Test stream_query skips execution when execute is False."""
        streamer = QueryStreamer()

        settings = SimpleNamespace(
            agent=SimpleNamespace(enabled=False, use_legacy_fallback=False)
        )
        monkeypatch.setattr("app.streaming.get_settings", lambda: settings)

        class StubEngine:
            def __init__(self) -> None:
                self.generate_calls = 0
                self.execute_calls = 0

            async def generate_sql(self, **kwargs) -> SimpleNamespace:
                self.generate_calls += 1
                return SimpleNamespace(
                    sql="SELECT 1",
                    confidence=0.9,
                    reasoning_trace=[],
                )

            async def execute_sql(self, **kwargs) -> None:
                self.execute_calls += 1
                raise AssertionError("execute_sql should not be called")

        engine = StubEngine()

        async def fake_get_engine() -> StubEngine:
            return engine

        monkeypatch.setattr(
            "app.text2sql_engine.get_text2sql_engine",
            fake_get_engine,
        )

        events = await collect_events(
            streamer.stream_query(
                natural_query="Show users",
                database_id="db1",
                execute=False,
            )
        )

        assert engine.generate_calls == 1
        assert engine.execute_calls == 0
        assert any(event.event_type == StreamEventType.QUERY_COMPLETE for event in events)

    @pytest.mark.asyncio
    async def test_stream_query_forwards_max_rows(self, monkeypatch) -> None:
        """Test stream_query forwards max_rows to execution."""
        from db.executor import QueryResult

        streamer = QueryStreamer()

        settings = SimpleNamespace(
            agent=SimpleNamespace(enabled=False, use_legacy_fallback=False)
        )
        monkeypatch.setattr("app.streaming.get_settings", lambda: settings)

        class StubEngine:
            def __init__(self) -> None:
                self.max_rows = None

            async def generate_sql(self, **kwargs) -> SimpleNamespace:
                return SimpleNamespace(
                    sql="SELECT 1",
                    confidence=0.9,
                    reasoning_trace=[],
                )

            async def execute_sql(self, **kwargs) -> QueryResult:
                self.max_rows = kwargs.get("max_rows")
                return QueryResult(
                    success=True,
                    sql="SELECT 1",
                    rows=[],
                    row_count=0,
                )

        engine = StubEngine()

        async def fake_get_engine() -> StubEngine:
            return engine

        monkeypatch.setattr(
            "app.text2sql_engine.get_text2sql_engine",
            fake_get_engine,
        )

        await collect_events(
            streamer.stream_query(
                natural_query="Show users",
                database_id="db1",
                execute=True,
                max_rows=42,
            )
        )

        assert engine.max_rows == 42

    @pytest.mark.asyncio
    async def test_stream_query_event_order(self, monkeypatch) -> None:
        """Test basic event ordering for stream_query."""
        streamer = QueryStreamer()

        settings = SimpleNamespace(
            agent=SimpleNamespace(enabled=False, use_legacy_fallback=False)
        )
        monkeypatch.setattr("app.streaming.get_settings", lambda: settings)

        class StubEngine:
            async def generate_sql(self, **kwargs) -> SimpleNamespace:
                return SimpleNamespace(
                    sql="SELECT 1",
                    confidence=0.9,
                    reasoning_trace=[],
                )

        async def fake_get_engine() -> StubEngine:
            return StubEngine()

        monkeypatch.setattr(
            "app.text2sql_engine.get_text2sql_engine",
            fake_get_engine,
        )

        events = await collect_events(
            streamer.stream_query(
                natural_query="Show users",
                database_id="db1",
                execute=False,
            )
        )

        assert events[0].event_type == StreamEventType.QUERY_START
        assert events[1].event_type == StreamEventType.QUERY_PROGRESS
        assert any(event.event_type == StreamEventType.SQL_GENERATED for event in events)
        assert events[-1].event_type == StreamEventType.QUERY_COMPLETE

    @pytest.mark.asyncio
    async def test_stream_query_allows_empty_sql_without_execution(
        self,
        monkeypatch,
    ) -> None:
        """Test stream_query completes when SQL is empty and execute is False."""
        streamer = QueryStreamer()

        settings = SimpleNamespace(
            agent=SimpleNamespace(enabled=False, use_legacy_fallback=False)
        )
        monkeypatch.setattr("app.streaming.get_settings", lambda: settings)

        class StubEngine:
            async def generate_sql(self, **kwargs) -> SimpleNamespace:
                return SimpleNamespace(
                    sql="",
                    confidence=0.0,
                    reasoning_trace=[],
                )

        async def fake_get_engine() -> StubEngine:
            return StubEngine()

        monkeypatch.setattr(
            "app.text2sql_engine.get_text2sql_engine",
            fake_get_engine,
        )

        events = await collect_events(
            streamer.stream_query(
                natural_query="Show users",
                database_id="db1",
                execute=False,
            )
        )

        assert events[-1].event_type == StreamEventType.QUERY_COMPLETE


class TestStreamResults:
    """Tests for stream_results function."""

    @pytest.mark.asyncio
    async def test_stream_empty_results(self) -> None:
        """Test streaming empty results."""
        events: list[StreamEvent] = []
        async for event in stream_results([]):
            events.append(event)

        assert len(events) == 1
        assert events[0].event_type == StreamEventType.RESULT_COMPLETE
        assert events[0].data["total_rows"] == 0

    @pytest.mark.asyncio
    async def test_stream_small_results(self) -> None:
        """Test streaming results smaller than batch size."""
        results = [{"id": i, "name": f"item_{i}"} for i in range(5)]
        events: list[StreamEvent] = []

        async for event in stream_results(results, batch_size=100):
            events.append(event)

        # Should have 1 batch + 1 complete event
        assert len(events) == 2
        assert events[0].event_type == StreamEventType.RESULT_BATCH
        assert events[0].data["total_rows"] == 5
        assert len(events[0].data["rows"]) == 5
        assert events[1].event_type == StreamEventType.RESULT_COMPLETE

    @pytest.mark.asyncio
    async def test_stream_large_results(self) -> None:
        """Test streaming results larger than batch size."""
        results = [{"id": i} for i in range(25)]
        events: list[StreamEvent] = []

        async for event in stream_results(results, batch_size=10):
            events.append(event)

        # Should have 3 batches (10, 10, 5) + 1 complete
        assert len(events) == 4

        # Check batch events
        batch_events = [
            e for e in events if e.event_type == StreamEventType.RESULT_BATCH
        ]
        assert len(batch_events) == 3

        # Verify batch boundaries
        assert batch_events[0].data["batch_start"] == 0
        assert batch_events[0].data["batch_end"] == 10
        assert batch_events[1].data["batch_start"] == 10
        assert batch_events[1].data["batch_end"] == 20
        assert batch_events[2].data["batch_start"] == 20
        assert batch_events[2].data["batch_end"] == 25

        # Verify complete event
        complete_event = events[-1]
        assert complete_event.event_type == StreamEventType.RESULT_COMPLETE
        assert complete_event.data["total_rows"] == 25

    @pytest.mark.asyncio
    async def test_stream_exact_batch_size(self) -> None:
        """Test streaming results exactly matching batch size."""
        results = [{"id": i} for i in range(10)]
        events: list[StreamEvent] = []

        async for event in stream_results(results, batch_size=10):
            events.append(event)

        assert len(events) == 2  # 1 batch + 1 complete
        assert events[0].event_type == StreamEventType.RESULT_BATCH
        assert len(events[0].data["rows"]) == 10


class TestHeartbeatGenerator:
    """Tests for heartbeat generator."""

    @pytest.mark.asyncio
    async def test_heartbeat_generation(self) -> None:
        """Test heartbeat event generation."""
        events: list[StreamEvent] = []

        async def collect_heartbeats(count: int) -> None:
            gen = heartbeat_generator(interval=0.1)
            collected = 0
            async for event in gen:
                events.append(event)
                collected += 1
                if collected >= count:
                    break

        await asyncio.wait_for(collect_heartbeats(3), timeout=2.0)

        assert len(events) == 3
        assert all(e.event_type == StreamEventType.HEARTBEAT for e in events)
        assert all("timestamp" in e.data for e in events)

    @pytest.mark.asyncio
    async def test_heartbeat_interval(self) -> None:
        """Test heartbeat interval timing."""
        timestamps: list[float] = []

        async def collect_timestamps() -> None:
            gen = heartbeat_generator(interval=0.1)
            count = 0
            async for event in gen:
                timestamps.append(event.data["timestamp"])
                count += 1
                if count >= 3:
                    break

        await asyncio.wait_for(collect_timestamps(), timeout=2.0)

        assert len(timestamps) == 3
        # Check intervals are approximately correct
        for i in range(1, len(timestamps)):
            interval = timestamps[i] - timestamps[i - 1]
            assert 0.05 <= interval <= 0.2  # Allow some tolerance


class TestCreateSSEResponse:
    """Tests for SSE response creation."""

    @pytest.mark.asyncio
    async def test_create_sse_response(self) -> None:
        """Test creating SSE response from event generator."""

        async def event_gen():
            yield StreamEvent(
                event_type=StreamEventType.QUERY_START,
                data={"query": "test"},
            )
            yield StreamEvent(
                event_type=StreamEventType.QUERY_COMPLETE,
                data={"success": True},
            )

        response = create_sse_response(event_gen())

        # Verify response type
        from sse_starlette.sse import EventSourceResponse

        assert isinstance(response, EventSourceResponse)


class TestStreamEventSerialization:
    """Tests for event serialization edge cases."""

    def test_nested_data_serialization(self) -> None:
        """Test serialization of nested data structures."""
        event = StreamEvent(
            event_type=StreamEventType.RESULT_BATCH,
            data={
                "rows": [
                    {"id": 1, "nested": {"key": "value"}},
                    {"id": 2, "array": [1, 2, 3]},
                ],
                "metadata": {"count": 2},
            },
        )

        json_str = event.to_json()
        parsed = json.loads(json_str)

        assert parsed["data"]["rows"][0]["nested"]["key"] == "value"
        assert parsed["data"]["rows"][1]["array"] == [1, 2, 3]

    def test_special_characters_in_data(self) -> None:
        """Test handling of special characters."""
        event = StreamEvent(
            event_type=StreamEventType.SQL_GENERATED,
            data={
                "sql": "SELECT * FROM users WHERE name = 'O''Brien'",
                "unicode": "测试数据",
            },
        )

        json_str = event.to_json()
        parsed = json.loads(json_str)

        assert "O''Brien" in parsed["data"]["sql"]
        assert parsed["data"]["unicode"] == "测试数据"

    def test_null_values_in_data(self) -> None:
        """Test handling of null values."""
        event = StreamEvent(
            event_type=StreamEventType.QUERY_ERROR,
            data={
                "error": "Test error",
                "stack_trace": None,
            },
        )

        json_str = event.to_json()
        parsed = json.loads(json_str)

        assert parsed["data"]["error"] == "Test error"
        assert parsed["data"]["stack_trace"] is None


class TestStreamingPerformance:
    """Performance-related tests for streaming."""

    @pytest.mark.asyncio
    async def test_large_result_streaming_memory(self) -> None:
        """Test that large results don't consume excessive memory."""
        # Generate large results
        large_results = [{"id": i, "data": "x" * 100} for i in range(1000)]

        batch_count = 0
        async for event in stream_results(large_results, batch_size=100):
            if event.event_type == StreamEventType.RESULT_BATCH:
                batch_count += 1
                # Each batch should only contain 100 items
                assert len(event.data["rows"]) <= 100

        assert batch_count == 10

    @pytest.mark.asyncio
    async def test_streaming_order_preservation(self) -> None:
        """Test that row order is preserved during streaming."""
        results = [{"id": i} for i in range(50)]
        received_ids: list[int] = []

        async for event in stream_results(results, batch_size=7):
            if event.event_type == StreamEventType.RESULT_BATCH:
                for row in event.data["rows"]:
                    received_ids.append(row["id"])

        assert received_ids == list(range(50))
