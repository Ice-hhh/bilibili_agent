from __future__ import annotations

import queue
import threading
import time
import uuid
from typing import Any

from services.storage import safe_video_id


class TaskManager:
    def __init__(self, video_store, bilibili, transcriber, rag_store):
        self.video_store = video_store
        self.bilibili = bilibili
        self.transcriber = transcriber
        self.rag_store = rag_store
        self._tasks: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def submit(self, payload: dict[str, Any]) -> str:
        task_id = uuid.uuid4().hex
        task = {
            "id": task_id,
            "payload": payload,
            "events": [],
            "queue": queue.Queue(),
            "done": False,
        }
        with self._lock:
            self._tasks[task_id] = task
        thread = threading.Thread(target=self._run, args=(task_id,), daemon=True)
        thread.start()
        return task_id

    def subscribe(self, task_id: str):
        task = self._tasks.get(task_id)
        if not task:
            yield {"status": "failed", "message": "任务不存在", "progress": 0}
            return

        for event in task["events"]:
            yield event

        while True:
            try:
                event = task["queue"].get(timeout=15)
            except queue.Empty:
                last_event = task["events"][-1] if task["events"] else {}
                yield {
                    "status": "heartbeat",
                    "message": last_event.get("message", "处理中..."),
                    "progress": last_event.get("progress", 0),
                }
                continue
            yield event
            if event.get("status") in {"completed", "failed"}:
                break

    def _emit(self, task_id: str, status: str, message: str, progress: int | None = None, **extra) -> None:
        task = self._tasks[task_id]
        if progress is None:
            progress = _default_progress(status)
        event = {"status": status, "message": message, "progress": progress, "time": time.time(), **extra}
        task["events"].append(event)
        task["queue"].put(event)

    def _run(self, task_id: str) -> None:
        task = self._tasks[task_id]
        payload = task["payload"]
        url = payload.get("url") or ""
        video_id = safe_video_id(payload.get("video_id") or url)
        if not url and video_id.startswith("BV"):
            url = f"https://www.bilibili.com/video/{video_id}"
        title = payload.get("title") or "未命名视频"

        try:
            self._emit(task_id, "started", "开始处理视频", progress=5, video_id=video_id)
            if self.video_store.is_processed(video_id):
                self._emit(task_id, "completed", "已成功读取视频", progress=100, video_id=video_id, cached=True)
                return

            self.video_store.save_meta(
                video_id,
                {
                    "title": title,
                    "author": payload.get("author") or "",
                    "cover": payload.get("cover") or "",
                    "url": url,
                    "processed": False,
                    "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                },
            )

            audio_path = self.video_store.audio_path(video_id)
            self._emit(task_id, "downloading", "正在下载并提取音频", progress=25, video_id=video_id)
            self.bilibili.download_audio(url, audio_path)
            self._emit(task_id, "downloaded", "音频下载完成", progress=45, video_id=video_id)

            self._emit(task_id, "transcribing", "正在使用 faster-whisper 转写音频，长视频可能需要几分钟", progress=60, video_id=video_id)
            transcript = self.transcriber.transcribe(
                audio_path,
                self.video_store.transcript_json_path(video_id),
                self.video_store.transcript_txt_path(video_id),
            )
            self._emit(task_id, "transcribed", "音频转写完成", progress=78, video_id=video_id)

            self._emit(task_id, "indexing", "正在切分文本并构建 RAG 索引", progress=88, video_id=video_id)
            self.rag_store.build(
                video_id,
                title,
                transcript,
                self.video_store.chunks_path(video_id),
                self.video_store.vectors_path(video_id),
            )

            self.video_store.save_meta(
                video_id,
                {
                    "processed": True,
                    "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "duration": transcript.get("duration", 0),
                },
            )
            self._emit(task_id, "completed", "已成功读取视频", progress=100, video_id=video_id)
        except Exception as exc:
            self.video_store.save_meta(video_id, {"processed": False, "error": str(exc)})
            self._emit(task_id, "failed", str(exc), progress=100, video_id=video_id)


def _default_progress(status: str) -> int:
    return {
        "queued": 3,
        "started": 5,
        "downloading": 25,
        "downloaded": 45,
        "transcribing": 60,
        "transcribed": 78,
        "indexing": 88,
        "completed": 100,
        "failed": 100,
    }.get(status, 0)
