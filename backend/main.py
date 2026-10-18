"""FastAPI application exposing Silicon River data."""
from __future__ import annotations

import json
import os
import sys
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path as PathLib
from typing import List, Optional
from urllib.parse import urlsplit

import psycopg
import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, Path
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, ConfigDict
from starlette.concurrency import run_in_threadpool

# 兼容两种运行布局，保证 `models` 在两种情况下都可被导入：
#   1) 本地开发：从项目根执行 `uvicorn backend.main:app`
#   2) Vercel Services：service root 设为 backend/，main.py 被当作顶层模块加载
BACKEND_DIR = PathLib(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent

for _search_path in (str(PROJECT_ROOT), str(BACKEND_DIR)):
    if _search_path not in sys.path:
        sys.path.insert(0, _search_path)

from models import (
    Model,
    ModelList,
    ProviderStat,
    TimelineModel,
    TimelineResponse,
    ModelAnalysis,
    AnalysisList,
    ArenaScoreInfo,
    ArenaScoreSummary,
    TimelineModelWithAnalysis,
)

ENV_PATH = PROJECT_ROOT / ".env"

if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH, override=False)

# 代理环境变量的兼容处理（ISSUE-002）：no_proxy 里带 `[::1]` 时 httpx 建 Client 就抛
# `InvalidURL: Invalid port: ':1]'`，头像回退链路会整条 500。Vercel 部署只带 backend/、
# 没有 `src/`，那里拿不到这个模块——云端也不会出现本机这套代理变量。
try:
    from src.net_env import sanitize_proxy_environment
except ImportError:  # pragma: no cover - 仅 Vercel（service root=backend/）走到
    sanitize_proxy_environment = None  # type: ignore[assignment]

if sanitize_proxy_environment is not None:
    sanitize_proxy_environment()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://USER:PASSWORD@HOST:5432/silicon_river")
# 数据库连接超时（秒）：数据库不可达时快速失败，不让请求挂到平台超时
DB_CONNECT_TIMEOUT = float(os.getenv("DB_CONNECT_TIMEOUT", "10"))
# 语句级超时（毫秒）：库侧慢查询 / 等锁时的止损点。
# connect_timeout 只管建连、池的 timeout 只管取连接，查询本身在这之前没有任何上限。
DB_STATEMENT_TIMEOUT_MS = int(os.getenv("DB_STATEMENT_TIMEOUT_MS", "5000"))
AVATAR_FETCH_TIMEOUT = float(os.getenv("AVATAR_FETCH_TIMEOUT", "6"))
AVATAR_CACHE_TTL = int(os.getenv("AVATAR_CACHE_TTL", "86400"))
AVATAR_MAX_BYTES = int(os.getenv("AVATAR_MAX_BYTES", "524288"))
# 头像回退抓取的域名白名单（SSRF 面收敛）：providers.avatar_url 由抓取脚本从上游写入，
# 接口侧不能把它当可信输入——否则「能写 providers 表」就等于「能让服务端请求任意地址」。
# 逗号分隔；子域名自动放行（huggingface.co 覆盖 cdn-avatars.huggingface.co）。
# 默认值取自线上 providers.avatar_url 的实测主机：目前只有 cdn-avatars.huggingface.co；
# huggingface.co / avatars.githubusercontent.com / openrouter.ai 是这三个上游的已知头像源。
AVATAR_ALLOWED_HOSTS = [
    host.strip().lower()
    for host in os.getenv(
        "AVATAR_ALLOWED_HOSTS",
        "cdn-avatars.huggingface.co,huggingface.co,avatars.githubusercontent.com,openrouter.ai",
    ).split(",")
    if host.strip()
]
# 最多跟随几次重定向：每一次跳转后的目标都要重新过白名单（不能只校验第一个 URL）。
AVATAR_MAX_REDIRECTS = int(os.getenv("AVATAR_MAX_REDIRECTS", "3"))
# 搜索串长度上限：真实模型名/关键词远短于此；超长串要么是误用，要么是想拿全表扫描
# 当廉价入口。超长直接 422 拒绝而不是截断——截断会把「搜到别的东西」藏起来。
SEARCH_MAX_LENGTH = 64

# ---------- 只读列表接口的缓存策略（ISSUE-021） ----------
# 这两个接口的响应体只随「每日同步」变化，但时间轴窗口的 end 是「服务端当前时间」，
# 所以两者的新鲜度要求不一样：
# - /api/models：数据一天最多变几次，1 分钟内复用旧值完全够用；
#   stale-while-revalidate=300 让浏览器先回旧值、后台再校验，弱网下不用空等回源。
CACHE_CONTROL_MODELS = "public, max-age=60, stale-while-revalidate=300"
# - /api/timeline：max-age 刻意压到 15 秒。默认 preset=30d 的窗口是「从现在往回 30 天」，
#   每过一秒窗口边界都在滑动；新模型入库后旧响应立刻过时。缓存只用来吸收一次页面加载里
#   的突发重复请求，不指望跨页面/跨会话复用，所以 max-age 不能取 60。
CACHE_CONTROL_TIMELINE = "public, max-age=15, stale-while-revalidate=60"

