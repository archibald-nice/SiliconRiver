"""Fetch Hugging Face models and persist them into PostgreSQL."""
from __future__ import annotations

import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Dict

import psycopg
import requests
from dotenv import load_dotenv
from huggingface_hub import HfApi, ModelInfo
from huggingface_hub.utils import HfHubHTTPError
from html.parser import HTMLParser
from urllib.parse import urljoin

try:
    from scripts.init_db import create_schema  # type: ignore
except Exception:  # pragma: no cover
    create_schema = None  # type: ignore

LOGGER = logging.getLogger("silicon_river.fetch")
LOGGING_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOGGING_LEVEL, format="%(asctime)s [%(levelname)s] %(message)s")

BASE_DIR = Path(__file__).resolve().parents[2]
ENV_PATH = BASE_DIR / ".env"
DEFAULT_DB_URL = "postgresql://USER:PASSWORD@HOST:5432/silicon_river"
HTTP_TIMEOUT = 15
AVATAR_MAX_BYTES = int(os.getenv("AVATAR_MAX_BYTES", "524288"))

# ---------- 模型简介 ----------
# 为什么必须单独去拉 README：
#   HF 已经把模型描述从卡片元数据里移除了。实测（huggingface_hub 0.35.3）：
#   list_models(full=True) 返回的 cardData 是 null，ModelInfo 上连 description
#   属性都没有；ModelCardData 现在只剩 license / library_name / pipeline_tag /
#   datasets 这类结构化字段，没有 summary。full / cardData / expand 三种参数组合
#   都试过，一律拿不到。简介现在只存在于仓库的 README.md 正文里。
FETCH_DESCRIPTIONS = os.getenv("FETCH_DESCRIPTIONS", "true").lower() == "true"
DESCRIPTION_CONCURRENCY = int(os.getenv("DESCRIPTION_CONCURRENCY", "8"))
DESCRIPTION_TIMEOUT = float(os.getenv("DESCRIPTION_TIMEOUT", "10"))
DESCRIPTION_MAX_CHARS = int(os.getenv("DESCRIPTION_MAX_CHARS", "300"))

# ---------- pipeline_tag 过滤（ISSUE-031 前置）----------
# 不带 filter 时 HF 会把该 org 的**全部**仓库拉回来（实测 nvidia 975 个仓库里只有
# 269 个是 text-generation），视觉/语音仓库会一起进时间轴。默认只抓 text-generation；
# 设成空字符串表示不过滤（拿全量）。
DEFAULT_PIPELINE_TAG = "text-generation"

# ---------- models.source 取值域 ----------
# ISSUE-004 跨源去重的依据：同一模型可能既有 HF 行又有 OpenRouter 行。
# 列定义与默认值见 scripts/init_db.py（列由建表侧负责，本文件只负责写入）。
#   值域：huggingface / openrouter / unknown
SOURCE_HUGGINGFACE = "huggingface"
SOURCE_OPENROUTER = "openrouter"
SOURCE_UNKNOWN = "unknown"


@dataclass(slots=True)
class ModelRecord:
    model_id: str
    provider: str
    model_name: str
    description: str
    tags: List[str]
    created_at: datetime
    downloads: int | None
    likes: int | None
    model_card_url: str
    inserted_at: datetime
    is_open_source: Optional[bool]
    price: Optional[Dict[str, object]]
    huggingface_rank: Optional[int]


def load_config() -> None:
    if ENV_PATH.exists():
        load_dotenv(dotenv_path=ENV_PATH, override=False, encoding="utf-8-sig")


def resolve_db_url() -> str:
    load_config()
    return os.getenv("DATABASE_URL", DEFAULT_DB_URL)


