import csv
import hashlib
import html
import json
import os
import re
import sqlite3
import time
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus, urlencode

import requests
from flask import Flask, g, jsonify, redirect, render_template, request, url_for


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "dance_repertoire.db"
BILIBILI_SEARCH_API = "https://api.bilibili.com/x/web-interface/search/type"

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret")


def app_mode():
    return os.environ.get("APP_MODE", "internal").strip().lower() or "internal"


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config.get("DB_PATH", DB_PATH))
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_error):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def now():
    return datetime.utcnow().isoformat(timespec="seconds")


def new_id():
    return str(uuid.uuid4())


def execute(sql, params=()):
    db = get_db()
    db.execute(sql, params)
    db.commit()


def query_all(sql, params=()):
    return get_db().execute(sql, params).fetchall()


def query_one(sql, params=()):
    return get_db().execute(sql, params).fetchone()


SCHEMA = """
CREATE TABLE IF NOT EXISTS dance_work (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  normalized_title TEXT DEFAULT '',
  aliases TEXT DEFAULT '',
  ethnicity TEXT DEFAULT '',
  region TEXT DEFAULT '',
  dance_type TEXT DEFAULT '',
  form TEXT DEFAULT '',
  gender_tendency TEXT DEFAULT '',
  duration_min REAL,
  duration_max REAL,
  props TEXT DEFAULT '',
  music_info TEXT DEFAULT '',
  premiere_info TEXT DEFAULT '',
  description TEXT DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dance_work_alias (
  id TEXT PRIMARY KEY,
  work_id TEXT NOT NULL,
  alias TEXT NOT NULL,
  normalized_alias TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(work_id) REFERENCES dance_work(id)
);

CREATE TABLE IF NOT EXISTS dance_video_version (
  id TEXT PRIMARY KEY,
  work_id TEXT NOT NULL,
  platform TEXT DEFAULT '',
  url TEXT NOT NULL,
  canonical_url TEXT DEFAULT '',
  platform_video_id TEXT DEFAULT '',
  title TEXT DEFAULT '',
  normalized_title TEXT DEFAULT '',
  uploader TEXT DEFAULT '',
  performer TEXT DEFAULT '',
  institution TEXT DEFAULT '',
  event_name TEXT DEFAULT '',
  publish_date TEXT DEFAULT '',
  duration_seconds INTEGER,
  thumbnail_url TEXT DEFAULT '',
  screenshot_url TEXT DEFAULT '',
  is_full_version INTEGER DEFAULT 0,
  is_teaching_version INTEGER DEFAULT 0,
  quality_score INTEGER DEFAULT 3,
  notes TEXT DEFAULT '',
  status TEXT DEFAULT 'active',
  created_at TEXT NOT NULL,
  updated_at TEXT DEFAULT '',
  FOREIGN KEY(work_id) REFERENCES dance_work(id)
);

CREATE TABLE IF NOT EXISTS expert (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  title TEXT DEFAULT '',
  organization TEXT DEFAULT '',
  bio TEXT DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS expert_review (
  id TEXT PRIMARY KEY,
  work_id TEXT NOT NULL,
  version_id TEXT,
  expert_id TEXT NOT NULL,
  status TEXT DEFAULT 'submitted',
  flexibility_score INTEGER DEFAULT 3,
  strength_score INTEGER DEFAULT 3,
  control_score INTEGER DEFAULT 3,
  explosiveness_score INTEGER DEFAULT 3,
  stamina_score INTEGER DEFAULT 3,
  coordination_score INTEGER DEFAULT 3,
  footwork_score INTEGER DEFAULT 3,
  turn_jump_score INTEGER DEFAULT 3,
  entry_threshold_score INTEGER DEFAULT 3,
  suggested_experience_years REAL DEFAULT 2,
  rehearsal_weeks_min INTEGER DEFAULT 8,
  rehearsal_weeks_max INTEGER DEFAULT 12,
  needs_professional_teacher INTEGER DEFAULT 1,
  music_access_difficulty INTEGER DEFAULT 3,
  costume_access_difficulty INTEGER DEFAULT 3,
  character_score INTEGER DEFAULT 3,
  emotional_range_score INTEGER DEFAULT 3,
  style_purity_score INTEGER DEFAULT 3,
  rhythm_difficulty_score INTEGER DEFAULT 3,
  stage_blocking_score INTEGER DEFAULT 3,
  creative_space_score INTEGER DEFAULT 3,
  originality_score INTEGER DEFAULT 3,
  exam_suitability_score INTEGER DEFAULT 3,
  competition_suitability_score INTEGER DEFAULT 3,
  teaching_suitability_score INTEGER DEFAULT 3,
  gala_suitability_score INTEGER DEFAULT 3,
  suitable_age_min INTEGER DEFAULT 14,
  suitable_age_max INTEGER DEFAULT 22,
  suitable_level TEXT DEFAULT '中级',
  summary TEXT DEFAULT '',
  strengths TEXT DEFAULT '',
  risks TEXT DEFAULT '',
  recommendation_note TEXT DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(work_id) REFERENCES dance_work(id),
  FOREIGN KEY(version_id) REFERENCES dance_video_version(id),
  FOREIGN KEY(expert_id) REFERENCES expert(id)
);

CREATE TABLE IF NOT EXISTS recommendation_log (
  id TEXT PRIMARY KEY,
  user_query TEXT NOT NULL,
  parsed_intent TEXT NOT NULL,
  recommended_work_ids TEXT NOT NULL,
  recommended_items_json TEXT DEFAULT '',
  llm_response TEXT DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recommendation_feedback (
  id TEXT PRIMARY KEY,
  log_id TEXT NOT NULL,
  work_id TEXT NOT NULL,
  rating TEXT NOT NULL,
  reason TEXT DEFAULT '',
  created_at TEXT NOT NULL
);
"""


SEED_WORKS = [
    {
        "title": "心迹",
        "aliases": "藏族舞心迹,女子独舞心迹",
        "ethnicity": "藏族",
        "region": "西藏",
        "dance_type": "民族民间舞",
        "form": "独舞",
        "gender_tendency": "女",
        "duration_min": 4,
        "duration_max": 6,
        "props": "哈达",
        "music_info": "藏族风格音乐",
        "premiere_info": "常见艺考与比赛改编剧目",
        "description": "以细腻情绪和藏族体态控制见长，适合有表达空间的女子独舞。",
    },
    {
        "title": "草原上的额吉",
        "aliases": "蒙古族舞额吉,草原额吉",
        "ethnicity": "蒙古族",
        "region": "内蒙古",
        "dance_type": "民族民间舞",
        "form": "独舞",
        "gender_tendency": "女",
        "duration_min": 4,
        "duration_max": 5,
        "props": "",
        "music_info": "蒙古族抒情音乐",
        "premiere_info": "常见教学与比赛版本",
        "description": "强调胸背开合、上身韵律和情感叙事，整体技术门槛中等。",
    },
    {
        "title": "花儿为什么这样红",
        "aliases": "维吾尔族独舞花儿为什么这样红",
        "ethnicity": "维吾尔族",
        "region": "新疆",
        "dance_type": "民族民间舞",
        "form": "独舞",
        "gender_tendency": "女",
        "duration_min": 3.5,
        "duration_max": 5,
        "props": "",
        "music_info": "新疆风格音乐",
        "premiere_info": "常见舞台改编剧目",
        "description": "节奏和眼神表达要求较高，适合节奏感与表情能力较强的学生。",
    },
    {
        "title": "雀之灵片段",
        "aliases": "傣族舞雀之灵,孔雀舞片段",
        "ethnicity": "傣族",
        "region": "云南",
        "dance_type": "民族民间舞",
        "form": "独舞",
        "gender_tendency": "女",
        "duration_min": 3,
        "duration_max": 5,
        "props": "",
        "music_info": "傣族孔雀舞音乐",
        "premiere_info": "经典剧目片段",
        "description": "审美辨识度高，但经典程度高，二度创作和个人条件匹配很重要。",
    },
    {
        "title": "长鼓行",
        "aliases": "朝鲜族长鼓舞,长鼓独舞",
        "ethnicity": "朝鲜族",
        "region": "东北",
        "dance_type": "民族民间舞",
        "form": "独舞",
        "gender_tendency": "不限",
        "duration_min": 4,
        "duration_max": 6,
        "props": "长鼓",
        "music_info": "朝鲜族长鼓舞音乐",
        "premiere_info": "常见课堂与比赛改编剧目",
        "description": "道具和节奏配合是核心，适合协调性好、节奏稳定的学生。",
    },
]


def init_db(seed=False):
    db = get_db()
    db.executescript(SCHEMA)
    db.commit()
    ensure_schema_migrations()
    if seed and query_one("SELECT COUNT(*) AS c FROM dance_work")["c"] == 0:
        seed_data()
        backfill_normalized_data()


def ensure_schema_migrations():
    ensure_columns(
        "dance_work",
        {
            "normalized_title": "TEXT DEFAULT ''",
        },
    )
    ensure_columns(
        "dance_video_version",
        {
            "canonical_url": "TEXT DEFAULT ''",
            "platform_video_id": "TEXT DEFAULT ''",
            "normalized_title": "TEXT DEFAULT ''",
            "status": "TEXT DEFAULT 'active'",
            "updated_at": "TEXT DEFAULT ''",
        },
    )
    ensure_columns(
        "recommendation_log",
        {
            "recommended_items_json": "TEXT DEFAULT ''",
        },
    )
    get_db().executescript(
        """
        CREATE TABLE IF NOT EXISTS dance_work_alias (
          id TEXT PRIMARY KEY,
          work_id TEXT NOT NULL,
          alias TEXT NOT NULL,
          normalized_alias TEXT NOT NULL,
          created_at TEXT NOT NULL,
          FOREIGN KEY(work_id) REFERENCES dance_work(id)
        );
        CREATE INDEX IF NOT EXISTS idx_work_normalized_title ON dance_work(normalized_title);
        CREATE INDEX IF NOT EXISTS idx_work_ethnicity_form ON dance_work(ethnicity, form);
        DROP INDEX IF EXISTS idx_work_status;
        CREATE INDEX IF NOT EXISTS idx_alias_normalized ON dance_work_alias(normalized_alias);
        CREATE INDEX IF NOT EXISTS idx_alias_work_id ON dance_work_alias(work_id);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_video_platform_video_id
          ON dance_video_version(platform, platform_video_id)
          WHERE platform_video_id != '';
        CREATE INDEX IF NOT EXISTS idx_video_canonical_url ON dance_video_version(canonical_url);
        CREATE INDEX IF NOT EXISTS idx_video_work_id ON dance_video_version(work_id);
        CREATE INDEX IF NOT EXISTS idx_review_work_id ON expert_review(work_id);
        CREATE INDEX IF NOT EXISTS idx_recommendation_created_at ON recommendation_log(created_at);
        CREATE TABLE IF NOT EXISTS recommendation_feedback (
          id TEXT PRIMARY KEY,
          log_id TEXT NOT NULL,
          work_id TEXT NOT NULL,
          rating TEXT NOT NULL,
          reason TEXT DEFAULT '',
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_feedback_log_work ON recommendation_feedback(log_id, work_id);
        CREATE INDEX IF NOT EXISTS idx_feedback_work_rating ON recommendation_feedback(work_id, rating);
        """
    )
    get_db().commit()
    ensure_work_search_index()
    remove_obsolete_work_state_columns()
    repair_obsolete_foreign_key_names()
    backfill_normalized_data()