# ---------- 数据库连接池参数 ----------
# min_size=0：冷启动不抢连接，空闲时也不占着 Supabase 的连接配额。
# max_size 刻意压得很小：Supabase 免费层连接数有限，而 serverless 的实例数会
#   横向放大，池开大反而更容易把上游配额打满。需要时用环境变量调。
DB_POOL_MIN_SIZE = int(os.getenv("DB_POOL_MIN_SIZE", "0"))
DB_POOL_MAX_SIZE = int(os.getenv("DB_POOL_MAX_SIZE", "4"))
# 空闲超过这个秒数就还给上游；Supabase 侧会掐掉长期空闲的连接。
DB_POOL_MAX_IDLE = float(os.getenv("DB_POOL_MAX_IDLE", "300"))
# 池里没有可用连接时，最多等这么久再报 PoolTimeout（而不是一直挂着）。
DB_POOL_TIMEOUT = float(os.getenv("DB_POOL_TIMEOUT", "10"))

_pool: Optional[ConnectionPool] = None
_pool_lock = threading.Lock()


def _configure_connection(conn: psycopg.Connection) -> None:
    """每条新连接建立后设置语句级超时。

    为什么不用 connect 的 `options="-c statement_timeout=..."`：`options` 是启动报文
    参数，Postgres 随后会再套用角色/库级设置，后者**覆盖**它。实测（2026-10-18，
    Supabase 5432 Session Pooler）传 `options="-c statement_timeout=5000"` 建连不报错，
    但 `current_setting('statement_timeout')` 仍是角色默认的 `2min` —— 也就是静默无效。
    连接建立后再 `SET` 才真正生效（同一环境实测值为 `5s`）。

    没配 configure 回调时池只负责建连；回调里若留下未结事务，psycopg_pool 会
    直接丢弃这条连接（它要求回调结束时连接处于 IDLE），所以 SET 之后必须 commit。
    """
    conn.execute(f"SET statement_timeout = {DB_STATEMENT_TIMEOUT_MS}")
    conn.commit()


def get_pool() -> ConnectionPool:
    """返回进程级连接池，首次调用时惰性建立。

    为什么需要池：原先每个请求都新建一条 psycopg 连接，等于每次都要走一遍
    TCP + TLS + 认证。Supabase 是远程库，这部分是纯粹的固定开销；而 Vercel 的
    Fluid compute 会在同一实例内复用进程，所以池能真正省下它。

    传给 `kwargs` 的连接参数：
    - prepare_threshold=None：关闭 psycopg 的自动预编译。psycopg3 默认对执行
      超过 5 次的语句做服务端预编译，但 Supabase 的 Transaction pooler
      （6543 端口，Supavisor/PgBouncer）不支持预编译语句，开着会报
      "prepared statement ... already exists" 之类的间歇性错误。
    - connect_timeout：数据库不可达时快速失败，避免函数一直挂到平台超时。

    语句级超时由 `configure` 回调设置（见 `_configure_connection`），不在 kwargs 里。
    """
    global _pool
    if _pool is not None and not _pool.closed:
        return _pool

    with _pool_lock:
        # 双重检查：可能已被另一个线程建好了
        if _pool is None or _pool.closed:
            _pool = ConnectionPool(
                conninfo=DATABASE_URL,
                min_size=DB_POOL_MIN_SIZE,
                max_size=DB_POOL_MAX_SIZE,
                max_idle=DB_POOL_MAX_IDLE,
                timeout=DB_POOL_TIMEOUT,
                kwargs={
                    "prepare_threshold": None,
                    "connect_timeout": DB_CONNECT_TIMEOUT,
                },
                configure=_configure_connection,
                open=False,
                name="silicon-river",
            )
            # open() 本身不建连接（min_size=0），只是把维护线程和调度器起起来
            _pool.open()
    return _pool


def close_pool() -> None:
    """关闭连接池并清空模块级引用。"""
    global _pool
    with _pool_lock:
        if _pool is not None and not _pool.closed:
            _pool.close()
        _pool = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    """应用生命周期。

    退出时关掉连接池：本地 `--reload` 和测试里的 TestClient 会反复启停应用，
    不关的话连接会一路泄漏到 Supabase（空闲连接同样占配额）。
    """
    yield
    close_pool()


def _utcnow() -> datetime:
    """UTC「现在」，返回 aware datetime。

    ISSUE-006 之后时间列统一是 `timestamptz`，库里存的是绝对时刻（UTC）：
    带 tzinfo 的值和列类型匹配，Postgres 不会按会话时区做隐式换算，
    序列化出来天然带 `+00:00`，前端 `new Date()` 才能按访问者本地时区正确渲染。
    """
    return datetime.now(timezone.utc)


# 生产环境是 Vercel Services 同域部署：前端用自己的域名发相对路径 /api/*，
# 由 vercel.json 的 rewrites 转到后端 service，浏览器根本不产生跨域请求。
# 所以这里只需要放行本地开发地址；需要别的来源就用 ALLOWED_ORIGINS 覆盖（逗号分隔）。
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]

