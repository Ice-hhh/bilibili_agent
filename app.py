from __future__ import annotations

import json
import logging
from pathlib import Path
from urllib.parse import unquote

from flask import Flask, Response, jsonify, request, send_from_directory
from flask_cors import CORS
import requests

from services.bilibili import BilibiliClient, BilibiliError
from services.config import settings
from services.llm import create_llm_client
from services.rag import RagStore
from services.storage import VideoStore
from services.tasks import TaskManager
from services.transcribe import TranscriptionService


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

BASE_DIR = Path(__file__).resolve().parent

app = Flask(__name__, static_folder="static", template_folder="templates")
CORS(app, resources={r"/api/*": {"origins": "*"}})

video_store = VideoStore(settings.data_dir)
bilibili = BilibiliClient(cookie_path=settings.bilibili_cookie_path)
rag_store = RagStore(settings.data_dir, settings.embedding_model)
transcriber = TranscriptionService(settings.whisper_model)
llm = create_llm_client(settings)
tasks = TaskManager(video_store, bilibili, transcriber, rag_store)


@app.get("/")
def index():
    return send_from_directory(app.template_folder, "index.html")


@app.get("/static/<path:filename>")
def static_files(filename: str):
    return send_from_directory(app.static_folder, filename)


@app.get("/api/health")
def health():
    return jsonify(
        {
            "ok": True,
            "llm_provider": settings.llm_provider,
            "ollama_base_url": settings.ollama_base_url,
            "ollama_model": settings.ollama_model,
            "openai_base_url": settings.openai_base_url,
            "openai_model": settings.openai_model,
            "embedding_model": settings.embedding_model,
            "whisper_model": settings.whisper_model,
            "data_dir": str(settings.data_dir),
        }
    )


@app.post("/api/search")
def search():
    payload = request.get_json(silent=True) or {}
    keyword = (payload.get("keyword") or "").strip()
    if not keyword:
        return jsonify({"error": "请输入搜索关键词"}), 400

    try:
        results = bilibili.search(keyword)
        return jsonify({"results": [item.to_dict() for item in results]})
    except BilibiliError as exc:
        return jsonify({"error": str(exc)}), 502


@app.post("/api/videos/process")
def process_video():
    payload = request.get_json(silent=True) or {}
    url = (payload.get("url") or "").strip()
    video_id = (payload.get("video_id") or "").strip()
    title = (payload.get("title") or "").strip()
    author = (payload.get("author") or "").strip()
    cover = (payload.get("cover") or "").strip()

    if not url and not video_id:
        return jsonify({"error": "缺少视频 URL 或 video_id"}), 400

    task_id = tasks.submit(
        {
            "url": url,
            "video_id": video_id,
            "title": title,
            "author": author,
            "cover": cover,
        }
    )
    return jsonify({"task_id": task_id})


@app.get("/api/tasks/<task_id>/events")
def task_events(task_id: str):
    def stream():
        for event in tasks.subscribe(task_id):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return Response(stream(), mimetype="text/event-stream", headers={"X-Accel-Buffering": "no"})


@app.get("/api/videos")
def videos():
    return jsonify({"videos": video_store.list_processed_videos()})


@app.get("/api/image-proxy")
def image_proxy():
    image_url = unquote((request.args.get("url") or "").strip())
    if not image_url.startswith(("http://", "https://")):
        return Response(status=400)

    try:
        upstream = requests.get(
            image_url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://www.bilibili.com",
            },
            timeout=10,
        )
        upstream.raise_for_status()
    except requests.RequestException:
        return Response(status=404)

    content_type = upstream.headers.get("Content-Type", "image/jpeg")
    return Response(upstream.content, mimetype=content_type)


@app.get("/api/auth/bilibili/status")
def bilibili_auth_status():
    cookie_path = settings.bilibili_cookie_path
    return jsonify(
        {
            "cookie_path": str(cookie_path),
            "has_cookie_file": cookie_path.exists(),
            "login_url": "https://www.bilibili.com",
            "note": "公开视频无需登录。需要登录的视频可导出 Netscape cookies 到该路径后重试。",
        }
    )


@app.post("/api/chat")
def chat():
    payload = request.get_json(silent=True) or {}
    video_id = (payload.get("video_id") or "").strip()
    message = (payload.get("message") or "").strip()

    if not video_id:
        return jsonify({"error": "请先选择并处理一个视频"}), 400
    if not message:
        return jsonify({"error": "请输入问题"}), 400

    video = video_store.get_video(video_id)
    if not video or not video.get("processed"):
        return jsonify({"error": "该视频还没有完成处理"}), 404

    contexts = rag_store.search(video_id, message, top_k=5)
    prompt = llm.build_rag_prompt(video.get("title", ""), contexts, message)

    def generate():
        for chunk in llm.generate_stream(prompt):
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

    return Response(generate(), mimetype="text/event-stream", headers={"X-Accel-Buffering": "no"})


if __name__ == "__main__":
    settings.ensure_dirs()
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True, use_reloader=False)