def ensure_work_search_index():
    db = get_db()
    try:
        db.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS work_search_fts
            USING fts5(work_id UNINDEXED, title, aliases, attributes, expert_text, video_text, tokenize='trigram')
            """
        )
    except sqlite3.OperationalError:
        db.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS work_search_fts
            USING fts5(work_id UNINDEXED, title, aliases, attributes, expert_text, video_text)
            """
        )
    db.commit()


def ensure_columns(table, columns):
    existing = {row["name"] for row in query_all(f"PRAGMA table_info({table})")}
    for name, definition in columns.items():
        if name not in existing:
            execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def remove_obsolete_work_state_columns():
    columns = [row["name"] for row in query_all("PRAGMA table_info(dance_work)")]
    obsolete = {"status", "merged_into_work_id"}
    if not obsolete.intersection(columns):
        return
    keep_columns = [name for name in columns if name not in obsolete]
    db = get_db()
    db.execute("PRAGMA foreign_keys = OFF")
    db.execute("PRAGMA legacy_alter_table = ON")
    db.execute("DROP INDEX IF EXISTS idx_work_status")
    db.execute("ALTER TABLE dance_work RENAME TO dance_work_old")
    db.execute(
        """
        CREATE TABLE dance_work (
          id TEXT PRIMARY KEY,
          title TEXT NOT NULL,
          normalized_title TEXT DEFAULT '',
          aliases TEXT DEFAULT '',
          ethnicity TEXT DEFAULT '',
          region TEXT DEFAULT '',
          dance_type TEXT DEFAULT '',
          form TEXT DEFAULT '',
          gender_tendency TEXT DEFAULT '',
          duration_min REAL,
          duration_max REAL,
          props TEXT DEFAULT '',
          music_info TEXT DEFAULT '',
          premiere_info TEXT DEFAULT '',
          description TEXT DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )
    names = ", ".join(keep_columns)
    db.execute(f"INSERT INTO dance_work ({names}) SELECT {names} FROM dance_work_old")
    db.execute("DROP TABLE dance_work_old")
    db.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_work_normalized_title ON dance_work(normalized_title);
        CREATE INDEX IF NOT EXISTS idx_work_ethnicity_form ON dance_work(ethnicity, form);
        """
    )
    db.execute("PRAGMA legacy_alter_table = OFF")
    db.commit()


def repair_obsolete_foreign_key_names():
    tables = ["dance_work_alias", "dance_video_version", "expert_review"]
    needs_repair = False
    for table in tables:
        for row in query_all(f"PRAGMA foreign_key_list({table})"):
            if row["table"] == "dance_work_old":
                needs_repair = True
                break
    if not needs_repair:
        return
    db = get_db()
    version = db.execute("PRAGMA schema_version").fetchone()[0]
    db.execute("PRAGMA writable_schema = ON")
    db.execute(
        """
        UPDATE sqlite_schema
        SET sql = replace(sql, 'dance_work_old', 'dance_work')
        WHERE type = 'table' AND sql LIKE '%dance_work_old%'
        """
    )
    db.execute("PRAGMA writable_schema = OFF")
    db.execute(f"PRAGMA schema_version = {version + 1}")
    db.commit()


def compact_text(*parts):
    return " ".join(str(part or "").strip() for part in parts if str(part or "").strip())


def format_duration_minutes(value):
    if value in (None, ""):
        return "-"
    try:
        total_seconds = int(round(float(value) * 60))
    except (TypeError, ValueError):
        return "-"
    minutes, seconds = divmod(total_seconds, 60)
    if seconds:
        return f"{minutes}分{seconds}秒"
    return f"{minutes}分钟"


@app.template_filter("duration_text")
def duration_text(value):
    return format_duration_minutes(value)


def review_search_text(work_id):
    rows = query_all(
        """
        SELECT summary, strengths, risks, recommendation_note, suitable_level
        FROM expert_review
        WHERE work_id = ?
        ORDER BY created_at DESC
        LIMIT 8
        """,
        (work_id,),
    )
    return compact_text(
        *[
            compact_text(row["summary"], row["strengths"], row["risks"], row["recommendation_note"], row["suitable_level"])
            for row in rows
        ]
    )


def video_search_text(work_id):
    rows = query_all(
        """
        SELECT title, platform, uploader, performer, institution, event_name, notes
        FROM dance_video_version
        WHERE work_id = ?
        ORDER BY quality_score DESC, created_at DESC
        LIMIT 12
        """,
        (work_id,),
    )
    return compact_text(
        *[
            compact_text(row["title"], row["platform"], row["uploader"], row["performer"], row["institution"], row["event_name"], row["notes"])
            for row in rows
        ]
    )


def work_search_document(work_id):
    work = query_one("SELECT * FROM dance_work WHERE id = ?", (work_id,))
    if not work:
        return None
    attributes = compact_text(
        work["ethnicity"],
        work["region"],
        work["dance_type"],
        work["form"],
        work["gender_tendency"],
        work["props"],
        work["music_info"],
        work["premiere_info"],
        work["description"],
    )
    return {
        "work_id": work_id,
        "title": work["title"],
        "aliases": work["aliases"],
        "attributes": attributes,
        "expert_text": review_search_text(work_id),
        "video_text": video_search_text(work_id),
    }


def refresh_work_search_index(work_id):
    doc = work_search_document(work_id)
    db = get_db()
    try:
        db.execute("DELETE FROM work_search_fts WHERE work_id = ?", (work_id,))
        if doc:
            db.execute(
                """
                INSERT INTO work_search_fts (work_id, title, aliases, attributes, expert_text, video_text)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    doc["work_id"],
                    doc["title"],
                    doc["aliases"],
                    doc["attributes"],
                    doc["expert_text"],
                    doc["video_text"],
                ),
            )
        db.commit()
    except sqlite3.OperationalError:
        db.rollback()


def rebuild_work_search_index():
    try:
        get_db().execute("DELETE FROM work_search_fts")
        get_db().commit()
    except sqlite3.OperationalError:
        return
    for work in query_all("SELECT id FROM dance_work"):
        refresh_work_search_index(work["id"])


def ensure_search_index_fresh():
    try:
        indexed = query_one("SELECT COUNT(DISTINCT work_id) AS c FROM work_search_fts")["c"]
    except sqlite3.OperationalError:
        return
    total = query_one("SELECT COUNT(*) AS c FROM dance_work")["c"]
    if indexed != total:
        rebuild_work_search_index()


def add_work_alias(work_id, alias):
    alias = (alias or "").strip()
    normalized = normalize_title(alias)
    if not alias or not normalized:
        return
    existing = query_one(
        "SELECT id FROM dance_work_alias WHERE work_id = ? AND normalized_alias = ?",
        (work_id, normalized),
    )
    if existing:
        return
    execute(
        "INSERT INTO dance_work_alias (id, work_id, alias, normalized_alias, created_at) VALUES (?, ?, ?, ?, ?)",
        (new_id(), work_id, alias, normalized, now()),
    )


def add_aliases_from_text(work_id, aliases):
    for alias in re.split(r"[,，;；\\n]+", aliases or ""):
        add_work_alias(work_id, alias)


def backfill_normalized_data():
    for work in query_all("SELECT id, title, aliases, normalized_title FROM dance_work"):
        normalized = work["normalized_title"] or normalize_title(work["title"])
        execute("UPDATE dance_work SET normalized_title = ? WHERE id = ?", (normalized, work["id"]))
        add_work_alias(work["id"], work["title"])
        add_aliases_from_text(work["id"], work["aliases"])
    for video in query_all("SELECT id, platform, url, title, canonical_url, platform_video_id, normalized_title FROM dance_video_version"):
        identity = video_identity(video["url"], video["platform"])
        execute(
            """
            UPDATE dance_video_version
            SET platform = ?, canonical_url = ?, platform_video_id = ?, normalized_title = ?,
                updated_at = COALESCE(NULLIF(updated_at, ''), created_at)
            WHERE id = ?
            """,
            (
                identity["platform"],
                video["canonical_url"] or identity["canonical_url"],
                video["platform_video_id"] or identity["platform_video_id"],
                video["normalized_title"] or normalize_title(video["title"]),
                video["id"],
            ),
        )
    ensure_search_index_fresh()


def find_duplicate_video(url, platform=None):
    identity = video_identity(url, platform)
    if identity["platform_video_id"]:
        row = query_one(
            """
            SELECT v.*, w.title AS work_title
            FROM dance_video_version v JOIN dance_work w ON w.id = v.work_id
            WHERE v.platform = ? AND v.platform_video_id = ?
            LIMIT 1
            """,
            (identity["platform"], identity["platform_video_id"]),
        )
        if row:
            return row
    return query_one(
        """
        SELECT v.*, w.title AS work_title
        FROM dance_video_version v JOIN dance_work w ON w.id = v.work_id
        WHERE v.canonical_url = ? OR v.url = ?
        LIMIT 1
        """,
        (identity["canonical_url"], url),
    )


def find_possible_works(title, limit=5):
    normalized = normalize_title(title)
    if not normalized:
        return []
    exact = query_all(
        """
        SELECT id, title, ethnicity, form, 1.0 AS match_score, '标题/别名精确匹配' AS match_reason
        FROM dance_work
        WHERE normalized_title = ?
        UNION
        SELECT w.id, w.title, w.ethnicity, w.form, 1.0 AS match_score, '别名精确匹配' AS match_reason
        FROM dance_work_alias a JOIN dance_work w ON w.id = a.work_id
        WHERE a.normalized_alias = ?
        LIMIT ?
        """,
        (normalized, normalized, limit),
    )
    seen = {row["id"] for row in exact}
    candidates = [dict(row) for row in exact]
    if len(candidates) < limit:
        fuzzy = query_all(
            """
            SELECT id, title, ethnicity, form, normalized_title
            FROM dance_work
            WHERE normalized_title LIKE ? OR ? LIKE '%' || normalized_title || '%'
            LIMIT ?
            """,
            (f"%{normalized}%", normalized, limit * 2),
        )
        for row in fuzzy:
            if row["id"] in seen:
                continue
            candidates.append(
                {
                    "id": row["id"],
                    "title": row["title"],
                    "ethnicity": row["ethnicity"],
                    "form": row["form"],
                    "match_score": 0.72,
                    "match_reason": "标题包含关系",
                }
            )
            seen.add(row["id"])
            if len(candidates) >= limit:
                break
    return candidates


def normalized_work_names(title, aliases=""):
    names = {normalize_title(title)}
    for alias in re.split(r"[,，;；\\n]+", aliases or ""):
        normalized = normalize_title(alias)
        if normalized:
            names.add(normalized)
    return sorted(name for name in names if name)


def find_duplicate_works(title, aliases="", exclude_work_id=None, limit=8):
    names = normalized_work_names(title, aliases)
    if not names:
        return []
    placeholders = ",".join("?" for _ in names)
    params = names + names
    exclude_clause = ""
    if exclude_work_id:
        exclude_clause = "AND w.id != ?"
        params.append(exclude_work_id)
    return query_all(
        f"""
        SELECT DISTINCT w.id, w.title, w.ethnicity, w.form, w.description
        FROM dance_work w
        LEFT JOIN dance_work_alias a ON a.work_id = w.id
        WHERE (w.normalized_title IN ({placeholders}) OR a.normalized_alias IN ({placeholders}))
          {exclude_clause}
        ORDER BY w.updated_at DESC
        LIMIT ?
        """,
        params + [limit],
    )


def insert_video_version(work_id, values):
    url = values.get("url", "").strip()
    platform = values.get("platform", "").strip() or infer_platform(url)
    duplicate = find_duplicate_video(url, platform)
    if duplicate:
        return duplicate["id"], False
    identity = video_identity(url, platform)
    video_id = new_id()
    execute(
        """
        INSERT INTO dance_video_version (
          id, work_id, platform, url, canonical_url, platform_video_id, title, normalized_title,
          uploader, performer, institution, event_name, publish_date, duration_seconds,
          thumbnail_url, screenshot_url, is_full_version, is_teaching_version, quality_score,
          notes, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            video_id,
            work_id,
            identity["platform"],
            url,
            identity["canonical_url"],
            identity["platform_video_id"],
            values.get("title", ""),
            normalize_title(values.get("title", "")),
            values.get("uploader", ""),
            values.get("performer", ""),
            values.get("institution", ""),
            values.get("event_name", ""),
            values.get("publish_date", ""),
            parse_int(values.get("duration_seconds")),
            values.get("thumbnail_url", ""),
            values.get("screenshot_url", ""),
            1 if values.get("is_full_version") else 0,
            1 if values.get("is_teaching_version") else 0,
            parse_int(values.get("quality_score"), 3),
            values.get("notes", ""),
            values.get("status", "active") or "active",
            now(),
            now(),
        ),
    )
    refresh_work_search_index(work_id)
    return video_id, True


