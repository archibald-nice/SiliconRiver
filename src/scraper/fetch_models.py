"""Fetch Hugging Face models and persist them into PostgreSQL."""
from __future__ import annotations

import json
import logging
import os
import re
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
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
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


@dataclass(slots=True)
class ModelRecord:
    model_id: str
    provider: str
    model_name: str
    description: str
    tags: List[str]
    created_at: str
    downloads: int | None
    likes: int | None
    model_card_url: str
    inserted_at: str
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


def normalise_datetime(value: datetime | None) -> datetime:
    if value is None:
        value = datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def format_timestamp(value: datetime | None) -> str:
    return normalise_datetime(value).strftime(TIMESTAMP_FORMAT)


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
    created_at = format_timestamp(getattr(info, "created_at", None) or getattr(info, "lastModified", None))
    inserted_at = format_timestamp(datetime.now(timezone.utc))
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


def save_models(conn: psycopg.Connection, provider: str, records: Iterable[ModelRecord], *, started_at: datetime) -> tuple[int, int]:
    processed = 0
    inserted = 0
    with conn.cursor() as cursor:
        for record in records:
            processed += 1
            cursor.execute(
                """
                INSERT INTO models (
                    model_id, provider, model_name, description, tags,
                    created_at, downloads, likes, model_card_url, inserted_at,
                    is_open_source, price, huggingface_rank
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (model_id) DO UPDATE SET
                    provider = EXCLUDED.provider,
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
                    huggingface_rank = COALESCE(EXCLUDED.huggingface_rank, models.huggingface_rank)
                RETURNING (xmax = 0) AS is_insert
                """,
                (
                    record.model_id,
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
                ),
            )
            # 不能用 cursor.rowcount：ON CONFLICT DO UPDATE 下它无论新增还是更新都是 1，
            # 会把「更新」也算成「新增」，污染 sync_log 审计表。
            # xmax = 0 表示这一行是本次 INSERT 产生的（新行），否则是被 UPDATE 的旧行。
            inserted_row = cursor.fetchone()
            is_insert = bool(inserted_row and inserted_row[0])
            cursor.execute("DELETE FROM model_tags WHERE model_id = %s", (record.model_id,))
            if record.tags:
                tag_rows = [
                    (record.model_id, tag, record.inserted_at)
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
                started_at.isoformat(),
                finished_at.isoformat(),
                "success",
                processed,
                inserted,
                None,
            ),
        )
    conn.commit()
    return processed, inserted


def fetch_and_store(limit: int = 50) -> dict[str, tuple[int, int]]:
    client = hf_client()
    providers = get_providers(os.getenv("PROVIDERS"))
    if not providers:
        raise RuntimeError("PROVIDERS is not configured. Set it in environment or .env file.")

    results: dict[str, tuple[int, int]] = {}
    token = os.getenv("HF_TOKEN")
    with ensure_db() as conn:
        for provider in providers:
            LOGGER.info("Fetching models for provider %s", provider)
            display_name, avatar_url = resolve_provider_profile(client, provider)
            avatar_content, avatar_mime = download_provider_avatar(avatar_url, token)
            try:
                upsert_provider(conn, provider, avatar_url, display_name, avatar_content, avatar_mime)
            except Exception as exc:  # pragma: no cover - database failure
                LOGGER.warning("Failed to upsert provider %s metadata: %s", provider, exc)
            models_iter = client.list_models(
                author=provider,
                sort="lastModified",
                direction=-1,
                limit=limit,
                full=True,
            )
            # 必须先物化：拉 README 简介需要先拿到全部 model_id 才能并发
            infos = list(models_iter)

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

            started_at = datetime.now(timezone.utc)
            records = (
                to_record(provider, info, description=descriptions.get(info.modelId))
                for info in infos
            )
            processed, inserted = save_models(conn, provider, records, started_at=started_at)
            LOGGER.info("Provider %s: processed=%s inserted=%s", provider, processed, inserted)
            results[provider] = (processed, inserted)
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
