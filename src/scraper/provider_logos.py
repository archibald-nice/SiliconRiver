"""厂商 logo 的映射表解析、候选排序与轻量下载。

这个模块只做三件事：读 `data/provider_logos.yaml`、按固定优先级展开候选 URL、
把候选下载成 `(blob, mime)`。它不碰数据库——写库是
`scripts/fill_provider_avatars.py` 的事，这样解析/下载逻辑可以被单测直接覆盖。

为什么需要这一层
----------------
后端运行期不允许回源外网：`backend/main.py` 只放行一份 AVATAR_ALLOWED_HOSTS
白名单，`cdn.jsdelivr.net` / `avatars.githubusercontent.com` 都不在里面，线上
`/api/providers/{id}/avatar` 读到 `avatar_blob` 就直接返回。所以头像必须在抓取侧
一次性下载成 blob 缓存，而不是让 API 每次现拉。

为什么维护一张显式映射表而不是运行时猜
----------------------------------------
两个主源合起来才接近全覆盖：LobeHub 约 40/55、GitHub org 约 50/55（其中 3 个
是**别家公司**）。slug/org 无法从 provider_id 机械推导（`Qwen` 大小写、`z.ai` 的
org 是 `zai-org`、`thinking machines` 的 org 是 `thinking-machines-lab`），猜错
的代价是把陌生公司的 logo 写进生产库。所以解析规则固化在 YAML 里，代码只负责
按顺序试。

为什么顺序是 LobeHub SVG → LobeHub PNG → GitHub → Google favicon
------------------------------------------------------------------
1. LobeHub 图标是**方形品牌图标**（不是带文字的 wordmark、不是真人头像），
   npm 包 license 是 MIT，jsDelivr 直出 1~3KB 的 SVG，最贴合"头像"这个用途；
2. 同一份图标的 PNG 变体（640×640）给不收 SVG 的消费端兜底；
3. GitHub org 头像分辨率/清晰度最好（128×128 PNG），但撞名风险最高，
   只对映射表里人工确认过的 org 使用；
4. Google favicon 只有 16~128px、可能是默认地球图，只用来填最后几个空位。

为什么排除下面这些源（都是实测踩过的坑，写在这里避免有人再试一遍）
------------------------------------------------------------------
- Clearbit Logo API：域名已无 A 记录，TLS 直接握手失败，容易被误判成本机网络问题；
- logo.dev / Brandfetch：都要注册拿 token/client-id，不是匿名接口；
- unavatar：匿名 25 次/天/IP，且对不存在的域名也返回 200 + 它自己的 logo；
- FaviconKit：任何域名都 301 到 GitHub 上的 1×1 占位图，服务已废；
- simple-icons：openai/microsoft/amazon/cohere/ibm/xai 全 404，AI 厂商覆盖最差；
- vectorlogo.zone：AI 新公司基本没有，跳过。

GitHub 撞名是这张表存在的最强理由：`perceptron` 是个人账号、`typesafehub` 是
Lightbend、`aionlabs` 是 Grupo Xiuh——它们都能返回 200，光看状态码发现不了。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import requests
import yaml

LOGGER = logging.getLogger(__name__)

# 项目根目录：本文件在 src/scraper/ 下，往上两级
BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_MAP_PATH = BASE_DIR / "data" / "provider_logos.yaml"

# LobeHub 图标包版本。注意两个包的版本号**不同步**：PNG 包没有 1.95.1
# （实测该路径 404），最低可用 1.97.1；不要为了"整齐"把两者改成同一个版本。
LOBEHUB_SVG_VERSION = "1.95.1"
LOBEHUB_PNG_VERSION = "1.97.1"
LOBEHUB_SVG_TEMPLATE = (
    "https://cdn.jsdelivr.net/npm/@lobehub/icons-static-svg@"
    + LOBEHUB_SVG_VERSION
    + "/icons/{slug}.svg"
)
LOBEHUB_PNG_TEMPLATE = (
    "https://cdn.jsdelivr.net/npm/@lobehub/icons-static-png@"
    + LOBEHUB_PNG_VERSION
    + "/dark/{slug}.png"
)
# github.com/<org>.png 会 302 到 avatars.githubusercontent.com，必须跟随跳转
GITHUB_TEMPLATE = "https://github.com/{org}.png?size=128"
# Google favicon 会先 301 到 t3.gstatic.com/faviconV2，同样必须跟随跳转
FAVICON_TEMPLATE = "https://www.google.com/s2/favicons?domain={domain}&sz=128"

DEFAULT_MAX_BYTES = 2_000_000
DEFAULT_TIMEOUT = 15


@dataclass(frozen=True, slots=True)
class ProviderLogoSpec:
    """映射表里的一行：一个 provider 在各来源上的标识。

    字段全部可选（`provider` 除外），空字符串与缺失等价。`enabled=False` 表示
    明确不下载：要么是真人头像（视觉上不是厂商 logo），要么三个来源都查不到。
    """

    provider: str
    display_name: str | None = None
    lobe_slug: str | None = None
    github_org: str | None = None
    domain: str | None = None
    enabled: bool = True
    note: str = ""


@dataclass(frozen=True, slots=True)
class LogoCandidate:
    """一个待尝试的下载地址。

    `source` 同时用于日志、汇总和写库时的来源标注，取值固定为
    `lobehub-svg` / `lobehub-png` / `github` / `favicon`。
    """

    url: str
    source: str


def build_session() -> requests.Session:
    """建一个带显式 UA 的 requests 会话。

    项目抓取侧统一用 requests（本机 `all_proxy=socks5://` 会打死 httpx，见
    AGENTS.md 4.2）。显式 UA 不是为了绕过限制，而是出问题时能在 CDN 侧日志里
    认出是我们。
    """
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "SiliconRiver-logo-fetcher/1.0",
            "Accept": "image/*,*/*;q=0.5",
        }
    )
    return session


def _clean_text(value: object) -> str | None:
    """把 YAML 里的空串/空白/None 统一成 None，避免生成 `.../icons/.svg` 这种 URL。"""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def load_logo_map(path: Path | None = None) -> dict[str, ProviderLogoSpec]:
    """读取映射表，返回 `provider -> spec` 的字典。

    文件缺失直接抛 `FileNotFoundError`（而不是回落到一份内置默认表）：
    映射表是"哪家公司对应哪个 slug/org"的唯一事实来源，缺失时静默回落等于
    按猜测的顺序抓图，比报错危险得多。格式错误同理抛 `ValueError`。
    """
    map_path = Path(path) if path is not None else DEFAULT_MAP_PATH
    if not map_path.is_file():
        raise FileNotFoundError(
            f"厂商 logo 映射表不存在：{map_path}\n"
            "  它是 provider_id → LobeHub/GitHub/favicon 标识的唯一来源。"
            "缺少它时不要猜 slug，先补文件。"
        )

    try:
        payload = yaml.safe_load(map_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"映射表不是合法 YAML：{map_path}（{exc}）") from exc

    if not isinstance(payload, list):
        raise ValueError(f"映射表顶层必须是列表（每行一个 - provider: ...）：{map_path}")

    specs: dict[str, ProviderLogoSpec] = {}
    for line_no, entry in enumerate(payload, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"映射表第 {line_no} 条不是对象（应为 `- provider: xxx`）")
        # provider 区分大小写（Qwen 与 qwen 是两条），这里只去首尾空白、不改大小写
        provider = _clean_text(entry.get("provider"))
        if not provider:
            raise ValueError(f"映射表第 {line_no} 条缺少 provider 字段")
        if provider in specs:
            raise ValueError(f"映射表里 provider 重复：{provider!r}（第 {line_no} 条）")

        enabled = entry.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError(
                f"{provider}: enabled 必须是布尔值 true/false，当前是 {enabled!r}"
            )

        specs[provider] = ProviderLogoSpec(
            provider=provider,
            display_name=_clean_text(entry.get("display_name")),
            lobe_slug=_clean_text(entry.get("lobe_slug")),
            github_org=_clean_text(entry.get("github_org")),
            domain=_clean_text(entry.get("domain")),
            enabled=enabled,
            note=_clean_text(entry.get("note")) or "",
        )
    return specs


def resolve_logo_sources(spec: ProviderLogoSpec) -> list[LogoCandidate]:
    """按 ①LobeHub SVG → ②LobeHub PNG → ③GitHub → ④Google favicon 展开候选。

    `enabled=False` 直接返回空列表：这类条目是刻意排除的（真人头像 / 三源都查
    不到），不是"漏配"，所以不该继续往下试 favicon。
    """
    if not spec.enabled:
        return []

    candidates: list[LogoCandidate] = []
    slug = (spec.lobe_slug or "").strip()
    if slug:
        # slug 来自人工维护的 YAML，理论上都是小写安全字符；仍然 quote 一次，
        # 免得将来有人填了带空格的 slug 而生成坏 URL。
        safe_slug = quote(slug, safe="")
        candidates.append(
            LogoCandidate(LOBEHUB_SVG_TEMPLATE.format(slug=safe_slug), "lobehub-svg")
        )
        candidates.append(
            LogoCandidate(LOBEHUB_PNG_TEMPLATE.format(slug=safe_slug), "lobehub-png")
        )
    if spec.github_org:
        candidates.append(
            LogoCandidate(
                GITHUB_TEMPLATE.format(org=quote(spec.github_org.strip(), safe="")),
                "github",
            )
        )
    if spec.domain:
        candidates.append(
            LogoCandidate(
                FAVICON_TEMPLATE.format(domain=quote(spec.domain.strip(), safe="")),
                "favicon",
            )
        )
    return candidates


def _download_with_reason(
    candidate: LogoCandidate,
    *,
    session: requests.Session,
    max_bytes: int,
    timeout: float,
) -> tuple[tuple[bytes, str] | None, str]:
    """下载并校验，返回 `((blob, mime), "")` 或 `(None, 失败原因)`。

    失败原因返回给调用方是为了输出可诊断的汇总（"typesafe 只有 favicon 且
    返回 404"比"失败了"有用得多），日志里也会再打一遍。
    """
    try:
        # allow_redirects 默认就是 True，这里显式写出来：GitHub 头像 302 到
        # avatars.githubusercontent.com、Google favicon 301 到 t3.gstatic.com，
        # 不跟跳转只能拿到 302/301 的空壳。
        response = session.get(candidate.url, timeout=timeout, allow_redirects=True)
    except requests.RequestException as exc:
        return None, f"请求异常：{exc}"

    try:
        if response.status_code != 200:
            # GitHub 的 `.png` 对不存在的 org 返回 404 + 9 字节 text/plain；
            # Google favicon 对查不到的域名返回 404 + 默认图。看状态码最干净。
            return None, f"HTTP {response.status_code}"

        content_type = (
            response.headers.get("Content-Type")
            or response.headers.get("content-type")
            or ""
        )
        mime = content_type.split(";")[0].strip().lower()
        if not mime.startswith("image/"):
            # 只认 image/*：文本/JSON 错误页、jsDelivr 的 404 文本都在这里被挡掉。
            return None, f"content-type 不是图片：{mime or '(缺失)'}"

        # 先看声明的长度能在下载大文件前省流量；没声明就等读完再量。
        declared = response.headers.get("Content-Length") or response.headers.get(
            "content-length"
        )
        if declared:
            try:
                if int(declared) > max_bytes:
                    return None, f"Content-Length {declared} 超过上限 {max_bytes}"
            except ValueError:
                pass  # 头部不规范就不信它，落到下面按实际长度校验

        blob = response.content
        if not blob:
            return None, "响应体为空"
        if len(blob) > max_bytes:
            # 上限的意义是防止误抓到 HTML 大页或异常源，不是质量门槛：
            # LobeHub PNG 约 11KB、GitHub 头像约 4KB，2MB 已经很宽松。
            return None, f"体积 {len(blob)} 字节超过上限 {max_bytes}"
        return (blob, mime), ""
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()


def download_logo(
    candidate: LogoCandidate,
    *,
    session: requests.Session,
    max_bytes: int = DEFAULT_MAX_BYTES,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[bytes, str] | None:
    """下载单个候选，返回 `(blob, mime)`；任何失败都返回 None 并 WARN。

    不抛异常是刻意的：批量补 54 家时单个源挂掉是常态（CDN 抖动、某家公司
    临时下线），一抛异常会让后面所有厂商一起放弃。调用方用返回值判断即可。
    """
    result, reason = _download_with_reason(
        candidate, session=session, max_bytes=max_bytes, timeout=timeout
    )
    if result is None:
        LOGGER.warning(
            "候选下载失败 %s（%s）：%s", candidate.source, candidate.url, reason
        )
    return result


def pick_best_logo(
    spec: ProviderLogoSpec,
    *,
    session: requests.Session,
    trace: list[str] | None = None,
) -> tuple[bytes, str, str] | None:
    """按优先级逐个尝试，返回 `(blob, mime, source_label)`；全不中返回 None。

    `trace` 是可选的诊断通道：每个候选的失败原因会追加进去，调用方（填充脚本）
    用它打印"为什么这家没补上"。不传就只打日志。
    """
    candidates = resolve_logo_sources(spec)
    if not candidates:
        reason = (
            "映射表标记 enabled=false（明确不下载）"
            if not spec.enabled
            else "映射表里没有任何可用来源（slug/org/domain 全空）"
        )
        if trace is not None:
            trace.append(reason)
        LOGGER.info("厂商 %s 跳过：%s", spec.provider, reason)
        return None

    for candidate in candidates:
        result, reason = _download_with_reason(
            candidate,
            session=session,
            max_bytes=DEFAULT_MAX_BYTES,
            timeout=DEFAULT_TIMEOUT,
        )
        if result is None:
            if trace is not None:
                trace.append(f"{candidate.source}: {reason}")
            LOGGER.warning("厂商 %s 的 %s 候选未命中：%s", spec.provider, candidate.source, reason)
            continue
        blob, mime = result
        LOGGER.info(
            "厂商 %s 命中 %s（%s，%d 字节）", spec.provider, candidate.source, mime, len(blob)
        )
        return blob, mime, candidate.source
    return None
