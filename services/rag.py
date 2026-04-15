from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any


class RagStore:
    def __init__(self, data_dir: Path, embedding_model_name: str):
        self.data_dir = data_dir
        self.embedding_model_name = embedding_model_name
        self._embedding_model = None
        self._embedding_backend = "hash"

    def build(self, video_id: str, title: str, transcript: dict[str, Any], chunks_path: Path, vectors_path: Path) -> None:
        if chunks_path.exists() and vectors_path.exists():
            return

        chunks = chunk_transcript(video_id, title, transcript)
        vectors = [self.embed(chunk["text"]) for chunk in chunks]
        chunks_path.write_text(
            "".join(json.dumps(chunk, ensure_ascii=False) + "\n" for chunk in chunks),
            encoding="utf-8",
        )
        vectors_path.write_text(
            json.dumps(
                {
                    "embedding_model": self.embedding_model_name,
                    "embedding_backend": self._embedding_backend,
                    "vectors": vectors,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def search(self, video_id: str, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        video_dir = self.data_dir / "videos" / video_id
        chunks_path = video_dir / "chunks.jsonl"
        vectors_path = video_dir / "vectors.json"
        if not chunks_path.exists() or not vectors_path.exists():
            return []

        chunks = [json.loads(line) for line in chunks_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        payload = json.loads(vectors_path.read_text(encoding="utf-8"))
        vectors = payload.get("vectors") or []
        query_vector = self.embed(query)

        scored = []
        for chunk, vector in zip(chunks, vectors):
            scored.append((cosine_similarity(query_vector, vector), chunk))
        scored.sort(key=lambda item: item[0], reverse=True)

        results = []
        for score, chunk in scored[:top_k]:
            item = dict(chunk)
            item["score"] = score
            results.append(item)
        return results

    def embed(self, text: str) -> list[float]:
        model = self._get_embedding_model()
        if model is not None:
            vector = model.encode(text, normalize_embeddings=True)
            return [float(x) for x in vector.tolist()]
        return hash_embedding(text)

    def _get_embedding_model(self):
        if self._embedding_model is not None:
            return self._embedding_model
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            self._embedding_backend = "hash"
            return None
        try:
            self._embedding_model = SentenceTransformer(self.embedding_model_name)
            self._embedding_backend = "sentence-transformers"
            return self._embedding_model
        except Exception:
            self._embedding_backend = "hash"
            return None


def chunk_transcript(video_id: str, title: str, transcript: dict[str, Any], max_chars: int = 900) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    current_chars = 0

    for segment in transcript.get("segments", []):
        text = (segment.get("text") or "").strip()
        if not text:
            continue
        if current and current_chars + len(text) > max_chars:
            chunks.append(_make_chunk(video_id, title, current, len(chunks)))
            current = []
            current_chars = 0
        current.append(segment)
        current_chars += len(text)

    if current:
        chunks.append(_make_chunk(video_id, title, current, len(chunks)))
    return chunks


def _make_chunk(video_id: str, title: str, segments: list[dict[str, Any]], index: int) -> dict[str, Any]:
    return {
        "chunk_id": f"{video_id}-{index:04d}",
        "video_id": video_id,
        "title": title,
        "start": float(segments[0].get("start", 0.0)),
        "end": float(segments[-1].get("end", 0.0)),
        "time_range": f"{_format_ts(segments[0].get('start', 0.0))} - {_format_ts(segments[-1].get('end', 0.0))}",
        "text": "".join(segment.get("text", "") for segment in segments),
    }


def hash_embedding(text: str, dimensions: int = 256) -> list[float]:
    vector = [0.0] * dimensions
    for token in _tokenize(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norm for x in vector]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    length = min(len(a), len(b))
    dot = sum(a[i] * b[i] for i in range(length))
    na = math.sqrt(sum(x * x for x in a[:length]))
    nb = math.sqrt(sum(x * x for x in b[:length]))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _tokenize(text: str) -> list[str]:
    clean = text.lower().strip()
    if not clean:
        return []
    tokens = clean.split()
    if len(tokens) > 1:
        return tokens
    return [clean[i : i + 2] for i in range(max(1, len(clean) - 1))]


def _format_ts(seconds: float) -> str:
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"
