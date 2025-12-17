"""
Tests for batch processing functionality.

Issue #8: Phase 3.1 Performance Optimization
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from models.inference import GenerationConfig, InferenceEngine, InferenceResult


class TestBatchProcessing:
    """Tests for batch processing in InferenceEngine."""

    @pytest.fixture
    def mock_model_loader(self) -> MagicMock:
        """Create a mock model loader."""
        loader = MagicMock()
        loader.model = MagicMock()
        loader.tokenizer = MagicMock()
        loader.tokenizer.pad_token_id = 0
        loader.tokenizer.eos_token_id = 2
        return loader

    @pytest.fixture
    def inference_engine(self, mock_model_loader: MagicMock) -> InferenceEngine:
        """Create an inference engine for testing."""
        with patch("models.inference.get_settings") as mock_settings:
            mock_settings.return_value.agent.min_confidence = 0.7
            return InferenceEngine(mock_model_loader)

    @pytest.mark.asyncio
    async def test_sequential_batch_processing(
        self, inference_engine: InferenceEngine
    ) -> None:
        """Test sequential batch processing."""
        prompts = ["prompt1", "prompt2", "prompt3"]

        # Mock the generate method
        async def mock_generate(prompt: str, *args, **kwargs) -> InferenceResult:
            return InferenceResult(
                generated_text=f"result_{prompt}",
                sql=f"SELECT * FROM {prompt}",
                confidence=0.9,
                inference_time_ms=100.0,
            )

        inference_engine.generate = mock_generate  # type: ignore

        results = await inference_engine.generate_batch(prompts, parallel=False)

        assert len(results) == 3
        assert all(r.sql is not None for r in results)
        assert results[0].sql == "SELECT * FROM prompt1"
        assert results[1].sql == "SELECT * FROM prompt2"
        assert results[2].sql == "SELECT * FROM prompt3"

    @pytest.mark.asyncio
    async def test_parallel_batch_processing(
        self, inference_engine: InferenceEngine
    ) -> None:
        """Test parallel batch processing."""
        prompts = ["prompt1", "prompt2", "prompt3", "prompt4"]

        call_times: list[float] = []

        async def mock_generate(prompt: str, *args, **kwargs) -> InferenceResult:
            call_times.append(asyncio.get_event_loop().time())
            await asyncio.sleep(0.1)  # Simulate processing time
            return InferenceResult(
                generated_text=f"result_{prompt}",
                sql=f"SELECT * FROM {prompt}",
                confidence=0.9,
                inference_time_ms=100.0,
            )

        inference_engine.generate = mock_generate  # type: ignore

        results = await inference_engine.generate_batch(
            prompts, parallel=True, max_concurrent=4
        )

        assert len(results) == 4
        # Results should maintain original order
        assert results[0].sql == "SELECT * FROM prompt1"
        assert results[1].sql == "SELECT * FROM prompt2"
        assert results[2].sql == "SELECT * FROM prompt3"
        assert results[3].sql == "SELECT * FROM prompt4"

    @pytest.mark.asyncio
    async def test_parallel_with_concurrency_limit(
        self, inference_engine: InferenceEngine
    ) -> None:
        """Test parallel processing respects concurrency limit."""
        prompts = ["p1", "p2", "p3", "p4", "p5", "p6"]
        concurrent_count = 0
        max_concurrent_seen = 0

        async def mock_generate(prompt: str, *args, **kwargs) -> InferenceResult:
            nonlocal concurrent_count, max_concurrent_seen
            concurrent_count += 1
            max_concurrent_seen = max(max_concurrent_seen, concurrent_count)
            await asyncio.sleep(0.05)
            concurrent_count -= 1
            return InferenceResult(
                generated_text=prompt,
                sql=f"SELECT * FROM {prompt}",
                confidence=0.9,
            )

        inference_engine.generate = mock_generate  # type: ignore

        results = await inference_engine.generate_batch(
            prompts, parallel=True, max_concurrent=2
        )

        assert len(results) == 6
        # Should never exceed max_concurrent=2
        assert max_concurrent_seen <= 2

    @pytest.mark.asyncio
    async def test_batch_error_handling_sequential(
        self, inference_engine: InferenceEngine
    ) -> None:
        """Test error handling in sequential batch processing."""
        prompts = ["good1", "bad", "good2"]

        async def mock_generate(prompt: str, *args, **kwargs) -> InferenceResult:
            if prompt == "bad":
                raise ValueError("Intentional error")
            return InferenceResult(
                generated_text=prompt,
                sql=f"SELECT * FROM {prompt}",
                confidence=0.9,
            )

        inference_engine.generate = mock_generate  # type: ignore

        results = await inference_engine.generate_batch(prompts, parallel=False)

        assert len(results) == 3
        # Good prompts should succeed
        assert results[0].sql == "SELECT * FROM good1"
        assert results[2].sql == "SELECT * FROM good2"
        # Bad prompt should have error in metadata
        assert results[1].sql is None
        assert "error" in results[1].metadata
        assert "Intentional error" in results[1].metadata["error"]

    @pytest.mark.asyncio
    async def test_batch_error_handling_parallel(
        self, inference_engine: InferenceEngine
    ) -> None:
        """Test error handling in parallel batch processing."""
        prompts = ["good1", "bad", "good2"]

        async def mock_generate(prompt: str, *args, **kwargs) -> InferenceResult:
            if prompt == "bad":
                raise ValueError("Parallel error")
            return InferenceResult(
                generated_text=prompt,
                sql=f"SELECT * FROM {prompt}",
                confidence=0.9,
            )

        inference_engine.generate = mock_generate  # type: ignore

        results = await inference_engine.generate_batch(
            prompts, parallel=True, max_concurrent=4
        )

        assert len(results) == 3
        # Order should be preserved
        assert results[0].sql == "SELECT * FROM good1"
        assert results[1].sql is None
        assert results[1].metadata.get("error") == "Parallel error"
        assert results[2].sql == "SELECT * FROM good2"

    @pytest.mark.asyncio
    async def test_empty_batch(self, inference_engine: InferenceEngine) -> None:
        """Test handling empty batch."""
        results = await inference_engine.generate_batch([], parallel=False)
        assert results == []

        results = await inference_engine.generate_batch([], parallel=True)
        assert results == []

    @pytest.mark.asyncio
    async def test_single_item_batch(self, inference_engine: InferenceEngine) -> None:
        """Test batch with single item."""

        async def mock_generate(prompt: str, *args, **kwargs) -> InferenceResult:
            return InferenceResult(
                generated_text=prompt,
                sql=f"SELECT * FROM {prompt}",
                confidence=0.9,
            )

        inference_engine.generate = mock_generate  # type: ignore

        # Sequential
        results = await inference_engine.generate_batch(["single"], parallel=False)
        assert len(results) == 1
        assert results[0].sql == "SELECT * FROM single"

        # Parallel
        results = await inference_engine.generate_batch(["single"], parallel=True)
        assert len(results) == 1
        assert results[0].sql == "SELECT * FROM single"

    @pytest.mark.asyncio
    async def test_batch_with_custom_config(
        self, inference_engine: InferenceEngine
    ) -> None:
        """Test batch processing with custom generation config."""
        prompts = ["test1", "test2"]
        custom_config = GenerationConfig(
            max_new_tokens=256,
            temperature=0.5,
        )

        received_configs: list[GenerationConfig | None] = []

        async def mock_generate(
            prompt: str, config: GenerationConfig | None = None, *args, **kwargs
        ) -> InferenceResult:
            received_configs.append(config)
            return InferenceResult(
                generated_text=prompt,
                sql=f"SELECT * FROM {prompt}",
                confidence=0.9,
            )

        inference_engine.generate = mock_generate  # type: ignore

        await inference_engine.generate_batch(
            prompts, config=custom_config, parallel=False
        )

        assert len(received_configs) == 2
        assert all(c == custom_config for c in received_configs)


class TestGenerationConfig:
    """Tests for GenerationConfig."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = GenerationConfig()
        assert config.max_new_tokens == 512
        assert config.temperature == 0.1
        assert config.do_sample is False
        assert config.num_beams == 1

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        config = GenerationConfig(
            max_new_tokens=256,
            temperature=0.5,
        )
        result = config.to_dict()

        assert result["max_new_tokens"] == 256
        assert result["temperature"] == 0.5
        assert "do_sample" in result
        assert "num_beams" in result

    def test_custom_values(self) -> None:
        """Test custom configuration values."""
        config = GenerationConfig(
            max_new_tokens=1024,
            temperature=0.8,
            top_p=0.9,
            do_sample=True,
            num_beams=4,
        )

        assert config.max_new_tokens == 1024
        assert config.temperature == 0.8
        assert config.top_p == 0.9
        assert config.do_sample is True
        assert config.num_beams == 4


class TestInferenceResult:
    """Tests for InferenceResult."""

    def test_result_creation(self) -> None:
        """Test creating an inference result."""
        result = InferenceResult(
            generated_text="Generated output",
            sql="SELECT * FROM users",
            input_tokens=100,
            output_tokens=50,
            inference_time_ms=1500.0,
            confidence=0.92,
        )

        assert result.generated_text == "Generated output"
        assert result.sql == "SELECT * FROM users"
        assert result.input_tokens == 100
        assert result.output_tokens == 50
        assert result.inference_time_ms == 1500.0
        assert result.confidence == 0.92

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        result = InferenceResult(
            generated_text="Test",
            sql="SELECT 1",
            confidence=0.8,
            metadata={"key": "value"},
        )
        data = result.to_dict()

        assert data["generated_text"] == "Test"
        assert data["sql"] == "SELECT 1"
        assert data["confidence"] == 0.8
        assert data["metadata"] == {"key": "value"}

    def test_default_values(self) -> None:
        """Test default values."""
        result = InferenceResult(generated_text="Test")

        assert result.sql is None
        assert result.input_tokens == 0
        assert result.output_tokens == 0
        assert result.confidence == 0.0
        assert result.metadata == {}
