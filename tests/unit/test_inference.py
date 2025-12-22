"""
Unit tests for inference engine module.

These tests verify inference functionality using mocks
to avoid requiring actual model inference.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import torch

from models.inference import (
    GenerationConfig,
    InferenceEngine,
    InferenceResult,
    calculate_confidence,
    extract_sql_from_output,
    get_inference_engine,
)


class TestGenerationConfig:
    """Tests for GenerationConfig dataclass."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = GenerationConfig()

        assert config.max_new_tokens == 512
        assert config.temperature == 0.1
        assert config.top_p == 0.95
        assert config.top_k == 50
        assert config.do_sample is False
        assert config.num_beams == 1
        assert config.repetition_penalty == 1.0
        assert config.length_penalty == 1.0
        assert config.early_stopping is True

    def test_custom_values(self) -> None:
        """Test custom configuration values."""
        config = GenerationConfig(
            max_new_tokens=256,
            temperature=0.7,
            do_sample=True,
        )

        assert config.max_new_tokens == 256
        assert config.temperature == 0.7
        assert config.do_sample is True

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        config = GenerationConfig(max_new_tokens=256)
        result = config.to_dict()

        assert isinstance(result, dict)
        assert result["max_new_tokens"] == 256
        assert "temperature" in result
        assert "top_p" in result


class TestInferenceResult:
    """Tests for InferenceResult dataclass."""

    def test_default_values(self) -> None:
        """Test default result values."""
        result = InferenceResult(generated_text="SELECT * FROM users")

        assert result.generated_text == "SELECT * FROM users"
        assert result.sql is None
        assert result.input_tokens == 0
        assert result.output_tokens == 0
        assert result.inference_time_ms == 0.0
        assert result.confidence == 0.0
        assert result.raw_output == ""
        assert result.metadata == {}

    def test_full_result(self) -> None:
        """Test result with all fields populated."""
        result = InferenceResult(
            generated_text="SELECT * FROM users",
            sql="SELECT * FROM users",
            input_tokens=50,
            output_tokens=10,
            inference_time_ms=150.5,
            confidence=0.95,
            raw_output="SELECT * FROM users",
            metadata={"prompt_type": "arctic"},
        )

        assert result.sql == "SELECT * FROM users"
        assert result.input_tokens == 50
        assert result.confidence == 0.95
        assert result.metadata["prompt_type"] == "arctic"

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        result = InferenceResult(
            generated_text="SELECT * FROM users",
            sql="SELECT * FROM users",
            confidence=0.95,
        )
        data = result.to_dict()

        assert isinstance(data, dict)
        assert data["generated_text"] == "SELECT * FROM users"
        assert data["sql"] == "SELECT * FROM users"
        assert data["confidence"] == 0.95


class TestExtractSqlFromOutput:
    """Tests for extract_sql_from_output function."""

    def test_plain_select(self) -> None:
        """Test extraction of plain SELECT query."""
        text = "SELECT * FROM users"
        result = extract_sql_from_output(text)

        assert result == "SELECT * FROM users"

    def test_select_with_newlines(self) -> None:
        """Test extraction with trailing content."""
        text = "SELECT * FROM users\nWHERE id = 1"
        result = extract_sql_from_output(text)

        assert "SELECT * FROM users" in result
        assert "WHERE id = 1" in result

    def test_markdown_sql_block(self) -> None:
        """Test extraction from markdown SQL block."""
        text = "Here is the query:\n```sql\nSELECT * FROM users\n```"
        result = extract_sql_from_output(text)

        assert result == "SELECT * FROM users"

    def test_generic_code_block(self) -> None:
        """Test extraction from generic code block with SELECT."""
        text = "```\nSELECT id FROM users\n```"
        result = extract_sql_from_output(text)

        assert result == "SELECT id FROM users"

    def test_xml_tags(self) -> None:
        """Test extraction from XML-style tags."""
        text = "<sql>SELECT * FROM users</sql>"
        result = extract_sql_from_output(text)

        assert result == "SELECT * FROM users"

    def test_sql_prefix(self) -> None:
        """Test extraction with SQL: prefix."""
        text = "SQL: SELECT * FROM users\n\nExplanation: This query..."
        result = extract_sql_from_output(text)

        assert result == "SELECT * FROM users"

    def test_with_keyword(self) -> None:
        """Test extraction of WITH (CTE) query."""
        text = "WITH active AS (SELECT * FROM users) SELECT * FROM active"
        result = extract_sql_from_output(text)

        assert "WITH active AS" in result

    def test_insert_query(self) -> None:
        """Test extraction of INSERT query."""
        text = "INSERT INTO users (name) VALUES ('John')"
        result = extract_sql_from_output(text)

        assert result == "INSERT INTO users (name) VALUES ('John')"

    def test_update_query(self) -> None:
        """Test extraction of UPDATE query."""
        text = "UPDATE users SET name = 'John'"
        result = extract_sql_from_output(text)

        assert result == "UPDATE users SET name = 'John'"

    def test_delete_query(self) -> None:
        """Test extraction of DELETE query."""
        text = "DELETE FROM users WHERE id = 1"
        result = extract_sql_from_output(text)

        assert result == "DELETE FROM users WHERE id = 1"

    def test_text_with_select_keyword(self) -> None:
        """Test extraction when text contains SELECT keyword somewhere."""
        text = "The result should be a SELECT query"
        result = extract_sql_from_output(text)

        assert result is not None  # Contains SELECT, so returns something

    def test_no_sql_content(self) -> None:
        """Test when text has no SQL content."""
        text = "This is just plain text with no queries"
        result = extract_sql_from_output(text)

        assert result is None

    def test_whitespace_handling(self) -> None:
        """Test that whitespace is properly stripped."""
        text = "  SELECT * FROM users  "
        result = extract_sql_from_output(text)

        assert result == "SELECT * FROM users"