def get_providers(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [provider.strip() for provider in raw.split(",") if provider.strip()]


def hf_client() -> HfApi:
    load_config()
    token = os.getenv("HF_TOKEN")
    if not token:
        LOGGER.warning("HF_TOKEN is not set; unauthenticated requests may be rate-limited.")
    return HfApi(token=token)


def resolve_pipeline_tag() -> str:
    """读 `HF_PIPELINE_TAG`（ISSUE-031 前置）。

    未设置 → 默认 ``DEFAULT_PIPELINE_TAG``（text-generation）；显式设成空字符串
    → 返回 ""，表示不过滤、把该 org 的全部仓库（含视觉/语音）都抓回来。
    """
    raw = os.getenv("HF_PIPELINE_TAG")
    if raw is None:
        return DEFAULT_PIPELINE_TAG
    return raw.strip()


def build_list_models_kwargs(provider: str, limit: int | None) -> dict:
    """构造 `HfApi.list_models` 的参数，按 pipeline_tag 过滤（ISSUE-031 前置）。

    huggingface_hub 0.35.3 的 `list_models` 签名是
    ``filter: Union[str, Iterable[str], None] = None``，内部 ``if filter:`` 为假就
    不往 query string 里放 filter，所以空 tag 时宁可**不传这个 kwarg**：语义上是
    「不过滤」，也不会因为传空串让调用方误以为过滤生效了。
    """
    kwargs: dict = {
        "author": provider,
        "sort": "lastModified",
        "direction": -1,
        "limit": limit,
        "full": True,
    }
    pipeline_tag = resolve_pipeline_tag()
    if pipeline_tag:
        LOGGER.info(
            "Provider %s：按 pipeline_tag=%s 过滤（只抓该任务的仓库，避免视觉/语音等"
            "非 LLM 仓库污染时间轴）",
            provider,
            pipeline_tag,
        )
        kwargs["filter"] = pipeline_tag
    else:
        LOGGER.info(
            "Provider %s：HF_PIPELINE_TAG 为空，未过滤，会包含非 LLM 仓库", provider
        )
    return kwargs


def normalise_datetime(value: datetime | str | None) -> datetime:
    """把 HF 给的时间值统一成 UTC aware `datetime`（ISSUE-006：不再格式化成字符串）。

    HF 的 `ModelInfo.created_at` 通常是 aware datetime，`lastModified` 等字段
    在部分版本里是字符串且带 `Z` 后缀；naive 值按 UTC 解释（这些列的语义本来
    就是 UTC）。入库列是 `timestamptz`，传 aware datetime 才不会丢时区语义。
    """
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return datetime.now(timezone.utc)
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        value = datetime.fromisoformat(text)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# 从 README 抽简介
# ---------------------------------------------------------------------------

_FRONT_MATTER_END = re.compile(r"\n---[ \t]*(?:\n|$)")
_HTML_TAG = re.compile(r"<[^>]+>")
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MD_EMPHASIS = re.compile(r"[*_`~]+")
_WHITESPACE = re.compile(r"\s+")

# 一眼就不是正文的行：表格、分隔线、注释、列表项、引用、标题
_NOT_PROSE_PREFIXES = ("|", "---", "===", "<!--", ">", "- ", "* ", "+ ", "#")


def _clean_markdown_line(line: str) -> str:
    """把一行 markdown 压成纯文本（去 HTML、图片、链接语法、强调符号）。"""
    line = _HTML_TAG.sub(" ", line)
    line = _MD_IMAGE.sub(" ", line)
    line = _MD_LINK.sub(r"\1", line)
    line = _MD_EMPHASIS.sub("", line)
    return _WHITESPACE.sub(" ", line).strip()


def extract_description_from_readme(
    text: str | None,
    max_chars: int = DESCRIPTION_MAX_CHARS,
) -> str:
    """从 README 正文里抽取第一段像样的文字作为简介。

    模型卡的 README 通常长这样，所以按顺序跳过：
        ---                 ← YAML front matter（license / tags 等）
        ---
        <div align="center">  ← HTML 容器
        ![logo](...)          ← 徽章、图片
        # 模型名               ← 标题
        We introduce ...      ← 这才是要的那段

    Args:
        text: README.md 的完整内容
        max_chars: 截断长度（数据库里 description 字段也按这个长度存）

    Returns:
        抽取到的简介；抽不到就返回空字符串（调用方据此判断失败）
    """
    if not text:
        return ""

    body = text.lstrip("\ufeff")
    # 去掉 YAML front matter（必须成对出现的 --- 才算）
    if body.startswith("---"):
        match = _FRONT_MATTER_END.search(body)
        if match:
            body = body[match.end():]

    for raw_line in body.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped.startswith(_NOT_PROSE_PREFIXES):
            continue
        line = _clean_markdown_line(raw_line)
        # 太短的不要：多半是被跳过的标题残留、单个人名、分隔符
        if len(line) < 30:
            continue
        return line[:max_chars]

    return ""


def fetch_model_description(
    model_id: str,
    token: str | None = None,
    timeout: float = DESCRIPTION_TIMEOUT,
) -> str:
    """拉取单个模型的 README.md 并抽取简介。任何失败都返回空字符串。"""
    url = f"https://huggingface.co/{model_id}/raw/main/README.md"
    headers = {"Accept": "text/plain", "User-Agent": "silicon-river/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    except requests.RequestException as exc:
        LOGGER.debug("README 拉取失败 %s: %s", model_id, exc)
        return ""

    if not response.ok:
        # 没有 README 的仓库会 404，这是正常情况，不该刷 warning
        LOGGER.debug("README 不可用 %s（HTTP %s）", model_id, response.status_code)
        return ""

    return extract_description_from_readme(response.text)


def fetch_descriptions(
    model_ids: Iterable[str],
    token: str | None = None,
) -> dict[str, str]:
    """并发拉取一批模型的简介。

    这是整个抓取流程里唯一会放大请求量的地方：每个模型一次请求。所以：
    - 并发可配（DESCRIPTION_CONCURRENCY），默认 8；
    - 单条失败只 debug 一行，不影响整批；
    - 返回的字典只包含**成功拿到简介**的模型，调用方据此保留旧值。

    Args:
        model_ids: 需要拉取的模型 ID 列表
        token: HF token（可选，有的话限速更宽松）

    Returns:
        {model_id: description}
    """
    ids = [mid for mid in model_ids if mid]
    if not FETCH_DESCRIPTIONS:
        LOGGER.info("FETCH_DESCRIPTIONS=false，跳过 README 拉取")
        return {}
    if not ids:
        return {}

    workers = max(1, DESCRIPTION_CONCURRENCY)
    LOGGER.info("拉取 %s 个模型的 README 简介（并发 %s）", len(ids), workers)

    found: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_model_description, mid, token): mid for mid in ids}
        for done, future in enumerate(as_completed(futures), start=1):
            model_id = futures[future]
            try:
                description = future.result()
            except Exception as exc:  # pragma: no cover - 线程内异常兜底
                LOGGER.debug("README 任务异常 %s: %s", model_id, exc)
                description = ""
            if description:
                found[model_id] = description
            if done % 50 == 0 or done == len(ids):
                LOGGER.info("  README 进度 %s/%s（已拿到 %s 条）", done, len(ids), len(found))

    LOGGER.info("README 完成：%s/%s 条拿到简介", len(found), len(ids))
    return found


