"""
Streaming endpoint E2E tests for Arctic Text2SQL Agent.

These tests verify the Server-Sent Events (SSE) streaming functionality
for query generation and result streaming.
"""

import asyncio
import contextlib
import json

import pytest

from app.streaming import (
    QueryStreamer,
    StreamEvent,
    StreamEventType,
    create_sse_response,
    heartbeat_generator,
    stream_results,
)
from tests.e2e.seed_data import ExpectedValues

# =============================================================================
# StreamEvent Tests
# =============================================================================


@pytest.mark.e2e
@pytest.mark.e2e_streaming
class TestStreamEvent:
    """Tests for StreamEvent creation and serialization."""

    def test_event_creation(self) -> None:
        """Test StreamEvent can be created with all event types."""
        for event_type in StreamEventType:
            event = StreamEvent(
                event_type=event_type,
                data={"test": "data"},
            )
            assert event.event_type == event_type
            assert event.data == {"test": "data"}

    def test_event_to_dict(self) -> None:
        """Test StreamEvent serializes to dict correctly."""
        event = StreamEvent(
            event_type=StreamEventType.QUERY_START,
            data={"query": "test query"},
            timestamp=1234567890.0,
        )

        result = event.to_dict()

        assert result["event"] == "query_start"
        assert result["data"] == {"query": "test query"}
        assert result["timestamp"] == 1234567890.0

    def test_event_to_json(self) -> None:
        """Test StreamEvent serializes to JSON correctly."""
        event = StreamEvent(
            event_type=StreamEventType.SQL_GENERATED,
            data={"sql": "SELECT * FROM users"},
        )

        json_str = event.to_json()
        parsed = json.loads(json_str)

        assert parsed["event"] == "sql_generated"
        assert parsed["data"]["sql"] == "SELECT * FROM users"
        assert "timestamp" in parsed


# =============================================================================
# Stream Results Tests
# =============================================================================


@pytest.mark.e2e
@pytest.mark.e2e_streaming
class TestStreamResults:
    """Tests for result streaming functionality."""

    @pytest.mark.asyncio
    async def test_stream_empty_results(self) -> None:
        """Test streaming empty result set."""
        events: list[StreamEvent] = []

        async for event in stream_results([], batch_size=10):
            events.append(event)

        # Should emit complete event even for empty results
        assert len(events) == 1
        assert events[0].event_type == StreamEventType.RESULT_COMPLETE
        assert events[0].data["total_rows"] == 0

    @pytest.mark.asyncio
    async def test_stream_single_batch(self) -> None:
        """Test streaming results in single batch."""
        results = [{"id": i, "name": f"item_{i}"} for i in range(5)]
        events: list[StreamEvent] = []

        async for event in stream_results(results, batch_size=10):
            events.append(event)

        # One batch + complete event
        assert len(events) == 2

        # First should be batch
        assert events[0].event_type == StreamEventType.RESULT_BATCH
        assert events[0].data["batch_start"] == 0
        assert events[0].data["batch_end"] == 5
        assert len(events[0].data["rows"]) == 5

        # Last should be complete
        assert events[1].event_type == StreamEventType.RESULT_COMPLETE
        assert events[1].data["total_rows"] == 5

    @pytest.mark.asyncio
    async def test_stream_multiple_batches(self) -> None:
        """Test streaming results in multiple batches."""
        results = [{"id": i} for i in range(25)]
        events: list[StreamEvent] = []

        async for event in stream_results(results, batch_size=10):
            events.append(event)

        # 3 batches + complete event
        assert len(events) == 4

        # Verify batch boundaries
        batch_events = [
            e for e in events if e.event_type == StreamEventType.RESULT_BATCH
        ]
        assert len(batch_events) == 3

        assert batch_events[0].data["batch_start"] == 0
        assert batch_events[0].data["batch_end"] == 10

        assert batch_events[1].data["batch_start"] == 10
        assert batch_events[1].data["batch_end"] == 20

        assert batch_events[2].data["batch_start"] == 20
        assert batch_events[2].data["batch_end"] == 25

    @pytest.mark.asyncio
    async def test_stream_preserves_row_data(self) -> None:
        """Test streaming preserves complete row data."""
        original_row = {
            "id": 1,
            "name": "Test Customer",
            "email": "test@example.com",
            "amount": 99.99,
            "nested": {"key": "value"},
        }
        results = [original_row]

        events: list[StreamEvent] = []
        async for event in stream_results(results, batch_size=10):
            events.append(event)

        batch_event = events[0]
        streamed_row = batch_event.data["rows"][0]

        assert streamed_row == original_row


# =============================================================================
# Heartbeat Tests
# =============================================================================


@pytest.mark.e2e
@pytest.mark.e2e_streaming
class TestHeartbeat:
    """Tests for heartbeat generation."""

    @pytest.mark.asyncio
    async def test_heartbeat_generator(self) -> None:
        """Test heartbeat generator produces events at interval."""
        events: list[StreamEvent] = []

        async def collect_heartbeats() -> None:
            count = 0
            async for event in heartbeat_generator(interval=0.1):
                events.append(event)
                count += 1
                if count >= 3:
                    break

        # Run with timeout
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(collect_heartbeats(), timeout=1.0)

        assert len(events) >= 2
        for event in events:
            assert event.event_type == StreamEventType.HEARTBEAT
            assert "timestamp" in event.data


