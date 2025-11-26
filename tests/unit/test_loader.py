"""
Unit tests for model loader module.

These tests verify model loading functionality using mocks
to avoid requiring actual model downloads.
"""

from unittest.mock import MagicMock, patch

import pytest
import torch

from models.loader import (
    ModelInfo,
    ModelLoader,
    get_memory_usage,
    get_model_loader,
    get_optimal_device,
    load_model,
    unload_model,
)


class TestGetOptimalDevice:
    """Tests for get_optimal_device function."""

    def test_cuda_available(self) -> None:
        """Test that CUDA is returned when available."""
        with patch.object(torch.cuda, "is_available", return_value=True):
            assert get_optimal_device() == "cuda"

    def test_mps_available_no_cuda(self) -> None:
        """Test that MPS is returned when CUDA unavailable but MPS is."""
        with (
            patch.object(torch.cuda, "is_available", return_value=False),
            patch.object(torch.backends.mps, "is_available", return_value=True),
        ):
            assert get_optimal_device() == "mps"

    def test_cpu_fallback(self) -> None:
        """Test that CPU is returned when no accelerator available."""
        with (
            patch.object(torch.cuda, "is_available", return_value=False),
            patch.object(torch.backends.mps, "is_available", return_value=False),
        ):
            assert get_optimal_device() == "cpu"


class TestGetMemoryUsage:
    """Tests for get_memory_usage function."""

    def test_cuda_memory_usage(self) -> None:
        """Test memory usage retrieval when CUDA available."""
        with (
            patch.object(torch.cuda, "is_available", return_value=True),
            patch.object(
                torch.cuda, "memory_allocated", return_value=1024 * 1024 * 100
            ),
        ):
            usage = get_memory_usage()
            assert usage == 100.0  # 100 MB

    def test_no_cuda_returns_none(self) -> None:
        """Test that None is returned when CUDA unavailable."""
        with patch.object(torch.cuda, "is_available", return_value=False):
            assert get_memory_usage() is None


class TestModelInfo:
    """Tests for ModelInfo dataclass."""

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        info = ModelInfo(
            model_name="test-model",
            device="cpu",
            quantization="8-bit",
            loaded=True,
            memory_usage_mb=1024.5,
            max_length=4096,
        )
        result = info.to_dict()

        assert result["model_name"] == "test-model"
        assert result["device"] == "cpu"
        assert result["quantization"] == "8-bit"
        assert result["loaded"] is True
        assert result["memory_usage_mb"] == 1024.5
        assert result["max_length"] == 4096

    def test_default_values(self) -> None:
        """Test default values for optional fields."""
        info = ModelInfo(
            model_name="test-model",
            device="cuda",
            quantization=None,
            loaded=False,
        )
        assert info.memory_usage_mb is None
        assert info.max_length == 4096


