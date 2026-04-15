import json
import tempfile
import unittest
from pathlib import Path

from services.rag import RagStore, chunk_transcript
from services.storage import VideoStore, safe_video_id


class CoreTest(unittest.TestCase):
    def test_safe_video_id_removes_unsafe_characters(self):
        self.assertEqual(safe_video_id("https://www.bilibili.com/video/BV1 23/?x=1"), "www.bilibili.com_video_BV1_23_x_1")

    def test_chunk_transcript_keeps_time_ranges(self):
        transcript = {
            "segments": [
                {"start": 0, "end": 5, "text": "第一段课程内容。"},
                {"start": 5, "end": 10, "text": "第二段课程内容。"},
            ]
        }
        chunks = chunk_transcript("BV1", "测试课程", transcript, max_chars=100)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["time_range"], "00:00 - 00:10")
        self.assertIn("第一段", chunks[0]["text"])

    def test_rag_build_and_search_with_hash_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = VideoStore(Path(temp_dir))
            rag = RagStore(Path(temp_dir), "missing-local-model")
            rag._get_embedding_model = lambda: None
            video_id = "BV_TEST"
            transcript = {
                "segments": [
                    {"start": 0, "end": 6, "text": "牛顿第二定律描述力和加速度的关系。"},
                    {"start": 6, "end": 12, "text": "唐诗强调意象和格律。"},
                ]
            }
            rag.build(video_id, "物理课程", transcript, store.chunks_path(video_id), store.vectors_path(video_id))
            results = rag.search(video_id, "加速度和力有什么关系", top_k=1)
            self.assertEqual(len(results), 1)
            self.assertIn("牛顿第二定律", results[0]["text"])
            self.assertTrue(store.chunks_path(video_id).exists())
            vectors = json.loads(store.vectors_path(video_id).read_text(encoding="utf-8"))
            self.assertIn("vectors", vectors)


if __name__ == "__main__":
    unittest.main()