def load_existing_descriptions(conn: psycopg.Connection, provider: str) -> dict[str, str]:
    """读取该厂商下已有非空简介的模型，用于跳过重复拉取。

    没有这个跳过，`daily_sync.sh` 每天都会为上千个老模型重拉一遍 README。
    """
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT model_id, description
                FROM models
                WHERE provider = %s AND description IS NOT NULL AND description <> ''
                """,
                (provider,),
            )
            return {row[0]: row[1] for row in cursor.fetchall()}
    except psycopg.Error as exc:  # pragma: no cover - 读失败就退回全量拉取
        LOGGER.warning("读取已有 description 失败（本厂商将全量拉取）：%s", exc)
        return {}


def _description_from_card_data(info: ModelInfo) -> str:
    """旧的提取路径，保底用。

    实测当前 HF 一律返回空（cardData 为 null，且 ModelInfo 已无 description 属性），
    但如果 HF 哪天把这两个字段加回来，走这条路比发一次 HTTP 便宜。
    """
    card_data = getattr(info, "cardData", None) or {}
    description = ""
    if isinstance(card_data, dict):
        description = card_data.get("summary") or card_data.get("description") or ""
    if not description:
        fallback = getattr(info, "description", None)
        if fallback:
            description = str(fallback)
    return str(description or "")


def to_record(provider: str, info: ModelInfo, description: str | None = None) -> ModelRecord:
    """把一个 HF ModelInfo 转成待入库的记录。

    Args:
        description: 已经拿到的简介（来自 README 或库里旧值）。传 None 时退回
                     卡片元数据里找 —— 那条路目前恒为空，仅作保底。
    """
    if description is None:
        description = _description_from_card_data(info)
    tags = list(getattr(info, "tags", []) or [])
    created_at = normalise_datetime(
        getattr(info, "created_at", None) or getattr(info, "lastModified", None)
    )
    inserted_at = datetime.now(timezone.utc)
    downloads = getattr(info, "downloads", None)
    likes = getattr(info, "likes", None)
    private_attr = getattr(info, "private", None)
    if private_attr is None:
        is_open_source = None
    else:
        is_open_source = True if private_attr is None else not bool(private_attr)

    return ModelRecord(
        model_id=info.modelId,
        provider=provider,
        model_name=info.modelId.split("/")[-1],
        description=(description or "")[:DESCRIPTION_MAX_CHARS],
        tags=tags,
        created_at=created_at,
        downloads=downloads,
        likes=likes,
        model_card_url=f"https://huggingface.co/{info.modelId}",
        inserted_at=inserted_at,
        is_open_source=is_open_source,
        price=None,
        huggingface_rank=None,
    )


def ensure_db(url: str | None = None) -> psycopg.Connection:
    db_url = url or resolve_db_url()
    if create_schema is not None:
        create_schema(db_url)
    conn = psycopg.connect(db_url)
    return conn


def upsert_provider(
    conn: psycopg.Connection,
    provider_id: str,
    avatar_url: str | None,
    display_name: str | None,
    avatar_content: bytes | None,
    avatar_mime: str | None,
) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO providers (provider_id, display_name, avatar_url, avatar_blob, avatar_mime, updated_at)
            VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (provider_id) DO UPDATE
            SET
                display_name = EXCLUDED.display_name,
                avatar_url = EXCLUDED.avatar_url,
                avatar_blob = EXCLUDED.avatar_blob,
                avatar_mime = EXCLUDED.avatar_mime,
                updated_at = CURRENT_TIMESTAMP
            """,
            (provider_id, display_name, avatar_url, avatar_content, avatar_mime),
        )


