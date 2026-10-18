"""排行榜模型名 → 本仓库 ``model_id`` 的匹配器（纯函数，可离线测试）。

为什么不能直接模糊匹配
----------------------
排行榜名和仓库 ``model_id`` 不是同一套命名：

* 排行榜用展示名（``Claude Opus 4.6 (High)``、``Qwen3-VL-235B-A22B-Thinking``），
  仓库用 HF / OpenRouter 的仓库名（``anthropic/claude-opus-4.6``、
  ``Qwen/Qwen3-VL-235B-A22B-Thinking-FP8``）；
* 尺寸是最容易配错的部分。``qwen3-vl-235b-a22b-thinking`` 与
  ``qwen3-vl-30b-a3b-thinking`` 只差几个 token，一旦用 substring / 编辑距离，
  235B 的分数会被写到 30B 头上（ISSUE-001 明确点名的坑）。

所以匹配分五层，越往后越保守：

1. **别名表**（``data/arena_aliases.yaml``，人工维护）——显式指定，优先级最高。
   它会绕过尺寸守卫（人明确写了就是人的责任），所以只该用于确定无误的映射；
2. **归一化全等**——小写、NFKC、去括号、去 org 前缀、去 ``:free/:batch/:nitro``、
   去 ``-latest/-preview/-beta``、去分隔符后完全相等；
3. **配置后缀归一**——在归一化基础上剥掉日期快照（``-20251101``）、推理档位
   （``-high/-medium/-low/-max``）、上下文窗口（``-32k/-128k``）；
   日期与档位是分档尝试的：``claude-opus-4-5`` 与 ``claude-opus-4-5-20251101``
   同时存在时，每一行只落到“总宽松度最小”的那条，不会把日期快照的分串给基础模型；
4. **token 子集匹配**——只允许差 ``instruct/chat/it/fp8/nvfp4`` 这类样板词
   （以及行名里粘着的 org 名），**必须**通过尺寸守卫，且必须唯一命中；
5. 其余一律 unmatched，并进报告供人工补别名。

尺寸守卫（:func:`sizes_compatible`）在每一层都生效（别名层除外）：名字里的
``235b``/``a22b``/``8x7b`` 必须两侧完全一致，缺一侧也拒绝。没有尺寸的纯模糊
匹配一律不做。
"""
from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import yaml

LOGGER = logging.getLogger("silicon_river.arena.matcher")

DEFAULT_ALIAS_PATH = Path(__file__).resolve().parents[3] / "data" / "arena_aliases.yaml"

_PAREN_RE = re.compile(r"[\(\[].*?[\)\]]")
_ORG_SPLIT = "/"
_VARIANT_SUFFIX_RE = re.compile(r":(?:free|batch|nitro|extended|online|floor)\b", re.IGNORECASE)
_SEPARATOR_RE = re.compile(r"[\s\-_.]+")
_TRAILING_MARKER_RE = re.compile(
    r"(?:[-_. ](?:latest|preview|beta|experimental))+$", re.IGNORECASE
)

# 日期型后缀（训练快照 / 发布日）。归一化时剥掉，否则
# ``claude-3-5-sonnet-20241022`` 永远配不上 ``claude-3-5-sonnet``。
_MONTHS = (
    "january|february|march|april|may|june|july|august|september|october|november|december"
    "|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
)
_DATE_SUFFIX_PATTERNS = (
    # 20241022 / 2024-10-22 / 2024_10_22
    re.compile(r"(?:[-_. ]|^)(?:19|20)\d{2}(?:[-_.]?\d{2}){2}$"),
    # 2025-09
    re.compile(r"(?:[-_. ]|^)(?:19|20)\d{2}[-_.]\d{2}$"),
    # 09-2025 / 09-2025
    re.compile(r"(?:[-_. ]|^)\d{2}[-_.](?:19|20)\d{2}$"),
    # 10-09（月-日）
    re.compile(r"(?:[-_. ]|^)(?:0[1-9]|1[0-2])[-_.](?:0[1-9]|[12]\d|3[01])$"),
    # 0709（MMDD）
    re.compile(r"(?:[-_. ]|^)(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])$"),
    # -2024（只留年份）
    re.compile(r"(?:[-_. ]|^)(?:19|20)\d{2}$"),
    # june-2024 / june 2024
    re.compile(rf"(?:[-_. ]|^)(?:{_MONTHS})[-_. ]?(?:19|20)\d{{2}}$", re.IGNORECASE),
)

