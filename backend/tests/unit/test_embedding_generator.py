"""Unit tests for EmbeddingGenerator (src/embedding/generator.py).

All tests mock SentenceTransformer — no model download required.
"""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.core.exceptions import EmbeddingError
from src.embedding.generator import EmbeddingGenerator


def _make_settings(
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2",
    embedding_dim: int = 384,
    embedding_batch_size: int = 32,
):
    settings = MagicMock()
    settings.embedding_model = embedding_model
    settings.embedding_dim = embedding_dim
    settings.embedding_batch_size = embedding_batch_size
    return settings


def _make_generator(mock_model: MagicMock | None = None) -> tuple[EmbeddingGenerator, MagicMock]:
    """Build an EmbeddingGenerator with a mocked SentenceTransformer."""
    if mock_model is None:
        mock_model = MagicMock()

    with patch("src.embedding.generator.SentenceTransformer", return_value=mock_model):
        gen = EmbeddingGenerator(_make_settings())
    return gen, mock_model


# ── Happy path ────────────────────────────────────────────────────────────────


class TestEncodeSingleHappyPath:
    def test_returns_list_of_floats(self):
        gen, model = _make_generator()
        model.encode.return_value = np.zeros(384)
        result = gen.encode_single("hello world")
        assert isinstance(result, list)
        assert all(isinstance(v, float) for v in result)

    def test_returns_384_dims(self):
        gen, model = _make_generator()
        model.encode.return_value = np.zeros(384)
        result = gen.encode_single("hello world")
        assert len(result) == 384

    def test_calls_encode_with_normalize_embeddings_true(self):
        gen, model = _make_generator()
        model.encode.return_value = np.zeros(384)
        gen.encode_single("some ticket text")
        call_kwargs = model.encode.call_args.kwargs
        assert call_kwargs.get("normalize_embeddings") is True

    def test_calls_encode_with_convert_to_numpy_true(self):
        gen, model = _make_generator()
        model.encode.return_value = np.zeros(384)
        gen.encode_single("some ticket text")
        call_kwargs = model.encode.call_args.kwargs
        assert call_kwargs.get("convert_to_numpy") is True

    def test_empty_string_returns_valid_vector(self):
        gen, model = _make_generator()
        model.encode.return_value = np.zeros(384)
        result = gen.encode_single("")
        assert len(result) == 384

    def test_returns_values_from_model_output(self):
        gen, model = _make_generator()
        expected = np.array([0.1] * 384)
        model.encode.return_value = expected
        result = gen.encode_single("text")
        assert result[0] == pytest.approx(0.1)


class TestEncodeBatchHappyPath:
    def test_returns_list_of_vectors(self):
        gen, model = _make_generator()
        model.encode.return_value = np.zeros((3, 384))
        result = gen.encode_batch(["a", "b", "c"])
        assert isinstance(result, list)
        assert len(result) == 3

    def test_each_vector_is_384_dims(self):
        gen, model = _make_generator()
        model.encode.return_value = np.zeros((3, 384))
        result = gen.encode_batch(["a", "b", "c"])
        assert all(len(v) == 384 for v in result)

    def test_empty_list_returns_empty_list(self):
        gen, model = _make_generator()
        result = gen.encode_batch([])
        assert result == []
        model.encode.assert_not_called()

    def test_uses_settings_batch_size_by_default(self):
        gen, model = _make_generator()
        model.encode.return_value = np.zeros((2, 384))
        gen.encode_batch(["a", "b"])
        call_kwargs = model.encode.call_args.kwargs
        assert call_kwargs.get("batch_size") == 32  # from _make_settings default

    def test_explicit_batch_size_overrides_settings(self):
        gen, model = _make_generator()
        model.encode.return_value = np.zeros((2, 384))
        gen.encode_batch(["a", "b"], batch_size=16)
        call_kwargs = model.encode.call_args.kwargs
        assert call_kwargs.get("batch_size") == 16

    def test_show_progress_false_by_default(self):
        gen, model = _make_generator()
        model.encode.return_value = np.zeros((2, 384))
        gen.encode_batch(["a", "b"])
        call_kwargs = model.encode.call_args.kwargs
        assert call_kwargs.get("show_progress_bar") is False

    def test_show_progress_true_passed_through(self):
        gen, model = _make_generator()
        model.encode.return_value = np.zeros((2, 384))
        gen.encode_batch(["a", "b"], show_progress=True)
        call_kwargs = model.encode.call_args.kwargs
        assert call_kwargs.get("show_progress_bar") is True

    def test_single_element_list_returns_one_vector(self):
        gen, model = _make_generator()
        model.encode.return_value = np.zeros((1, 384))
        result = gen.encode_batch(["only one"])
        assert len(result) == 1
        assert len(result[0]) == 384


# ── Error handling ────────────────────────────────────────────────────────────


class TestEmbeddingErrors:
    def test_model_load_failure_raises_embedding_error(self):
        with patch(
            "src.embedding.generator.SentenceTransformer",
            side_effect=RuntimeError("model not found"),
        ):
            with pytest.raises(EmbeddingError) as exc_info:
                EmbeddingGenerator(_make_settings())
            assert "model not found" in exc_info.value.message.lower() or \
                   "failed to load" in exc_info.value.message.lower()

    def test_encode_single_failure_raises_embedding_error(self):
        gen, model = _make_generator()
        model.encode.side_effect = RuntimeError("GPU OOM")
        with pytest.raises(EmbeddingError) as exc_info:
            gen.encode_single("test text")
        assert exc_info.value.error_code == "EMBEDDING_ERROR"

    def test_encode_batch_failure_raises_embedding_error(self):
        gen, model = _make_generator()
        model.encode.side_effect = RuntimeError("CUDA error")
        with pytest.raises(EmbeddingError):
            gen.encode_batch(["a", "b", "c"])

    def test_embedding_error_has_detail_dict(self):
        gen, model = _make_generator()
        model.encode.side_effect = ValueError("bad input")
        with pytest.raises(EmbeddingError) as exc_info:
            gen.encode_single("test")
        assert "error" in exc_info.value.detail


# ── Properties ────────────────────────────────────────────────────────────────


class TestProperties:
    def test_model_name_returns_settings_model(self):
        gen, _ = _make_generator()
        assert gen.model_name == "sentence-transformers/all-MiniLM-L6-v2"

    def test_embedding_dim_returns_384(self):
        gen, _ = _make_generator()
        assert gen.embedding_dim == 384


# ── Edge cases ────────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_long_text_truncated_by_model_no_error(self):
        """Very long text — model truncates internally; no exception from generator."""
        gen, model = _make_generator()
        model.encode.return_value = np.zeros(384)
        long_text = "word " * 10_000
        result = gen.encode_single(long_text)
        assert len(result) == 384

    def test_unicode_text_encoded_without_error(self):
        gen, model = _make_generator()
        model.encode.return_value = np.zeros(384)
        result = gen.encode_single("VPN ने काम करना बंद कर दिया है")  # Hindi
        assert len(result) == 384

    def test_batch_vectors_are_separate_lists(self):
        gen, model = _make_generator()
        arr = np.eye(3, 384)  # 3 different non-zero rows
        model.encode.return_value = arr
        result = gen.encode_batch(["a", "b", "c"])
        # Verify they are independent lists, not views
        assert result[0] is not result[1]