def _extract_display_name(info: object, provider_id: str) -> str:
    candidates = ("displayName", "fullname", "name")
    if isinstance(info, dict):
        for key in candidates:
            value = info.get(key)
            if isinstance(value, str) and value.strip():
                return value
        nested = info.get("organization") or info.get("user")
        if isinstance(nested, dict):
            for key in candidates:
                value = nested.get(key)
                if isinstance(value, str) and value.strip():
                    return value
        return info.get("id") or info.get("uid") or provider_id
    for attr in candidates:
        value = getattr(info, attr, None)
        if isinstance(value, str) and value.strip():
            return value
    return getattr(info, "id", provider_id)


def _extract_avatar_url(info: object) -> str | None:
    candidates = ("avatarUrl", "avatar_url", "avatar")
    if isinstance(info, dict):
        for key in candidates:
            value = info.get(key)
            if isinstance(value, str) and value.strip():
                return value
        nested = info.get("organization") or info.get("user")
        if isinstance(nested, dict):
            for key in candidates:
                value = nested.get(key)
                if isinstance(value, str) and value.strip():
                    return value
        return None
    for attr in candidates:
        value = getattr(info, attr, None)
        if isinstance(value, str) and value.strip():
            return value
    return None


def resolve_provider_profile(client: HfApi, provider_id: str) -> tuple[str, str | None]:
    resolver_groups = (
        ("organization_info", "get_org"),
        ("user_info", "get_user"),
    )
    for resolver_names in resolver_groups:
        resolver = None
        resolver_name = None
        for name in resolver_names:
            if hasattr(client, name):
                resolver = getattr(client, name)
                resolver_name = name
                break
        if resolver is None or resolver_name is None:
            continue
        try:
            info = resolver(provider_id)
        except HfHubHTTPError as error:
            if getattr(error, "response", None) is not None and error.response.status_code == 404:
                continue
            LOGGER.warning("Failed to fetch %s for %s: %s", resolver_name, provider_id, error)
            continue
        except Exception as exc:  # pragma: no cover - unexpected
            LOGGER.warning("Unexpected error calling %s for %s: %s", resolver_name, provider_id, exc)
            continue
        info_object = info.dict() if hasattr(info, "dict") else info
        display_name = _extract_display_name(info_object, provider_id)
        avatar_url = _extract_avatar_url(info_object)
        if avatar_url is None:
            LOGGER.debug("Provider %s missing avatar in %s payload: %s", provider_id, resolver_name, info_object)
        return display_name, avatar_url
    token = os.getenv("HF_TOKEN")
    display_name, avatar_url = fetch_provider_profile_http(provider_id, token)
    return display_name, avatar_url