# 推理档位后缀：``gpt-5-high`` 与 ``gpt-5`` 是同一个仓库的不同推理档。
_EFFORT_SUFFIX_RE = re.compile(
    r"(?:[-_. ](?:high|medium|low|max|xhigh|minimal))+$", re.IGNORECASE
)

# 上下文窗口后缀：``claude-opus-4-5-high-32k`` 里的 ``32k`` 是推理配置，
# 不是另一份权重。排行榜常把 ``high-32k``、``thinking-16k`` 粘在名字尾部。
_CONTEXT_SUFFIX_RE = re.compile(r"(?:[-_. ](?:\d+k|\d{3}k|\d+m))+$", re.IGNORECASE)

# token 子集匹配允许的“样板词”差异。只放确定不代表新模型的词：
# 量化/格式后缀、HF 常见的使用方式后缀。``thinking`` / ``vl`` / ``vision``
# 这类代表模型变体，**故意不放**——它们配错就是另一个模型的分数。
_CANDIDATE_EXTRA_TOKENS = frozenset(
    {
        "instruct",
        "chat",
        "it",
        "base",
        "hf",
        "fp8",
        "fp16",
        "bf16",
        "awq",
        "gptq",
        "int4",
        "int8",
        "quantized",
        "gguf",
    }
)
_ROW_EXTRA_TOKENS = frozenset(
    {
        "instruct",
        "chat",
        "it",
        "base",
        "hf",
        # 排行榜可能单独列量化版（nvfp4/awq/gptq/int4…），权重相同。
        "fp8",
        "fp16",
        "bf16",
        "fp4",
        "nvfp4",
        "int4",
        "int8",
        "awq",
        "gptq",
        "gguf",
        "quantized",
    }
)

_MIXTURE_SIZE_RE = re.compile(
    r"(?<![a-z0-9])(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*b(?![a-z0-9])",
    re.IGNORECASE,
)
_ACTIVE_SIZE_RE = re.compile(
    r"(?<![a-z0-9])a(\d+(?:\.\d+)?)\s*b(?![a-z0-9])", re.IGNORECASE
)
_TOTAL_SIZE_RE = re.compile(
    r"(?<![a-z0-9])(\d+(?:\.\d+)?)\s*b(?![a-z0-9])", re.IGNORECASE
)


@dataclass(frozen=True, slots=True)
class SizeSignature:
    """名字里出现的参数量签名（只做相等/不等判断，不做数值比较）。

    * ``total``：``235b``、``30B``、``70b`` 这类总参数量；
    * ``active``：``a22b``、``a4b`` 这类激活参数量（MoE）；
    * ``mixture``：``8x7b`` 这类“N 个 M 专家”的写法。

    三者分开存是因为 ``235b-a22b`` 与 ``235b-a3b`` 总参数同为 235B，
    但激活参数不同，必须算两个模型。
    """

    total: frozenset[str] = frozenset()
    active: frozenset[str] = frozenset()
    mixture: frozenset[str] = frozenset()


def _prepare_name(name: str) -> str:
    """做所有匹配层共用的基础清理，但保留分隔符（token 化要用）。"""
    text = unicodedata.normalize("NFKC", str(name)).strip().lower()
    text = unquote(text)
    # 排行榜经常把备注塞在括号里：``Claude Opus 4.6 (High)``。
    text = _PAREN_RE.sub(" ", text)
    # 只保留最后一段，去掉 org 前缀（``openai/gpt-4o`` → ``gpt-4o``）。
    text = text.split(_ORG_SPLIT)[-1]
    # OpenRouter 的变体后缀不是模型本身。
    text = _VARIANT_SUFFIX_RE.sub(" ", text)
    return text.strip()


