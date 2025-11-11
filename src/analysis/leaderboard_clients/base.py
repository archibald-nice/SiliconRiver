"""排行榜客户端基类定义。"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

LOGGER = logging.getLogger("silicon_river.leaderboard_clients")


class LeaderboardClient(ABC):
    """排行榜数据客户端基类。

    所有排行榜客户端都应继承此类并实现抽象方法。
    """

    def __init__(self, name: str):
        """初始化排行榜客户端。

        Args:
            name: 排行榜名称（如 'SWE-bench', 'LMSYS Arena' 等）
        """
        self.name = name
        self.enabled = True

    @abstractmethod
    async def fetch_leaderboard(self) -> dict[str, Any]:
        """获取排行榜数据。

        Returns:
            排行榜数据字典，结构由具体实现决定
        """
        pass

    @abstractmethod
    def find_model_rank(
        self,
        data: dict[str, Any],
        model_name: str
    ) -> dict[str, Any] | None:
        """在排行榜数据中查找模型排名。

        Args:
            data: 排行榜数据
            model_name: 模型名称

        Returns:
            包含 rank、score 等信息的字典，如果未找到返回 None
        """
        pass

    def normalize_model_name(self, name: str) -> str:
        """标准化模型名称以便进行匹配。

        Args:
            name: 原始模型名称

        Returns:
            标准化后的名称
        """
        # 移除常见的前缀和后缀
        name = name.lower().strip()

        # 移除版本号
        import re
        name = re.sub(r'-v\d+(\.\d+)*$', '', name)
        name = re.sub(r'\s+v\d+(\.\d+)*$', '', name)

        return name

    def match_model_names(self, name1: str, name2: str, threshold: float = 0.8) -> bool:
        """模糊匹配模型名称。

        Args:
            name1: 第一个名称
            name2: 第二个名称
            threshold: 匹配阈值（0-1），默认 0.8

        Returns:
            是否匹配
        """
        norm1 = self.normalize_model_name(name1)
        norm2 = self.normalize_model_name(name2)

        if norm1 == norm2:
            return True

        # 简单的子字符串匹配
        if norm1 in norm2 or norm2 in norm1:
            return True

        # 使用 Levenshtein 距离进行相似度匹配
        try:
            from difflib import SequenceMatcher
            ratio = SequenceMatcher(None, norm1, norm2).ratio()
            return ratio >= threshold
        except Exception:
            return False

    async def __aenter__(self):
        """异步上下文管理器进入。"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器退出。"""
        pass