def merge_works(source_work_id, target_work_id):
    if source_work_id == target_work_id:
        return False, "不能合并到自身。"
    source = query_one("SELECT * FROM dance_work WHERE id = ?", (source_work_id,))
    target = query_one("SELECT * FROM dance_work WHERE id = ?", (target_work_id,))
    if not source or not target:
        return False, "剧目不存在。"
    db = get_db()
    try:
        db.execute("BEGIN")
        for alias in [source["title"], source["aliases"] or ""]:
            for part in re.split(r"[,，;；\\n]+", alias or ""):
                normalized = normalize_title(part)
                if part.strip() and normalized:
                    existing = db.execute(
                        "SELECT id FROM dance_work_alias WHERE work_id = ? AND normalized_alias = ?",
                        (target_work_id, normalized),
                    ).fetchone()
                    if not existing:
                        db.execute(
                            "INSERT INTO dance_work_alias (id, work_id, alias, normalized_alias, created_at) VALUES (?, ?, ?, ?, ?)",
                            (new_id(), target_work_id, part.strip(), normalized, now()),
                        )
        db.execute("UPDATE dance_video_version SET work_id = ?, updated_at = ? WHERE work_id = ?", (target_work_id, now(), source_work_id))
        db.execute("UPDATE expert_review SET work_id = ?, updated_at = ? WHERE work_id = ?", (target_work_id, now(), source_work_id))
        db.execute("UPDATE recommendation_feedback SET work_id = ? WHERE work_id = ?", (target_work_id, source_work_id))
        db.execute("UPDATE dance_work_alias SET work_id = ? WHERE work_id = ?", (target_work_id, source_work_id))
        db.execute("DELETE FROM dance_work WHERE id = ?", (source_work_id,))
        db.execute("UPDATE dance_work SET updated_at = ? WHERE id = ?", (now(), target_work_id))
        db.commit()
        refresh_work_search_index(target_work_id)
        refresh_work_search_index(source_work_id)
        return True, "合并完成，原剧目已从数据库删除。"
    except Exception as exc:
        db.rollback()
        return False, f"合并失败：{exc}"


def delete_work_records(work_id):
    db = get_db()
    try:
        db.execute("BEGIN")
        db.execute("DELETE FROM expert_review WHERE work_id = ?", (work_id,))
        db.execute("DELETE FROM dance_video_version WHERE work_id = ?", (work_id,))
        db.execute("DELETE FROM dance_work_alias WHERE work_id = ?", (work_id,))
        db.execute("DELETE FROM recommendation_feedback WHERE work_id = ?", (work_id,))
        db.execute("DELETE FROM dance_work WHERE id = ?", (work_id,))
        db.commit()
        refresh_work_search_index(work_id)
        return True, "剧目已删除。"
    except Exception as exc:
        db.rollback()
        return False, f"删除失败：{exc}"


def seed_data():
    experts = [
        ("林老师", "民族民间舞教师", "艺考培训机构"),
        ("周老师", "高校舞蹈编导", "艺术院校"),
        ("陈老师", "比赛评审", "舞蹈协会"),
    ]
    expert_ids = []
    for name, title, org in experts:
        eid = new_id()
        expert_ids.append(eid)
        execute(
            "INSERT INTO expert (id, name, title, organization, bio, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (eid, name, title, org, "示例专家账号，用于本地演示。", now()),
        )

    for index, work in enumerate(SEED_WORKS):
        wid = new_id()
        execute(
            """
            INSERT INTO dance_work (
              id, title, aliases, ethnicity, region, dance_type, form, gender_tendency,
              duration_min, duration_max, props, music_info, premiere_info, description,
              created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                wid,
                work["title"],
                work["aliases"],
                work["ethnicity"],
                work["region"],
                work["dance_type"],
                work["form"],
                work["gender_tendency"],
                work["duration_min"],
                work["duration_max"],
                work["props"],
                work["music_info"],
                work["premiere_info"],
                work["description"],
                now(),
                now(),
            ),
        )
        for version_index, platform in enumerate(["B站", "YouTube"]):
            vid = new_id()
            execute(
                """
                INSERT INTO dance_video_version (
                  id, work_id, platform, url, title, uploader, performer, institution,
                  event_name, publish_date, duration_seconds, thumbnail_url, screenshot_url,
                  is_full_version, is_teaching_version, quality_score, notes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    vid,
                    wid,
                    platform,
                    f"https://example.com/{platform.lower()}/{wid[:8]}-{version_index}",
                    f"{work['ethnicity']}《{work['title']}》参考版本 {version_index + 1}",
                    "示例上传者",
                    "示例表演者",
                    "示例院校",
                    "示例展演",
                    "2025-01-01",
                    280,
                    "",
                    "",
                    1 if version_index == 0 else 0,
                    0,
                    4 - version_index,
                    "示例链接，请替换为真实公开视频地址。",
                    now(),
                ),
            )
        review_profile = {
            "心迹": (3, 2, 4, 2, 3, 4, 3, 2, 2, 8, 12, 5, 5, 5, 4, 5),
            "草原上的额吉": (2, 3, 4, 2, 3, 3, 3, 2, 2, 8, 12, 5, 4, 4, 4, 4),
            "花儿为什么这样红": (3, 3, 3, 4, 4, 4, 4, 3, 3, 10, 16, 4, 4, 5, 4, 3),
            "雀之灵片段": (5, 3, 5, 2, 3, 5, 3, 2, 4, 12, 20, 5, 5, 5, 4, 2),
            "长鼓行": (2, 3, 3, 3, 4, 5, 4, 2, 3, 10, 14, 4, 4, 4, 4, 3),
        }[work["title"]]
        add_review(
            work_id=wid,
            version_id=None,
            expert_id=expert_ids[index % len(expert_ids)],
            values={
                "flexibility_score": review_profile[0],
                "strength_score": review_profile[1],
                "control_score": review_profile[2],
                "explosiveness_score": review_profile[3],
                "stamina_score": review_profile[4],
                "coordination_score": review_profile[5],
                "footwork_score": review_profile[6],
                "turn_jump_score": review_profile[7],
                "entry_threshold_score": review_profile[8],
                "rehearsal_weeks_min": review_profile[9],
                "rehearsal_weeks_max": review_profile[10],
                "character_score": review_profile[11],
                "emotional_range_score": review_profile[12],
                "style_purity_score": review_profile[13],
                "creative_space_score": review_profile[14],
                "originality_score": review_profile[15],
                "exam_suitability_score": 4,
                "competition_suitability_score": 4,
                "teaching_suitability_score": 3,
                "gala_suitability_score": 3,
                "summary": f"《{work['title']}》的示例专家评分，适合验证推荐逻辑。",
                "strengths": "风格辨识度清晰，便于做人物和情绪处理。",
                "risks": "需要教师把控民族风格，避免只学外形。",
                "recommendation_note": "可作为艺考备选，需结合学生个人条件二次判断。",
            },
        )


REVIEW_FIELDS = [
    "flexibility_score",
    "strength_score",
    "control_score",
    "explosiveness_score",
    "stamina_score",
    "coordination_score",
    "footwork_score",
    "turn_jump_score",
    "entry_threshold_score",
    "suggested_experience_years",
    "rehearsal_weeks_min",
    "rehearsal_weeks_max",
    "needs_professional_teacher",
    "music_access_difficulty",
    "costume_access_difficulty",
    "character_score",
    "emotional_range_score",
    "style_purity_score",
    "rhythm_difficulty_score",
    "stage_blocking_score",
    "creative_space_score",
    "originality_score",
    "exam_suitability_score",
    "competition_suitability_score",
    "teaching_suitability_score",
    "gala_suitability_score",
    "suitable_age_min",
    "suitable_age_max",
    "suitable_level",
    "summary",
    "strengths",
    "risks",
    "recommendation_note",
]

REVIEW_RATING_FIELDS = {
    field
    for field in REVIEW_FIELDS
    if field.endswith("_score") or field.endswith("_difficulty")
}
REVIEW_RATING_FIELDS.add("needs_professional_teacher")


def add_review(work_id, version_id, expert_id, values):
    row = {field: values.get(field) for field in REVIEW_FIELDS}
    for field in REVIEW_FIELDS:
        if row[field] is None:
            if field.endswith("_score") or field.endswith("_difficulty"):
                row[field] = 3
            elif field in {"rehearsal_weeks_min", "rehearsal_weeks_max"}:
                row[field] = 8 if field.endswith("min") else 12
            elif field == "suggested_experience_years":
                row[field] = 2
            elif field == "needs_professional_teacher":
                row[field] = 1
            elif field == "suitable_age_min":
                row[field] = 14
            elif field == "suitable_age_max":
                row[field] = 22
            elif field == "suitable_level":
                row[field] = "中级"
            else:
                row[field] = ""
        elif field in REVIEW_RATING_FIELDS:
            row[field] = max(1, min(5, parse_int(row[field], 3)))
    columns = ["id", "work_id", "version_id", "expert_id", "status"] + REVIEW_FIELDS + ["created_at", "updated_at"]
    placeholders = ", ".join(["?"] * len(columns))
    execute(
        f"INSERT INTO expert_review ({', '.join(columns)}) VALUES ({placeholders})",
        [new_id(), work_id, version_id, expert_id, "submitted"] + [row[field] for field in REVIEW_FIELDS] + [now(), now()],
    )
    refresh_work_search_index(work_id)