def _strip_date_suffix(text: str) -> str:
    for pattern in _DATE_SUFFIX_PATTERNS:
        stripped = pattern.sub("", text).strip()
        if stripped != text:
            return stripped
    return text


def _strip_suffixes(text: str, *, strip_date: bool, strip_effort: bool) -> str:
    """循环剥掉尾部配置后缀，直到稳定。

    排行榜会把多个配置后缀叠着写：``claude-opus-4-5-20251101-high-32k``、
    ``deepseek-v4-pro-high-20260813``。固定「先档位后日期」的顺序剥不干净——
    日期被 ``-high`` 挡在后面，档位又不在尾部；反过来 ``-20251101-high``
    也一样。所以每轮依次试「上下文 → 档位 → 日期」，直到不再变化。

    上下文窗口（``-32k/-16k/-128k/-1m``）永远剥：那是同一个权重的推理配置。
    """
    for _ in range(4):
        previous = text
        text = _CONTEXT_SUFFIX_RE.sub("", text).strip()
        if strip_effort:
            text = _EFFORT_SUFFIX_RE.sub("", text).strip()
        if strip_date:
            text = _strip_date_suffix(text).strip()
        # ``-preview`` 可能压在档位后面（``…-high-preview``），也要参与循环：
        # 先剥 preview，下一轮才能把 ``-high`` 剥掉。
        text = _TRAILING_MARKER_RE.sub("", text).strip()
        if text == previous:
            break
    return text


def _normalize(
    name: str, *, strip_date: bool = True, strip_effort: bool = False
) -> str:
    text = _prepare_name(name)
    text = _strip_suffixes(text, strip_date=strip_date, strip_effort=strip_effort)
    text = _SEPARATOR_RE.sub("", text)
    return text


def normalize_name(name: str) -> str:
    """归一化到用于“全等”比较的紧凑键（会剥掉日期快照后缀）。

    >>> normalize_name("Claude-3.5-Sonnet (High)")
    'claude35sonnet'
    >>> normalize_name("~anthropic/claude-fable-latest")
    'claudefable'
    >>> normalize_name("Qwen/Qwen3-VL-235B-A22B-Thinking:free")
    'qwen3vl235ba22bthinking'
    >>> normalize_name("claude-opus-4-5-20251101")
    'claudeopus45'
    """
    return _normalize(name)


def match_forms(name: str) -> list[str]:
    """返回按优先级排列的归一化候选键：原样键 → 去掉推理档位后的键。"""
    forms: list[str] = []
    base = _normalize(name)
    if base:
        forms.append(base)

    alt = _normalize(name, strip_effort=True)
    if alt and alt not in forms:
        forms.append(alt)
    return forms


def scored_forms(name: str) -> list[tuple[str, int]]:
    """返回 ``(归一化键, 宽松度)``，宽松度越小越精确。

    宽松度含义：

    * 0 —— 原样（日期、推理档位都保留）；
    * 1 —— 剥掉 ``-high/-medium/-low/-max`` 推理档位；
    * 2 —— 剥掉日期快照后缀（``-20251101``、``-09-2025`` 等）；
    * 3 —— 两者都剥。

    匹配时取“行宽松度 + 候选宽松度”最小的候选。这样
    ``claude-opus-4-5`` 与 ``claude-opus-4-5-20251101`` 同时存在时，
    各行的分数只会落到各自精确命中的那一个上，而不是两边都写。
    """
    scored: list[tuple[str, int]] = []
    seen: set[str] = set()
    for strip_date, date_stage in ((False, 0), (True, 2)):
        for strip_effort, effort_stage in ((False, 0), (True, 1)):
            key = _normalize(
                name, strip_date=strip_date, strip_effort=strip_effort
            )
            if key and key not in seen:
                seen.add(key)
                scored.append((key, date_stage + effort_stage))
    return sorted(scored, key=lambda item: item[1])


