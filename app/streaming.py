"""
Response streaming for large query results.

Issue #8: Phase 3.1 Performance Optimization

This module provides:
- Server-Sent Events (SSE) for streaming responses
- Chunked result streaming for large datasets
- Progress updates during query generation
"""

import asyncio
import json
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from enum import Enum
from typing import Any

from sse_starlette.sse import EventSourceResponse

from app.logging_config import get_logger

logger = get_logger(__name__)


class StreamEventType(str, Enum):
    """Types of streaming events."""

    # Query lifecycle events
    QUERY_START = "query_start"
    QUERY_PROGRESS = "query_progress"
    QUERY_COMPLETE = "query_complete"
    QUERY_ERROR = "query_error"

    # Reasoning events (ReAct)
    REASONING_STEP = "reasoning_step"
    REASONING_COMPLETE = "reasoning_complete"

    # SQL events
    SQL_GENERATED = "sql_generated"
    SQL_VALIDATED = "sql_validated"

    # Result events
    RESULT_ROW = "result_row"
    RESULT_BATCH = "result_batch"
    RESULT_COMPLETE = "result_complete"

    # Metadata
    HEARTBEAT = "heartbeat"


@dataclass
class StreamEvent:
    """Represents a streaming event."""

    event_type: StreamEventType
    data: dict[str, Any]
    timestamp: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "event": self.event_type.value,
            "data": self.data,
            "timestamp": self.timestamp or time.time(),
        }

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict())