def _http_get_json(url: str, token: str | None) -> dict | None:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        response = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT)
    except requests.RequestException as exc:
        LOGGER.debug("HTTP metadata request failed %s: %s", url, exc)
        return None
    if response.status_code == 404:
        return None
    if not response.ok:
        LOGGER.debug("HTTP metadata request %s returned %s: %s", url, response.status_code, response.text)
        return None
    try:
        return response.json()
    except ValueError:
        LOGGER.debug("HTTP metadata response from %s is not JSON", url)
        return None


def fetch_provider_profile_http(provider_id: str, token: str | None) -> tuple[str, str | None]:
    endpoints = (
        f"https://huggingface.co/api/organizations/{provider_id}",
        f"https://huggingface.co/api/users/{provider_id}",
    )
    for url in endpoints:
        payload = _http_get_json(url, token)
        if not payload:
            continue
        display_name = _extract_display_name(payload, provider_id)
        avatar_url = _extract_avatar_url(payload)
        if avatar_url or display_name != provider_id:
            return display_name, avatar_url
    display_name, avatar_url = fetch_provider_profile_html(provider_id)
    return display_name, avatar_url


def download_provider_avatar(avatar_url: str | None, token: str | None) -> tuple[bytes | None, str | None]:
    if not avatar_url:
        return None, None
    headers = {"Accept": "image/*"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        response = requests.get(avatar_url, headers=headers, timeout=HTTP_TIMEOUT)
    except requests.RequestException as exc:
        LOGGER.debug("Avatar download failed %s: %s", avatar_url, exc)
        return None, None
    if not response.ok:
        LOGGER.debug("Avatar download %s returned %s", avatar_url, response.status_code)
        return None, None
    content = response.content
    if len(content) > AVATAR_MAX_BYTES:
        LOGGER.debug("Avatar %s exceeds max bytes (%s)", avatar_url, AVATAR_MAX_BYTES)
        return None, None
    content_type = response.headers.get("content-type")
    if content_type:
        content_type = content_type.split(";")[0].strip()
    return content, content_type


class _ProfileHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.meta: dict[str, str] = {}
        self._h1_active = False
        self.heading: list[str] = []
        self.img_candidates: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key: value for key, value in attrs if value is not None}
        if tag == "meta":
            prop = attrs_dict.get("property")
            content = attrs_dict.get("content")
            if prop in {"og:image", "og:title"} and content:
                self.meta[prop] = content
        elif tag == "h1":
            self._h1_active = True
        elif tag == "img":
            src = attrs_dict.get("src")
            if src:
                classes = attrs_dict.get("class", "")
                if any(keyword in classes for keyword in ("object-cover", "avatar", "rounded-full")):
                    self.img_candidates.append(src)

    def handle_endtag(self, tag: str) -> None:
        if tag == "h1":
            self._h1_active = False

    def handle_data(self, data: str) -> None:
        if self._h1_active and data.strip():
            self.heading.append(data.strip())