def parse_int(value, default=None):
    try:
        if value in (None, ""):
            return default
        return int(value)
    except ValueError:
        return default


def parse_rating(value, default=3):
    return max(1, min(5, parse_int(value, default)))


def parse_float(value, default=None):
    try:
        if value in (None, ""):
            return default
        return float(value)
    except ValueError:
        return default


TITLE_NOISE_TERMS = [
    "民族民间舞",
    "民族舞",
    "中国舞",
    "藏族舞",
    "蒙古族舞",
    "维吾尔族舞",
    "傣族舞",
    "朝鲜族舞",
    "女子独舞",
    "男子独舞",
    "独舞",
    "群舞",
    "双人舞",
    "三人舞",
    "艺考",
    "剧目",
    "完整版",
    "完整",
    "教学版",
    "教学",
    "比赛版",
    "比赛",
    "参考",
    "舞蹈",
]


def normalize_title(title):
    text = (title or "").lower()
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", "", text)
    for left, right in [("《", "》"), ("〈", "〉"), ("「", "」"), ("『", "』"), ("【", "】"), ("[", "]"), ("(", ")")]:
        text = text.replace(left, "").replace(right, "")
    for term in TITLE_NOISE_TERMS:
        text = text.replace(term.lower(), "")
    text = re.sub(r"[\\s\\-_—·,，.。:：;；!！?？/\\\\|]+", "", text)
    return text.strip()


def infer_platform(url):
    lowered = (url or "").lower()
    if "youtube.com" in lowered or "youtu.be" in lowered:
        return "YouTube"
    if "bilibili.com" in lowered or "b23.tv" in lowered:
        return "B站"
    if "douyin.com" in lowered:
        return "抖音"
    if "xiaohongshu.com" in lowered or "xhslink.com" in lowered:
        return "小红书"
    return "其他"


def youtube_video_id(url):
    patterns = [
        r"(?:v=)([A-Za-z0-9_-]{6,})",
        r"youtu\.be/([A-Za-z0-9_-]{6,})",
        r"youtube\.com/shorts/([A-Za-z0-9_-]{6,})",
        r"youtube\.com/embed/([A-Za-z0-9_-]{6,})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url or "")
        if match:
            return match.group(1)
    return None


def bilibili_bvid(url):
    match = re.search(r"(BV[A-Za-z0-9]+)", url or "")
    return match.group(1) if match else None


def platform_video_id(platform, url):
    platform = platform or infer_platform(url)
    if platform == "B站":
        return bilibili_bvid(url) or ""
    if platform == "YouTube":
        return youtube_video_id(url) or ""
    return ""


def canonicalize_video_url(url, platform=None):
    platform = platform or infer_platform(url)
    video_id = platform_video_id(platform, url)
    if platform == "B站" and video_id:
        return f"https://www.bilibili.com/video/{video_id}"
    if platform == "YouTube" and video_id:
        return f"https://www.youtube.com/watch?v={video_id}"
    return (url or "").strip()


def video_identity(url, platform=None):
    platform = platform or infer_platform(url)
    return {
        "platform": platform,
        "platform_video_id": platform_video_id(platform, url),
        "canonical_url": canonicalize_video_url(url, platform),
    }


def embed_url_for(url):
    platform = infer_platform(url)
    if platform == "YouTube":
        video_id = youtube_video_id(url)
        if video_id:
            return f"https://www.youtube.com/embed/{video_id}?{urlencode({'rel': 0})}"
    if platform == "B站":
        bvid = bilibili_bvid(url)
        if bvid:
            params = {
                "isOutside": "true",
                "bvid": bvid,
                "p": 1,
                "autoplay": 0,
                "danmaku": 0,
                "poster": 1,
            }
            return f"https://player.bilibili.com/player.html?{urlencode(params)}"
    return ""


def classify_dance_video(keyword="", title="", uploader=""):
    text = f"{keyword} {title} {uploader}".lower()
    positive_terms = [
        "舞", "舞蹈", "跳舞", "中国舞", "民族民间舞", "民族舞", "民间舞", "古典舞",
        "现代舞", "当代舞", "芭蕾", "拉丁", "街舞", "独舞", "双人舞", "三人舞", "群舞",
        "剧目", "艺考", "附中", "桃李杯", "荷花奖", "舞蹈教学", "舞蹈课堂",
        "藏族舞", "蒙古族舞", "维吾尔族舞", "傣族舞", "朝鲜族舞", "秧歌", "花鼓灯",
        "dance", "dancing", "dancer", "choreography", "choreo", "solo dance", "folk dance",
    ]
    strong_terms = [
        "民族民间舞", "中国舞", "古典舞", "独舞", "群舞", "剧目", "艺考", "藏族舞",
        "蒙古族舞", "维吾尔族舞", "傣族舞", "朝鲜族舞", "choreography", "folk dance",
    ]
    negative_terms = [
        "伴奏", "纯音乐", "歌曲", "翻唱", "电视剧", "电影", "游戏", "解说", "reaction",
        "cover song", "lyrics", "instrumental", "ost",
    ]
    score = 0.0
    reasons = []
    for term in strong_terms:
        if term.lower() in text:
            score += 0.32
            reasons.append(f"强舞蹈词：{term}")
            break
    matched_positive = [term for term in positive_terms if term.lower() in text]
    if matched_positive:
        score += min(0.5, 0.16 * len(matched_positive))
        reasons.append("舞蹈相关词：" + "、".join(matched_positive[:4]))
    matched_negative = [term for term in negative_terms if term.lower() in text]
    if matched_negative:
        score -= min(0.35, 0.12 * len(matched_negative))
        reasons.append("干扰词：" + "、".join(matched_negative[:3]))
    if keyword and any(term.lower() in keyword.lower() for term in positive_terms):
        score += 0.14
        reasons.append("搜索词本身包含舞蹈意图")
    confidence = round(max(0.0, min(1.0, score)), 2)
    return confidence >= 0.35, confidence, "；".join(reasons) or "未命中明显舞蹈词"


def clean_bilibili_title(title):
    title = html.unescape(title or "")
    title = re.sub(r"<[^>]+>", "", title)
    return re.sub(r"\s+", " ", title).strip()


def bilibili_result_to_candidate(item):
    bvid = (item.get("bvid") or "").strip()
    url = f"https://www.bilibili.com/video/{bvid}" if bvid else (item.get("arcurl") or "")
    if url.startswith("http://"):
        url = "https://" + url[len("http://") :]
    thumbnail = item.get("pic") or ""
    if thumbnail.startswith("//"):
        thumbnail = "https:" + thumbnail
    pubdate = item.get("pubdate")
    publish_date = ""
    if isinstance(pubdate, int) and pubdate > 0:
        publish_date = datetime.fromtimestamp(pubdate).strftime("%Y-%m-%d")
    return {
        "platform": "B站",
        "url": url,
        "title": clean_bilibili_title(item.get("title", "")),
        "uploader": item.get("author", ""),
        "publish_date": publish_date,
        "thumbnail_url": thumbnail,
        "platform_video_id": bvid,
    }


def bilibili_search_headers(referer="https://search.bilibili.com/"):
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Origin": "https://search.bilibili.com",
        "Referer": referer,
        "Connection": "keep-alive",
    }


def load_bilibili_search_json(keyword, max_results=12):
    session = requests.Session()
    search_page_url = f"https://search.bilibili.com/all?keyword={quote_plus(keyword)}"
    try:
        session.get(search_page_url, headers=bilibili_search_headers("https://www.bilibili.com/"), timeout=10)
    except requests.RequestException:
        pass

    params = {
        "search_type": "video",
        "keyword": keyword,
        "page": 1,
        "page_size": max_results,
    }
    last_response = None
    for attempt in range(2):
        response = session.get(
            BILIBILI_SEARCH_API,
            params=params,
            headers=bilibili_search_headers(search_page_url),
            timeout=20,
        )
        last_response = response
        if response.status_code == 412 and attempt == 0:
            time.sleep(0.8)
            try:
                session.get(search_page_url, headers=bilibili_search_headers("https://www.bilibili.com/"), timeout=10)
            except requests.RequestException:
                pass
            continue
        if response.status_code == 412:
            return None, "B站临时限制了这次自动搜索。通常等几十秒再点一次搜索就可以；也可以点上方“B站原站”先手动查看。"
        response.raise_for_status()
        return response.json(), ""
    if last_response is not None:
        last_response.raise_for_status()
    return None, "B站搜索暂时没有返回结果，请稍后重试。"


def search_bilibili_candidates(keyword, max_results=12):
    try:
        data, warning = load_bilibili_search_json(keyword, max_results)
        if warning:
            return [], warning
        if data.get("code") != 0:
            return [], f"B站搜索失败：{data.get('message', 'unknown error')}"
        items = []
        for item in (data.get("data") or {}).get("result", [])[:max_results]:
            candidate = bilibili_result_to_candidate(item)
            if not candidate["url"]:
                continue
            items.append(candidate)
        return items, ""
    except Exception as exc:
        return [], f"B站搜索失败：{exc}"


def guess_matched_work(keyword, title=""):
    text = f"{keyword} {title}".strip()
    works = query_all("SELECT id, title, aliases FROM dance_work")
    for work in works:
        names = [work["title"]] + [name.strip() for name in (work["aliases"] or "").split(",") if name.strip()]
        for name in names:
            if name and name in text:
                return work["id"]
    return None


def level_to_max_score(level):
    mapping = {"weak": 2, "low": 2, "medium": 3, "high": 5, "弱": 2, "偏弱": 2, "中等": 3, "好": 5}
    return mapping.get(level or "", 3)


def parse_ability_level(text, keywords):
    weak_words = ["弱", "偏弱", "不好", "较弱", "一般偏弱", "差"]
    medium_words = ["中等", "一般", "普通", "还可以", "尚可"]
    high_words = ["好", "强", "较好", "优秀", "突出"]
    for keyword in keywords:
        for word in weak_words:
            if f"{keyword}{word}" in text or f"{keyword}偏{word}" in text:
                return "weak"
        for word in medium_words:
            if f"{keyword}{word}" in text:
                return "medium"
        for word in high_words:
            if f"{keyword}{word}" in text:
                return "high"
    return None