class QueryStreamer:
    """
    Streams query generation progress and results.

    Provides real-time updates during:
    - Model inference
    - SQL validation
    - Query execution
    - Result streaming

    Usage:
        streamer = QueryStreamer()
        async for event in streamer.stream_query(query, database_id):
            yield event
    """

    def __init__(
        self,
        batch_size: int = 100,
        heartbeat_interval: float = 15.0,
    ) -> None:
        """
        Initialize query streamer.

        Args:
            batch_size: Number of rows per result batch
            heartbeat_interval: Seconds between heartbeat events
        """
        self._batch_size = batch_size
        self._heartbeat_interval = heartbeat_interval

    async def stream_query(
        self,
        natural_query: str,
        database_id: str,
        execute: bool = False,
        show_reasoning: bool = False,
        max_rows: int = 1000,
    ) -> AsyncGenerator[StreamEvent, None]:
        """
        Stream query generation and execution.

        Args:
            natural_query: Natural language query
            database_id: Database identifier
            execute: Whether to execute the SQL
            show_reasoning: Whether to stream reasoning steps
            max_rows: Maximum rows to return

        Yields:
            StreamEvent for each progress update
        """
        start_time = time.time()

        # Emit query start event
        yield StreamEvent(
            event_type=StreamEventType.QUERY_START,
            data={
                "query": natural_query,
                "database_id": database_id,
                "execute": execute,
            },
        )

        try:
            # Import engine
            from app.text2sql_engine import get_text2sql_engine

            engine = await get_text2sql_engine()

            # Progress: Starting generation
            yield StreamEvent(
                event_type=StreamEventType.QUERY_PROGRESS,
                data={"stage": "generating", "progress": 0.1},
            )

            # Generate SQL with streaming reasoning if requested
            if show_reasoning:
                # Stream reasoning steps
                async for reasoning_event in self._stream_reasoning(
                    engine, natural_query, database_id
                ):
                    yield reasoning_event
            else:
                # Generate without streaming reasoning
                result = await engine.generate_sql(
                    natural_query=natural_query,
                    database_id=database_id,
                    execute=False,
                    show_reasoning=False,
                )

                yield StreamEvent(
                    event_type=StreamEventType.SQL_GENERATED,
                    data={
                        "sql": result.sql,
                        "confidence": result.confidence,
                    },
                )

            # Progress: SQL generated
            yield StreamEvent(
                event_type=StreamEventType.QUERY_PROGRESS,
                data={"stage": "generated", "progress": 0.5},
            )

            # Execute if requested
            if execute and result.sql:
                async for exec_event in self._stream_execution(
                    engine, result.sql, database_id, max_rows
                ):
                    yield exec_event

            # Query complete
            yield StreamEvent(
                event_type=StreamEventType.QUERY_COMPLETE,
                data={
                    "total_time_ms": (time.time() - start_time) * 1000,
                    "sql": result.sql,
                    "confidence": result.confidence,
                },
            )

        except Exception as e:
            logger.error("stream_query_error", error=str(e))
            yield StreamEvent(
                event_type=StreamEventType.QUERY_ERROR,
                data={
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )

    async def _stream_reasoning(
        self,
        engine: Any,
        natural_query: str,
        database_id: str,
    ) -> AsyncGenerator[StreamEvent, None]:
        """Stream reasoning steps during generation."""
        # For now, use regular generation and emit steps
        # In future, this could hook into agent's step-by-step execution

        yield StreamEvent(
            event_type=StreamEventType.REASONING_STEP,
            data={
                "step": 1,
                "thought": "Analyzing natural language query...",
            },
        )

        result = await engine.generate_sql(
            natural_query=natural_query,
            database_id=database_id,
            execute=False,
            show_reasoning=True,
        )

        # Emit reasoning trace if available
        if result.reasoning_trace:
            for step in result.reasoning_trace:
                yield StreamEvent(
                    event_type=StreamEventType.REASONING_STEP,
                    data={
                        "step": step.step,
                        "thought": step.thought,
                        "action": step.action,
                        "observation": step.observation,
                    },
                )
                # Small delay between steps for smoother streaming
                await asyncio.sleep(0.05)

        yield StreamEvent(
            event_type=StreamEventType.REASONING_COMPLETE,
            data={
                "total_steps": (
                    len(result.reasoning_trace) if result.reasoning_trace else 0
                )
            },
        )

        yield StreamEvent(
            event_type=StreamEventType.SQL_GENERATED,
            data={
                "sql": result.sql,
                "confidence": result.confidence,
            },
        )

    async def _stream_execution(
        self,
        engine: Any,
        sql: str,
        database_id: str,
        max_rows: int,
    ) -> AsyncGenerator[StreamEvent, None]:
        """Stream query execution results."""
        yield StreamEvent(
            event_type=StreamEventType.QUERY_PROGRESS,
            data={"stage": "executing", "progress": 0.6},
        )

        try:
            # Execute the query
            result = await engine.generate_sql(
                natural_query=sql,  # Pass SQL directly
                database_id=database_id,
                execute=True,
                show_reasoning=False,
                max_rows=max_rows,
            )

            if result.execution_results:
                rows = result.execution_results
                total_rows = len(rows)

                # Stream results in batches
                for batch_start in range(0, total_rows, self._batch_size):
                    batch_end = min(batch_start + self._batch_size, total_rows)
                    batch = rows[batch_start:batch_end]

                    yield StreamEvent(
                        event_type=StreamEventType.RESULT_BATCH,
                        data={
                            "rows": batch,
                            "batch_start": batch_start,
                            "batch_end": batch_end,
                            "total_rows": total_rows,
                        },
                    )

                    # Small delay between batches
                    await asyncio.sleep(0.01)

                yield StreamEvent(
                    event_type=StreamEventType.RESULT_COMPLETE,
                    data={
                        "total_rows": total_rows,
                        "row_count": result.row_count,
                    },
                )
            else:
                yield StreamEvent(
                    event_type=StreamEventType.RESULT_COMPLETE,
                    data={"total_rows": 0, "row_count": 0},
                )

        except Exception as e:
            logger.error("stream_execution_error", error=str(e))
            yield StreamEvent(
                event_type=StreamEventType.QUERY_ERROR,
                data={
                    "error": str(e),
                    "stage": "execution",
                },
            )


async def stream_results(
    results: list[dict[str, Any]],
    batch_size: int = 100,
) -> AsyncGenerator[StreamEvent, None]:
    """
    Stream a list of results in batches.

    Args:
        results: List of result rows
        batch_size: Number of rows per batch

    Yields:
        StreamEvent for each batch
    """
    total_rows = len(results)

    for batch_start in range(0, total_rows, batch_size):
        batch_end = min(batch_start + batch_size, total_rows)
        batch = results[batch_start:batch_end]

        yield StreamEvent(
            event_type=StreamEventType.RESULT_BATCH,
            data={
                "rows": batch,
                "batch_start": batch_start,
                "batch_end": batch_end,
                "total_rows": total_rows,
            },
        )

        # Small delay between batches
        await asyncio.sleep(0.01)

    yield StreamEvent(
        event_type=StreamEventType.RESULT_COMPLETE,
        data={"total_rows": total_rows},
    )


def create_sse_response(
    event_generator: AsyncGenerator[StreamEvent, None],
) -> EventSourceResponse:
    """
    Create SSE response from event generator.

    Args:
        event_generator: Async generator yielding StreamEvents

    Returns:
        EventSourceResponse for FastAPI
    """

    async def event_stream() -> AsyncGenerator[dict[str, str], None]:
        async for event in event_generator:
            yield {
                "event": event.event_type.value,
                "data": event.to_json(),
            }

    return EventSourceResponse(event_stream())


async def heartbeat_generator(
    interval: float = 15.0,
) -> AsyncGenerator[StreamEvent, None]:
    """
    Generate heartbeat events to keep connection alive.

    Args:
        interval: Seconds between heartbeats

    Yields:
        Heartbeat StreamEvents
    """
    while True:
        yield StreamEvent(
            event_type=StreamEventType.HEARTBEAT,
            data={"timestamp": time.time()},
        )
        await asyncio.sleep(interval)