def size_signature(name: str) -> SizeSignature:
    """从名字里抽取总参数 / 激活参数 / N×M 专家签名。"""
    text = unicodedata.normalize("NFKC", str(name)).lower()
    mixtures = frozenset(
        f"{a}x{b}b" for a, b in _MIXTURE_SIZE_RE.findall(text)
    )
    totals = frozenset(
        f"{value}b" for value in _TOTAL_SIZE_RE.findall(text)
    )
    actives = frozenset(
        f"a{value}b" for value in _ACTIVE_SIZE_RE.findall(text)
    )
    return SizeSignature(total=totals, active=actives, mixture=mixtures)


def sizes_compatible(left: str, right: str) -> bool:
    """尺寸守卫：两侧的参数量必须完全一致；缺一侧也按不一致处理。

    宁可漏配（少一条排名），也不能把 235B 的分数写到 30B 头上。
    """
    a = size_signature(left)
    b = size_signature(right)
    if a.mixture != b.mixture:
        return False
    if a.total != b.total:
        return False
    if a.active != b.active:
        return False
    return True


def has_size(name: str) -> bool:
    signature = size_signature(name)
    return bool(signature.total or signature.active or signature.mixture)


def _tokens(name: str) -> frozenset[str]:
    text = _prepare_name(name)
    text = _strip_date_suffix(text)
    return frozenset(re.findall(r"[a-z0-9]+", text))


def load_aliases(
    path: str | Path | None = None, source: str | None = None
) -> dict[str, str]:
    """读取别名表；``source`` 为 ``lmarena`` / ``swebench`` 时叠加对应小节。

    文件不存在时返回空表（仓库初次 clone 不该因为缺别名文件就崩）。
    """
    alias_path = Path(path) if path is not None else DEFAULT_ALIAS_PATH
    if not alias_path.exists():
        return {}

    raw = yaml.safe_load(alias_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, Mapping):
        raise ValueError(f"别名文件顶层必须是 mapping：{alias_path}")

    sections = ["shared"]
    if source:
        sections.append(source)

    merged: dict[str, str] = {}
    for section in sections:
        block = raw.get(section) or {}
        if not isinstance(block, Mapping):
            raise ValueError(f"别名文件 {alias_path} 的 {section!r} 小节必须是 mapping")
        for key, value in block.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise ValueError(
                    f"别名文件 {alias_path} 的 {section!r} 小节只接受 str→str：{key!r}"
                )
            merged[key] = value
    return merged


@dataclass(frozen=True, slots=True)
class ArenaMatch:
    """一条排行榜行与仓库 ``model_id`` 的匹配结果。"""

    row: Any
    model_id: str
    method: str  # alias | exact | effort | date | lenient | fuzzy


def _org_tokens(model_id: str) -> frozenset[str]:
    """取 ``model_id`` 的 org 段 token（``nvidia/...`` → ``{"nvidia"}``）。

    排行榜行偶尔把 org 粘在名字里（``nvidia-nemotron-3-ultra-...``），
    而候选 id 的 org 在斜杠前被 :func:`_prepare_name` 丢掉了；token 子集层
    需要把它补回来，否则这类行永远差一个 ``nvidia``。
    """
    if _ORG_SPLIT not in model_id:
        return frozenset()
    org = model_id.split(_ORG_SPLIT, 1)[0].lstrip("~")
    return frozenset(re.findall(r"[a-z0-9]+", org.lower()))


@dataclass(frozen=True, slots=True)
class _IndexedCandidate:
    model_id: str
    forms: tuple[tuple[str, int], ...]
    tokens: frozenset[str]
    org_tokens: frozenset[str] = frozenset()
    size: tuple[frozenset[str], frozenset[str], frozenset[str]] = (
        frozenset(),
        frozenset(),
        frozenset(),
    )