app = FastAPI(title="Silicon River API", version="0.1.0", lifespan=lifespan)

if ALLOWED_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )


def get_db():
    """数据库连接依赖。

    两点刻意为之：
    - 写成同步生成器：psycopg 是同步驱动，FastAPI 会把同步依赖和同步路由一起
      丢进线程池执行；写成 `async def` 会让建连接阻塞事件循环。
    - 用 `pool.connection()` 而不是 getconn/putconn：这个上下文管理器在正常退出时
      **提交**、异常退出时**回滚**，并把连接（或坏掉的连接）归还池子，
      不会把带未结事务的连接漏给下一个请求。
    """
    with get_pool().connection() as conn:
        yield conn


@app.get("/api/models", response_model=ModelList)
def list_models(
    response: Response,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    provider: Optional[str] = None,
    tag: Optional[str] = Query(None, max_length=SEARCH_MAX_LENGTH),
    search: Optional[str] = Query(None, max_length=SEARCH_MAX_LENGTH),
    conn: psycopg.Connection = Depends(get_db),
):
    """分页查询模型列表。

    total 与 items 必须来自**同一次查询**（ISSUE-021）：原先先 `SELECT COUNT(*)`
    再 `LIMIT/OFFSET` 是两条独立语句，同步任务在两条语句之间提交时，客户端会拿到
    「total 属于新快照、items 属于旧快照」的组合。这里合并成一条语句，快照天然一致。
    """
    offset = (page - 1) * page_size
    filters: List[str] = []
    params: List[object] = []

    if provider:
        filters.append("provider = %s")
        params.append(provider)
    if tag:
        filters.append("tags ILIKE %s ESCAPE '\\'")
        params.append(f"%{_escape_like(tag)}%")
    if search:
        filters.append("(model_name ILIKE %s ESCAPE '\\' OR description ILIKE %s ESCAPE '\\')")
        params.extend([f"%{_escape_like(search)}%", f"%{_escape_like(search)}%"])

    where_clause = f" WHERE {' AND '.join(filters)}" if filters else ""

    with conn.cursor(row_factory=dict_row) as cursor:
        # 一条语句同时取 total 与当页数据：filtered 被 count 和 page 两个 CTE 引用，
        # 两者共享同一个快照。用 LEFT JOIN（以只返回一行的 count 为左表）而不是
        # `COUNT(*) OVER()` 的原因：窗口函数的行数由结果的 LIMIT 决定，当 offset
        # 超出末尾时结果为空、total 会错误地变成 0；count 左连接保证即使当页为空
        # 也仍返回一行 total，接口对「翻过头」的分页请求保持原有语义。
        cursor.execute(
            f"""
            WITH filtered AS (
                SELECT model_id, provider, model_name, description, tags, created_at,
                       downloads, likes, model_card_url
                FROM models
                {where_clause}
            )
            SELECT page.*, total.total
            FROM (SELECT COUNT(*) AS total FROM filtered) AS total
            LEFT JOIN (
                SELECT * FROM filtered
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
            ) AS page ON TRUE
            ORDER BY page.created_at DESC NULLS LAST
            """,
            [*params, page_size, offset],
        )
        rows = cursor.fetchall()

    total = int(rows[0]["total"]) if rows else 0
    items = [
        Model(
            model_id=row["model_id"],
            provider=row["provider"],
            model_name=row["model_name"],
            description=row["description"],
            tags=_parse_tags(row["tags"]),
            created_at=row["created_at"],
            downloads=row["downloads"],
            likes=row["likes"],
            model_card_url=row["model_card_url"],
        )
        for row in rows
        # 当页为空时 count 左连接会补一行全 NULL 的占位行，只用来承载 total
        if row["model_id"] is not None
    ]

    response.headers["Cache-Control"] = CACHE_CONTROL_MODELS
    return ModelList(items=items, total=total, page=page, page_size=page_size)


