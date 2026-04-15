from __future__ import annotations

import json
from pathlib import Path


class TranscriptionError(RuntimeError):
    pass


class TranscriptionService:
    def __init__(self, model_name: str):
        self.model_name = model_name
        self._model = None

    def transcribe(self, audio_path: Path, transcript_json_path: Path, transcript_txt_path: Path) -> dict:
        if transcript_json_path.exists() and transcript_txt_path.exists():
            return json.loads(transcript_json_path.read_text(encoding="utf-8"))

        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise TranscriptionError("未安装 faster-whisper，请先执行：pip install faster-whisper") from exc

        try:
            if self._model is None:
                self._model = WhisperModel(self.model_name, device="auto", compute_type="auto")
            segments, info = self._model.transcribe(
                str(audio_path),
                language="zh",
                vad_filter=True,
                initial_prompt="这是一段中文课程录播，请准确转写专业术语、公式描述和课堂讲解。",
            )
            segment_list = []
            lines = []
            for segment in segments:
                text = segment.text.strip()
                if not text:
                    continue
                item = {
                    "start": float(segment.start),
                    "end": float(segment.end),
                    "text": text,
                }
                segment_list.append(item)
                lines.append(f"[{_format_ts(segment.start)} - {_format_ts(segment.end)}] {text}")

            payload = {
                "language": getattr(info, "language", "zh"),
                "duration": float(getattr(info, "duration", 0.0) or 0.0),
                "segments": segment_list,
            }
            transcript_json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            transcript_txt_path.write_text("\n".join(lines), encoding="utf-8")
            return payload
        except Exception as exc:
            raise TranscriptionError(f"语音转写失败：{exc}") from exc


def _format_ts(seconds: float) -> str:
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"