class TestCalculateConfidence:
    """Tests for calculate_confidence function."""

    def test_empty_scores(self) -> None:
        """Test with no scores."""
        output_ids = torch.tensor([[1, 2, 3]])
        result = calculate_confidence(output_ids, None)

        assert result == 0.5

    def test_empty_score_tuple(self) -> None:
        """Test with empty score tuple."""
        output_ids = torch.tensor([[1, 2, 3]])
        result = calculate_confidence(output_ids, ())

        assert result == 0.5

    def test_with_scores(self) -> None:
        """Test confidence calculation with actual scores."""
        output_ids = torch.tensor([[1, 2, 3, 4]])
        # Create mock scores with high probability for tokens
        score1 = torch.zeros(1, 10)
        score1[0, 2] = 10.0  # High logit for token 2
        score2 = torch.zeros(1, 10)
        score2[0, 3] = 10.0  # High logit for token 3
        scores = (score1, score2)

        result = calculate_confidence(output_ids, scores)

        assert 0.0 <= result <= 1.0

    def test_confidence_bounds(self) -> None:
        """Test that confidence is bounded between 0 and 1."""
        output_ids = torch.tensor([[1, 2]])
        score = torch.ones(1, 10)  # Uniform probabilities
        scores = (score,)

        result = calculate_confidence(output_ids, scores)

        assert 0.0 <= result <= 1.0


