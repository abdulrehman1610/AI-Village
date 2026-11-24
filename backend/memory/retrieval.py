from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from memory.embeddings import EmbeddingService, unpack_embedding
from memory.models import MemoryRecord
from memory.store import MemoryStore


@dataclass(frozen=True)
class ScoredMemory:
    """Memory record annotated with total weighted and normalized component scores."""

    memory: MemoryRecord
    score: float
    recency_score: float
    importance_score: float
    relevance_score: float


def min_max_normalize(values: NDArray[np.float64]) -> NDArray[np.float64]:
    """Min-max normalize values to [0, 1] with a finite zero-range guard."""
    if values.size == 0:
        return values
    min_v = float(np.min(values))
    max_v = float(np.max(values))
    span = max_v - min_v
    if span < 1e-9:
        return np.asarray(np.clip(values, 0.0, 1.0), dtype=np.float64)
    return np.asarray((values - min_v) / span, dtype=np.float64)


def cosine_similarity_batch(
    matrix: NDArray[np.float32],
    query: NDArray[np.float32],
) -> NDArray[np.float64]:
    """Compute vectorized cosine similarities between each row of matrix and query."""
    if matrix.shape[0] == 0:
        return np.empty(0, dtype=np.float64)

    mat64 = np.asarray(matrix, dtype=np.float64)
    query64 = np.asarray(query, dtype=np.float64).reshape(-1)
    norms = np.linalg.norm(mat64, axis=1)
    query_norm = float(np.linalg.norm(query64))
    denom = np.maximum(norms * query_norm, 1e-12)
    return np.asarray((mat64 @ query64) / denom, dtype=np.float64)


class MemoryRetriever:
    """Weighted recency + importance + cosine relevance memory retriever."""

    def __init__(
        self,
        store: MemoryStore,
        embedding_service: EmbeddingService,
        *,
        w_recency: float = 1.0,
        w_importance: float = 1.0,
        w_relevance: float = 1.0,
        decay_per_hour: float = 0.995,
        default_top_k: int = 8,
    ) -> None:
        self.store = store
        self.embedding_service = embedding_service
        self.w_recency = w_recency
        self.w_importance = w_importance
        self.w_relevance = w_relevance
        self.decay_per_hour = decay_per_hour
        self.default_top_k = default_top_k

    async def retrieve(
        self,
        agent_id: str,
        query: str,
        current_tick: int,
        *,
        top_k: int | None = None,
        touch: bool = True,
    ) -> list[ScoredMemory]:
        """Rank candidate memories for agent_id against query and return top-k results."""
        k = self.default_top_k if top_k is None else top_k
        if k <= 0:
            return []

        candidates = await self.store.list_memories(agent_id)
        if not candidates:
            return []

        query_vec = await self.embedding_service.embed(query)
        matrix = np.vstack([unpack_embedding(memory.embedding) for memory in candidates])

        last_access_ticks = np.array(
            [memory.last_access_tick for memory in candidates],
            dtype=np.float64,
        )
        importances = np.array([memory.importance for memory in candidates], dtype=np.float64)

        hours = np.maximum(0.0, (float(current_tick) - last_access_ticks) / 60.0)
        recency_raw = np.asarray(np.power(self.decay_per_hour, hours), dtype=np.float64)
        importance_raw = importances / 10.0
        relevance_raw = cosine_similarity_batch(matrix, query_vec)

        rec_norm = min_max_normalize(recency_raw)
        imp_norm = min_max_normalize(importance_raw)
        rel_norm = min_max_normalize(relevance_raw)

        total_scores = (
            self.w_recency * rec_norm
            + self.w_importance * imp_norm
            + self.w_relevance * rel_norm
        )

        scored = [
            ScoredMemory(
                memory=memory,
                score=float(total_scores[idx]),
                recency_score=float(rec_norm[idx]),
                importance_score=float(imp_norm[idx]),
                relevance_score=float(rel_norm[idx]),
            )
            for idx, memory in enumerate(candidates)
        ]
        scored.sort(
            key=lambda item: (item.score, item.memory.created_tick, item.memory.id or 0),
            reverse=True,
        )
        top_results = scored[:k]

        if touch:
            touch_ids = [item.memory.id for item in top_results if item.memory.id is not None]
            if touch_ids:
                await self.store.touch_memories(touch_ids, current_tick)
                for item in top_results:
                    item.memory.last_access_tick = current_tick

        return top_results