def fetch_provider_profile_html(provider_id: str) -> tuple[str, str | None]:
    url = f"https://huggingface.co/{provider_id}"
    try:
        response = requests.get(url, headers={"Accept": "text/html"}, timeout=HTTP_TIMEOUT)
    except requests.RequestException as exc:
        LOGGER.debug("HTML metadata request failed %s: %s", url, exc)
        return provider_id, None
    if not response.ok:
        LOGGER.debug("HTML metadata request %s returned %s", url, response.status_code)
        return provider_id, None

    parser = _ProfileHTMLParser()
    parser.feed(response.text)

    display_name = parser.meta.get("og:title") or (" ".join(parser.heading).strip() if parser.heading else provider_id)
    raw_avatar = next(iter(parser.img_candidates), None) or parser.meta.get("og:image")
    avatar_url = urljoin(url, raw_avatar) if raw_avatar else None
    return display_name or provider_id, avatar_url


# ---------------------------------------------------------------------------
# 大小写归一（ISSUE-004）
# ---------------------------------------------------------------------------
# 同一模型会在两个源里出现两种写法：HF 保留 org 原始大小写（`Qwen/Qwen3.6-27B`），
# OpenRouter 一律小写（`qwen/qwen3.6-27b`）。两者在 `models` 里就是两行、时间轴上是
# 两个节点（生产库实测 29 组 / 60 行，占全库 18% 重复的一部分）。
#
# 这里的做法是「写入时归一到已存在的那一行」：不再新建大小写变体，把本次抓到的字段
# 更新到先入库的那一行上；provider 只在大小写之外真的不同时才覆盖，避免 `Qwen`/`qwen`
# 这种展示名被两个源来回改写（命名统一属 ISSUE-005，还没定）。
def resolve_case_variant(cursor, model_id: str) -> str | None:
    """返回库里与 ``model_id`` 仅大小写不同的既有 model_id；没有则 None。"""
    if not model_id:
        return None
    cursor.execute(
        "SELECT model_id FROM models WHERE lower(model_id) = lower(%s) LIMIT 1",
        (model_id,),
    )
    row = cursor.fetchone()
    if not row:
        return None
    existing = row[0]
    return existing if existing != model_id else None


