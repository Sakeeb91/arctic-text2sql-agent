"""
Agent model backends for local and remote inference.
"""

import asyncio
from typing import Any, Coroutine, TypeVar

from smolagents.models import ChatMessage, MessageRole, Model, get_clean_message_list
from smolagents.monitoring import TokenUsage

from app.monitoring.model_instrumentation import ModelInstrumentor

T = TypeVar("T")


def _run_coroutine_sync(coro: Coroutine[Any, Any, T]) -> T:
    """Run an async coroutine from sync code paths."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = None

    if loop is None or loop.is_running():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(coro)


def _render_prompt(messages: list[ChatMessage | dict[str, Any]]) -> str:
    """Render agent messages to a plain text prompt."""
    cleaned = get_clean_message_list(messages, flatten_messages_as_text=True)
    rendered: list[str] = []

    for message in cleaned:
        role = message.get("role")
        role_text = role.value if hasattr(role, "value") else str(role)
        content = message.get("content") or ""
        rendered.append(f"{role_text}: {content}")

    return "\n\n".join(rendered)


def _truncate_on_stop_sequences(text: str, stop_sequences: list[str] | None) -> str:
    """Truncate output at the first stop sequence if present."""
    if not stop_sequences:
        return text

    positions = [
        text.find(seq) for seq in stop_sequences if seq and text.find(seq) != -1
    ]
    if not positions:
        return text

    return text[: min(positions)]


class LocalInferenceModel(Model):
    """smolagents Model wrapper for the local Text2SQL inference engine."""

    def __init__(
        self,
        model_loader: Any,
        model_id: str | None,
        instrumentor: ModelInstrumentor,
    ) -> None:
        super().__init__(model_id=model_id, flatten_messages_as_text=True)
        from models.inference import InferenceEngine

        self._model_loader = model_loader
        self._instrumentor = instrumentor
        self._inference_engine = InferenceEngine(model_loader)
        self._last_inference: Any | None = None
        self._confidence_history: list[float] = []

    @property
    def last_confidence(self) -> float:
        if self._last_inference is None:
            return 0.5
        return float(getattr(self._last_inference, "confidence", 0.5))

    def generate(
        self,
        messages: list[ChatMessage | dict],
        stop_sequences: list[str] | None = None,
        response_format: dict[str, str] | None = None,
        tools_to_call_from: list[Any] | None = None,
        **kwargs: Any,
    ) -> ChatMessage:
        if response_format is not None:
            raise ValueError("LocalInferenceModel does not support structured outputs.")

        completion_kwargs = self._prepare_completion_kwargs(
            messages=messages,
            stop_sequences=stop_sequences,
            response_format=response_format,
            tools_to_call_from=tools_to_call_from,
            **kwargs,
        )
        prompt = _render_prompt(completion_kwargs["messages"])

        with self._instrumentor.trace_inference(
            operation="code_agent"
        ) as trace_context:
            result = _run_coroutine_sync(self._generate_async(prompt))
            trace_context["input_tokens"] = getattr(result, "input_tokens", 0)
            trace_context["output_tokens"] = getattr(result, "output_tokens", 0)
            trace_context["confidence"] = getattr(result, "confidence", 0.0)

        self._last_inference = result
        if hasattr(result, "confidence"):
            self._confidence_history.append(float(result.confidence))

        content = _truncate_on_stop_sequences(result.generated_text, stop_sequences)
        token_usage = TokenUsage(
            input_tokens=getattr(result, "input_tokens", 0),
            output_tokens=getattr(result, "output_tokens", 0),
        )

        return ChatMessage(
            role=MessageRole.ASSISTANT,
            content=content,
            raw=getattr(result, "raw_output", None),
            token_usage=token_usage,
        )

    async def _generate_async(self, prompt: str) -> Any:
        if not self._model_loader.is_loaded:
            await self._model_loader.load()
        return await self._inference_engine.generate(prompt, extract_sql=False)