def rule_parse_user_query(text):
    intent = {
        "age": None,
        "gender": None,
        "heightCm": None,
        "flexibilityLevel": None,
        "strengthLevel": None,
        "controlLevel": None,
        "staminaLevel": None,
        "coordinationLevel": None,
        "techniqueLevel": None,
        "preparationWeeks": None,
        "goal": None,
        "ethnicity": None,
        "form": None,
        "avoidCommonRepertoire": False,
        "preferences": [],
        "constraints": [],
    }
    age = re.search(r"(\d{1,2})\s*岁", text)
    if age:
        intent["age"] = int(age.group(1))
    height = re.search(r"(\d{3})\s*(?:cm|厘米|公分)", text, re.I)
    if height:
        intent["heightCm"] = int(height.group(1))
    if any(word in text for word in ["女生", "女", "女孩"]):
        intent["gender"] = "female"
    elif any(word in text for word in ["男生", "男", "男孩"]):
        intent["gender"] = "male"
    ethnicities = ["藏族", "蒙古族", "维吾尔族", "朝鲜族", "傣族", "汉族", "苗族", "彝族"]
    for ethnicity in ethnicities:
        if ethnicity in text:
            intent["ethnicity"] = ethnicity
            break
    for form in ["独舞", "双人舞", "三人舞", "群舞"]:
        if form in text:
            intent["form"] = form
            break
    if "艺考" in text:
        intent["goal"] = "exam"
    elif "比赛" in text:
        intent["goal"] = "competition"
    elif "晚会" in text:
        intent["goal"] = "gala"
    intent["flexibilityLevel"] = parse_ability_level(text, ["软度", "柔韧", "软开", "开度"])
    intent["strengthLevel"] = parse_ability_level(text, ["力量"])
    intent["controlLevel"] = parse_ability_level(text, ["控制", "控制力"])
    intent["staminaLevel"] = parse_ability_level(text, ["耐力", "体能"])
    intent["coordinationLevel"] = parse_ability_level(text, ["协调", "协调性"])
    intent["techniqueLevel"] = parse_ability_level(text, ["技巧", "技术", "旋转跳跃", "跳转"])
    month = re.search(r"(\d+)\s*个?月", text)
    if month:
        intent["preparationWeeks"] = int(month.group(1)) * 4
    week = re.search(r"(\d+)\s*周", text)
    if week:
        intent["preparationWeeks"] = int(week.group(1))
    if any(word in text for word in ["不俗套", "冷门", "少见", "新颖"]):
        intent["avoidCommonRepertoire"] = True
        intent["preferences"].append("不俗套")
    if any(word in text for word in ["艺术表现空间", "表现空间", "人物塑造", "情绪"]):
        intent["preferences"].append("艺术表现空间大")
    if any(word in text for word in ["技巧不能太强", "技巧不要太高", "技巧偏弱"]):
        intent["constraints"].append("技巧不能太强")
    return intent


def deepseek_parse_user_query(text):
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        return None
    system = (
        "你是舞蹈剧目推荐系统的需求解析器。"
        "只输出 JSON，不要 Markdown。字段包括 age, gender, heightCm, flexibilityLevel, "
        "strengthLevel, controlLevel, staminaLevel, coordinationLevel, techniqueLevel, "
        "preparationWeeks, goal, ethnicity, form, avoidCommonRepertoire, "
        "preferences, constraints。未知字段用 null、false 或空数组。"
        "gender 使用 female/male/unknown；goal 使用 exam/competition/gala/teaching/unknown；"
        "各项身体能力 level 使用 weak/medium/high。"
    )
    try:
        response = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": text},
                ],
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
            },
            timeout=20,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        fallback = rule_parse_user_query(text)
        fallback.update({key: value for key, value in parsed.items() if value not in (None, "", [])})
        return fallback
    except Exception:
        return None


def parse_user_query(text):
    return normalize_intent(deepseek_parse_user_query(text) or rule_parse_user_query(text))


def normalize_intent(intent):
    ethnicity_map = {
        "tibetan": "藏族",
        "藏": "藏族",
        "mongolian": "蒙古族",
        "蒙古": "蒙古族",
        "uyghur": "维吾尔族",
        "uighur": "维吾尔族",
        "维吾尔": "维吾尔族",
        "dai": "傣族",
        "korean": "朝鲜族",
        "朝鲜": "朝鲜族",
    }
    form_map = {
        "solo": "独舞",
        "single": "独舞",
        "duet": "双人舞",
        "double": "双人舞",
        "group": "群舞",
    }
    normalized = dict(intent or {})
    ethnicity = str(normalized.get("ethnicity") or "").strip().lower()
    form = str(normalized.get("form") or "").strip().lower()
    if ethnicity in ethnicity_map:
        normalized["ethnicity"] = ethnicity_map[ethnicity]
    if form in form_map:
        normalized["form"] = form_map[form]
    return normalized


def review_averages(work_id):
    row = query_one(
        """
        SELECT
          COUNT(*) AS review_count,
          AVG(flexibility_score) AS flexibility_score,
          AVG(strength_score) AS strength_score,
          AVG(control_score) AS control_score,
          AVG(explosiveness_score) AS explosiveness_score,
          AVG(stamina_score) AS stamina_score,
          AVG(coordination_score) AS coordination_score,
          AVG(footwork_score) AS footwork_score,
          AVG(turn_jump_score) AS turn_jump_score,
          AVG(entry_threshold_score) AS entry_threshold_score,
          AVG(rehearsal_weeks_min) AS rehearsal_weeks_min,
          AVG(rehearsal_weeks_max) AS rehearsal_weeks_max,
          AVG(needs_professional_teacher) AS needs_professional_teacher,
          AVG(music_access_difficulty) AS music_access_difficulty,
          AVG(costume_access_difficulty) AS costume_access_difficulty,
          AVG(character_score) AS character_score,
          AVG(emotional_range_score) AS emotional_range_score,
          AVG(style_purity_score) AS style_purity_score,
          AVG(rhythm_difficulty_score) AS rhythm_difficulty_score,
          AVG(creative_space_score) AS creative_space_score,
          AVG(originality_score) AS originality_score,
          AVG(exam_suitability_score) AS exam_suitability_score,
          AVG(competition_suitability_score) AS competition_suitability_score,
          AVG(gala_suitability_score) AS gala_suitability_score
        FROM expert_review
        WHERE work_id = ?
        """,
        (work_id,),
    )
    return dict(row)


def needs_recheck(work_id):
    rows = query_all(
        """
        SELECT flexibility_score, strength_score, control_score, turn_jump_score,
               creative_space_score, originality_score, exam_suitability_score
        FROM expert_review WHERE work_id = ?
        """,
        (work_id,),
    )
    if len(rows) < 2:
        return False
    fields = rows[0].keys()
    for field in fields:
        values = [row[field] for row in rows if row[field] is not None]
        if values and max(values) - min(values) >= 3:
            return True
    return False


def clamp(value, low=0.0, high=1.0):
    return max(low, min(high, value))


def fit_requirement(requirement, user_max):
    requirement = requirement or 3
    user_max = user_max or 3
    if requirement <= user_max:
        return clamp(1.0 - max(0, user_max - requirement) * 0.08)
    return clamp(1.0 - (requirement - user_max) * 0.35)


def ability_match(label, requirement, level):
    max_score = level_to_max_score(level)
    fit = fit_requirement(requirement, max_score)
    requirement = requirement or 3
    detail = None
    if level and fit < 0.72:
        detail = f"{label}要求偏高"
    elif level and fit >= 0.9:
        detail = f"{label}匹配"
    return fit, detail


def hard_filter_recommendation(intent, work, avg):
    reasons = []
    if intent.get("ethnicity") and work["ethnicity"] and work["ethnicity"] != intent["ethnicity"]:
        return False, [f"民族不匹配：需求是 {intent['ethnicity']}，该剧目是 {work['ethnicity']}"]
    if intent.get("form") and work["form"] and work["form"] != intent["form"]:
        return False, [f"形式不匹配：需求是 {intent['form']}，该剧目是 {work['form']}"]
    if intent.get("preparationWeeks") and (avg.get("rehearsal_weeks_max") or 12) > intent["preparationWeeks"] + 4:
        return False, [f"排练周期明显超过准备时间：约 {int(avg.get('rehearsal_weeks_max') or 12)} 周"]
    max_tech = level_to_max_score(intent.get("techniqueLevel"))
    if intent.get("techniqueLevel") in ("weak", "偏弱", "弱") and max(avg.get("turn_jump_score") or 3, avg.get("entry_threshold_score") or 3) >= 5:
        return False, ["技巧门槛过高，不适合技巧偏弱的学生"]
    max_flex = level_to_max_score(intent.get("flexibilityLevel"))
    if intent.get("flexibilityLevel") in ("weak", "偏弱", "弱") and (avg.get("flexibility_score") or 3) >= 5:
        return False, ["柔韧要求过高，不适合软度偏弱的学生"]
    if intent.get("goal") == "exam" and (avg.get("exam_suitability_score") or 3) < 2.5:
        return False, ["艺考适配度较低"]
    return True, reasons


def score_recommendation(intent, work, avg, versions):
    reasons = []
    risks = []
    passed, filter_risks = hard_filter_recommendation(intent, work, avg)
    if not passed:
        return {"score": 0, "dimensions": {}, "reasons": [], "risks": filter_risks, "filtered": True}
    if intent.get("ethnicity") and work["ethnicity"] == intent["ethnicity"]:
        reasons.append(f"民族匹配：{work['ethnicity']}")
    if intent.get("form") and work["form"] == intent["form"]:
        reasons.append(f"形式匹配：{work['form']}")

    ability_specs = [
        ("柔韧", avg.get("flexibility_score"), intent.get("flexibilityLevel")),
        ("力量", avg.get("strength_score"), intent.get("strengthLevel")),
        ("控制", avg.get("control_score"), intent.get("controlLevel")),
        ("耐力", avg.get("stamina_score"), intent.get("staminaLevel")),
        ("协调性", avg.get("coordination_score"), intent.get("coordinationLevel")),
        ("技巧", max(avg.get("turn_jump_score") or 3, avg.get("entry_threshold_score") or 3), intent.get("techniqueLevel")),
    ]
    ability_parts = []
    ability_details = []
    for label, requirement, level in ability_specs:
        fit, detail = ability_match(label, requirement, level)
        ability_parts.append(fit)
        if detail:
            ability_details.append(detail)
    ability_fit = sum(ability_parts) / len(ability_parts)
    if ability_fit >= 0.82:
        reasons.append("身体与技巧要求匹配度较高")
    if ability_details:
        reasons.extend([detail for detail in ability_details if "匹配" in detail][:2])
        risks.extend([detail for detail in ability_details if "偏高" in detail][:2])
    if ability_fit < 0.62:
        risks.append("身体或技巧要求存在压力")

    time_fit = 0.75
    if intent.get("preparationWeeks"):
        max_weeks = avg.get("rehearsal_weeks_max") or 12
        time_fit = clamp(intent["preparationWeeks"] / max(max_weeks, 1))
        if time_fit >= 0.9:
            reasons.append(f"预计排练周期约 {int(avg.get('rehearsal_weeks_min') or 0)}-{int(max_weeks)} 周")
        elif time_fit < 0.75:
            risks.append(f"排练周期可能超过 {intent['preparationWeeks']} 周")

    if intent.get("goal") == "competition":
        scene_score = avg.get("competition_suitability_score") or 3
    elif intent.get("goal") == "gala":
        scene_score = avg.get("gala_suitability_score") or 3
    elif intent.get("goal") == "teaching":
        scene_score = avg.get("teaching_suitability_score") or 3
    else:
        scene_score = avg.get("exam_suitability_score") or 3
    scene_fit = clamp(scene_score / 5)
    if scene_fit >= 0.8:
        reasons.append("使用场景适配度较高")

    artistic_values = [
        avg.get("creative_space_score") or 3,
        avg.get("character_score") or 3,
        avg.get("emotional_range_score") or 3,
        avg.get("style_purity_score") or 3,
        avg.get("originality_score") or 3,
    ]
    artistic_fit = clamp(sum(artistic_values) / len(artistic_values) / 5)
    if artistic_fit >= 0.8:
        reasons.append("艺术表现和二度创作空间较好")
    if intent.get("avoidCommonRepertoire"):
        originality = avg.get("originality_score") or 3
        artistic_fit = clamp(artistic_fit * 0.75 + (originality / 5) * 0.25)
        if originality < 4:
            risks.append("新颖度一般，可能需要二度创作避免俗套")

    video_fit = 0.45
    if versions:
        video_fit = clamp(sum((v["quality_score"] or 3) for v in versions) / len(versions) / 5)
        reasons.append(f"已有 {len(versions)} 个参考视频版本")

    risk_penalty = 0
    if avg.get("music_access_difficulty", 3) >= 4:
        risk_penalty += 0.04
        risks.append("音乐获取可能偏难")
    if avg.get("costume_access_difficulty", 3) >= 4:
        risk_penalty += 0.04
        risks.append("服装获取可能偏难")
    if avg.get("needs_professional_teacher", 1):
        risks.append("建议由专业教师把控风格")

    dimensions = {
        "ability_fit": round(ability_fit, 3),
        "time_fit": round(time_fit, 3),
        "scene_fit": round(scene_fit, 3),
        "artistic_fit": round(artistic_fit, 3),
        "video_fit": round(video_fit, 3),
        "risk_penalty": round(risk_penalty, 3),
    }
    score = (
        ability_fit * 0.30
        + time_fit * 0.20
        + scene_fit * 0.25
        + artistic_fit * 0.20
        + video_fit * 0.05
        - risk_penalty
    ) * 100
    return {
        "score": round(max(0, min(100, score)), 1),
        "dimensions": dimensions,
        "reasons": reasons[:5],
        "risks": risks[:4],
        "filtered": False,
    }


