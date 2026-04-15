from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent


def _path_from_env(name: str, default: str) -> Path:
    value = os.getenv(name, default)
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = ROOT_DIR / path
    return path


@dataclass(frozen=True)
class Settings:
    llm_provider: str = os.getenv("LLM_PROVIDER", "ollama")
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct")
    openai_base_url: str = os.getenv("OPENAI_COMPAT_BASE_URL", "http://127.0.0.1:8080/v1")
    openai_model: str = os.getenv("OPENAI_COMPAT_MODEL", "Qwen1.5-7B-Chat")
    openai_api_key: str = os.getenv("OPENAI_COMPAT_API_KEY", "")
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
    whisper_model: str = os.getenv("WHISPER_MODEL", "small")
    data_dir: Path = _path_from_env("DATA_DIR", "data")
    bilibili_cookie_path: Path = _path_from_env("BILIBILI_COOKIE_PATH", "data/bilibili-cookies.txt")

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "videos").mkdir(parents=True, exist_ok=True)


settings = Settings()
