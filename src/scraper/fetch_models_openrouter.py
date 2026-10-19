"""Fetch model metadata from OpenRouter and persist into PostgreSQL."""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Dict
from urllib.parse import quote

import psycopg

from src.scraper.batch_write import chunked as _chunked
from src.scraper.batch_write import enabled as batch_write_enabled
from src.scraper.batch_write import size as batch_size
import requests
from dotenv import load_dotenv

from src.scraper.fetch_models import (
    SOURCE_OPENROUTER,
    StageTimer,
    resolve_case_variant,
)

try:
    from scripts.init_db import create_schema  # type: ignore
except Exception:  # pragma: no cover
    create_schema = None  # type: ignore

LOGGER = logging.getLogger("silicon_river.fetch.openrouter")
LOGGING_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOGGING_LEVEL, format="%(asctime)s [%(levelname)s] %(message)s")

BASE_DIR = Path(__file__).resolve().parents[2]
ENV_PATH = BASE_DIR / ".env"
DEFAULT_DB_URL = "postgresql://USER:PASSWORD@HOST:5432/silicon_river"
DEFAULT_ENDPOINT = "https://openrouter.ai/api/v1/models"

# ISSUE-004（2026-10-18）：OpenRouter 的「变体」不是独立发布，抓进来只会让同一个模型
# 在时间轴上出现两三次：
#   - 路由变体 `:batch` / `:free` / `:nitro` / `:extended` / `:online` / `:thinking` / `:floor`
#     （实测 92 行带冒号，其中 `:batch` 78、`:free` 14）；
#   - 隐藏/路由别名 `~x-ai/grok-latest` 这类带 `~` 前缀的 id（17 行）。
# 生产库 1707 行里，「变体后缀」一类重复就有 80 组 / 160 行（docs/issues/004）。
# 这些 id 照抓的话每次同步都会重建一遍重复，所以在选择阶段直接跳过。
_VARIANT_SUFFIX_RE = re.compile(
    r":(?:free|batch|nitro|extended|online|thinking|floor)\b", re.IGNORECASE
)


def is_variant_id(model_id: str | None) -> bool:
    """是否是 OpenRouter 的变体/别名 id（不该作为独立模型入库，ISSUE-004）。"""
    if not model_id:
        return False
    if model_id.lstrip().startswith("~"):
        return True
    return bool(_VARIANT_SUFFIX_RE.search(model_id))

# ISSUE-032：provider key 别名表。键既可能是 model_id 的斜杠前缀，也可能是 name 里
# 冒号前的展示名，值统一成 `PROVIDERS_OPENROUTER` 白名单收录的写法。
#
# 依据（2026-10-18 上游只读快照，471 条实测；id 前缀 → 展示名对照）：
#   - 前 4 条是 AGENTS.md 铁律 12 早就记下的「id 前缀 ≠ 展示名」；
#   - `xai` 来自 `xAI: Grok Latest`：展示名解析出 `xai`，白名单里是 `spacexai`；
#   - 其余按快照里同一厂商的 id 前缀 / 展示名对出来的：
#     `liquid`→LiquidAI、`aion-labs`→AionLabs、`arcee-ai`→Arcee AI、
#     `bytedance-seed`→ByteDance Seed、`ibm-granite`→IBM、`inference-net`→Inference.net、
#     `nex-agi`→Nex AGI、`nousresearch`→Nous、`prism-ml`→PrismML、
#     `thinkingmachines`→Thinking Machines。
#     这些前缀在快照里 100% 只对应一个展示名，没有歧义。
# 不收录 `rekaai` / `anthropic`：白名单直接收了这两个 id 前缀本身（`rekaai` 上游 name 是
# "Reka Edge"、不带冒号），把它们映射成 `reka` / `claude` 反而会让白名单重新 0 命中。
PROVIDER_KEY_ALIASES: dict[str, str] = {
    "mistralai": "mistral",
    "meta-llama": "meta",
    "z-ai": "z.ai",
    "x-ai": "spacexai",
    "xai": "spacexai",
    "liquid": "liquidai",
    "aion-labs": "aionlabs",
    "arcee-ai": "arcee ai",
    "bytedance-seed": "bytedance seed",
    "ibm-granite": "ibm",
    "inference-net": "inference.net",
    "nex-agi": "nex agi",
    "nousresearch": "nous",
    "prism-ml": "prismml",
    "thinkingmachines": "thinking machines",
}


