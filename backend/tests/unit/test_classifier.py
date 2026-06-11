"""Unit tests for TicketClassifier (src/classification/classifier.py).

All tests use mocked artifacts and embedding generators — no disk access
and no model loading required.
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

import numpy as np
import pytest

from src.classification.classifier import TicketClassifier, TrainedModelArtifact
from src.classification.confidence import ConfidenceLevel
from src.core.exceptions import ClassificationError
from src.db.models import TicketCategory


ALL_CATS = [c.value for c in TicketCategory]


def _make_settings(model_dir: str = "data/models") -> MagicMock:
    s = MagicMock()
    s.model_dir = model_dir
    s.confidence_high_threshold = 0.85
    s.confidence_low_threshold = 0.60
    s.multi_domain_diff_threshold = 0.15
    s.embedding_model = "sentence-transformers/all-MiniLM-L6-v2"
    s.embedding_dim = 384
    s.embedding_batch_size = 32
    return s


def _make_mock_pipeline(probabilities: list[float]) -> MagicMock:
    """Return a mock sklearn Pipeline whose predict_proba returns given probs."""
    pipeline = MagicMock()
    pipeline.predict_proba.return_value = np.array([probabilities])
    return pipeline


def _make_artifact(probabilities: list[float] | None = None) -> TrainedModelArtifact:
    """Build a TrainedModelArtifact with a mocked sklearn pipeline."""
    if probabilities is None:
        # Default: NETWORK wins with 0.92 confidence
        probabilities = [0.02, 0.02, 0.02, 0.02, 0.92, 0.0]
        # Matches ALL_CATS order: infra, app, sec, db, access_mgmt, network
        # Reorder: infra=0.02, app=0.02, sec=0.02, db=0.02, access=0.0, network=0.92
        probabilities = [0.02, 0.02, 0.02, 0.02, 0.0, 0.92]

    le = MagicMock()
    le.classes_ = ALL_CATS

    return TrainedModelArtifact(
        pipeline=_make_mock_pipeline(probabilities),
        label_encoder=le,
        model_version="logistic_regression_v20260602_120000",
        trained_at="2026-06-02T12:00:00+00:00",
        training_samples=8000,
        categories=ALL_CATS,
    )


def _make_classifier(artifact: TrainedModelArtifact | None = None) -> TicketClassifier:
    """Build a TicketClassifier by patching joblib.load — no disk write needed."""
    if artifact is None:
        artifact = _make_artifact()

    settings = _make_settings()
    mock_gen = MagicMock()
    mock_gen.encode_single.return_value = [0.1] * 384

    # Patch both Path.exists (so the file appears present) and joblib.load
    # (so we return our mock artifact) — avoids pickling MagicMock objects.
    with patch("src.classification.classifier.Path.exists", return_value=True), \
         patch("src.classification.classifier.joblib.load", return_value=artifact):
        classifier = TicketClassifier(
            model_path=Path("data/models/classifier.pkl"),
            settings=settings,
            embedding_generator=mock_gen,
        )
    return classifier


# ── Happy path ────────────────────────────────────────────────────────────────


class TestTicketClassifierHappyPath:
    def test_predict_returns_classification_output(self):
        clf = _make_classifier()
        output = clf.predict("VPN authentication is failing for all remote users")
        assert output is not None

    def test_predicted_category_is_ticket_category(self):
        clf = _make_classifier()
        output = clf.predict("server is down")
        assert isinstance(output.predicted_category, TicketCategory)

    def test_predicted_category_matches_highest_probability(self):
        # NETWORK (index 5) has prob 0.92 — should win
        artifact = _make_artifact(probabilities=[0.02, 0.02, 0.02, 0.02, 0.0, 0.92])
        clf = _make_classifier(artifact)
        output = clf.predict("test text")
        assert output.predicted_category == TicketCategory.NETWORK

    def test_confidence_matches_top_probability(self):
        artifact = _make_artifact(probabilities=[0.02, 0.02, 0.02, 0.02, 0.0, 0.92])
        clf = _make_classifier(artifact)
        output = clf.predict("test text")
        assert output.confidence == pytest.approx(0.92, abs=1e-4)

    def test_high_probability_gives_high_confidence_level(self):
        artifact = _make_artifact(probabilities=[0.02, 0.02, 0.02, 0.02, 0.0, 0.92])
        clf = _make_classifier(artifact)
        output = clf.predict("test text")
        assert output.confidence_level == ConfidenceLevel.HIGH

    def test_medium_probability_gives_medium_confidence_level(self):
        # INFRASTRUCTURE wins with 0.70 → MEDIUM (0.60 <= 0.70 < 0.85)
        artifact = _make_artifact(probabilities=[0.70, 0.15, 0.05, 0.05, 0.025, 0.025])
        clf = _make_classifier(artifact)
        output = clf.predict("test text")
        assert output.confidence_level == ConfidenceLevel.MEDIUM

    def test_top_categories_has_at_most_3_entries(self):
        clf = _make_classifier()
        output = clf.predict("test text")
        assert len(output.top_categories) <= 3

    def test_multi_domain_detected_when_gap_small(self):
        # INFRASTRUCTURE=0.45, APPLICATION=0.40 → gap=0.05 < 0.15
        artifact = _make_artifact(probabilities=[0.45, 0.40, 0.05, 0.04, 0.03, 0.03])
        clf = _make_classifier(artifact)
        output = clf.predict("test text")
        assert output.is_multi_domain is True

    def test_not_multi_domain_when_gap_large(self):
        # NETWORK wins with 0.92 → gap >> 0.15
        artifact = _make_artifact(probabilities=[0.02, 0.02, 0.02, 0.02, 0.0, 0.92])
        clf = _make_classifier(artifact)
        output = clf.predict("test text")
        assert output.is_multi_domain is False

    def test_classification_method_from_artifact_version(self):
        clf = _make_classifier()
        output = clf.predict("test")
        assert "logistic_regression" in output.classification_method


# ── Error handling ─────────────────────────────────────────────────────────────


class TestTicketClassifierErrors:
    def test_missing_model_file_raises_classification_error(self):
        settings = _make_settings()
        with pytest.raises(ClassificationError) as exc_info:
            TicketClassifier(
                model_path=Path("/nonexistent/path/classifier.pkl"),
                settings=settings,
            )
        assert exc_info.value.error_code == "CLASSIFICATION_ERROR"

    def test_wrong_type_in_pkl_raises_classification_error(self):
        import joblib

        settings = _make_settings()
        with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as f:
            tmp_path = Path(f.name)

        joblib.dump({"not": "an artifact"}, tmp_path)
        with pytest.raises(ClassificationError, match="TrainedModelArtifact"):
            TicketClassifier(model_path=tmp_path, settings=settings)

    def test_predict_proba_failure_raises_classification_error(self):
        artifact = _make_artifact()
        artifact.pipeline.predict_proba.side_effect = RuntimeError("model error")
        clf = _make_classifier(artifact)
        with pytest.raises(ClassificationError):
            clf.predict("test text")

    def test_embedding_failure_raises_classification_error(self):
        clf = _make_classifier()
        clf._embedding_generator.encode_single.side_effect = Exception("GPU OOM")
        with pytest.raises(ClassificationError):
            clf.predict("test text")


# ── from_settings factory ──────────────────────────────────────────────────────


class TestFromSettings:
    def test_from_settings_uses_model_dir(self, tmp_path):
        settings = _make_settings(model_dir=str(tmp_path))
        artifact = _make_artifact()

        mock_gen = MagicMock()
        mock_gen.encode_single.return_value = [0.1] * 384

        with patch("src.classification.classifier.Path.exists", return_value=True), \
             patch("src.classification.classifier.joblib.load", return_value=artifact), \
             patch("src.classification.classifier.EmbeddingGenerator", return_value=mock_gen):
            clf = TicketClassifier.from_settings(settings)

        output = clf.predict("test text")
        assert output is not None

    def test_from_settings_raises_when_file_missing(self, tmp_path):
        settings = _make_settings(model_dir=str(tmp_path))
        # tmp_path exists but classifier.pkl does not → should raise
        with pytest.raises(ClassificationError):
            TicketClassifier.from_settings(settings)