class _CandidateIndex:
    def __init__(self, model_ids: Iterable[str]):
        self.model_ids: tuple[str, ...] = tuple(dict.fromkeys(model_ids))
        self._by_form: dict[str, list[tuple[_IndexedCandidate, int]]] = {}
        # 模糊层按尺寸签名分桶：同尺寸才可能匹配，否则 1 万行 × 1700 候选逐一
        # 比 token 子集要跑几分钟（2026-10-18 实测同步卡在这一步）。
        self._by_size: dict[tuple, list[_IndexedCandidate]] = {}
        self._candidates: list[_IndexedCandidate] = []
        for model_id in self.model_ids:
            forms = tuple(scored_forms(model_id))
            if not forms:
                continue
            signature = size_signature(model_id)
            candidate = _IndexedCandidate(
                model_id=model_id,
                forms=forms,
                tokens=_tokens(model_id),
                org_tokens=_org_tokens(model_id),
                size=(signature.mixture, signature.total, signature.active),
            )
            self._candidates.append(candidate)
            self._by_size.setdefault(candidate.size, []).append(candidate)
            for form, stage in forms:
                self._by_form.setdefault(form, []).append((candidate, stage))

    def entries(self, form: str) -> list[tuple[_IndexedCandidate, int]]:
        return self._by_form.get(form, [])

    @property
    def candidates(self) -> tuple[_IndexedCandidate, ...]:
        return tuple(self._candidates)

    def same_size(self, name: str) -> list[_IndexedCandidate]:
        """只返回尺寸签名与 ``name`` 完全一致（含同为无尺寸）的候选。"""
        signature = size_signature(name)
        return self._by_size.get(
            (signature.mixture, signature.total, signature.active), []
        )


def _coerce_model_id(item: Any) -> str | None:
    if isinstance(item, str):
        return item
    if isinstance(item, Mapping):
        for key in ("model_id", "id"):
            value = item.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def _candidate_ids(candidates: Iterable[Any] | Mapping[str, Any]) -> list[str]:
    # 传 ``{model_id: row}`` 这种映射时，键就是 id；传单行 dict 时取 model_id。
    if isinstance(candidates, Mapping) and "model_id" not in candidates:
        items: Iterable[Any] = candidates.keys()
    else:
        items = candidates  # type: ignore[assignment]
    ids: list[str] = []
    for item in items:
        model_id = _coerce_model_id(item)
        if model_id:
            ids.append(model_id)
    return ids


def _alias_lookup(
    aliases: Mapping[str, str] | None,
) -> tuple[dict[str, str], dict[str, str]]:
    """返回 (原样键表, 归一化键表)。归一化键冲突时丢弃，避免猜。"""
    raw_map: dict[str, str] = {}
    norm_map: dict[str, str] = {}
    conflicts: set[str] = set()
    for key, value in (aliases or {}).items():
        raw_map[key.strip().lower()] = value
        for form in match_forms(key):
            previous = norm_map.get(form)
            if previous is not None and previous != value:
                conflicts.add(form)
            else:
                norm_map[form] = value
    for form in conflicts:
        LOGGER.warning("别名表存在冲突，已忽略归一化键 %r", form)
        norm_map.pop(form, None)
    return raw_map, norm_map


def _lookup_alias(
    name: str, raw_map: Mapping[str, str], norm_map: Mapping[str, str]
) -> str | None:
    hit = raw_map.get(name.strip().lower())
    if hit:
        return hit
    for form in match_forms(name):
        hit = norm_map.get(form)
        if hit:
            return hit
    return None