@dataclass(slots=True)
class ModelRecord:
    model_id: str
    provider: str
    model_name: str
    description: str
    created_at: datetime
    model_card_url: str
    inserted_at: datetime
    price: Optional[Dict[str, object]]
    is_open_source: Optional[bool]
    huggingface_rank: Optional[int]
    # 该模型在 Hugging Face 上的 model_id（OpenRouter 的 hugging_face_id）。
    # ISSUE-004 跨源合并：有值时把这一行并入 HF 那一行（merged_into）。
    hf_model_id: Optional[str] = None


def load_config() -> None:
    if ENV_PATH.exists():
        load_dotenv(dotenv_path=ENV_PATH, override=False, encoding="utf-8-sig")


def resolve_db_url() -> str:
    load_config()
    return os.getenv("DATABASE_URL", DEFAULT_DB_URL)


def get_providers(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [provider.strip().lower() for provider in raw.split(",") if provider.strip()]


def ensure_db(url: str | None = None) -> psycopg.Connection:
    db_url = url or resolve_db_url()
    if create_schema is not None:
        create_schema(db_url)
    conn = psycopg.connect(db_url)
    return conn


def upsert_provider(
    conn: psycopg.Connection,
    provider_id: str,
    display_name: str | None = None,
    avatar_url: str | None = None,
) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO providers (provider_id, display_name, avatar_url, updated_at)
            VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (provider_id) DO UPDATE
            SET
                display_name = EXCLUDED.display_name,
                avatar_url = COALESCE(EXCLUDED.avatar_url, providers.avatar_url),
                updated_at = CURRENT_TIMESTAMP
            """,
            (provider_id, display_name or provider_id, avatar_url),
        )


def normalise_timestamp(epoch_seconds: int | float | None) -> datetime:
    """OpenRouter 的 `created` 是 unix 秒 → UTC aware datetime（ISSUE-006）。

    缺值时退回当前 UTC 时刻（旧行为如此，抓取侧本来就是「不知道就当现在」）。
    """
    if epoch_seconds is None:
        return datetime.now(timezone.utc)
    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc)


def _id_prefix(model_id: str | None) -> str:
    """model_id 的斜杠前缀（小写）。

    OpenRouter 的 `latest` 路由别名形如 `~x-ai/grok-latest`、`~anthropic/claude-opus-latest`，
    `~` 不是厂商名的一部分，先剥掉再查别名表。
    """
    if not model_id or "/" not in model_id:
        return ""
    prefix = model_id.split("/", 1)[0].strip().lower()
    return prefix.lstrip("~")


def _display_prefix(name: str | None) -> str:
    """`name` 里 `Display: Model` 的 Display（铁律 12 的白名单口径）；没有冒号返回空串。"""
    if not name or ":" not in name:
        return ""
    return name.split(":", 1)[0].strip().lower()


def extract_provider(name: str | None, model_id: str | None = None) -> str:
    """解析 provider key；回落顺序见 `provider_key_for()` 的文档（ISSUE-032）。

    保留这个入口是因为 issue / ARCHITECTURE 都按名字引用它，逻辑只有一份。
    """
    id_prefix = _id_prefix(model_id)
    display = _display_prefix(name)
    candidates: list[str] = []
    # ① 已登记品牌的 id 前缀（`mistralai`→`mistral`）优先
    if id_prefix in PROVIDER_KEY_ALIASES:
        candidates.append(PROVIDER_KEY_ALIASES[id_prefix])
    # ② name 的 `Display:` 前缀（铁律 12）
    if display:
        candidates.append(PROVIDER_KEY_ALIASES.get(display, display))
    # ③ 未登记的 id 前缀本身就是白名单条目时（`qwen` / `gryphe` / `anthracite-org`）
    if id_prefix:
        candidates.append(id_prefix)
    # ④ 兜底：整个 name 小写（历史行为，解析不出时不会误放行）
    stripped = (name or "").strip().lower()
    if stripped:
        candidates.append(stripped)
    for candidate in candidates:
        if candidate:
            return candidate
    return "unknown"


def provider_key_for(raw: dict) -> str:
    """白名单匹配用的 provider key（ISSUE-032 修过回落顺序）。

    回落顺序：
      1. `id` 的斜杠前缀，但**只有登记在 `PROVIDER_KEY_ALIASES` 里的品牌前缀**才算解析
         成功（`mistralai`→`mistral`、`~x-ai`→`spacexai`）。未登记的前缀（如
         `cognitivecomputations`、`openrouter`）是 org / 转售命名空间，不代表厂商品牌，
         交给下一步 —— 否则 2026-10-18 快照里 90 条「只能靠展示名匹配」的模型会被反向丢掉。
      2. `name` 的 `Display:` 前缀（铁律 12：白名单按展示名收录）。
      3. 未经别名映射的 id 前缀（`qwen` / `gryphe` / `anthracite-org` / `rekaai` 这类
         前缀本身就是白名单条目；旧实现走到这里时退化成了整个 name 小写）。
      4. `name` 整串小写（兜底，与旧行为一致）。
      5. `"unknown"`。

    必须与 `to_record()` 入库时的 provider 口径完全一致，否则「过滤用的 key」
    和「入库用的 provider」会分叉：过滤放行了、入库却算到别家。
    """
    model_id = raw.get("id") or ""
    name = raw.get("name") or model_id
    return extract_provider(name, model_id or None)


def _clean_hf_id(raw: dict) -> Optional[str]:
    """取 OpenRouter 条目里的 ``hugging_face_id``（没有/空串/非字符串都返回 None）。"""
    value = raw.get("hugging_face_id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def infer_is_open_source(raw: dict) -> bool:
    """判断 OpenRouter 上这条记录是不是开放权重模型（ISSUE-036）。

    依据是 OpenRouter 自己返回的 ``hugging_face_id``：它指向该模型在 Hugging Face
    上的仓库，有值就说明权重可下载（开放权重）。实测 471 条里 180 条带该字段，
    包括 ``deepseek/deepseek-v4.1-flash-1017`` → ``deepseek-ai/DeepSeek-V4.1-Flash-1017``。

    历史实现只把 id 里带 ``:free`` 的当作开源、其余**一律**判成闭源，于是
    DeepSeek / Llama 这类开放权重模型的 OpenRouter 行会被打上「闭源」标签
    （同一模型在 HF 行上是「开源」，页面上就成了自相矛盾的两张卡）。
    ``:free`` 是**计费**属性，不是权重属性，不能当开源证据（16 个 :free 里 15 个
    另有 hf_id，剩下那个也就不必靠猜）。
    """
    return _clean_hf_id(raw) is not None


def to_record(raw: dict) -> ModelRecord:
    model_id = raw.get("id") or ""
    name = raw.get("name") or model_id
    provider = provider_key_for(raw)
    description = raw.get("description") or ""
    created = raw.get("created")
    created_at = normalise_timestamp(created if isinstance(created, (int, float)) else None)
    model_name = name
    inserted_at = datetime.now(timezone.utc)
    encoded_id = quote(model_id or name, safe="")
    model_card_url = f"https://openrouter.ai/models/{encoded_id}"
    pricing = raw.get("pricing")
    price_payload: Optional[Dict[str, object]] = pricing if isinstance(pricing, dict) and pricing else None
    is_open_source = infer_is_open_source(raw)
    return ModelRecord(
        model_id=model_id or encoded_id,
        provider=provider or "unknown",
        model_name=model_name,
        description=description[:5000],
        created_at=created_at,
        model_card_url=model_card_url,
        inserted_at=inserted_at,
        price=price_payload,
        is_open_source=is_open_source,
        huggingface_rank=None,
        hf_model_id=_clean_hf_id(raw),
    )


OR_BATCH_UPSERT_SQL = """
INSERT INTO models (
    model_id, provider, model_name, description, tags,
    created_at, downloads, likes, model_card_url, inserted_at,
    price, is_open_source, huggingface_rank, source, merged_into
)
SELECT * FROM unnest(
    %(model_id)s::text[], %(provider)s::text[], %(model_name)s::text[],
    %(description)s::text[], %(tags)s::text[], %(created_at)s::timestamptz[],
    %(downloads)s::int4[], %(likes)s::int4[], %(model_card_url)s::text[],
    %(inserted_at)s::timestamptz[], %(price)s::jsonb[], %(is_open_source)s::bool[],
    %(huggingface_rank)s::int4[], %(source)s::text[], %(merged_into)s::text[]
) AS incoming
ON CONFLICT (model_id) DO UPDATE SET
    provider = CASE
        WHEN lower(models.provider) = lower(EXCLUDED.provider) THEN models.provider
        ELSE EXCLUDED.provider
    END,
    model_name = EXCLUDED.model_name,
    -- OpenRouter 不提供简介/标签（description 恒空、tags 恒 []）：
    -- 大小写归一后会写进 HF 那一行，这里必须「空值不覆盖」，
    -- 否则每天凌晨的 OR 同步都会把 HF 的简介与 license 标签清空。
    description = CASE
        WHEN COALESCE(EXCLUDED.description, '') = '' THEN models.description
        ELSE EXCLUDED.description
    END,
    tags = CASE WHEN EXCLUDED.tags = '[]' THEN models.tags ELSE EXCLUDED.tags END,
    -- 发布时间同理：HF 的是仓库发布日，不能被 OR 的 created 覆盖。
    created_at = COALESCE(models.created_at, EXCLUDED.created_at),
    model_card_url = EXCLUDED.model_card_url,
    -- inserted_at 记首次入库，不随更新改写（ISSUE-035）
    price = COALESCE(EXCLUDED.price, models.price),
    is_open_source = EXCLUDED.is_open_source,
    huggingface_rank = COALESCE(EXCLUDED.huggingface_rank, models.huggingface_rank),
    merged_into = EXCLUDED.merged_into,
    -- 来源只认「首个已知值」（ISSUE-004）
    source = COALESCE(NULLIF(models.source, 'unknown'), EXCLUDED.source)
RETURNING (xmax = 0) AS is_insert
"""


def _save_models_batched(conn: psycopg.Connection, provider: str, records: List[ModelRecord]) -> tuple[int, int]:
    """一批模型一条语句写完（ISSUE-034）。

    与 `fetch_models.py` 的同名函数同构，区别：OR 不写标签，但要算 `merged_into`
    （把这一行挂到同模型的 HF 行后面，ISSUE-004）。
    """
    processed = 0
    inserted = 0
    for chunk in _chunked(records, batch_size()):
        with conn.cursor() as cursor:
            # ① 大小写归一：本批里已在库的 id
            cursor.execute(
                "SELECT model_id, lower(model_id) FROM models WHERE lower(model_id) = ANY(%s)",
                ([record.model_id.lower() for record in chunk],),
            )
            existing = {row[1]: row[0] for row in cursor.fetchall()}

            # ② 被合并目标：本批记录的 hf_model_id 在库里有没有对应行
            hf_ids = [record.hf_model_id.lower() for record in chunk if record.hf_model_id]
            hf_existing: Dict[str, str] = {}
            if hf_ids:
                cursor.execute(
                    "SELECT model_id, lower(model_id) FROM models WHERE lower(model_id) = ANY(%s)",
                    (hf_ids,),
                )
                hf_existing = {row[1]: row[0] for row in cursor.fetchall()}

            targets: Dict[str, ModelRecord] = {}
            for record in chunk:
                target = existing.get(record.model_id.lower()) or record.model_id
                targets[target] = record
            processed += len(chunk)

            merged_into: List[Optional[str]] = []
            for target, record in targets.items():
                twin = None
                if record.hf_model_id:
                    twin = hf_existing.get(record.hf_model_id.lower())
                if twin and twin.lower() != target.lower():
                    merged_into.append(twin)
                else:
                    merged_into.append(None)

            cursor.execute(
                OR_BATCH_UPSERT_SQL,
                {
                    "model_id": list(targets.keys()),
                    "provider": [provider for _ in targets],
                    "model_name": [record.model_name for record in targets.values()],
                    "description": [record.description for record in targets.values()],
                    "tags": [json.dumps([], ensure_ascii=False) for _ in targets],
                    "created_at": [record.created_at for record in targets.values()],
                    "downloads": [None for _ in targets],
                    "likes": [None for _ in targets],
                    "model_card_url": [record.model_card_url for record in targets.values()],
                    "inserted_at": [record.inserted_at for record in targets.values()],
                    "price": [
                        json.dumps(record.price, ensure_ascii=False)
                        if record.price is not None
                        else None
                        for record in targets.values()
                    ],
                    "is_open_source": [record.is_open_source for record in targets.values()],
                    "huggingface_rank": [record.huggingface_rank for record in targets.values()],
                    "source": [SOURCE_OPENROUTER] * len(targets),
                    "merged_into": merged_into,
                },
            )
            inserted += sum(1 for row in cursor.fetchall() if row[0])
        # 一批一个事务：整批失败整批回滚
        conn.commit()
    return processed, inserted


def save_models(conn: psycopg.Connection, provider: str, records: Iterable[ModelRecord]) -> tuple[int, int]:
    """写一批模型；默认走批量语句，`SCRAPER_BATCH_WRITE=0` 退回逐行写。"""
    materialised = list(records)
    if batch_write_enabled():
        return _save_models_batched(conn, provider, materialised)
    return _save_models_rowwise(conn, provider, materialised)


def _save_models_rowwise(conn: psycopg.Connection, provider: str, records: List[ModelRecord]) -> tuple[int, int]:
    processed = 0
    inserted = 0
    with conn.cursor() as cursor:
        for record in records:
            processed += 1
            # ISSUE-004：`qwen/qwen3.6-27b` 与 HF 的 `Qwen/Qwen3.6-27B` 是同一个模型，
            # 归一到先入库的那一行，别再建大小写变体。
            target_id = resolve_case_variant(cursor, record.model_id) or record.model_id
            cursor.execute(
                """
                INSERT INTO models (
                    model_id, provider, model_name, description, tags,
                    created_at, downloads, likes, model_card_url, inserted_at,
                    price, is_open_source, huggingface_rank, source, merged_into
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    -- 跨源合并（ISSUE-004）：该模型在 HF 上已有行时，把这一行挂到那一行后面。
                    -- 子查询用 lower() 匹配，容忍 `qwen/…` 与 `Qwen/…` 的大小写差异；
                    -- 排除自己，避免 id 与 hf_id 相同时把自己并给自己。
                    CASE WHEN %s::text IS NULL THEN NULL
                         ELSE (SELECT t.model_id FROM models AS t
                                WHERE lower(t.model_id) = lower(%s)
                                  AND lower(t.model_id) <> lower(%s)
                                LIMIT 1)
                    END
                )
                ON CONFLICT (model_id) DO UPDATE SET
                    provider = CASE
                        WHEN lower(models.provider) = lower(EXCLUDED.provider) THEN models.provider
                        ELSE EXCLUDED.provider
                    END,
                    model_name = EXCLUDED.model_name,
                    -- OpenRouter 不提供简介/标签（description 恒空、tags 恒 []）：
                    -- 大小写归一后会写进 HF 那一行，这里必须「空值不覆盖」，
                    -- 否则每天凌晨的 OR 同步都会把 HF 的简介与 license 标签清空。
                    description = CASE
                        WHEN COALESCE(EXCLUDED.description, '') = '' THEN models.description
                        ELSE EXCLUDED.description
                    END,
                    tags = CASE WHEN EXCLUDED.tags = '[]' THEN models.tags ELSE EXCLUDED.tags END,
                    -- 发布时间同理：HF 的是仓库发布日，不能被 OR 的 created 覆盖，否则时间轴上的点会跳。
                    created_at = COALESCE(models.created_at, EXCLUDED.created_at),
                    model_card_url = EXCLUDED.model_card_url,
                    -- inserted_at 记首次入库，不随更新改写（ISSUE-035）
                    price = COALESCE(EXCLUDED.price, models.price),
                    is_open_source = EXCLUDED.is_open_source,
                    huggingface_rank = COALESCE(EXCLUDED.huggingface_rank, models.huggingface_rank),
                    merged_into = EXCLUDED.merged_into,
                    -- 来源只认「首个已知值」：跨源合并行（HF 与 OpenRouter 写同一 model_id
                    -- 或大小写归一后落到同一行）不要互相覆盖，否则每日固定「先 HF 后 OR」
                    -- 会让所有合并行的 source 恒为 openrouter，ISSUE-004 判源就失效了。
                    source = COALESCE(NULLIF(models.source, 'unknown'), EXCLUDED.source)
                RETURNING (xmax = 0) AS is_insert
                """,
                (
                    target_id,
                    provider,
                    record.model_name,
                    record.description,
                    json.dumps([], ensure_ascii=False),
                    record.created_at,
                    None,
                    None,
                    record.model_card_url,
                    record.inserted_at,
                    json.dumps(record.price, ensure_ascii=False) if record.price is not None else None,
                    record.is_open_source,
                    record.huggingface_rank,
                    SOURCE_OPENROUTER,
                    record.hf_model_id,
                    record.hf_model_id,
                    target_id,
                ),
            )
            # 同 fetch_models.py：rowcount 在 ON CONFLICT DO UPDATE 下恒为 1，
            # 会把更新误计成新增。xmax = 0 才是「这一行是本次新插入的」。
            row = cursor.fetchone()
            if row and row[0]:
                inserted += 1
    conn.commit()
    return processed, inserted


def fetch_remote_models(endpoint: str) -> List[dict]:
    LOGGER.info("Requesting OpenRouter models from %s", endpoint)
    response = requests.get(endpoint, timeout=30)
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data", [])
    if not isinstance(data, list):
        raise ValueError("Unexpected response schema from OpenRouter.")
    LOGGER.info("Fetched %s models from OpenRouter", len(data))
    return data


def select_models(
    raw_models: List[dict],
    providers_filter: list[str],
    limit: int | None = None,
    *,
    logger: logging.Logger = LOGGER,
) -> tuple[List[dict], Dict[str, int]]:
    """先按白名单过滤，再按 limit 截断（ISSUE-030）。

    `limit` 是「拿到足够多已过滤结果就停」的安全阀，**不是丢弃源数据的手段**。
    反例（ISSUE-030 之前的实现）：先 `raw_models[:limit]` 再过滤，上游模型总数一旦
    超过 limit，排在窗口后面的白名单模型连进入过滤的机会都没有——不报错、不告警、
    静默消失。现在截断只会砍掉**已命中白名单**的模型，并且一定打 WARNING。

    返回 `(选中的模型列表, 统计)`；统计里的 upstream_total / matched_total /
    selected / dropped 用于日志和回归测试。
    """
    upstream_total = len(raw_models)
    if providers_filter:
        matched = [item for item in raw_models if provider_key_for(item) in providers_filter]
    else:
        matched = list(raw_models)

    # ISSUE-004：变体/别名 id 先剔除，再参与截断计数（它们不是独立发布）。
    variants = [item for item in matched if is_variant_id(item.get("id"))]
    if variants:
        matched = [item for item in matched if not is_variant_id(item.get("id"))]
        logger.info(
            "跳过 %s 个 OpenRouter 变体/别名 id（:free/:batch/~latest 之类不是独立发布，ISSUE-004）：%s",
            len(variants),
            ", ".join(str(item.get("id")) for item in variants[:5]),
        )
    matched_total = len(matched)

    # ISSUE-032：白名单里一条都没匹配到的条目必须告警。旧实现完全静默，
    # 「填错一个词 = 整家厂商消失」永远发现不了（AGENTS.md 铁律 12 / 踩坑 4.1）。
    if providers_filter:
        matched_keys = {provider_key_for(item) for item in matched}
        zero_hit = [entry for entry in dict.fromkeys(providers_filter) if entry not in matched_keys]
        if zero_hit:
            logger.warning(
                "OpenRouter 白名单里有 %s 个条目一条都没匹配到：%s —— 配置了这个厂商，"
                "但上游没有任何模型的 provider key 命中它；多半是白名单写法与上游展示名 / "
                "id 前缀不一致（对照 AGENTS.md 铁律 12、ISSUE-032），不修就是整家厂商静默消失",
                len(zero_hit),
                ", ".join(zero_hit),
            )

    dropped = 0
    selected = matched
    if limit is not None and limit > 0 and matched_total > limit:
        dropped = matched_total - limit
        selected = matched[:limit]
        # 静默失败是本仓库最危险的模式（AGENTS.md 踩坑 4.1），截断必须留痕。
        logger.warning(
            "OpenRouter 抓取窗口截断：上游 %s 条，白名单命中 %s 条，窗口 %s 条，"
            "丢弃 %s 条白名单模型（截断发生在过滤之后，丢的是已命中模型；"
            "把 OPENROUTER_DAILY_FETCH_LIMIT 调大或设为 0 可消除）",
            upstream_total,
            matched_total,
            limit,
            dropped,
        )
    else:
        logger.info(
            "OpenRouter 抓取窗口：上游 %s 条，白名单命中 %s 条，窗口 %s，实际抓取 %s 条",
            upstream_total,
            matched_total,
            limit if limit and limit > 0 else "不截断",
            len(selected),
        )

    return selected, {
        "upstream_total": upstream_total,
        "matched_total": matched_total,
        "selected": len(selected),
        "dropped": dropped,
        "skipped_variants": len(variants),
    }


def fetch_and_store(endpoint: str | None = None, *, limit: int | None = None) -> dict[str, tuple[int, int]]:
    load_config()
    endpoint_url = endpoint or os.getenv("OPENROUTER_MODELS_URL", DEFAULT_ENDPOINT)
    providers_filter = get_providers(os.getenv("PROVIDERS_OPENROUTER"))
    # ISSUE-034：分两段计时（上游拉取 / 写库），异常退出也能看出卡在哪一段。
    timer = StageTimer("fetch", "write")
    selected_models: List[dict] = []
    results: dict[str, tuple[int, int]] = {}
    finished = False
    try:
        timer.begin("fetch")
        raw_models = fetch_remote_models(endpoint_url)
        # ISSUE-030：白名单过滤必须在 limit 截断之前，limit 只是过滤后的安全阀。
        selected_models, _selection = select_models(raw_models, providers_filter, limit)

        # 写库段包含 ensure_db()（建表检查 + 建连）与逐条 upsert。
        timer.begin("write")
        with ensure_db() as conn:
            for item in selected_models:
                record = to_record(item)
                provider_key = record.provider
                provider_display = (item.get("name") or provider_key).split(":", 1)[0].strip()
                if not provider_display and record.model_id and "/" in record.model_id:
                    provider_display = record.model_id.split("/", 1)[0].strip()
                provider_display = provider_display or provider_key
                upsert_provider(conn, provider_id=provider_key, display_name=provider_display)
                processed, inserted = save_models(conn, provider_key, [record])
                existing = results.get(provider_key, (0, 0))
                results[provider_key] = (existing[0] + processed, existing[1] + inserted)
        timer.stop()
        finished = True
        return results
    finally:
        suffix = "" if finished else f"（中断于 {timer.current or '?'} 段）"
        LOGGER.info(
            "OpenRouter 计时%s: %s 共 %.1fs（%s 个模型）",
            suffix,
            timer.describe(("fetch", "write")),
            timer.total,
            len(selected_models),
        )


if __name__ == "__main__":
    summary = fetch_and_store()
    for provider, (processed, inserted) in summary.items():
        print(f"{provider}: processed={processed} inserted={inserted}")

    # 爬虫完成后，运行AI分析
    try:
        from src.scraper.analysis_orchestrator import run_post_scrape_analysis

        LOGGER.info("OpenRouter爬虫完成，开始运行AI分析...")
        analysis_result = run_post_scrape_analysis()
        LOGGER.info(f"AI分析完成: {analysis_result}")
    except Exception as e:
        LOGGER.warning(f"AI分析运行失败: {e}")