# =============================================================================
# QueryStreamer Tests
# =============================================================================


@pytest.mark.e2e
@pytest.mark.e2e_streaming
class TestQueryStreamer:
    """Tests for QueryStreamer class."""

    def test_streamer_initialization(self) -> None:
        """Test QueryStreamer initializes with correct defaults."""
        streamer = QueryStreamer()
        assert streamer._batch_size == 100
        assert streamer._heartbeat_interval == 15.0

    def test_streamer_custom_config(self) -> None:
        """Test QueryStreamer accepts custom configuration."""
        streamer = QueryStreamer(batch_size=50, heartbeat_interval=5.0)
        assert streamer._batch_size == 50
        assert streamer._heartbeat_interval == 5.0


# =============================================================================
# SSE Response Tests
# =============================================================================


@pytest.mark.e2e
@pytest.mark.e2e_streaming
class TestSSEResponse:
    """Tests for SSE response creation."""

    @pytest.mark.asyncio
    async def test_create_sse_response_structure(self) -> None:
        """Test SSE response has correct structure."""

        async def simple_generator():
            yield StreamEvent(
                event_type=StreamEventType.QUERY_START,
                data={"query": "test"},
            )
            yield StreamEvent(
                event_type=StreamEventType.QUERY_COMPLETE,
                data={"total_time_ms": 100},
            )

        response = create_sse_response(simple_generator())

        # EventSourceResponse should be created
        assert response is not None
        assert hasattr(response, "body_iterator")


# =============================================================================
# Integration Tests with Real Data
# =============================================================================


@pytest.mark.e2e
@pytest.mark.e2e_streaming
class TestStreamingIntegration:
    """Integration tests for streaming with realistic data."""

    @pytest.mark.asyncio
    async def test_stream_customer_results(self) -> None:
        """Test streaming customer-like result data."""
        # Simulate customer query results
        customers = [
            {
                "id": i,
                "name": f"Customer {i}",
                "email": f"customer{i}@example.com",
                "state": ["California", "New York", "Texas"][i % 3],
            }
            for i in range(ExpectedValues.TOTAL_CUSTOMERS)
        ]

        events: list[StreamEvent] = []
        async for event in stream_results(customers, batch_size=5):
            events.append(event)

        # Should have batches + complete
        batch_events = [
            e for e in events if e.event_type == StreamEventType.RESULT_BATCH
        ]
        complete_event = next(
            (e for e in events if e.event_type == StreamEventType.RESULT_COMPLETE),
            None,
        )

        assert len(batch_events) == 2  # 10 customers / 5 batch_size = 2 batches
        assert complete_event is not None
        assert complete_event.data["total_rows"] == ExpectedValues.TOTAL_CUSTOMERS

    @pytest.mark.asyncio
    async def test_stream_order_results(self) -> None:
        """Test streaming order-like result data."""
        # Simulate order query results
        orders = [
            {
                "id": i,
                "customer_id": (i % 10) + 1,
                "amount": float(100 + i * 10),
                "status": ["pending", "completed", "shipped"][i % 3],
            }
            for i in range(ExpectedValues.TOTAL_ORDERS)
        ]

        events: list[StreamEvent] = []
        async for event in stream_results(orders, batch_size=10):
            events.append(event)

        complete_event = next(
            (e for e in events if e.event_type == StreamEventType.RESULT_COMPLETE),
            None,
        )

        assert complete_event is not None
        assert complete_event.data["total_rows"] == ExpectedValues.TOTAL_ORDERS

    @pytest.mark.asyncio
    async def test_stream_aggregation_results(self) -> None:
        """Test streaming aggregation results."""
        # Simulate GROUP BY results
        aggregated = [
            {"status": "completed", "count": 8, "total_amount": 2500.00},
            {"status": "pending", "count": 4, "total_amount": 1200.00},
            {"status": "shipped", "count": 3, "total_amount": 800.00},
        ]

        events: list[StreamEvent] = []
        async for event in stream_results(aggregated, batch_size=10):
            events.append(event)

        # Small result set should be single batch
        assert len(events) == 2  # 1 batch + complete

        batch_event = events[0]
        assert batch_event.event_type == StreamEventType.RESULT_BATCH
        assert len(batch_event.data["rows"]) == 3


# =============================================================================
# Error Scenario Tests
# =============================================================================


@pytest.mark.e2e
@pytest.mark.e2e_streaming
class TestStreamingErrors:
    """Tests for streaming error scenarios."""

    def test_query_error_event(self) -> None:
        """Test query error event structure."""
        event = StreamEvent(
            event_type=StreamEventType.QUERY_ERROR,
            data={
                "error": "Connection timeout",
                "error_type": "DatabaseConnectionError",
                "stage": "execution",
            },
        )

        result = event.to_dict()

        assert result["event"] == "query_error"
        assert result["data"]["error"] == "Connection timeout"
        assert result["data"]["error_type"] == "DatabaseConnectionError"

    def test_all_event_types_serializable(self) -> None:
        """Test all event types can be serialized to JSON."""
        for event_type in StreamEventType:
            event = StreamEvent(
                event_type=event_type,
                data={"test_key": "test_value", "number": 123, "nested": {"a": 1}},
            )

            # Should not raise
            json_str = event.to_json()
            parsed = json.loads(json_str)

            assert parsed["event"] == event_type.value
            assert "data" in parsed
            assert "timestamp" in parsed