@app.get("/api/models/analyzed", response_model=AnalysisList)
def list_analyzed_models(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    provider: Optional[str] = None,
    feature: Optional[str] = None,
    search: Optional[str] = Query(None, max_length=SEARCH_MAX_LENGTH),
    conn: psycopg.Connection = Depends(get_db),
):
    """获取已分析的模型列表。支持按提供商、特征、搜索过滤。"""
    offset = (page - 1) * page_size
    filters: List[str] = []
    params: List[object] = []

    if provider:
        filters.append("COALESCE(ma.provider, m.provider) = %s")
        params.append(provider)
    if feature:
        filters.append("%s = ANY(ma.key_features)")
        params.append(feature)
    if search:
        filters.append(
            "(COALESCE(ma.model_name, m.model_name) ILIKE %s ESCAPE '\\' "
            "OR m.description ILIKE %s ESCAPE '\\' "
            "OR ma.analysis_summary ILIKE %s ESCAPE '\\')"
        )
        like = f"%{_escape_like(search)}%"
        params.extend([like, like, like])

    where_clause = " AND ".join(filters) if filters else "1=1"

    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            f"""
            SELECT COUNT(DISTINCT ma.model_id) AS total
            FROM model_analysis ma
            LEFT JOIN models m ON ma.model_id = m.model_id
            WHERE {where_clause}
            """,
            params,
        )
        total_row = cursor.fetchone()
        total = int(total_row["total"]) if total_row else 0

        query_params = [*params, page_size, offset]
        cursor.execute(
            f"""
            SELECT
                ma.model_id,
                ma.analysis_summary,
                ma.key_features,
                ma.use_cases,
                ma.performance_metrics,
                ma.llm_model_used,
                ma.analyzed_at,
                array_agg(DISTINCT mt.tag) FILTER (WHERE mt.tag IS NOT NULL) as tags,
                COALESCE(ma.provider, m.provider) as provider,
                COALESCE(ma.model_name, m.model_name) as model_name
            FROM model_analysis ma
            LEFT JOIN models m ON ma.model_id = m.model_id
            LEFT JOIN model_tags mt ON ma.model_id = mt.model_id
            WHERE {where_clause}
            GROUP BY ma.id, ma.model_id, ma.analysis_summary, ma.key_features,
                     ma.use_cases, ma.performance_metrics, ma.llm_model_used, ma.analyzed_at,
                     COALESCE(ma.provider, m.provider),
                     COALESCE(ma.model_name, m.model_name)
            ORDER BY ma.analyzed_at DESC
            LIMIT %s OFFSET %s
            """,
            query_params,
        )
        rows = cursor.fetchall()

    items = [
        ModelAnalysis(
            model_id=row["model_id"],
            analysis_summary=row["analysis_summary"],
            key_features=row["key_features"] or [],
            use_cases=row["use_cases"] or [],
            performance_metrics=row["performance_metrics"],
            llm_model_used=row["llm_model_used"],
            analyzed_at=row["analyzed_at"],
            tags=list(filter(None, row["tags"] or [])),
        )
        for row in rows
    ]

    return AnalysisList(items=items, total=total, page=page, page_size=page_size)


@app.get("/api/timeline", response_model=TimelineResponse)
def timeline_models(
    response: Response,
    preset: str = Query("30d", pattern="^(30d|6m|1y|all)$"),
    year: Optional[int] = Query(None, ge=1900, le=3000),
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=10, le=500),
    sort: str = Query("asc", pattern="^(asc|desc)$"),
    provider: Optional[str] = Query(None),
    model_name: Optional[str] = Query(None, max_length=SEARCH_MAX_LENGTH),
    open_source: Optional[bool] = Query(None),
    conn: psycopg.Connection = Depends(get_db),
):
    """时间轴窗口内的模型分页。

    total 与 items 合并进同一条语句（ISSUE-021，同 `/api/models`）：`filtered` CTE
    只筛模型行，count 与当页数据都从它派生，因此共享同一快照。count 数的是**模型行**
    而不是 LEFT JOIN 之后的宽行，保持与改动前 `SELECT COUNT(*) FROM models` 的口径一致
    （`model_analysis.model_id` 有唯一约束，宽行不会放大，但口径显式写清更稳妥）。
    """
    start, end, label = _calculate_timeline_window(preset=preset, year=year)
    order_clause = "ASC" if sort == "asc" else "DESC"
    offset = (page - 1) * page_size
    filters: List[str] = []
    params: List[object] = []

    if year is None and preset == "all":
        filters.append("1=1")
    else:
        filters.append("m.created_at BETWEEN %s AND %s")
        params.extend([start, end])

    if provider:
        filters.append("m.provider = %s")
        params.append(provider)
    if model_name:
        filters.append("m.model_name ILIKE %s ESCAPE '\\'")
        params.append(f"%{_escape_like(model_name)}%")
    if open_source is True:
        filters.append("m.is_open_source = TRUE")
    elif open_source is False:
        filters.append("(m.is_open_source = FALSE OR m.is_open_source IS NULL)")

    where_clause = " AND ".join(filters)

    with conn.cursor(row_factory=dict_row) as cursor:
        # 结构与 `/api/models` 相同：count 左连接当页数据，一条语句出结果。
        # 当页为空（offset 超出末尾）时仍返回一行承载 total，避免 total 变成 0。
        cursor.execute(
            f"""
            WITH filtered AS (
                SELECT m.model_id, m.provider, m.model_name, m.description, m.tags,
                       m.created_at, m.model_card_url, m.is_open_source, m.price,
                       m.huggingface_rank
                FROM models AS m
                WHERE {where_clause}
            )
            SELECT page.*, total.total
            FROM (SELECT COUNT(*) AS total FROM filtered) AS total
            LEFT JOIN (
                SELECT f.*, p.avatar_url, ma.analysis_summary
                FROM filtered AS f
                LEFT JOIN providers AS p ON f.provider = p.provider_id
                LEFT JOIN model_analysis AS ma ON f.model_id = ma.model_id
                ORDER BY f.created_at {order_clause}
                LIMIT %s OFFSET %s
            ) AS page ON TRUE
            ORDER BY page.created_at {order_clause} NULLS LAST
            """,
            [*params, page_size, offset],
        )
        rows = cursor.fetchall()

    total = int(rows[0]["total"]) if rows else 0
    items = [
        TimelineModel(
            model_id=row["model_id"],
            provider=row["provider"],
            model_name=row["model_name"],
            description=row["description"],
            created_at=row["created_at"],
            model_card_url=row["model_card_url"],
            tags=_parse_tags(row["tags"]),
            avatar_url=row.get("avatar_url"),
            is_open_source=row.get("is_open_source"),
            price=row.get("price"),
            huggingface_rank=row.get("huggingface_rank"),
            analysis_summary=row.get("analysis_summary"),
        )
        for row in rows
        # 当页为空时 count 左连接补的那行占位行为 NULL，过滤掉
        if row["model_id"] is not None
    ]

    response.headers["Cache-Control"] = CACHE_CONTROL_TIMELINE
    return TimelineResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        start=start,
        end=end,
        preset="year" if year is not None else preset,
        label=label,
    )