def match_arena_rows(
    rows: Iterable[Any],
    candidates: Iterable[Any] | Mapping[str, Any],
    aliases: Mapping[str, str] | None = None,
) -> tuple[list[ArenaMatch], list[Any]]:
    """把排行榜行匹配到仓库 ``model_id``。

    Args:
        rows: 任意带 ``model_name`` 属性的对象（``ArenaRow`` 即可）。
        candidates: 仓库里现有的 ``model_id`` 字符串，或带 ``model_id`` 的 dict 行。
        aliases: ``{排行榜名: model_id}``，通常来自 :func:`load_aliases`。

    Returns:
        ``(matched, unmatched)``。``matched`` 里同一行可能对应多个 ``model_id``
        （HF 与 OpenRouter 各有一份同名模型时，两边都应该拿到这条排名）；
        ``unmatched`` 是**一条都没配上**的行。别名指向不存在的 model_id 时，
        该行会如实落进 ``unmatched`` 并打 warning——绝不猜一个相近的 id。
    """
    candidate_ids = _candidate_ids(candidates)
    index = _CandidateIndex(candidate_ids)
    known_ids = set(index.model_ids)
    raw_aliases, norm_aliases = _alias_lookup(aliases)

    matched: list[ArenaMatch] = []
    unmatched: list[Any] = []
    warned: set[str] = set()

    for row in rows:
        name = getattr(row, "model_name", None)
        if not isinstance(name, str) or not name.strip():
            unmatched.append(row)
            continue

        alias_target = _lookup_alias(name, raw_aliases, norm_aliases)
        if alias_target:
            if alias_target in known_ids:
                matched.append(ArenaMatch(row=row, model_id=alias_target, method="alias"))
            else:
                LOGGER.warning(
                    "别名 %r → %r 指向的 model_id 不在库里，按未命中处理",
                    name,
                    alias_target,
                )
                unmatched.append(row)
            continue

        # 归一化全等：按“总宽松度”取最精确的一层，避免日期变体互相串分。
        best_stage: dict[str, int] = {}
        rejected_by_size: list[str] = []
        for form, row_stage in scored_forms(name):
            for candidate, candidate_stage in index.entries(form):
                if not sizes_compatible(name, candidate.model_id):
                    rejected_by_size.append(candidate.model_id)
                    continue
                stage = row_stage + candidate_stage
                if stage < best_stage.get(candidate.model_id, 99):
                    best_stage[candidate.model_id] = stage
        if best_stage:
            top = min(best_stage.values())
            method = {0: "exact", 1: "effort", 2: "date"}.get(top, "lenient")
            for model_id, stage in sorted(best_stage.items()):
                if stage == top:
                    matched.append(ArenaMatch(row=row, model_id=model_id, method=method))
            continue
        if rejected_by_size:
            LOGGER.warning(
                "名称 %r 归一化后命中 %s，但尺寸签名不一致，拒绝匹配",
                name,
                ", ".join(sorted(set(rejected_by_size))[:5]),
            )

        # 最后一层：token 子集 + 尺寸守卫 + 唯一命中。
        if not has_size(name):
            unmatched.append(row)
            continue
        row_tokens = _tokens(name)
        if len(row_tokens) < 2:
            unmatched.append(row)
            continue

        fuzzy_hits: list[_IndexedCandidate] = []
        for candidate in index.same_size(name):
            # same_size 已保证签名相等（含“双方都无尺寸”），这里只需排除无尺寸候选。
            if not candidate.size[0] and not candidate.size[1] and not candidate.size[2]:
                continue
            candidate_tokens = candidate.tokens
            row_extra = row_tokens - candidate_tokens
            candidate_extra = candidate_tokens - row_tokens
            if not row_extra <= (_ROW_EXTRA_TOKENS | candidate.org_tokens):
                continue
            if not candidate_extra <= _CANDIDATE_EXTRA_TOKENS:
                continue
            if row_extra == candidate_extra == frozenset():
                # 完全相等却没走 exact，通常是被日期/后缀剥成了空串，不做兜底。
                continue
            if len(row_tokens & candidate_tokens) < 2:
                continue
            fuzzy_hits.append(candidate)

        if len(fuzzy_hits) == 1:
            matched.append(
                ArenaMatch(row=row, model_id=fuzzy_hits[0].model_id, method="fuzzy")
            )
        elif len(fuzzy_hits) > 1 and len(
            {normalize_name(candidate.model_id) for candidate in fuzzy_hits}
        ) == 1:
            # 多个候选只是同一模型的 ``:free/:batch`` 变体（归一化后同一个键），
            # 与 exact 层的处理保持一致：都给这条排名。
            for candidate in fuzzy_hits:
                matched.append(
                    ArenaMatch(row=row, model_id=candidate.model_id, method="fuzzy")
                )
        else:
            if len(fuzzy_hits) > 1 and name not in warned:
                warned.add(name)
                LOGGER.warning(
                    "名称 %r 有 %d 个模糊候选，无法确定，按未命中处理：%s",
                    name,
                    len(fuzzy_hits),
                    ", ".join(candidate.model_id for candidate in fuzzy_hits[:5]),
                )
            unmatched.append(row)

    return matched, unmatched
