from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path

import requests

from services.models import SearchResult
from services.storage import safe_video_id


class BilibiliError(RuntimeError):
    pass


class BilibiliClient:
    def __init__(self, cookie_path: Path, timeout: int = 20):
        self.cookie_path = cookie_path
        self.timeout = timeout

    def search(self, keyword: str, limit: int = 10) -> list[SearchResult]:
        direct = self._direct_video_result(keyword)
        if direct:
            return [direct]

        errors: list[str] = []
        try:
            return self._search_public_api(keyword, limit)
        except Exception as exc:
            errors.append(str(exc))
            logging.warning("B站公开搜索接口失败，尝试 yt-dlp 搜索: %s", exc)
        try:
            return self._search_ytdlp(keyword, limit)
        except Exception as exc:
            errors.append(str(exc))
            raise BilibiliError(
                "B站搜索被风控或网络拒绝。公开视频可直接粘贴 B站视频链接/BV号处理；"
                "如需模糊搜索，请先登录 B站并导出 cookies。详情："
                + " | ".join(error for error in errors if error)
            ) from exc

    def _search_public_api(self, keyword: str, limit: int) -> list[SearchResult]:
        url = "https://api.bilibili.com/x/web-interface/search/type"
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.bilibili.com",
        }
        response = requests.get(
            url,
            params={"search_type": "video", "keyword": keyword, "page": 1},
            headers=headers,
            cookies=self._load_netscape_cookies(),
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 0:
            raise BilibiliError(payload.get("message") or "B站搜索失败")

        items = (payload.get("data") or {}).get("result") or []
        results: list[SearchResult] = []
        for item in items[:limit]:
            bvid = item.get("bvid") or ""
            arcurl = item.get("arcurl") or (f"https://www.bilibili.com/video/{bvid}" if bvid else "")
            title = _strip_html(item.get("title") or "")
            author = item.get("author") or item.get("typename") or "未知 UP"
            cover = item.get("pic") or ""
            if cover.startswith("//"):
                cover = "https:" + cover
            results.append(
                SearchResult(
                    video_id=safe_video_id(bvid or arcurl),
                    title=title,
                    author=author,
                    duration=item.get("duration") or "",
                    cover=cover,
                    url=arcurl,
                    description=_strip_html(item.get("description") or ""),
                )
            )
        return results

    def _search_ytdlp(self, keyword: str, limit: int) -> list[SearchResult]:
        command = ["yt-dlp", "--dump-single-json", f"bilisearch{limit}:{keyword}"]
        if self.cookie_path.exists():
            command[1:1] = ["--cookies", str(self.cookie_path)]
        try:
            completed = subprocess.run(command, check=True, capture_output=True, text=True, timeout=60)
        except FileNotFoundError as exc:
            raise BilibiliError("未找到 yt-dlp，请先安装：pip install yt-dlp") from exc
        except subprocess.CalledProcessError as exc:
            raise BilibiliError(exc.stderr.strip() or "yt-dlp 搜索失败") from exc

        payload = json.loads(completed.stdout)
        entries = payload.get("entries") or []
        results: list[SearchResult] = []
        for item in entries[:limit]:
            url = item.get("webpage_url") or item.get("url") or ""
            video_id = safe_video_id(item.get("id") or url)
            duration = item.get("duration")
            results.append(
                SearchResult(
                    video_id=video_id,
                    title=item.get("title") or "未命名视频",
                    author=item.get("uploader") or "未知 UP",
                    duration=_format_duration(duration),
                    cover=item.get("thumbnail") or "",
                    url=url,
                    description=item.get("description") or "",
                )
            )
        return results

    def _direct_video_result(self, value: str) -> SearchResult | None:
        text = value.strip()
        bvid_match = re.search(r"(BV[a-zA-Z0-9]{8,})", text)
        if "bilibili.com/video/" not in text and not bvid_match:
            return None

        bvid = bvid_match.group(1) if bvid_match else safe_video_id(text)
        url = text if text.startswith("http") else f"https://www.bilibili.com/video/{bvid}"
        return SearchResult(
            video_id=safe_video_id(bvid),
            title=f"B站视频 {bvid}",
            author="待下载后识别",
            duration="",
            cover="",
            url=url,
            description="用户直接输入的视频链接",
        )

    def download_audio(self, url: str, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists() and output_path.stat().st_size > 0:
            return output_path

        output_template = str(output_path.with_suffix(".%(ext)s"))
        command = [
            "yt-dlp",
            "--no-playlist",
            "-x",
            "--audio-format",
            "mp3",
            "--audio-quality",
            "0",
            "-o",
            output_template,
            url,
        ]
        if self.cookie_path.exists():
            command[1:1] = ["--cookies", str(self.cookie_path)]

        try:
            subprocess.run(command, check=True, capture_output=True, text=True, timeout=60 * 60)
        except FileNotFoundError as exc:
            raise BilibiliError("未找到 yt-dlp，请先安装：pip install yt-dlp") from exc
        except subprocess.CalledProcessError as exc:
            raise BilibiliError(exc.stderr.strip() or "音频下载失败") from exc

        if output_path.exists():
            return output_path

        candidates = sorted(output_path.parent.glob("audio.*"))
        if candidates:
            candidates[0].rename(output_path)
            return output_path
        raise BilibiliError("音频下载完成后未找到输出文件")

    def _load_netscape_cookies(self) -> dict[str, str]:
        if not self.cookie_path.exists():
            return {}
        cookies: dict[str, str] = {}
        for line in self.cookie_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 7:
                cookies[parts[5]] = parts[6]
        return cookies


def _strip_html(value: str) -> str:
    return value.replace("<em class=\"keyword\">", "").replace("</em>", "").strip()


def _format_duration(seconds: int | float | None) -> str:
    if seconds is None:
        return ""
    seconds = int(seconds)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"