class TestModelLoader:
    """Tests for ModelLoader class."""

    @pytest.fixture
    def mock_settings(self) -> MagicMock:
        """Create mock settings."""
        settings = MagicMock()
        settings.huggingface.model_name = "test-model"
        settings.huggingface.device = "cpu"
        settings.huggingface.enable_8bit_quantization = False
        settings.huggingface.enable_4bit_quantization = False
        settings.huggingface.token = "test-token"
        return settings

    def test_init_with_defaults(self, mock_settings: MagicMock) -> None:
        """Test initialization with default values from settings."""
        with patch("models.loader.get_settings", return_value=mock_settings):
            loader = ModelLoader()

            assert loader._model_name == "test-model"
            assert loader._device == "cpu"
            assert loader._enable_8bit is False
            assert loader._enable_4bit is False
            assert loader.is_loaded is False

    def test_init_with_overrides(self, mock_settings: MagicMock) -> None:
        """Test initialization with custom values."""
        with patch("models.loader.get_settings", return_value=mock_settings):
            loader = ModelLoader(
                model_name="custom-model",
                device="cuda",
                enable_8bit=True,
            )

            assert loader._model_name == "custom-model"
            assert loader._device == "cuda"
            assert loader._enable_8bit is True

    def test_is_loaded_property(self, mock_settings: MagicMock) -> None:
        """Test is_loaded property."""
        with patch("models.loader.get_settings", return_value=mock_settings):
            loader = ModelLoader()
            assert loader.is_loaded is False

            loader._is_loaded = True
            assert loader.is_loaded is True

    def test_model_property_raises_when_not_loaded(
        self, mock_settings: MagicMock
    ) -> None:
        """Test that model property raises when not loaded."""
        with patch("models.loader.get_settings", return_value=mock_settings):
            from app.exceptions import ModelLoadException

            loader = ModelLoader()

            with pytest.raises(ModelLoadException):
                _ = loader.model

    def test_tokenizer_property_raises_when_not_loaded(
        self, mock_settings: MagicMock
    ) -> None:
        """Test that tokenizer property raises when not loaded."""
        with patch("models.loader.get_settings", return_value=mock_settings):
            from app.exceptions import ModelLoadException

            loader = ModelLoader()

            with pytest.raises(ModelLoadException):
                _ = loader.tokenizer

    def test_get_info(self, mock_settings: MagicMock) -> None:
        """Test get_info method."""
        with (
            patch("models.loader.get_settings", return_value=mock_settings),
            patch("models.loader.get_memory_usage", return_value=500.0),
        ):
            loader = ModelLoader()
            info = loader.get_info()

            assert info.model_name == "test-model"
            assert info.device == "cpu"
            assert info.quantization is None
            assert info.loaded is False

    def test_get_info_with_8bit_quantization(self, mock_settings: MagicMock) -> None:
        """Test get_info with 8-bit quantization enabled."""
        with patch("models.loader.get_settings", return_value=mock_settings):
            loader = ModelLoader(enable_8bit=True)
            info = loader.get_info()

            assert info.quantization == "8-bit"

    def test_get_info_with_4bit_quantization(self, mock_settings: MagicMock) -> None:
        """Test get_info with 4-bit quantization enabled."""
        with patch("models.loader.get_settings", return_value=mock_settings):
            loader = ModelLoader(enable_4bit=True)
            info = loader.get_info()

            assert info.quantization == "4-bit"

    def test_get_actual_device_auto(self, mock_settings: MagicMock) -> None:
        """Test _get_actual_device with auto setting."""
        mock_settings.huggingface.device = "auto"
        with (
            patch("models.loader.get_settings", return_value=mock_settings),
            patch("models.loader.get_optimal_device", return_value="cuda"),
        ):
            loader = ModelLoader()
            assert loader._get_actual_device() == "cuda"

    def test_get_actual_device_explicit(self, mock_settings: MagicMock) -> None:
        """Test _get_actual_device with explicit setting."""
        mock_settings.huggingface.device = "mps"
        with patch("models.loader.get_settings", return_value=mock_settings):
            loader = ModelLoader()
            assert loader._get_actual_device() == "mps"

    @pytest.mark.asyncio
    async def test_load_returns_cached_when_loaded(
        self, mock_settings: MagicMock
    ) -> None:
        """Test that load returns cached model when already loaded."""
        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        with patch("models.loader.get_settings", return_value=mock_settings):
            loader = ModelLoader()
            loader._model = mock_model
            loader._tokenizer = mock_tokenizer
            loader._is_loaded = True

            result = await loader.load()

            assert result == (mock_model, mock_tokenizer)

    @pytest.mark.asyncio
    async def test_load_model_success(self, mock_settings: MagicMock) -> None:
        """Test successful model loading."""
        mock_model = MagicMock()
        # Configure .to() to return the same mock
        mock_model.to.return_value = mock_model
        mock_tokenizer = MagicMock()
        mock_tokenizer.pad_token = None
        mock_tokenizer.eos_token = "<eos>"

        with (
            patch("models.loader.get_settings", return_value=mock_settings),
            patch(
                "models.loader.AutoTokenizer.from_pretrained",
                return_value=mock_tokenizer,
            ),
            patch(
                "models.loader.AutoModelForCausalLM.from_pretrained",
                return_value=mock_model,
            ),
        ):
            loader = ModelLoader()
            model, tokenizer = await loader.load()

            assert model == mock_model
            assert tokenizer == mock_tokenizer
            assert loader.is_loaded is True
            assert tokenizer.pad_token == "<eos>"

    @pytest.mark.asyncio
    async def test_load_model_failure(self, mock_settings: MagicMock) -> None:
        """Test model loading failure."""
        from app.exceptions import ModelLoadException

        with (
            patch("models.loader.get_settings", return_value=mock_settings),
            patch(
                "models.loader.AutoTokenizer.from_pretrained",
                side_effect=Exception("Download failed"),
            ),
        ):
            loader = ModelLoader()

            with pytest.raises(ModelLoadException) as exc_info:
                await loader.load()

            assert "Download failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_warmup_success(self, mock_settings: MagicMock) -> None:
        """Test successful model warmup."""
        mock_model = MagicMock()
        mock_tokenizer = MagicMock()
        mock_tokenizer.return_value = {"input_ids": torch.tensor([[1, 2, 3]])}

        with patch("models.loader.get_settings", return_value=mock_settings):
            loader = ModelLoader()
            loader._model = mock_model
            loader._tokenizer = mock_tokenizer
            loader._is_loaded = True

            # Should not raise
            await loader.warmup()

    @pytest.mark.asyncio
    async def test_warmup_fails_when_not_loaded(self, mock_settings: MagicMock) -> None:
        """Test warmup fails when model not loaded."""
        from app.exceptions import ModelLoadException

        with patch("models.loader.get_settings", return_value=mock_settings):
            loader = ModelLoader()

            with pytest.raises(ModelLoadException):
                await loader.warmup()

    def test_unload(self, mock_settings: MagicMock) -> None:
        """Test model unloading."""
        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        with (
            patch("models.loader.get_settings", return_value=mock_settings),
            patch.object(torch.cuda, "is_available", return_value=False),
        ):
            loader = ModelLoader()
            loader._model = mock_model
            loader._tokenizer = mock_tokenizer
            loader._is_loaded = True

            loader.unload()

            assert loader._model is None
            assert loader._tokenizer is None
            assert loader.is_loaded is False


