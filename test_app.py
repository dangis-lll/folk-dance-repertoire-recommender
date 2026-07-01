from pathlib import Path
import os
import tempfile
import unittest
import uuid
from unittest.mock import Mock, patch

from app import (
    app,
    bilibili_result_to_candidate,
    build_video_search_keyword,
    canonicalize_video_url,
    classify_dance_video,
    embed_url_for,
    find_duplicate_video,
    format_duration_minutes,
    init_db,
    normalize_title,
    parse_user_query,
    query_one,
    search_bilibili_candidates,
    score_video_work_match,
)


class FakeBilibiliResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self.payload = payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"{self.status_code} error")

    def json(self):
        return self.payload


class DanceRepertoireAppTest(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        self.tempdir = tempfile.TemporaryDirectory()
        app.config["DB_PATH"] = str(Path(self.tempdir.name) / "test_dance_repertoire.db")
        self.ctx = app.app_context()
        self.ctx.push()
        init_db(seed=True)
        self.client = app.test_client()

    def tearDown(self):
        self.ctx.pop()
        self.tempdir.cleanup()

    def test_seed_data_exists(self):
        self.assertGreaterEqual(query_one("SELECT COUNT(*) AS c FROM dance_work")["c"], 5)
        self.assertGreaterEqual(query_one("SELECT COUNT(*) AS c FROM expert_review")["c"], 5)

    def test_pages_load(self):
        self.assertEqual(self.client.get("/works").status_code, 200)
        self.assertEqual(self.client.get("/works/new").status_code, 200)
        self.assertEqual(self.client.get("/recommend").status_code, 200)
        self.assertEqual(self.client.get("/discover").status_code, 200)
        self.assertEqual(self.client.get("/quality").status_code, 200)
        self.assertIn('href="/works"', self.client.get("/works").data.decode("utf-8"))
        self.assertIn("data-work-select-filter", self.client.get("/discover").data.decode("utf-8"))

    def test_title_and_video_normalization(self):
        self.assertEqual(normalize_title("藏族舞《心迹》女子独舞完整版"), "心迹")
        self.assertEqual(format_duration_minutes(3.5), "3分30秒")
        self.assertEqual(format_duration_minutes(5), "5分钟")
        self.assertEqual(
            canonicalize_video_url("https://www.bilibili.com/video/BV1QK421k75Y/?spm_id_from=abc"),
            "https://www.bilibili.com/video/BV1QK421k75Y",
        )

    def test_bilibili_search_result_prefers_bvid_for_embed(self):
        candidate = bilibili_result_to_candidate(
            {
                "bvid": "BV1QK421k75Y",
                "arcurl": "https://www.bilibili.com/video/av123456",
                "title": '<em class="keyword">藏族舞</em> 剧目',
                "author": "teacher",
                "pic": "//i0.hdslb.com/example.jpg",
            }
        )
        embed_url = embed_url_for(candidate["url"])
        self.assertEqual(candidate["url"], "https://www.bilibili.com/video/BV1QK421k75Y")
        self.assertEqual(candidate["platform_video_id"], "BV1QK421k75Y")
        self.assertIn("player.bilibili.com/player.html", embed_url)
        self.assertIn("bvid=BV1QK421k75Y", embed_url)

    def test_bilibili_search_retries_once_after_412(self):
        payload = {
            "code": 0,
            "data": {
                "result": [
                    {
                        "bvid": "BV1RetryDance",
                        "arcurl": "https://www.bilibili.com/video/av999",
                        "title": "藏族舞 独舞",
                        "author": "teacher",
                    }
                ]
            },
        }
        fake_session = Mock()
        fake_session.get.side_effect = [
            FakeBilibiliResponse(),
            FakeBilibiliResponse(status_code=412),
            FakeBilibiliResponse(),
            FakeBilibiliResponse(payload=payload),
        ]
        with patch("app.requests.Session", return_value=fake_session), patch("app.time.sleep"):
            items, warning = search_bilibili_candidates("藏族舞", max_results=1)
        self.assertEqual(warning, "")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["url"], "https://www.bilibili.com/video/BV1RetryDance")
        self.assertEqual(fake_session.get.call_count, 4)

    def test_new_work_duplicate_requires_confirmation(self):
        before = query_one("SELECT COUNT(*) AS c FROM dance_work WHERE normalized_title = ?", ("心迹",))["c"]
        response = self.client.post(
            "/works/new",
            data={"title": "藏族舞《心迹》女子独舞", "ethnicity": "藏族", "form": "独舞", "dance_type": "民族民间舞"},
        )
        self.assertEqual(response.status_code, 200)
        page = response.data.decode("utf-8")
        self.assertIn("可能已有这个剧目", page)
        after_warning = query_one("SELECT COUNT(*) AS c FROM dance_work WHERE normalized_title = ?", ("心迹",))["c"]
        self.assertEqual(after_warning, before)

        confirmed = self.client.post(
            "/works/new",
            data={
                "title": "藏族舞《心迹》女子独舞",
                "ethnicity": "藏族",
                "form": "独舞",
                "dance_type": "民族民间舞",
                "force_create": "1",
            },
        )
        self.assertEqual(confirmed.status_code, 302)
        after_confirm = query_one("SELECT COUNT(*) AS c FROM dance_work WHERE normalized_title = ?", ("心迹",))["c"]
        self.assertEqual(after_confirm, before + 1)

    def test_direct_ingest_can_create_new_work(self):
        url = "https://www.bilibili.com/video/BV1NEWdance1"
        response = self.client.post(
            "/discover/ingest",
            data={
                "source_keyword": "藏族舞",
                "platform": "B站",
                "url": url,
                "title": "藏族舞 新剧目 独舞",
                "new_title": "新藏族独舞测试",
                "new_ethnicity": "藏族",
                "new_form": "独舞",
                "new_aliases": "测试别名",
            },
        )
        self.assertEqual(response.status_code, 302)
        work = query_one("SELECT * FROM dance_work WHERE title = ?", ("新藏族独舞测试",))
        self.assertIsNotNone(work)
        version = query_one("SELECT * FROM dance_video_version WHERE platform_video_id = ?", ("BV1NEWdance1",))
        self.assertIsNotNone(version)
        self.assertEqual(version["work_id"], work["id"])
        self.assertIsNotNone(find_duplicate_video("https://m.bilibili.com/video/BV1NEWdance1"))

    def test_direct_ingest_can_attach_existing_work_and_dedup_video(self):
        work = query_one("SELECT * FROM dance_work WHERE title = ?", ("心迹",))
        url = "https://www.youtube.com/watch?v=abc123XYZ_0"
        first = self.client.post(
            "/discover/ingest",
            data={
                "source_keyword": "心迹",
                "platform": "YouTube",
                "url": url,
                "title": "folk dance solo choreography",
                "work_id": work["id"],
            },
        )
        second = self.client.post(
            "/discover/ingest",
            data={
                "source_keyword": "心迹",
                "platform": "YouTube",
                "url": "https://youtu.be/abc123XYZ_0",
                "title": "duplicate link",
                "work_id": work["id"],
            },
        )
        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        count = query_one("SELECT COUNT(*) AS c FROM dance_video_version WHERE platform_video_id = ?", ("abc123XYZ_0",))["c"]
        self.assertEqual(count, 1)

    def test_recommend_api_returns_dimensions_and_log_snapshot(self):
        response = self.client.post(
            "/api/recommend",
            json={"query": "18 year old female exam medium flexibility weak technique three months"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("intent", data)
        self.assertIn("recommendations", data)
        self.assertIn("missingFields", data)
        self.assertIn("directMatches", data)
        self.assertGreaterEqual(len(data["recommendations"]), 1)
        self.assertIn("logId", data)
        self.assertIn("dimensions", data["recommendations"][0])
        self.assertIn("retrieval_fit", data["recommendations"][0]["dimensions"])
        log = query_one("SELECT * FROM recommendation_log ORDER BY created_at DESC LIMIT 1")
        self.assertTrue(log["recommended_items_json"])

    def test_recommend_page_can_lookup_work_by_title(self):
        response = self.client.post("/recommend", data={"user_query": "心迹"})
        self.assertEqual(response.status_code, 200)
        page = response.data.decode("utf-8")
        self.assertIn("数据库中找到的剧目", page)
        self.assertIn("心迹", page)
        self.assertIn("缺少这些选剧条件", page)
        self.assertIn("搜索/更新视频资料", page)
        self.assertIn("/discover?work_id=", page)

        api_response = self.client.post("/api/recommend", json={"query": "心迹"})
        data = api_response.get_json()
        self.assertGreaterEqual(len(data["directMatches"]), 1)
        self.assertEqual(data["directMatches"][0]["work"]["title"], "心迹")
        self.assertIn("age", data["intent"])
        self.assertIn("年龄", data["missingFields"])

    def test_deepseek_unknown_does_not_override_rule_parse(self):
        fake_response = Mock()
        fake_response.raise_for_status.return_value = None
        fake_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": '{"ethnicity":"unknown","form":"unknown","goal":"exam"}',
                    }
                }
            ]
        }
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}), patch("app.requests.post", return_value=fake_response):
            intent = parse_user_query("18岁女生，藏族独舞，参加艺考")
        self.assertEqual(intent["ethnicity"], "藏族")
        self.assertEqual(intent["form"], "独舞")
        self.assertEqual(intent["goal"], "exam")

    def test_recommend_api_handles_work_without_reviews(self):
        title = f"藏族冷门独舞测试 {uuid.uuid4().hex[:8]}"
        self.client.post(
            "/works/new",
            data={"title": title, "ethnicity": "藏族", "form": "独舞", "dance_type": "民族民间舞"},
        )
        response = self.client.post("/api/recommend", json={"query": "藏族 独舞 艺考"})
        self.assertEqual(response.status_code, 200)

    def test_search_index_and_feedback_loop(self):
        indexed = query_one("SELECT COUNT(*) AS c FROM work_search_fts")["c"]
        works = query_one("SELECT COUNT(*) AS c FROM dance_work")["c"]
        self.assertEqual(indexed, works)

        response = self.client.post(
            "/api/recommend",
            json={"query": "藏族 独舞 艺考 软度中等 技巧偏弱"},
        )
        data = response.get_json()
        self.assertGreaterEqual(len(data["recommendations"]), 1)
        work_id = data["recommendations"][0]["work"]["id"]
        feedback_response = self.client.post(
            "/recommendation-feedback",
            data={"log_id": data["logId"], "work_id": work_id, "rating": "fit"},
        )
        self.assertEqual(feedback_response.status_code, 302)
        self.assertEqual(query_one("SELECT COUNT(*) AS c FROM recommendation_feedback")["c"], 1)

    def test_clear_recommendation_logs(self):
        self.client.post(
            "/api/recommend",
            json={"query": "18 year old female exam medium flexibility weak technique three months"},
        )
        self.assertGreater(query_one("SELECT COUNT(*) AS c FROM recommendation_log")["c"], 0)
        response = self.client.post("/logs/clear")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(query_one("SELECT COUNT(*) AS c FROM recommendation_log")["c"], 0)

    def test_merge_work_moves_videos_and_deletes_source(self):
        self.client.post(
            "/works/new",
            data={"title": "Merge Target Work", "ethnicity": "Test", "form": "Solo", "dance_type": "Dance"},
        )
        self.client.post(
            "/works/new",
            data={"title": "Merge Source Work", "ethnicity": "Test", "form": "Solo", "dance_type": "Dance"},
        )
        target = query_one("SELECT * FROM dance_work WHERE title = ?", ("Merge Target Work",))
        source = query_one("SELECT * FROM dance_work WHERE title = ?", ("Merge Source Work",))
        self.client.post(
            "/discover/ingest",
            data={
                "platform": "B站",
                "url": "https://www.bilibili.com/video/BVMERGE12345",
                "title": "merge source video dance",
                "work_id": source["id"],
            },
        )
        response = self.client.post(f"/works/{source['id']}/merge", data={"target_work_id": target["id"]})
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(query_one("SELECT * FROM dance_work WHERE id = ?", (source["id"],)))
        moved_video = query_one("SELECT * FROM dance_video_version WHERE platform_video_id = ?", ("BVMERGE12345",))
        self.assertEqual(moved_video["work_id"], target["id"])

    def test_delete_work_removes_related_records(self):
        title = f"Delete Me Work {uuid.uuid4().hex[:8]}"
        self.client.post(
            "/works/new",
            data={"title": title, "ethnicity": "Test", "form": "Solo", "dance_type": "Dance"},
        )
        work = query_one("SELECT * FROM dance_work WHERE title = ?", (title,))
        delete_response = self.client.post(f"/works/{work['id']}/delete")
        self.assertEqual(delete_response.status_code, 302)
        self.assertIsNone(query_one("SELECT * FROM dance_work WHERE id = ?", (work["id"],)))

        visible_page = self.client.get("/works").data.decode("utf-8")
        self.assertNotIn(title, visible_page)

    def test_dance_classifier(self):
        is_dance, confidence, _reason = classify_dance_video("dance exam", "folk dance solo choreography", "")
        self.assertTrue(is_dance)
        self.assertGreaterEqual(confidence, 0.35)
        is_dance, _confidence, _reason = classify_dance_video("game", "game commentary episode", "")
        self.assertFalse(is_dance)

    def test_video_search_keyword_uses_work_context(self):
        work = query_one("SELECT * FROM dance_work WHERE title = ?", ("心迹",))
        keyword = build_video_search_keyword(work)
        self.assertIn("藏族舞", keyword)
        self.assertIn("心迹", keyword)
        self.assertIn("女子独舞", keyword)
        self.assertIn("剧目", keyword)

        match_score, _reason = score_video_work_match(
            work,
            {"title": "藏族舞《心迹》女子独舞完整版", "uploader": "dance teacher"},
            keyword,
        )
        unrelated_score, _reason = score_video_work_match(
            work,
            {"title": "心迹 原创歌曲 MV", "uploader": "music"},
            "心迹",
        )
        self.assertGreater(match_score, unrelated_score)

    def test_discover_with_work_context_sorts_current_work_first(self):
        work = query_one("SELECT * FROM dance_work WHERE title = ?", ("心迹",))
        payload = {
            "code": 0,
            "data": {
                "result": [
                    {
                        "bvid": "BVSONG000001",
                        "title": "心迹 原创歌曲 MV",
                        "author": "music",
                    },
                    {
                        "bvid": "BVDANCE00001",
                        "title": "藏族舞《心迹》女子独舞完整版 剧目",
                        "author": "dance teacher",
                    },
                ]
            },
        }
        with patch("app.load_bilibili_search_json", return_value=(payload, "")):
            response = self.client.post(
                "/discover",
                data={"action": "search", "work_id": work["id"], "keyword": build_video_search_keyword(work)},
            )
        page = response.data.decode("utf-8")
        self.assertLess(page.index("BVDANCE00001"), page.index("BVSONG000001"))
        self.assertIn("当前剧目", page)

    def test_discover_from_work_page_runs_search_automatically(self):
        work = query_one("SELECT * FROM dance_work WHERE title = ?", ("草原上的额吉",))
        payload = {
            "code": 0,
            "data": {
                "result": [
                    {
                        "bvid": "BVEJIDANCE01",
                        "title": "蒙古族舞《草原上的额吉》女子独舞完整版",
                        "author": "dance teacher",
                    }
                ]
            },
        }
        with patch("app.load_bilibili_search_json", return_value=(payload, "")):
            response = self.client.get(f"/discover?work_id={work['id']}")
        page = response.data.decode("utf-8")
        self.assertIn("BVEJIDANCE01", page)
        self.assertIn("蒙古族舞 草原上的额吉 女子独舞", page)

    def test_body_condition_parser_and_teacher_label(self):
        intent = parse_user_query("18岁女生，软度中等，力量一般，控制弱，协调性弱，耐力好，技巧偏弱")
        self.assertEqual(intent["flexibilityLevel"], "medium")
        self.assertEqual(intent["strengthLevel"], "medium")
        self.assertEqual(intent["controlLevel"], "weak")
        self.assertEqual(intent["coordinationLevel"], "weak")
        self.assertEqual(intent["staminaLevel"], "high")
        self.assertEqual(intent["techniqueLevel"], "weak")

        work = query_one("SELECT * FROM dance_work LIMIT 1")
        page = self.client.get(f"/works/{work['id']}/reviews/new").data.decode("utf-8")
        self.assertIn("是否需要专业教师指导", page)
        self.assertNotIn("需要专业教师 1/0", page)
        self.assertIn("rating-scale", page)
        self.assertIn('name="flexibility_score" type="radio" value="5"', page)
        self.assertNotIn('max="20"', page)

    def test_review_scores_are_clamped_to_five(self):
        work = query_one("SELECT * FROM dance_work LIMIT 1")
        expert = query_one("SELECT * FROM expert LIMIT 1")
        response = self.client.post(
            f"/works/{work['id']}/reviews/new",
            data={
                "expert_id": expert["id"],
                "flexibility_score": "20",
                "strength_score": "0",
                "control_score": "4",
            },
        )
        self.assertEqual(response.status_code, 302)
        row = query_one(
            """
            SELECT flexibility_score, strength_score, control_score
            FROM expert_review
            WHERE work_id = ? AND flexibility_score = 5 AND strength_score = 1 AND control_score = 4
            LIMIT 1
            """,
            (work["id"],),
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["flexibility_score"], 5)
        self.assertEqual(row["strength_score"], 1)
        self.assertEqual(row["control_score"], 4)

    def test_single_annotator_review_does_not_require_expert_id(self):
        work = query_one("SELECT * FROM dance_work LIMIT 1")
        response = self.client.post(
            f"/works/{work['id']}/reviews/new",
            data={
                "flexibility_score": "4",
                "summary": "单人标注测试",
            },
        )
        self.assertEqual(response.status_code, 302)
        row = query_one(
            "SELECT summary, expert_id FROM expert_review WHERE work_id = ? AND summary = ? LIMIT 1",
            (work["id"], "单人标注测试"),
        )
        self.assertIsNotNone(row)
        self.assertTrue(row["expert_id"])

    def test_export_database_downloads_sqlite_file(self):
        response = self.client.get("/export/db")
        try:
            self.assertEqual(response.status_code, 200)
            disposition = response.headers.get("Content-Disposition", "")
            self.assertIn("attachment", disposition)
            self.assertIn(".db", disposition)
            self.assertTrue(response.data.startswith(b"SQLite format 3"))
        finally:
            response.close()


if __name__ == "__main__":
    unittest.main()