def save_models(conn: psycopg.Connection, provider: str, records: Iterable[ModelRecord], *, started_at: datetime) -> tuple[int, int]:
    processed = 0
    inserted = 0
    with conn.cursor() as cursor:
        for record in records:
            processed += 1
            # ISSUE-004：同一模型另一种大小写已在库里时，写到既有那行上，别再建一行。
            target_id = resolve_case_variant(cursor, record.model_id) or record.model_id
            cursor.execute(
                """
                INSERT INTO models (
                    model_id, provider, model_name, description, tags,
                    created_at, downloads, likes, model_card_url, inserted_at,
                    is_open_source, price, huggingface_rank, source
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (model_id) DO UPDATE SET
                    provider = CASE
                        WHEN lower(models.provider) = lower(EXCLUDED.provider) THEN models.provider
                        ELSE EXCLUDED.provider
                    END,
                    model_name = EXCLUDED.model_name,
                    description = EXCLUDED.description,
                    tags = EXCLUDED.tags,
                    created_at = EXCLUDED.created_at,
                    downloads = EXCLUDED.downloads,
                    likes = EXCLUDED.likes,
                    model_card_url = EXCLUDED.model_card_url,
                    inserted_at = EXCLUDED.inserted_at,
                    is_open_source = EXCLUDED.is_open_source,
                    price = COALESCE(EXCLUDED.price, models.price),
                    huggingface_rank = COALESCE(EXCLUDED.huggingface_rank, models.huggingface_rank),
                    -- 来源只认「首个已知值」：跨源合并行（HF 与 OpenRouter 写同一 model_id
                    -- 或大小写归一后落到同一行）不要互相覆盖，否则每日固定「先 HF 后 OR」
                    -- 会让所有合并行的 source 恒为 openrouter，ISSUE-004 判源就失效了。
                    source = COALESCE(NULLIF(models.source, 'unknown'), EXCLUDED.source)
                RETURNING (xmax = 0) AS is_insert
                """,
                (
                    target_id,
                    record.provider,
                    record.model_name,
                    record.description,
                    json.dumps(record.tags, ensure_ascii=False),
                    record.created_at,
                    record.downloads,
                    record.likes,
                    record.model_card_url,
                    record.inserted_at,
                    record.is_open_source,
                    json.dumps(record.price, ensure_ascii=False) if record.price is not None else None,
                    record.huggingface_rank,
                    SOURCE_HUGGINGFACE,
                ),
            )
            # 不能用 cursor.rowcount：ON CONFLICT DO UPDATE 下它无论新增还是更新都是 1，
            # 会把「更新」也算成「新增」，污染 sync_log 审计表。
            # xmax = 0 表示这一行是本次 INSERT 产生的（新行），否则是被 UPDATE 的旧行。
            inserted_row = cursor.fetchone()
            is_insert = bool(inserted_row and inserted_row[0])
            cursor.execute("DELETE FROM model_tags WHERE model_id = %s", (target_id,))
            if record.tags:
                tag_rows = [
                    (target_id, tag, record.inserted_at)
                    for tag in record.tags
                ]
                cursor.executemany(
                    """
                    INSERT INTO model_tags (model_id, tag, inserted_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (model_id, tag) DO UPDATE SET inserted_at = EXCLUDED.inserted_at
                    """,
                    tag_rows,
                )
            if is_insert:
                inserted += 1
        finished_at = datetime.now(timezone.utc)
        cursor.execute(
            """
            INSERT INTO sync_log (provider, started_at, finished_at, status, processed, inserted, error_message)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                provider,
                normalise_datetime(started_at),
                finished_at,
                "success",
                processed,
                inserted,
                None,
            ),
        )
    conn.commit()
    return processed, inserted


class StageTimer:
    """分阶段累计耗时（ISSUE-034）。

    用来回答「生产 16 分钟 vs 本地 29 秒，瓶颈在哪一段」：原来只有一行
    `processed=/inserted=`，拉列表、读 README、写库三段耗时全糊在一起。

    用法::

        timer = StageTimer("profile", "list", "readme", "write")
        timer.begin("list")
        ...
        timer.begin("readme")   # 进入新阶段时自动结算上一段
        ...
        timer.stop()

    异常中途退出时不用 ``stop()``：``current`` 指出卡在哪一段，``describe()`` /
    ``total`` 会把**正在跑的那一段**按此刻已耗时间算进去（只读取，不改状态）。
    """

    __slots__ = ("_totals", "_current", "_started")

    def __init__(self, *stages: str) -> None:
        self._totals: dict[str, float] = {name: 0.0 for name in stages}
        self._current: str | None = None
        self._started = 0.0

    def begin(self, name: str) -> None:
        """进入 ``name`` 阶段（先结算上一个尚未结算的阶段）。"""
        now = time.perf_counter()
        self._close(now)
        self._totals.setdefault(name, 0.0)
        self._current = name
        self._started = now

    def stop(self) -> None:
        """结算当前阶段（正常收尾时调用）。"""
        self._close(time.perf_counter())
        self._current = None

    def _close(self, now: float) -> None:
        if self._current is not None:
            self._totals[self._current] = self._totals.get(self._current, 0.0) + (now - self._started)

    @property
    def current(self) -> str | None:
        """当前（或异常中断时停在的）阶段名。"""
        return self._current

    def _snapshot(self) -> dict[str, float]:
        totals = dict(self._totals)
        if self._current is not None:
            totals[self._current] = totals.get(self._current, 0.0) + (
                time.perf_counter() - self._started
            )
        return totals

    @property
    def total(self) -> float:
        return sum(self._snapshot().values())

    def describe(self, order: Iterable[str]) -> str:
        """按 ``order`` 输出 `list=53.3s readme=0.2s ...` 形式的片段。"""
        totals = self._snapshot()
        return " ".join(f"{name}={totals.get(name, 0.0):.1f}s" for name in order)


def fetch_and_store(limit: int = 50) -> dict[str, tuple[int, int]]:
    """按 PROVIDERS 逐家抓 HF 模型。

    ``limit`` 是**每家**的抓取窗口；``<= 0`` 表示不限制（交给 huggingface_hub 分页拉全）。
    窗口用满时会打 WARNING —— 与 ISSUE-030 同一类坑：上限把模型无声截断，
    表现是「某家模型比官网少」，不报错也没人发现（ISSUE-031：新增 org 动辄 200+ 个模型）。
    """
    client = hf_client()
    providers = get_providers(os.getenv("PROVIDERS"))
    if not providers:
        raise RuntimeError("PROVIDERS is not configured. Set it in environment or .env file.")

    effective_limit = limit if limit and limit > 0 else None
    results: dict[str, tuple[int, int]] = {}
    token = os.getenv("HF_TOKEN")
    with ensure_db() as conn:
        for provider in providers:
            LOGGER.info("Fetching models for provider %s", provider)
            # ISSUE-034：分阶段计时，异常退出也要能看出卡在哪一段。
            timer = StageTimer("profile", "list", "readme", "write")
            model_count = 0
            finished = False
            try:
                timer.begin("profile")
                display_name, avatar_url = resolve_provider_profile(client, provider)
                avatar_content, avatar_mime = download_provider_avatar(avatar_url, token)
                try:
                    upsert_provider(conn, provider, avatar_url, display_name, avatar_content, avatar_mime)
                except Exception as exc:  # pragma: no cover - database failure
                    LOGGER.warning("Failed to upsert provider %s metadata: %s", provider, exc)

                timer.begin("list")
                models_iter = client.list_models(
                    **build_list_models_kwargs(provider, effective_limit)
                )
                # 必须先物化：拉 README 简介需要先拿到全部 model_id 才能并发
                infos = list(models_iter)
                model_count = len(infos)
                if effective_limit is not None and model_count >= effective_limit:
                    LOGGER.warning(
                        "Provider %s：抓取窗口 %s 条已用满，大概率还有模型被截断"
                        "（HF_DAILY_FETCH_LIMIT，设 0 表示不限）",
                        provider,
                        effective_limit,
                    )

                timer.begin("readme")
                # 只给「还没有简介」的模型拉 README。
                #   首次抓取：492 个全拉；
                #   后续 daily_sync：绝大多数已有简介，跳过，避免每天白跑上千次请求。
                existing = load_existing_descriptions(conn, provider)
                missing = [info.modelId for info in infos if not existing.get(info.modelId)]
                if missing:
                    LOGGER.info(
                        "Provider %s：%s 个模型需要拉简介（已有 %s 个可跳过）",
                        provider, len(missing), len(infos) - len(missing),
                    )
                fetched = fetch_descriptions(missing, token=token)
                descriptions = {**existing, **fetched}

                timer.begin("write")
                started_at = datetime.now(timezone.utc)
                records = (
                    to_record(provider, info, description=descriptions.get(info.modelId))
                    for info in infos
                )
                processed, inserted = save_models(conn, provider, records, started_at=started_at)
                timer.stop()
                finished = True
                LOGGER.info("Provider %s: processed=%s inserted=%s", provider, processed, inserted)
                results[provider] = (processed, inserted)
            finally:
                suffix = "" if finished else f"（中断于 {timer.current or '?'} 段）"
                LOGGER.info(
                    "Provider %s 计时%s: %s 共 %.1fs（%s 个模型）",
                    provider,
                    suffix,
                    timer.describe(("list", "readme", "write", "profile")),
                    timer.total,
                    model_count,
                )
    return results


if __name__ == "__main__":
    summary = fetch_and_store()
    for provider, (processed, inserted) in summary.items():
        print(f"{provider}: processed={processed} inserted={inserted}")

    # 爬虫完成后，运行AI分析
    try:
        from src.scraper.analysis_orchestrator import run_post_scrape_analysis

        LOGGER.info("爬虫完成，开始运行AI分析...")
        analysis_result = run_post_scrape_analysis()
        LOGGER.info(f"AI分析完成: {analysis_result}")
    except Exception as e:
        LOGGER.warning(f"AI分析运行失败: {e}")