class TestGlobalLoaderFunctions:
    """Tests for global model loader functions."""

    @pytest.fixture
    def mock_settings(self) -> MagicMock:
        """Create mock settings."""
        settings = MagicMock()
        settings.huggingface.model_name = "test-model"
        settings.huggingface.device = "cpu"
        settings.huggingface.enable_8bit_quantization = False
        settings.huggingface.enable_4bit_quantization = False
        settings.huggingface.token = None
        return settings

    @pytest.mark.asyncio
    async def test_get_model_loader_creates_instance(
        self, mock_settings: MagicMock
    ) -> None:
        """Test get_model_loader creates instance when none exists."""
        import models.loader as loader_module

        # Reset global state
        loader_module._model_loader = None

        with patch("models.loader.get_settings", return_value=mock_settings):
            loader = await get_model_loader()

            assert loader is not None
            assert isinstance(loader, ModelLoader)

    @pytest.mark.asyncio
    async def test_get_model_loader_returns_same_instance(
        self, mock_settings: MagicMock
    ) -> None:
        """Test get_model_loader returns same instance on subsequent calls."""
        import models.loader as loader_module

        loader_module._model_loader = None

        with patch("models.loader.get_settings", return_value=mock_settings):
            loader1 = await get_model_loader()
            loader2 = await get_model_loader()

            assert loader1 is loader2

    @pytest.mark.asyncio
    async def test_load_model_function(self, mock_settings: MagicMock) -> None:
        """Test load_model convenience function."""
        import models.loader as loader_module

        loader_module._model_loader = None

        mock_model = MagicMock()
        # Configure .to() to return the same mock
        mock_model.to.return_value = mock_model
        mock_tokenizer = MagicMock()
        mock_tokenizer.pad_token = "<pad>"

        with (
            patch("models.loader.get_settings", return_value=mock_settings),
            patch(
                "models.loader.AutoTokenizer.from_pretrained",
                return_value=mock_tokenizer,
            ),
            patch(
                "models.loader.AutoModelForCausalLM.from_pretrained",
                return_value=mock_model,
            ),
        ):
            model, tokenizer = await load_model()

            assert model == mock_model
            assert tokenizer == mock_tokenizer

    def test_unload_model_function(self, mock_settings: MagicMock) -> None:
        """Test unload_model convenience function."""
        import models.loader as loader_module

        # Create mock loader
        mock_loader = MagicMock()
        loader_module._model_loader = mock_loader

        with patch.object(torch.cuda, "is_available", return_value=False):
            unload_model()

            mock_loader.unload.assert_called_once()
            assert loader_module._model_loader is None

    def test_unload_model_when_none(self) -> None:
        """Test unload_model when no loader exists."""
        import models.loader as loader_module

        loader_module._model_loader = None

        # Should not raise
        unload_model()
