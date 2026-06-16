"""Unit tests for embedding/generator.py."""

import pytest

from src.embedding.generator import EmbeddingGenerator


@pytest.fixture
def generator() -> EmbeddingGenerator:
    return EmbeddingGenerator()


@pytest.mark.asyncio
async def test_encode_single_string_returns_flat_list(generator: EmbeddingGenerator) -> None:
    vector = await generator.encode("disk full on /var")

    assert isinstance(vector, list)
    assert len(vector) == 384
    assert all(isinstance(v, float) for v in vector)


@pytest.mark.asyncio
async def test_encode_list_returns_list_of_lists(generator: EmbeddingGenerator) -> None:
    vectors = await generator.encode(["disk full", "VPN timeout"])

    assert isinstance(vectors, list)
    assert len(vectors) == 2
    assert len(vectors[0]) == 384


@pytest.mark.asyncio
async def test_encode_one_equivalent_to_encode_single(generator: EmbeddingGenerator) -> None:
    v1 = await generator.encode("test ticket")
    v2 = await generator.encode_one("test ticket")

    assert v1 == pytest.approx(v2, abs=1e-6)


@pytest.mark.asyncio
async def test_vectors_are_unit_normalized(generator: EmbeddingGenerator) -> None:
    import math

    vector = await generator.encode_one("server is down")
    magnitude = math.sqrt(sum(v * v for v in vector))

    assert magnitude == pytest.approx(1.0, abs=1e-5)


@pytest.mark.asyncio
async def test_different_texts_produce_different_vectors(generator: EmbeddingGenerator) -> None:
    v1 = await generator.encode_one("network connectivity issue")
    v2 = await generator.encode_one("database backup failed")

    assert v1 != v2