@app.get("/api/stats/providers", response_model=List[ProviderStat])
def provider_stats(conn: psycopg.Connection = Depends(get_db)):
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT provider, COUNT(*) as model_count
            FROM models
            GROUP BY provider
            ORDER BY model_count DESC
            """
        )
        rows = cursor.fetchall()
    return [ProviderStat(provider=row["provider"], model_count=row["model_count"]) for row in rows]


def _load_provider_avatar_row(conn: psycopg.Connection, provider_id: str) -> Optional[dict]:
    """读取厂商头像字段（同步；路由里必须经 run_in_threadpool 调用）。"""
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "SELECT avatar_blob, avatar_mime, avatar_url FROM providers WHERE provider_id = %s",
            (provider_id,),
        )
        return cursor.fetchone()


def _cache_provider_avatar(
    conn: psycopg.Connection, provider_id: str, content: bytes, content_type: str
) -> None:
    """把上游图片写进 providers.avatar_blob（同步；同样走线程池）。

    缓存写失败不影响本次响应：图片已经拿到了，没写进去只是下次再抓一遍。
    """
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE providers
                SET avatar_blob = %s, avatar_mime = %s, updated_at = CURRENT_TIMESTAMP
                WHERE provider_id = %s
                """,
                (content, content_type, provider_id),
            )
        conn.commit()
    except Exception:  # pragma: no cover - cache write failure
        conn.rollback()


def _avatar_target_allowed(url: str) -> bool:
    """头像抓取目标是否可信：http/https + 白名单主机 + 常规端口。

    `avatar_url` 是数据库里的值（抓取脚本从上写入），本身不可信；不校验的话
    「能写 providers 表」就等于「能让服务端请求任意地址」（SSRF）。
    主机按「等于白名单项或其子域」匹配：`huggingface.co` 覆盖
    `cdn-avatars.huggingface.co`，同时挡掉 `huggingface.co.evil.com` 这种后缀伪装
    （`host.endswith("." + allowed)` 前面必须有分隔点，斜杠/用户名也解析不出来）。
    """
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    if port not in (None, 80, 443):
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        return False
    return any(host == allowed or host.endswith("." + allowed) for allowed in AVATAR_ALLOWED_HOSTS)


async def _fetch_avatar_upstream(avatar_url: str) -> httpx.Response:
    """抓取头像，重定向逐跳校验并限制次数。

    不用 `follow_redirects=True`：那样只有第一个 URL 受校验，上游回一个 302
    （甚至指向 169.254.169.254）就能绕过白名单。

    首跳的校验放在建客户端之前：被拒的 URL 不该取决于客户端能否建起来
    （例如本机 `all_proxy=socks5://` 又没装 socksio 时 httpx 建客户端就抛 ImportError，
    那会把一个本该 403 的请求变成 500）。
    """
    if not _avatar_target_allowed(avatar_url):
        raise HTTPException(status_code=403, detail="Avatar source is not allowed")
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(AVATAR_FETCH_TIMEOUT, connect=AVATAR_FETCH_TIMEOUT),
        follow_redirects=False,
        headers={"Accept": "image/*"},
    ) as client:
        url = avatar_url
        for _ in range(AVATAR_MAX_REDIRECTS + 1):
            upstream = await client.get(url)
            next_request = upstream.next_request
            if next_request is None:
                return upstream
            await upstream.aclose()
            url = str(next_request.url)
            if not _avatar_target_allowed(url):
                raise HTTPException(status_code=403, detail="Avatar source is not allowed")
    raise HTTPException(status_code=502, detail="Too many avatar redirects")