def fts_terms_from_query(user_query, intent):
    terms = []
    for value in [
        intent.get("ethnicity"),
        intent.get("region"),
        intent.get("form"),
        intent.get("goal"),
        user_query,
    ]:
        if not value:
            continue
        for token in re.findall(r"[\u4e00-\u9fffA-Za-z0-9_]{2,}", str(value)):
            if token not in terms:
                terms.append(token)
    return terms[:12]


def safe_fts_query(terms):
    escaped = []
    for term in terms:
        term = term.replace('"', '""')
        if term:
            escaped.append(f'"{term}"')
    return " OR ".join(escaped)


def search_candidate_work_ids(user_query, intent, limit=80):
    candidate_scores = {}
    params = []
    where = []
    if intent.get("ethnicity"):
        where.append("(ethnicity = ? OR ethnicity = '')")
        params.append(intent["ethnicity"])
    if intent.get("form"):
        where.append("(form = ? OR form = '')")
        params.append(intent["form"])
    sql = "SELECT id FROM dance_work"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY updated_at DESC LIMIT ?"
    for index, row in enumerate(query_all(sql, params + [limit])):
        candidate_scores[row["id"]] = max(candidate_scores.get(row["id"], 0), 1.0 - index * 0.004)

    fts_query = safe_fts_query(fts_terms_from_query(user_query, intent))
    if fts_query:
        try:
            for row in query_all(
                """
                SELECT work_id, bm25(work_search_fts) AS rank
                FROM work_search_fts
                WHERE work_search_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (fts_query, limit),
            ):
                current = candidate_scores.get(row["work_id"], 0)
                candidate_scores[row["work_id"]] = max(current, 0.75)
        except sqlite3.OperationalError:
            like_terms = fts_terms_from_query(user_query, intent)[:4]
            if like_terms:
                like_where = " OR ".join(["title LIKE ? OR aliases LIKE ? OR description LIKE ?" for _ in like_terms])
                like_params = []
                for term in like_terms:
                    like_params.extend([f"%{term}%", f"%{term}%", f"%{term}%"])
                for row in query_all(f"SELECT id FROM dance_work WHERE {like_where} LIMIT ?", like_params + [limit]):
                    candidate_scores[row["id"]] = max(candidate_scores.get(row["id"], 0), 0.65)

    if not candidate_scores:
        for row in query_all("SELECT id FROM dance_work ORDER BY updated_at DESC LIMIT ?", (limit,)):
            candidate_scores[row["id"]] = 0.5
    return candidate_scores


def feedback_fit(work_id):
    row = query_one(
        """
        SELECT
          SUM(CASE WHEN rating = 'fit' THEN 1 ELSE 0 END) AS fit_count,
          SUM(CASE WHEN rating = 'not_fit' THEN 1 ELSE 0 END) AS not_fit_count,
          COUNT(*) AS total
        FROM recommendation_feedback
        WHERE work_id = ?
        """,
        (work_id,),
    )
    total = row["total"] or 0
    if not total:
        return 0.0
    fit_count = row["fit_count"] or 0
    not_fit_count = row["not_fit_count"] or 0
    return clamp((fit_count - not_fit_count) / max(total, 3), -0.25, 0.25)


def generate_recommendation_text(user_query, intent, ranked):
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key or not ranked:
        return ""
    payload = []
    for item in ranked[:5]:
        payload.append(
            {
                "title": item["work"]["title"],
                "score": item["score"],
                "dimensions": item.get("dimensions", {}),
                "reasons": item["reasons"],
                "risks": item["risks"],
                "summary": item["summary"],
            }
        )
    try:
        response = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
                "messages": [
                    {
                        "role": "system",
                        "content": "你是舞蹈艺考剧目推荐助手。基于数据库结果生成简洁中文建议，不要编造数据库外事实。",
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {"用户需求": user_query, "解析结果": intent, "候选剧目": payload},
                            ensure_ascii=False,
                        ),
                    },
                ],
                "temperature": 0.3,
            },
            timeout=20,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except Exception:
        return ""


def recommend(user_query):
    intent = parse_user_query(user_query)
    candidate_scores = search_candidate_work_ids(user_query, intent)
    placeholders = ",".join("?" for _ in candidate_scores)
    if placeholders:
        works = query_all(f"SELECT * FROM dance_work WHERE id IN ({placeholders})", list(candidate_scores.keys()))
    else:
        works = []
    ranked = []
    for work in works:
        avg = review_averages(work["id"])
        versions = query_all("SELECT * FROM dance_video_version WHERE work_id = ? ORDER BY quality_score DESC", (work["id"],))
        score_data = score_recommendation(intent, work, avg, versions)
        if score_data.get("filtered"):
            continue
        retrieval_fit = candidate_scores.get(work["id"], 0.5)
        teacher_feedback_fit = feedback_fit(work["id"])
        score_data["dimensions"]["retrieval_fit"] = round(retrieval_fit, 3)
        score_data["dimensions"]["teacher_feedback_fit"] = round(teacher_feedback_fit, 3)
        score_data["score"] = round(clamp((score_data["score"] + retrieval_fit * 4 + teacher_feedback_fit * 8) / 100) * 100, 1)
        summary_row = query_one(
            "SELECT summary, strengths, risks, recommendation_note FROM expert_review WHERE work_id = ? ORDER BY created_at DESC LIMIT 1",
            (work["id"],),
        )
        ranked.append(
            {
                "work": work,
                "avg": avg,
                "versions": versions,
                "summary": dict(summary_row) if summary_row else {},
                **score_data,
            }
        )
    ranked.sort(key=lambda item: item["score"], reverse=True)
    ranked = [item for item in ranked if item["score"] >= 45][:8]
    llm_text = generate_recommendation_text(user_query, intent, ranked)
    log_id = new_id()
    recommended_items = [
        {
            "work_id": item["work"]["id"],
            "title": item["work"]["title"],
            "score": item["score"],
            "dimensions": item.get("dimensions", {}),
            "reasons": item["reasons"],
            "risks": item["risks"],
            "score_snapshot": item["avg"],
        }
        for item in ranked
    ]
    execute(
        """
        INSERT INTO recommendation_log (id, user_query, parsed_intent, recommended_work_ids, recommended_items_json, llm_response, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            log_id,
            user_query,
            json.dumps(intent, ensure_ascii=False),
            json.dumps([item["work"]["id"] for item in ranked], ensure_ascii=False),
            json.dumps(recommended_items, ensure_ascii=False),
            llm_text,
            now(),
        ),
    )
    return intent, ranked, llm_text, log_id


def render_page(template_name, title="民族民间舞剧目系统", **context):
    context.setdefault("app_mode", app_mode())
    context.setdefault("title", title)
    return render_template(template_name, **context)


@app.before_request
def ensure_db():
    init_db(seed=True)


@app.route("/")
def index():
    return redirect(url_for("works"))


@app.route("/works")
def works():
    q = request.args.get("q", "").strip()
    ethnicity = request.args.get("ethnicity", "").strip()
    params = []
    where = []
    if q:
        where.append("(title LIKE ? OR aliases LIKE ? OR description LIKE ?)")
        params += [f"%{q}%", f"%{q}%", f"%{q}%"]
    if ethnicity:
        where.append("ethnicity = ?")
        params.append(ethnicity)
    sql = "SELECT * FROM dance_work"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY updated_at DESC"
    rows = query_all(sql, params)
    ethnicities = query_all("SELECT DISTINCT ethnicity FROM dance_work WHERE ethnicity != '' ORDER BY ethnicity")
    cards = []
    for row in rows:
        avg = review_averages(row["id"])
        cards.append({"work": row, "avg": avg, "recheck": needs_recheck(row["id"])})
    return render_page(
        "works.html",
        "剧目库",
        cards=cards,
        q=q,
        ethnicity=ethnicity,
        ethnicities=ethnicities,
    )


WORK_FORM_FIELDS = [
    "title",
    "aliases",
    "ethnicity",
    "region",
    "dance_type",
    "form",
    "gender_tendency",
    "duration_min",
    "duration_max",
    "props",
    "music_info",
    "premiere_info",
    "description",
]


def duplicate_work_confirmation(action, values, duplicates):
    preserved = {field: values.get(field, "") for field in WORK_FORM_FIELDS}
    return render_page(
        "duplicate_work_confirmation.html",
        "可能重复",
        action=action,
        preserved=preserved,
        duplicates=duplicates,
    )


