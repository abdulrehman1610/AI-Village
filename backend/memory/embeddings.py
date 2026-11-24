from __future__ import annotations

import asyncio
import hashlib
import re
import threading
from collections.abc import Sequence
from typing import Any, Literal, Protocol, runtime_checkable

import numpy as np
from numpy.typing import NDArray

EMBEDDING_DIM = 384
EmbeddingVector = NDArray[np.float32]

_TOKEN_PATTERN = re.compile(r"[a-z0-9_]+")


def pack_embedding(vec: EmbeddingVector) -> bytes:
    """Serialize a 384-d float32 embedding vector into a 1,536-byte blob."""
    arr = np.asarray(vec, dtype=np.float32).reshape(-1)
    if arr.size != EMBEDDING_DIM:
        shape = np.asarray(vec).shape
        raise ValueError(f"Expected embedding vector of length {EMBEDDING_DIM}, got shape {shape}.")
    return arr.tobytes()


def unpack_embedding(blob: bytes) -> EmbeddingVector:
    """Deserialize a 1,536-byte binary blob back into a writable 384-d float32 vector."""
    expected_bytes = EMBEDDING_DIM * 4
    if len(blob) != expected_bytes:
        raise ValueError(
            f"Expected {expected_bytes}-byte float32 embedding blob, got {len(blob)} bytes."
        )
    return np.frombuffer(blob, dtype=np.float32).copy()


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Contract for synchronous batch text embedding providers."""

    def embed_batch(self, texts: Sequence[str]) -> list[EmbeddingVector]: ...


class DeterministicEmbeddingProvider:
    """Zero-network, zero-torch signed BLAKE2b token/bigram embedding provider."""

    def _embed_one(self, text: str) -> EmbeddingVector:
        tokens = _TOKEN_PATTERN.findall(text.lower())
        features = list(tokens)
        features.extend(f"{tokens[i]}_{tokens[i + 1]}" for i in range(len(tokens) - 1))

        vec = np.zeros(EMBEDDING_DIM, dtype=np.float32)
        for feature in features:
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            h_val = int.from_bytes(digest, "little")
            idx = h_val % EMBEDDING_DIM
            sign = 1.0 if ((h_val >> 16) & 1) == 0 else -1.0
            vec[idx] += np.float32(sign)

        norm = float(np.linalg.norm(vec))
        if norm < 1e-12:
            vec[0] = np.float32(1.0)
            return vec
        return (vec / np.float32(norm)).astype(np.float32, copy=False)

    def embed_batch(self, texts: Sequence[str]) -> list[EmbeddingVector]:
        """Generate deterministic L2-normalized 384-d embeddings for a batch of texts."""
        return [self._embed_one(text) for text in texts]


class SentenceTransformerEmbeddingProvider:
    """Lazy CPU SentenceTransformer embedding provider (all-MiniLM-L6-v2)."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2", device: str = "cpu") -> None:
        self.model_name = model_name
        self.device = device
        self._model: Any = None
        self._lock = threading.Lock()

    def _get_model(self) -> Any:
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from sentence_transformers import SentenceTransformer

                    self._model = SentenceTransformer(self.model_name, device=self.device)
        return self._model

    def embed_batch(self, texts: Sequence[str]) -> list[EmbeddingVector]:
        """Encode texts into L2-normalized 384-d float32 vectors using SentenceTransformer."""
        if not texts:
            return []
        encoded = self._get_model().encode(
            list(texts),
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        matrix = np.atleast_2d(np.asarray(encoded, dtype=np.float32))
        if matrix.shape[1] != EMBEDDING_DIM:
            raise ValueError(
                f"Expected {EMBEDDING_DIM}-d embeddings from {self.model_name}, "
                f"got shape {matrix.shape}."
            )
        return [np.asarray(row, dtype=np.float32).reshape(-1).copy() for row in matrix]


class EmbeddingService:
    """Async facade over deterministic mock or lazy local embedding providers."""

    def __init__(self, provider: EmbeddingProvider) -> None:
        self.provider = provider

    @classmethod
    def from_mode(
        cls,
        mode: Literal["mock", "local"],
        model_name: str = "all-MiniLM-L6-v2",
    ) -> EmbeddingService:
        """Instantiate an EmbeddingService from an explicit provider mode."""
        if mode == "mock":
            return cls(DeterministicEmbeddingProvider())
        if mode == "local":
            return cls(SentenceTransformerEmbeddingProvider(model_name=model_name))
        raise ValueError(f"Unsupported embedding mode: {mode!r}")

    async def embed(self, text: str) -> EmbeddingVector:
        """Embed a single text string into a 384-d float32 vector."""
        vectors = await self.embed_batch([text])
        return vectors[0]

    async def embed_batch(self, texts: Sequence[str]) -> list[EmbeddingVector]:
        """Embed a sequence of texts without blocking the asyncio event loop."""
        if not texts:
            return []
        if isinstance(self.provider, DeterministicEmbeddingProvider):
            return self.provider.embed_batch(texts)
        return await asyncio.to_thread(self.provider.embed_batch, texts)