@app.get("/api/providers/{provider_id}/avatar")
async def provider_avatar(provider_id: str, conn: psycopg.Connection = Depends(get_db)):
    """按需缓存并回传厂商头像。

    这是唯一的 async 路由：需要 await 上游 HTTP 请求。但 psycopg 是**同步**驱动，
    所以两处数据库读/写都经 `run_in_threadpool` 挪出事件循环——直接在 async 函数里
    调 `conn.cursor()` / `conn.commit()` 会卡住整个实例的并发（ISSUE-018）。

    上游 URL 来自数据库，不能当可信输入：协议 + 域名白名单、重定向逐跳校验、
    只接受 `image/*` 的响应才算图片（ISSUE-019）。
    """
    row = await run_in_threadpool(_load_provider_avatar_row, conn, provider_id)
    if not row:
        raise HTTPException(status_code=404, detail="Provider not found")

    avatar_blob = row.get("avatar_blob")
    avatar_mime = row.get("avatar_mime") or "image/png"
    if avatar_blob:
        # 已有缓存字节的厂商完全不受本次改动影响：不发请求、也不过白名单
        headers = {"Cache-Control": f"public, max-age={AVATAR_CACHE_TTL}"}
        return Response(content=avatar_blob, media_type=avatar_mime, headers=headers)

    avatar_url = row.get("avatar_url")
    if not avatar_url:
        raise HTTPException(status_code=404, detail="Avatar unavailable")

    try:
        upstream = await _fetch_avatar_upstream(avatar_url)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch avatar: {exc}") from exc

    if upstream.status_code == 404:
        raise HTTPException(status_code=404, detail="Avatar not found")
    if upstream.status_code >= 500:
        raise HTTPException(status_code=502, detail="Avatar provider error")
    if upstream.status_code >= 400:
        raise HTTPException(status_code=upstream.status_code, detail="Avatar fetch error")

    content = upstream.content
    content_type = (upstream.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if not content_type.startswith("image/"):
        # 以前这里会把上游的 content-type 原样回传并缓存，文本/HTML 也能当头像落库
        raise HTTPException(status_code=502, detail="Avatar source did not return an image")
    if not content:
        raise HTTPException(status_code=502, detail="Avatar source returned an empty body")

    if len(content) <= AVATAR_MAX_BYTES:
        await run_in_threadpool(
            _cache_provider_avatar, conn, provider_id, content, content_type
        )

    headers = {
        "Cache-Control": f"public, max-age={AVATAR_CACHE_TTL}",
        "X-Content-Type-Options": "nosniff",
    }
    for header in ("ETag", "Last-Modified"):
        value = upstream.headers.get(header)
        if value:
            headers[header] = value

    return Response(content=content, media_type=content_type, headers=headers)


def _escape_like(value: str) -> str:
    """把 LIKE/ILIKE 元字符转成字面量。

    参数绑定只防 SQL 注入，**不处理通配符**：`%{value}%` 里的模式串仍然会把用户
    输入的 `%` / `_` 当成通配符（输入一个 `%` 就等于取消搜索，输入 `_` 会匹配任意
    单字符）。转义顺序必须先是反斜杠，否则会把后面加的转义符再转一遍。

    配套的 SQL 里都要写 `ESCAPE '\\'`，让 Postgres 用反斜杠当转义符。
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _calculate_timeline_window(preset: str, year: Optional[int]) -> tuple[datetime, datetime, str]:
    """时间轴查询窗口，边界一律是 UTC aware datetime。

    `models.created_at` 是 `timestamptz`，比较时不能混用 naive 值（否则会按
    会话时区隐式换算）。**年份窗口按 UTC 年切**：前端按访问者本地时区显示，
    跨年边界（例如 UTC+8 的 1 月 1 日 00:00–07:59）可能落到相邻年份的视觉位置上，
    这是有意取舍——服务端不做时区猜测，前端要按本地年切可以自己传更精确的窗口。
    """
    now = _utcnow()
    if year is not None:
        start_dt = datetime(year, 1, 1, tzinfo=timezone.utc)
        end_dt = datetime(year, 12, 31, 23, 59, 59, 999999, tzinfo=timezone.utc)
        return start_dt, end_dt, f"{year}年"

    preset = preset or "30d"
    if preset == "all":
        start_dt = datetime(1970, 1, 1, tzinfo=timezone.utc)
        end_dt = now
        return start_dt, end_dt, "全部"
    if preset == "6m":
        start_dt = now - timedelta(days=182)
        label = "近半年"
    elif preset == "1y":
        start_dt = datetime(now.year, 1, 1, tzinfo=timezone.utc)
        end_dt = now
        return start_dt, end_dt, "今年"
    else:
        start_dt = now - timedelta(days=30)
        label = "近30天"
    end_dt = now
    return start_dt, end_dt, label

def _parse_tags(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    raw = raw.strip()
    if raw.startswith("["):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    return [tag.strip() for tag in raw.split(",") if tag.strip()]


class ModelIdRequest(BaseModel):
    """请求体：包含模型ID"""
    # 不声明会触发 pydantic 的 protected namespace "model_" 警告
    model_config = ConfigDict(protected_namespaces=())

    model_id: str


@app.post("/api/models/analysis", response_model=ModelAnalysis)
def get_model_analysis(
    request: ModelIdRequest,
    conn: psycopg.Connection = Depends(get_db)
):
    """获取单个模型的AI分析结果。"""
    model_id = request.model_id

    with conn.cursor(row_factory=dict_row) as cursor:
        # provider 取自关联的 models 表（ISSUE-016）：model_analysis 自己那份 provider
        # 是分析时抄下来的副本，而 models.provider 才是站内筛选/头像用的权威值。
        # 两者可能不一致（`aion-labs` vs `aionlabs`），所以不做 COALESCE 兜底，
        # 直接按 models.provider 返回；models 行缺失时留 NULL，前端自有回退。
        cursor.execute(
            """
            SELECT
                ma.model_id,
                m.provider AS provider,
                ma.analysis_summary,
                ma.key_features,
                ma.use_cases,
                ma.performance_metrics,
                ma.llm_model_used,
                ma.analyzed_at,
                ma.is_milestone,
                ma.milestone_features,
                ma.updated_at,
                array_agg(DISTINCT mt.tag) FILTER (WHERE mt.tag IS NOT NULL) as tags
            FROM model_analysis ma
            LEFT JOIN models m ON ma.model_id = m.model_id
            LEFT JOIN model_tags mt ON ma.model_id = mt.model_id
            WHERE ma.model_id = %s
            GROUP BY ma.id, ma.model_id, m.provider, ma.analysis_summary, ma.key_features,
                     ma.use_cases, ma.performance_metrics, ma.llm_model_used, ma.analyzed_at,
                     ma.is_milestone, ma.milestone_features, ma.updated_at
            """,
            [model_id],
        )
        row = cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Model analysis not found")

    return ModelAnalysis(
        model_id=row["model_id"],
        provider=row["provider"],
        analysis_summary=row["analysis_summary"],
        key_features=row["key_features"] or [],
        use_cases=row["use_cases"] or [],
        performance_metrics=row["performance_metrics"],
        llm_model_used=row["llm_model_used"],
        analyzed_at=row["analyzed_at"],
        tags=list(filter(None, row["tags"] or [])),
        is_milestone=bool(row["is_milestone"]),
        milestone_features=row["milestone_features"],
        updated_at=row["updated_at"],
    )


def _fetch_arena_summary(conn: psycopg.Connection, model_id: str) -> ArenaScoreSummary:
    """查询单个模型的行业评分，汇总为 ArenaScoreSummary。

    抽成普通函数是为了让两个同步路由共用，不需要在事件循环里 await。
    """
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT model_id, source, rank, score, category, updated_at
            FROM model_arena_info
            WHERE model_id = %s
            ORDER BY source, category
            """,
            (model_id,)
        )
        rows = cursor.fetchall()

    if not rows:
        return ArenaScoreSummary(model_id=model_id, has_score=False)

    details = [
        ArenaScoreInfo(
            model_id=row["model_id"],
            source=row["source"],
            rank=row["rank"],
            score=row["score"],
            category=row["category"],
            updated_at=row["updated_at"]
        )
        for row in rows
    ]

    # 计算综合评分
    overall_scores = [d.score for d in details if d.category == "overall" and d.score is not None]
    combined_score = round(sum(overall_scores) / len(overall_scores), 2) if overall_scores else None

    sources = list(set(d.source for d in details))

    return ArenaScoreSummary(
        model_id=model_id,
        has_score=True,
        sources=sources,
        combined_score=combined_score,
        details=details
    )


