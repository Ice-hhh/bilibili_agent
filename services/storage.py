from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def safe_video_id(value: str) -> str:
    value = value.strip()
    if not value:
        return "unknown"
    value = re.sub(r"https?://", "", value)
    value = re.sub(r"[^a-zA-Z0-9_.-]+", "_", value)
    return value.strip("_")[:120] or "unknown"


class VideoStore:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.videos_dir = data_dir / "videos"
        self.videos_dir.mkdir(parents=True, exist_ok=True)

    def video_dir(self, video_id: str) -> Path:
        path = self.videos_dir / safe_video_id(video_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def meta_path(self, video_id: str) -> Path:
        return self.video_dir(video_id) / "meta.json"

    def transcript_json_path(self, video_id: str) -> Path:
        return self.video_dir(video_id) / "transcript.json"

    def transcript_txt_path(self, video_id: str) -> Path:
        return self.video_dir(video_id) / "transcript.txt"

    def chunks_path(self, video_id: str) -> Path:
        return self.video_dir(video_id) / "chunks.jsonl"

    def vectors_path(self, video_id: str) -> Path:
        return self.video_dir(video_id) / "vectors.json"

    def audio_path(self, video_id: str) -> Path:
        return self.video_dir(video_id) / "audio.mp3"

    def save_meta(self, video_id: str, data: dict[str, Any]) -> dict[str, Any]:
        current = self.get_video(video_id) or {}
        merged = {**current, **data, "video_id": safe_video_id(video_id)}
        path = self.meta_path(video_id)
        path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
        return merged

    def get_video(self, video_id: str) -> dict[str, Any] | None:
        path = self.meta_path(video_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def is_processed(self, video_id: str) -> bool:
        meta = self.get_video(video_id) or {}
        return bool(
            meta.get("processed")
            and self.transcript_json_path(video_id).exists()
            and self.chunks_path(video_id).exists()
            and self.vectors_path(video_id).exists()
        )

    def list_processed_videos(self) -> list[dict[str, Any]]:
        videos: list[dict[str, Any]] = []
        for meta_path in sorted(self.videos_dir.glob("*/meta.json"), reverse=True):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if meta.get("processed"):
                videos.append(meta)
        return videos