class TestInferenceEngine:
    """Tests for InferenceEngine class."""

    @pytest.fixture
    def mock_settings(self) -> MagicMock:
        """Create mock settings."""
        settings = MagicMock()
        settings.agent.min_confidence = 0.7
        settings.cache = MagicMock(enabled=False)
        return settings

    @pytest.fixture
    def mock_model_loader(self) -> MagicMock:
        """Create mock model loader."""
        loader = MagicMock()
        loader.model = MagicMock()
        loader.tokenizer = MagicMock()
        loader.tokenizer.pad_token_id = 0
        loader.tokenizer.eos_token_id = 1
        return loader

    def test_init(self, mock_settings: MagicMock, mock_model_loader: MagicMock) -> None:
        """Test engine initialization."""
        with patch("models.inference.get_settings", return_value=mock_settings):
            engine = InferenceEngine(mock_model_loader)

            assert engine._loader == mock_model_loader
            assert engine._min_confidence == 0.7
            assert isinstance(engine._default_config, GenerationConfig)

    def test_init_with_custom_config(
        self, mock_settings: MagicMock, mock_model_loader: MagicMock
    ) -> None:
        """Test engine initialization with custom config."""
        custom_config = GenerationConfig(max_new_tokens=256)

        with patch("models.inference.get_settings", return_value=mock_settings):
            engine = InferenceEngine(mock_model_loader, custom_config)

            assert engine._default_config.max_new_tokens == 256

    def test_model_property(
        self, mock_settings: MagicMock, mock_model_loader: MagicMock
    ) -> None:
        """Test model property access."""
        with patch("models.inference.get_settings", return_value=mock_settings):
            engine = InferenceEngine(mock_model_loader)

            assert engine.model == mock_model_loader.model

    def test_tokenizer_property(
        self, mock_settings: MagicMock, mock_model_loader: MagicMock
    ) -> None:
        """Test tokenizer property access."""
        with patch("models.inference.get_settings", return_value=mock_settings):
            engine = InferenceEngine(mock_model_loader)

            assert engine.tokenizer == mock_model_loader.tokenizer

    @pytest.mark.asyncio
    async def test_generate_success(
        self, mock_settings: MagicMock, mock_model_loader: MagicMock
    ) -> None:
        """Test successful generation."""
        # Setup mock tokenizer
        mock_model_loader.tokenizer.return_value = {
            "input_ids": torch.tensor([[1, 2, 3]]),
            "attention_mask": torch.tensor([[1, 1, 1]]),
        }
        mock_model_loader.tokenizer.decode.return_value = "SELECT * FROM users"

        # Setup mock model
        mock_output = MagicMock()
        mock_output.sequences = torch.tensor([[1, 2, 3, 4, 5, 6]])
        mock_output.scores = None
        mock_model_loader.model.generate.return_value = mock_output
        mock_model_loader.model.parameters.return_value = iter(
            [torch.nn.Parameter(torch.zeros(1))]
        )

        with patch("models.inference.get_settings", return_value=mock_settings):
            engine = InferenceEngine(mock_model_loader)
            result = await engine.generate("Question: Show all users")

            assert isinstance(result, InferenceResult)
            assert result.generated_text == "SELECT * FROM users"
            assert result.inference_time_ms > 0

    @pytest.mark.asyncio
    async def test_generate_with_sql_extraction(
        self, mock_settings: MagicMock, mock_model_loader: MagicMock
    ) -> None:
        """Test generation with SQL extraction enabled."""
        mock_model_loader.tokenizer.return_value = {
            "input_ids": torch.tensor([[1, 2, 3]]),
            "attention_mask": torch.tensor([[1, 1, 1]]),
        }
        mock_model_loader.tokenizer.decode.return_value = "SELECT * FROM users"

        mock_output = MagicMock()
        mock_output.sequences = torch.tensor([[1, 2, 3, 4, 5, 6]])
        mock_output.scores = None
        mock_model_loader.model.generate.return_value = mock_output
        mock_model_loader.model.parameters.return_value = iter(
            [torch.nn.Parameter(torch.zeros(1))]
        )

        with patch("models.inference.get_settings", return_value=mock_settings):
            engine = InferenceEngine(mock_model_loader)
            result = await engine.generate("Question: Show users", extract_sql=True)

            assert result.sql == "SELECT * FROM users"

    @pytest.mark.asyncio
    async def test_generate_without_sql_extraction(
        self, mock_settings: MagicMock, mock_model_loader: MagicMock
    ) -> None:
        """Test generation with SQL extraction disabled."""
        mock_model_loader.tokenizer.return_value = {
            "input_ids": torch.tensor([[1, 2, 3]]),
            "attention_mask": torch.tensor([[1, 1, 1]]),
        }
        mock_model_loader.tokenizer.decode.return_value = "Some explanation text"

        mock_output = MagicMock()
        mock_output.sequences = torch.tensor([[1, 2, 3, 4, 5]])
        mock_output.scores = None
        mock_model_loader.model.generate.return_value = mock_output
        mock_model_loader.model.parameters.return_value = iter(
            [torch.nn.Parameter(torch.zeros(1))]
        )

        with patch("models.inference.get_settings", return_value=mock_settings):
            engine = InferenceEngine(mock_model_loader)
            result = await engine.generate("Question: Explain", extract_sql=False)

            assert result.sql is None

    @pytest.mark.asyncio
    async def test_generate_token_limit_exceeded(
        self, mock_settings: MagicMock, mock_model_loader: MagicMock
    ) -> None:
        """Test that token limit exception is raised properly."""
        from app.exceptions import TokenLimitExceededException

        # Create input that's too long
        mock_model_loader.tokenizer.return_value = {
            "input_ids": torch.ones(1, 5000),  # Exceeds max length
            "attention_mask": torch.ones(1, 5000),
        }

        with patch("models.inference.get_settings", return_value=mock_settings):
            engine = InferenceEngine(mock_model_loader)

            with pytest.raises(TokenLimitExceededException):
                await engine.generate("Very long prompt...")

    @pytest.mark.asyncio
    async def test_generate_inference_exception(
        self, mock_settings: MagicMock, mock_model_loader: MagicMock
    ) -> None:
        """Test that inference exception is raised on failure."""
        from app.exceptions import ModelInferenceException

        mock_model_loader.tokenizer.return_value = {
            "input_ids": torch.tensor([[1, 2, 3]]),
            "attention_mask": torch.tensor([[1, 1, 1]]),
        }
        mock_model_loader.model.generate.side_effect = RuntimeError("CUDA error")
        mock_model_loader.model.parameters.return_value = iter(
            [torch.nn.Parameter(torch.zeros(1))]
        )

        with patch("models.inference.get_settings", return_value=mock_settings):
            engine = InferenceEngine(mock_model_loader)

            with pytest.raises(ModelInferenceException):
                await engine.generate("Question: Show users")

    @pytest.mark.asyncio
    async def test_generate_sql_convenience_method(
        self, mock_settings: MagicMock, mock_model_loader: MagicMock
    ) -> None:
        """Test generate_sql convenience method."""
        mock_model_loader.tokenizer.return_value = {
            "input_ids": torch.tensor([[1, 2, 3]]),
            "attention_mask": torch.tensor([[1, 1, 1]]),
        }
        mock_model_loader.tokenizer.decode.return_value = "SELECT * FROM users"

        mock_output = MagicMock()
        mock_output.sequences = torch.tensor([[1, 2, 3, 4, 5, 6]])
        mock_output.scores = None
        mock_model_loader.model.generate.return_value = mock_output
        mock_model_loader.model.parameters.return_value = iter(
            [torch.nn.Parameter(torch.zeros(1))]
        )

        with patch("models.inference.get_settings", return_value=mock_settings):
            engine = InferenceEngine(mock_model_loader)
            sql = await engine.generate_sql("Question: Show users")

            assert sql == "SELECT * FROM users"

    @pytest.mark.asyncio
    async def test_generate_batch(
        self, mock_settings: MagicMock, mock_model_loader: MagicMock
    ) -> None:
        """Test batch generation."""
        mock_model_loader.tokenizer.return_value = {
            "input_ids": torch.tensor([[1, 2, 3]]),
            "attention_mask": torch.tensor([[1, 1, 1]]),
        }
        mock_model_loader.tokenizer.decode.side_effect = [
            "SELECT * FROM users",
            "SELECT * FROM orders",
        ]

        mock_output = MagicMock()
        mock_output.sequences = torch.tensor([[1, 2, 3, 4, 5, 6]])
        mock_output.scores = None
        mock_model_loader.model.generate.return_value = mock_output
        mock_model_loader.model.parameters.return_value = iter(
            [torch.nn.Parameter(torch.zeros(1))]
        )

        with patch("models.inference.get_settings", return_value=mock_settings):
            engine = InferenceEngine(mock_model_loader)
            prompts = ["Show users", "Show orders"]
            results = await engine.generate_batch(prompts)

            assert len(results) == 2
            assert all(isinstance(r, InferenceResult) for r in results)

    @pytest.mark.asyncio
    async def test_generate_batch_with_failure(
        self, mock_settings: MagicMock, mock_model_loader: MagicMock
    ) -> None:
        """Test batch generation with one failing prompt."""
        call_count = 0

        def mock_tokenizer_call(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("Tokenizer error")
            return {
                "input_ids": torch.tensor([[1, 2, 3]]),
                "attention_mask": torch.tensor([[1, 1, 1]]),
            }

        mock_model_loader.tokenizer.side_effect = mock_tokenizer_call
        mock_model_loader.tokenizer.decode.return_value = "SELECT * FROM users"

        mock_output = MagicMock()
        mock_output.sequences = torch.tensor([[1, 2, 3, 4, 5, 6]])
        mock_output.scores = None
        mock_model_loader.model.generate.return_value = mock_output
        mock_model_loader.model.parameters.return_value = iter(
            [torch.nn.Parameter(torch.zeros(1))]
        )

        with patch("models.inference.get_settings", return_value=mock_settings):
            engine = InferenceEngine(mock_model_loader)
            prompts = ["Show users", "Show orders"]
            results = await engine.generate_batch(prompts)

            assert len(results) == 2
            # Second result should have error in metadata
            assert results[1].sql is None
            assert "error" in results[1].metadata


class TestGetInferenceEngine:
    """Tests for get_inference_engine function."""

    @pytest.fixture
    def mock_settings(self) -> MagicMock:
        """Create mock settings."""
        settings = MagicMock()
        settings.agent.min_confidence = 0.7
        return settings

    @pytest.mark.asyncio
    async def test_creates_engine(self, mock_settings: MagicMock) -> None:
        """Test that get_inference_engine creates an engine."""
        import models.inference as inference_module

        inference_module._inference_engine = None

        mock_loader = MagicMock()

        with patch("models.inference.get_settings", return_value=mock_settings):
            engine = await get_inference_engine(mock_loader)

            assert engine is not None
            assert isinstance(engine, InferenceEngine)

    @pytest.mark.asyncio
    async def test_returns_same_instance(self, mock_settings: MagicMock) -> None:
        """Test that get_inference_engine returns same instance."""
        import models.inference as inference_module

        inference_module._inference_engine = None

        mock_loader = MagicMock()

        with patch("models.inference.get_settings", return_value=mock_settings):
            engine1 = await get_inference_engine(mock_loader)
            engine2 = await get_inference_engine(mock_loader)

            assert engine1 is engine2