# 用 {model_id:path} 而不是 {model_id}：真实的 model_id 形如 "provider/model-name"，
# 默认的字符串转换器不匹配斜杠，原来的写法对任何真实 ID 都只能返回 404。
@app.get("/api/arena/scores/{model_id:path}")
def get_model_arena_scores(
    model_id: str = Path(..., description="模型ID"),
    conn: psycopg.Connection = Depends(get_db),
) -> ArenaScoreSummary:
    """获取模型的行业评分信息。"""
    return _fetch_arena_summary(conn, model_id)


# 为什么用 POST 而不是 GET /api/models/{model_id}/analysis-with-scores：
# 真实 model_id 形如 "provider/model-name"，含斜杠。默认的字符串转换器不匹配斜杠，
# 写成 {model_id} 匹配不到任何真实 ID；写成 {model_id:path} 又会被后面的兜底路由
# 或贪婪回溯搅乱。项目里 /api/models/analysis 已经为同一个根因采用 POST + 请求体，
# 这里沿用同一约定。
@app.post("/api/models/analysis-with-scores")
def get_model_analysis_with_scores(
    request: ModelIdRequest,
    conn: psycopg.Connection = Depends(get_db),
) -> TimelineModelWithAnalysis:
    """获取模型的完整分析数据（包括里程碑信息和评分）。"""
    model_id = request.model_id
    with conn.cursor(row_factory=dict_row) as cursor:
        # 查询基础模型信息
        cursor.execute(
            """
            SELECT m.model_id, m.provider, m.model_name, m.description, m.created_at,
                   m.model_card_url, m.tags, m.is_open_source, m.price,
                   m.huggingface_rank,
                   ma.analysis_summary, ma.is_milestone, ma.milestone_features
            FROM models m
            LEFT JOIN model_analysis ma ON m.model_id = ma.model_id
            WHERE m.model_id = %s
            """,
            (model_id,)
        )
        row = cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Model not found")

    # 获取评分信息
    score_summary = _fetch_arena_summary(conn, model_id)

    return TimelineModelWithAnalysis(
        model_id=row["model_id"],
        provider=row["provider"],
        model_name=row["model_name"],
        description=row["description"],
        created_at=row["created_at"],
        model_card_url=row["model_card_url"],
        tags=_parse_tags(row["tags"]),
        avatar_url=None,  # 可以通过额外的提供商查询获取
        is_open_source=row["is_open_source"],
        price=row["price"],
        huggingface_rank=row["huggingface_rank"],
        analysis_summary=row["analysis_summary"],
        is_milestone=row["is_milestone"] or False,
        milestone_features=row["milestone_features"],
        arena_score=score_summary
    )