def create_work_from_values(values):
    work_id = new_id()
    execute(
        """
        INSERT INTO dance_work (
          id, title, normalized_title, aliases, ethnicity, region, dance_type, form, gender_tendency,
          duration_min, duration_max, props, music_info, premiere_info, description,
          created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            work_id,
            values.get("title", "").strip(),
            normalize_title(values.get("title", "")),
            values.get("aliases", "").strip(),
            values.get("ethnicity", "").strip(),
            values.get("region", "").strip(),
            values.get("dance_type", "民族民间舞").strip() or "民族民间舞",
            values.get("form", "独舞").strip() or "独舞",
            values.get("gender_tendency", "").strip(),
            parse_float(values.get("duration_min")),
            parse_float(values.get("duration_max")),
            values.get("props", "").strip(),
            values.get("music_info", "").strip(),
            values.get("premiere_info", "").strip(),
            values.get("description", "").strip(),
            now(),
            now(),
        ),
    )
    add_work_alias(work_id, values.get("title", ""))
    add_aliases_from_text(work_id, values.get("aliases", ""))
    refresh_work_search_index(work_id)
    return work_id


@app.route("/works/new", methods=["GET", "POST"])
def new_work():
    if request.method == "POST":
        duplicates = find_duplicate_works(request.form.get("title", ""), request.form.get("aliases", ""))
        if duplicates and request.form.get("force_create") != "1":
            return duplicate_work_confirmation(url_for("new_work"), request.form, duplicates)
        wid = create_work_from_values(request.form)
        return redirect(url_for("work_detail", work_id=wid))
    return render_page("work_form.html", "新增剧目", action=url_for("new_work"), work=None)


@app.route("/works/<work_id>/edit", methods=["GET", "POST"])
def edit_work(work_id):
    work = query_one("SELECT * FROM dance_work WHERE id = ?", (work_id,))
    if not work:
        return "Not found", 404
    if request.method == "POST":
        execute(
            """
            UPDATE dance_work SET title=?, normalized_title=?, aliases=?, ethnicity=?, region=?, dance_type=?, form=?,
              gender_tendency=?, duration_min=?, duration_max=?, props=?, music_info=?,
              premiere_info=?, description=?, updated_at=? WHERE id=?
            """,
            (
                request.form["title"],
                normalize_title(request.form["title"]),
                request.form.get("aliases", ""),
                request.form.get("ethnicity", ""),
                request.form.get("region", ""),
                request.form.get("dance_type", ""),
                request.form.get("form", ""),
                request.form.get("gender_tendency", ""),
                parse_float(request.form.get("duration_min")),
                parse_float(request.form.get("duration_max")),
                request.form.get("props", ""),
                request.form.get("music_info", ""),
                request.form.get("premiere_info", ""),
                request.form.get("description", ""),
                now(),
                work_id,
            ),
        )
        add_work_alias(work_id, request.form["title"])
        add_aliases_from_text(work_id, request.form.get("aliases", ""))
        refresh_work_search_index(work_id)
        return redirect(url_for("work_detail", work_id=work_id))
    return render_page("work_form.html", "编辑剧目", action=url_for("edit_work", work_id=work_id), work=work)


@app.route("/works/<work_id>")
def work_detail(work_id):
    work = query_one("SELECT * FROM dance_work WHERE id = ?", (work_id,))
    if not work:
        return "Not found", 404
    versions = query_all("SELECT * FROM dance_video_version WHERE work_id = ? ORDER BY created_at DESC", (work_id,))
    reviews = query_all(
        """
        SELECT r.*, e.name AS expert_name, e.title AS expert_title
        FROM expert_review r JOIN expert e ON e.id = r.expert_id
        WHERE r.work_id = ? ORDER BY r.created_at DESC
        """,
        (work_id,),
    )
    avg = review_averages(work_id)
    return render_page(
        "work_detail.html",
        work["title"],
        work=work,
        versions=versions,
        reviews=reviews,
        avg=avg,
        recheck=needs_recheck(work_id),
    )


@app.route("/works/<work_id>/delete", methods=["POST"])
def delete_work(work_id):
    work = query_one("SELECT * FROM dance_work WHERE id = ?", (work_id,))
    if not work:
        return "Not found", 404
    delete_work_records(work_id)
    return redirect(url_for("works"))


@app.route("/works/<work_id>/merge", methods=["GET", "POST"])
def merge_work_page(work_id):
    work = query_one("SELECT * FROM dance_work WHERE id = ?", (work_id,))
    if not work:
        return "Not found", 404
    if request.method == "POST":
        target_id = request.form.get("target_work_id")
        ok, message = merge_works(work_id, target_id)
        if ok:
            return redirect(url_for("work_detail", work_id=target_id))
        return redirect(url_for("merge_work_page", work_id=work_id, message=message))
    targets = query_all(
        "SELECT id, title, ethnicity, form FROM dance_work WHERE id != ? ORDER BY title",
        (work_id,),
    )
    versions_count = query_one("SELECT COUNT(*) AS c FROM dance_video_version WHERE work_id = ?", (work_id,))["c"]
    reviews_count = query_one("SELECT COUNT(*) AS c FROM expert_review WHERE work_id = ?", (work_id,))["c"]
    message = request.args.get("message", "")
    return render_page(
        "merge_work.html",
        "合并剧目",
        work=work,
        targets=targets,
        versions_count=versions_count,
        reviews_count=reviews_count,
        message=message,
    )


@app.route("/works/<work_id>/videos/new", methods=["GET", "POST"])
def new_video(work_id):
    work = query_one("SELECT * FROM dance_work WHERE id = ?", (work_id,))
    if not work:
        return "Not found", 404
    if request.method == "POST":
        insert_video_version(work_id, request.form)
        return redirect(url_for("work_detail", work_id=work_id))
    return render_page("new_video.html", "新增视频版本", work=work)


@app.route("/videos/<version_id>")
def video_view(version_id):
    version = query_one(
        """
        SELECT v.*, w.title AS work_title, w.id AS work_id
        FROM dance_video_version v JOIN dance_work w ON w.id = v.work_id
        WHERE v.id = ?
        """,
        (version_id,),
    )
    if not version:
        return "Not found", 404
    embed_url = embed_url_for(version["url"])
    return render_page(
        "video_view.html",
        "视频浏览",
        version=version,
        embed_url=embed_url,
    )


@app.route("/works/<work_id>/reviews/new", methods=["GET", "POST"])
def new_review(work_id):
    work = query_one("SELECT * FROM dance_work WHERE id = ?", (work_id,))
    if not work:
        return "Not found", 404
    experts = query_all("SELECT * FROM expert ORDER BY name")
    versions = query_all("SELECT * FROM dance_video_version WHERE work_id = ? ORDER BY created_at DESC", (work_id,))
    if request.method == "POST":
        values = {}
        for field in REVIEW_FIELDS:
            if field in {"summary", "strengths", "risks", "recommendation_note", "suitable_level"}:
                values[field] = request.form.get(field, "")
            elif field in {"suggested_experience_years"}:
                values[field] = parse_float(request.form.get(field), 2)
            elif field in REVIEW_RATING_FIELDS:
                values[field] = parse_rating(request.form.get(field), 3)
            else:
                values[field] = parse_int(request.form.get(field), 3)
        add_review(
            work_id=work_id,
            version_id=request.form.get("version_id") or None,
            expert_id=request.form["expert_id"],
            values=values,
        )
        return redirect(url_for("work_detail", work_id=work_id))
    core_number_fields = [
        ("rehearsal_weeks_min", "最短排练周数", "预计最少需要集中排练几周。"),
        ("rehearsal_weeks_max", "最长排练周数", "多数学生完成到可上台状态的保守周期。"),
    ]
    core_rating_fields = [
        ("entry_threshold_score", "入门门槛", "1=容易上手，5=入门要求很高"),
        ("flexibility_score", "柔韧要求", "1=软度要求低，5=软度要求很高"),
        ("turn_jump_score", "技巧要求", "1=技巧少，5=旋转跳跃等技巧要求很高"),
        ("style_purity_score", "风格纯度", "1=风格要求宽松，5=民族风格必须非常准确"),
        ("creative_space_score", "艺术表现空间", "1=表现空间小，5=人物和情绪空间很大"),
        ("originality_score", "新颖度", "1=非常常见，5=较少见或容易做出新意"),
        ("exam_suitability_score", "艺考适配", "1=不建议艺考用，5=很适合艺考"),
    ]
    rating_groups = [
        ("身体要求", [
            ("strength_score", "力量", "1=力量要求低，5=力量要求高"),
            ("control_score", "控制", "1=控制要求低，5=控制要求高"),
            ("explosiveness_score", "爆发力", "1=爆发力要求低，5=爆发力要求高"),
            ("stamina_score", "耐力", "1=体能压力小，5=体能压力大"),
            ("coordination_score", "协调性", "1=协调要求低，5=协调要求高"),
            ("footwork_score", "脚下技术", "1=脚下简单，5=脚下技术复杂")
        ]),
        ("学习成本", [
            ("music_access_difficulty", "音乐获取难度", "1=容易找到，5=很难找到或需要重新制作"),
            ("costume_access_difficulty", "服装获取难度", "1=容易解决，5=服装道具成本高")
        ]),
        ("表演要求", [
            ("character_score", "人物塑造", "1=人物要求低，5=人物塑造要求高"),
            ("emotional_range_score", "情绪跨度", "1=情绪单一，5=情绪层次复杂"),
            ("rhythm_difficulty_score", "节奏难度", "1=节奏简单，5=节奏复杂"),
            ("stage_blocking_score", "舞台调度", "1=调度简单，5=调度复杂")
        ]),
        ("使用场景", [
            ("competition_suitability_score", "比赛适配", "1=不适合比赛，5=很适合比赛"),
            ("teaching_suitability_score", "教学适配", "1=不适合课堂教学，5=很适合教学"),
            ("gala_suitability_score", "晚会适配", "1=不适合晚会，5=很适合晚会")
        ]),
    ]
    extra_number_groups = [
        ("学习成本", [
            ("suggested_experience_years", "建议舞龄", "建议学习中国舞或民族民间舞的年数。")
        ]),
        ("使用场景", [
            ("suitable_age_min", "适合最小年龄", "年龄下限。"),
            ("suitable_age_max", "适合最大年龄", "年龄上限。")
        ]),
    ]
    return render_page(
        "new_review.html",
        "新增专家评分",
        work=work,
        experts=experts,
        versions=versions,
        core_number_fields=core_number_fields,
        core_rating_fields=core_rating_fields,
        rating_groups=rating_groups,
        extra_number_groups=extra_number_groups,
    )


@app.route("/recommend", methods=["GET", "POST"])
def recommend_page():
    user_query = request.form.get("user_query", "").strip()
    result = None
    if request.method == "POST" and user_query:
        intent, ranked, llm_text, log_id = recommend(user_query)
        result = {
            "log_id": log_id,
            "intent": intent,
            "intent_json": json.dumps(intent, ensure_ascii=False, indent=2),
            "ranked": ranked,
            "llm_text": llm_text,
        }
    return render_page(
        "recommend.html",
        "帮我选剧目",
        user_query=user_query,
        result=result,
    )


@app.route("/api/works")
def api_works():
    rows = query_all("SELECT * FROM dance_work ORDER BY updated_at DESC")
    data = []
    for row in rows:
        item = dict(row)
        item["reviewAverages"] = review_averages(row["id"])
        item["needsRecheck"] = needs_recheck(row["id"])
        data.append(item)
    return jsonify(data)


@app.route("/api/works/<work_id>")
def api_work_detail(work_id):
    work = query_one("SELECT * FROM dance_work WHERE id = ?", (work_id,))
    if not work:
        return jsonify({"error": "not_found"}), 404
    versions = query_all("SELECT * FROM dance_video_version WHERE work_id = ? ORDER BY created_at DESC", (work_id,))
    reviews = query_all(
        """
        SELECT r.*, e.name AS expert_name, e.title AS expert_title
        FROM expert_review r JOIN expert e ON e.id = r.expert_id
        WHERE r.work_id = ? ORDER BY r.created_at DESC
        """,
        (work_id,),
    )
    return jsonify(
        {
            "work": dict(work),
            "versions": [dict(row) for row in versions],
            "reviews": [dict(row) for row in reviews],
            "reviewAverages": review_averages(work_id),
            "needsRecheck": needs_recheck(work_id),
        }
    )


@app.route("/api/recommend", methods=["POST"])
def api_recommend():
    payload = request.get_json(silent=True) or {}
    user_query = (payload.get("query") or payload.get("user_query") or "").strip()
    if not user_query:
        return jsonify({"error": "query_required"}), 400
    intent, ranked, llm_text, log_id = recommend(user_query)
    items = []
    for item in ranked:
        items.append(
            {
                "work": dict(item["work"]),
                "score": item["score"],
                "dimensions": item.get("dimensions", {}),
                "reasons": item["reasons"],
                "risks": item["risks"],
                "reviewAverages": item["avg"],
                "expertSummary": item["summary"],
                "versions": [dict(row) for row in item["versions"][:3]],
            }
        )
    return jsonify({"intent": intent, "recommendations": items, "llmText": llm_text, "logId": log_id})


@app.route("/recommendation-feedback", methods=["POST"])
def recommendation_feedback():
    log_id = request.form.get("log_id", "").strip()
    work_id = request.form.get("work_id", "").strip()
    rating = request.form.get("rating", "").strip()
    reason = request.form.get("reason", "").strip()
    if rating not in {"fit", "not_fit", "too_hard", "too_common", "video_weak"}:
        return redirect(url_for("logs"))
    if not query_one("SELECT id FROM recommendation_log WHERE id = ?", (log_id,)):
        return redirect(url_for("logs"))
    if not query_one("SELECT id FROM dance_work WHERE id = ?", (work_id,)):
        return redirect(url_for("logs"))
    execute(
        """
        INSERT INTO recommendation_feedback (id, log_id, work_id, rating, reason, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (new_id(), log_id, work_id, rating, reason, now()),
    )
    return redirect(url_for("logs"))


@app.route("/discover", methods=["GET", "POST"])
def discover_page():
    keyword = request.values.get("keyword", "").strip()
    message = request.args.get("message", "")
    search_results = []
    internal_mode = app_mode() == "internal"
    if request.method == "POST" and request.form.get("action") == "search" and internal_mode:
        keyword = request.form.get("keyword", "").strip()
        if keyword:
            raw_results, warning = search_bilibili_candidates(keyword)
            message = warning or f"B站搜索完成，返回 {len(raw_results)} 条结果。搜索结果不会自动入库。"
            seen = set()
            for item in raw_results:
                identity = video_identity(item["url"], item["platform"])
                key = (identity["platform"], identity["platform_video_id"] or identity["canonical_url"])
                if key in seen:
                    continue
                seen.add(key)
                duplicate = find_duplicate_video(item["url"], item["platform"])
                is_dance, confidence, reason = classify_dance_video(keyword, item["title"], item["uploader"])
                search_results.append(
                    {
                        **item,
                        **identity,
                        "embed_url": embed_url_for(item["url"]),
                        "is_dance_video": is_dance,
                        "dance_confidence": confidence,
                        "dance_reason": reason,
                        "duplicate": duplicate,
                        "possible_works": find_possible_works(item["title"]),
                    }
                )
    search_links = []
    if keyword:
        q = quote_plus(keyword)
        search_links = [
            ("B站原站", f"https://search.bilibili.com/all?keyword={q}"),
            ("YouTube", f"https://www.youtube.com/results?search_query={q}"),
            ("抖音", f"https://www.douyin.com/search/{q}"),
            ("小红书", f"https://www.xiaohongshu.com/search_result?keyword={q}"),
        ]
    works = query_all("SELECT id, title, ethnicity, form FROM dance_work ORDER BY title")
    return render_page(
        "discover.html",
        "搜视频入库",
        keyword=keyword,
        message=message,
        search_links=search_links,
        search_results=search_results,
        works=works,
        internal_mode=internal_mode,
    )


@app.route("/discover/ingest", methods=["POST"])
def ingest_discovered_video():
    url = request.form.get("url", "").strip()
    if not url:
        return redirect(url_for("discover_page", message="缺少视频链接。"))
    duplicate = find_duplicate_video(url, request.form.get("platform", ""))
    if duplicate:
        return redirect(url_for("work_detail", work_id=duplicate["work_id"]))
    new_title = request.form.get("new_title", "").strip()
    if new_title:
        work_id = create_work_from_values(
            {
                "title": new_title,
                "aliases": request.form.get("new_aliases", ""),
                "ethnicity": request.form.get("new_ethnicity", ""),
                "region": "",
                "dance_type": "民族民间舞",
                "form": request.form.get("new_form", "独舞"),
                "gender_tendency": "",
                "premiere_info": "由数据采编工作台新建。",
                "description": f"由视频《{request.form.get('title', '')}》入库时新建，待补充专家信息。",
            }
        )
    else:
        work_id = request.form.get("work_id")
        if not query_one("SELECT id FROM dance_work WHERE id = ?", (work_id,)):
            return redirect(url_for("discover_page", message="请选择已有剧目，或填写新剧目名。"))
    insert_video_version(
        work_id,
        {
            "platform": request.form.get("platform", ""),
            "url": url,
            "title": request.form.get("title", ""),
            "uploader": request.form.get("uploader", ""),
            "publish_date": request.form.get("publish_date", ""),
            "thumbnail_url": request.form.get("thumbnail_url", ""),
            "quality_score": 3,
            "notes": request.form.get("notes", "") or f"由数据采编工作台入库。关键词：{request.form.get('source_keyword', '')}",
        },
    )
    return redirect(url_for("work_detail", work_id=work_id))


@app.route("/quality")
def quality_dashboard():
    totals = {
        "works": query_one("SELECT COUNT(*) AS c FROM dance_work")["c"],
        "videos": query_one("SELECT COUNT(*) AS c FROM dance_video_version")["c"],
        "reviews": query_one("SELECT COUNT(*) AS c FROM expert_review")["c"],
    }
    no_video = query_all(
        f"""
        SELECT w.*
        FROM dance_work w
        LEFT JOIN dance_video_version v ON v.work_id = w.id
        GROUP BY w.id
        HAVING COUNT(v.id) = 0
        ORDER BY w.updated_at DESC
        LIMIT 30
        """
    )
    no_review = query_all(
        f"""
        SELECT w.*
        FROM dance_work w
        LEFT JOIN expert_review r ON r.work_id = w.id
        GROUP BY w.id
        HAVING COUNT(r.id) = 0
        ORDER BY w.updated_at DESC
        LIMIT 30
        """
    )
    incomplete = query_all(
        f"""
        SELECT *
        FROM dance_work
        WHERE COALESCE(ethnicity, '') = '' OR COALESCE(form, '') = '' OR COALESCE(description, '') = ''
        ORDER BY updated_at DESC
        LIMIT 30
        """
    )
    duplicate_groups = query_all(
        f"""
        SELECT normalized_title, COUNT(*) AS c, GROUP_CONCAT(title, ' / ') AS titles
        FROM dance_work
        WHERE COALESCE(normalized_title, '') != ''
        GROUP BY normalized_title
        HAVING COUNT(*) > 1
        ORDER BY c DESC, normalized_title
        LIMIT 30
        """
    )
    recheck_rows = []
    for work in query_all("SELECT id, title, ethnicity, form FROM dance_work ORDER BY updated_at DESC"):
        if needs_recheck(work["id"]):
            recheck_rows.append(work)
        if len(recheck_rows) >= 30:
            break
    blank_platform_id = query_all(
        """
        SELECT v.*, w.title AS work_title
        FROM dance_video_version v JOIN dance_work w ON w.id = v.work_id
        WHERE COALESCE(v.platform_video_id, '') = '' AND v.platform IN ('B站', 'YouTube')
        ORDER BY v.created_at DESC
        LIMIT 30
        """
    )
    return render_page(
        "quality.html",
        "资料检查",
        totals=totals,
        no_video=no_video,
        no_review=no_review,
        incomplete=incomplete,
        duplicate_groups=duplicate_groups,
        recheck_rows=recheck_rows,
        blank_platform_id=blank_platform_id,
    )


@app.route("/import", methods=["GET", "POST"])
def import_page():
    if app_mode() != "internal":
        return redirect(url_for("works"))
    imported = None
    if request.method == "POST":
        file = request.files.get("file")
        if file:
            text = file.read().decode("utf-8-sig")
            reader = csv.DictReader(text.splitlines())
            imported = 0
            for row in reader:
                title = (row.get("title") or "").strip()
                url = (row.get("url") or "").strip()
                if not title:
                    continue
                existing = query_one("SELECT * FROM dance_work WHERE title = ? OR aliases LIKE ?", (title, f"%{title}%"))
                if existing:
                    work_id = existing["id"]
                else:
                    work_id = create_work_from_values(
                        {
                            "title": title,
                            "aliases": row.get("aliases", ""),
                            "ethnicity": row.get("ethnicity", ""),
                            "region": row.get("region", ""),
                            "dance_type": row.get("danceType", row.get("dance_type", "民族民间舞")),
                            "form": row.get("form", ""),
                            "gender_tendency": row.get("genderTendency", row.get("gender_tendency", "")),
                            "props": row.get("props", ""),
                            "music_info": row.get("musicInfo", row.get("music_info", "")),
                            "premiere_info": row.get("premiereInfo", row.get("premiere_info", "")),
                            "description": row.get("description", ""),
                        }
                    )
                    imported += 1
                if url:
                    insert_video_version(
                        work_id,
                        {
                            "platform": row.get("platform", ""),
                            "url": url,
                            "title": row.get("videoTitle", row.get("video_title", "")),
                            "uploader": row.get("uploader", ""),
                            "performer": row.get("performer", ""),
                            "institution": row.get("institution", ""),
                            "event_name": row.get("eventName", row.get("event_name", "")),
                            "publish_date": row.get("publishDate", row.get("publish_date", "")),
                            "thumbnail_url": row.get("thumbnailUrl", row.get("thumbnail_url", "")),
                            "screenshot_url": row.get("screenshotUrl", row.get("screenshot_url", "")),
                            "quality_score": row.get("qualityScore", row.get("quality_score")),
                            "notes": row.get("notes", ""),
                        },
                    )
            imported = imported or 0
    return render_page("import.html", "批量导入", imported=imported)


@app.route("/logs")
def logs():
    rows = query_all("SELECT * FROM recommendation_log ORDER BY created_at DESC LIMIT 50")
    display_rows = []
    for row in rows:
        item = dict(row)
        try:
            item["recommended_count"] = len(json.loads(row["recommended_work_ids"]))
        except Exception:
            item["recommended_count"] = 0
        display_rows.append(item)
    return render_page("logs.html", "推荐记录", rows=display_rows)


@app.route("/logs/clear", methods=["POST"])
def clear_logs():
    execute("DELETE FROM recommendation_feedback")
    execute("DELETE FROM recommendation_log")
    return redirect(url_for("logs"))


@app.cli.command("init-db")
def init_db_command():
    init_db(seed=True)
    print(f"SQLite database initialized at {DB_PATH}")


if __name__ == "__main__":
    with app.app_context():
        init_db(seed=True)
    app.run(debug=True, host="127.0.0.1", port=int(os.environ.get("PORT", "5000")))