# --------------------------------------------------------------------------
# 兜底路由之前的「已知路径 + 错误方法」显式注册（ISSUE-022）
# --------------------------------------------------------------------------
# 这两个路径只有 POST 版本。不显式注册 GET 的话，请求会一路落到文件末尾的
# `/api/models/{model_id:path}`，被当成 model_id="analysis" 去查库，回 404
# "Model not found" —— 把「方法用错了」伪装成「模型不存在」，排障时极具误导性。
# 显式返回 405 + Allow，语义才是准确的。注意：必须注册在兜底路由**之前**，
# 否则 `:path` 转换器会先把它们吃掉（顺序不变量由 tests/test_api_contract.py 守着）。
@app.get("/api/models/analysis")
def models_analysis_get_not_allowed():
    """GET 该路径是方法错误，不是资源不存在：正确入口是 POST。"""
    raise HTTPException(
        status_code=405,
        detail="Method Not Allowed: use POST /api/models/analysis",
        headers={"Allow": "POST"},
    )


@app.get("/api/models/analysis-with-scores")
def models_analysis_with_scores_get_not_allowed():
    """GET 该路径是方法错误，不是资源不存在：正确入口是 POST。"""
    raise HTTPException(
        status_code=405,
        detail="Method Not Allowed: use POST /api/models/analysis-with-scores",
        headers={"Allow": "POST"},
    )


# 兜底路由：必须放在所有 /api/models/<固定路径> 之后。
# `:path` 转换器会匹配任意层级的剩余路径（真实 model_id 形如 "provider/name"，
# 含斜杠，默认的字符串转换器匹配不到）。
#
# 这个路由会把「未定义的 /api/models/* 路径」也一起吃下来，所以函数内必须把
# 「路径不存在」和「模型不存在」分开（ISSUE-022）。判定分两步：
#   1. 不含斜杠的单段路径不可能是模型 ID（HF / OpenRouter 的 model_id 都是
#      `组织/模型名`，这正是这里必须用 `:path` 的原因）→ 视为未知路径；
#   2. 含斜杠但库里查不到时，再看首段命名空间是否真的存在过（`SELECT 1 FROM models
#      WHERE model_id LIKE '<首段>/%'`）。命名空间不存在 = 十有八九是拼错的路径
#      （`/api/models/anything/typo`）；命名空间存在 = 真的是模型名写错了。
# 三条分支都是 404，但 detail 不同，调用方能区分「接口不存在」与「模型不存在」；
# 真实模型的详情请求在第 2 步之前就以 200 返回，不受影响。
@app.get("/api/models/{model_id:path}", response_model=Model)
def get_model(model_id: str, conn: psycopg.Connection = Depends(get_db)):
    if "/" not in model_id:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown API path: /api/models/{model_id}",
        )

    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT model_id, provider, model_name, description, tags, created_at, downloads, likes, model_card_url
            FROM models
            WHERE model_id = %s
            """,
            [model_id],
        )
        row = cursor.fetchone()

        if not row:
            # 首段命名空间在 models 表里是否出现过。这里故意查 models 而不是 providers：
            # model_id 的前缀是「仓库组织名」，与 providers.provider_id 并不总相等
            # （`aion-labs` vs `aionlabs`），只有 models 表认识 `aion-labs` 这种前缀。
            provider_prefix = model_id.split("/", 1)[0]
            cursor.execute(
                "SELECT 1 FROM models WHERE model_id LIKE %s ESCAPE '\\' LIMIT 1",
                [f"{_escape_like(provider_prefix)}/%"],
            )
            if cursor.fetchone() is None:
                raise HTTPException(
                    status_code=404,
                    detail=(
                        "Unknown API path: no models under provider namespace "
                        f"'{provider_prefix}'"
                    ),
                )

    if not row:
        raise HTTPException(status_code=404, detail="Model not found")
    return Model(
        model_id=row["model_id"],
        provider=row["provider"],
        model_name=row["model_name"],
        description=row["description"],
        tags=_parse_tags(row["tags"]),
        created_at=row["created_at"],
        downloads=row["downloads"],
        likes=row["likes"],
        model_card_url=row["model_card_url"],
    )


@app.get("/health")
def healthcheck():
    return {"status": "ok"}
