"""平台配额比例分配器。

根据平台权重计算搜索配额和 top_k 槽位分配，确保多平台搜索结果的多元化。
"""

import math
from dataclasses import dataclass
from typing import Dict, List

TOTAL_SEARCH_COUNT = 40
XHS_WEIGHT = 0.4  # 小红书固定权重 40%
XHS_PLATFORM = "xiaohongshu"


@dataclass
class SlotAllocation:
    """单个平台的配额分配结果。"""
    platform: str
    search_count: int   # 该平台的搜索数量
    top_k_slots: int    # 该平台的 top_k 槽位数


class SlotAllocator:
    """平台配额比例分配器。"""

    @staticmethod
    def allocate(
        platforms: List[str],
        total: int = TOTAL_SEARCH_COUNT,
    ) -> Dict[str, SlotAllocation]:
        """
        计算各平台的搜索数量配额。

        规则:
        - 单平台: 全部 total 分配给该平台
        - 多平台: 小红书 40%, 其余均分 60%
        - 余数按权重降序依次补 1
        - 总和恒等于 total

        Args:
            platforms: 参与搜索的平台列表
            total: 总搜索数量，默认 40
        Returns:
            平台名 -> SlotAllocation 的映射
        """
        if not platforms:
            return {}

        # 单平台：全部分配
        if len(platforms) == 1:
            p = platforms[0]
            return {p: SlotAllocation(platform=p, search_count=total, top_k_slots=0)}

        # 多平台：计算权重
        has_xhs = XHS_PLATFORM in platforms
        other_platforms = [p for p in platforms if p != XHS_PLATFORM]
        num_others = len(other_platforms)

        # 计算每个平台的权重
        weights = {}  # type: Dict[str, float]
        if has_xhs:
            weights[XHS_PLATFORM] = XHS_WEIGHT
            other_weight = (1.0 - XHS_WEIGHT) / num_others if num_others > 0 else 0.0
            for p in other_platforms:
                weights[p] = other_weight
        else:
            # 没有小红书时，所有平台均分
            equal_weight = 1.0 / len(platforms)
            for p in platforms:
                weights[p] = equal_weight

        # floor 分配
        allocations = {}  # type: Dict[str, int]
        for p in platforms:
            allocations[p] = int(math.floor(total * weights[p]))

        # 计算余数
        remainder = total - sum(allocations.values())

        # 按权重降序补 1（权重相同时保持原始顺序）
        sorted_platforms = sorted(platforms, key=lambda p: weights[p], reverse=True)
        for i in range(remainder):
            allocations[sorted_platforms[i]] += 1

        return {
            p: SlotAllocation(platform=p, search_count=allocations[p], top_k_slots=0)
            for p in platforms
        }

    @staticmethod
    def allocate_top_k(
        allocations: Dict[str, SlotAllocation],
        top_k: int,
    ) -> Dict[str, int]:
        """
        按与搜索数量相同的比例分配 top_k 槽位。

        Args:
            allocations: allocate() 的输出
            top_k: 最终返回结果数量
        Returns:
            平台名 -> top_k 槽位数
        """
        if not allocations:
            return {}

        total_search = sum(a.search_count for a in allocations.values())
        if total_search == 0:
            return {p: 0 for p in allocations}

        # floor 分配
        slots = {}  # type: Dict[str, int]
        exact = {}  # type: Dict[str, float]
        for p, alloc in allocations.items():
            exact_val = top_k * alloc.search_count / total_search
            exact[p] = exact_val
            slots[p] = int(math.floor(exact_val))

        # 余数按小数部分降序补 1（最大余数法）
        remainder = top_k - sum(slots.values())
        sorted_platforms = sorted(
            allocations.keys(),
            key=lambda p: exact[p] - math.floor(exact[p]),
            reverse=True,
        )
        for i in range(remainder):
            slots[sorted_platforms[i % len(sorted_platforms)]] += 1

        return slots

    @staticmethod
    def redistribute(
        allocations: Dict[str, SlotAllocation],
        actual_counts: Dict[str, int],
        top_k: int,
    ) -> Dict[str, int]:
        """
        重新分配 top_k 槽位：当某平台实际返回结果少于配额时，
        将未使用的槽位按比例分配给有剩余结果的平台。

        Args:
            allocations: 原始分配
            actual_counts: 各平台实际返回的结果数量
            top_k: 最终返回结果数量
        Returns:
            平台名 -> 调整后的 top_k 槽位数
        """
        if not allocations:
            return {}

        # 先按比例分配初始 top_k 槽位
        initial_slots = SlotAllocator.allocate_top_k(allocations, top_k)

        # 将每个平台的槽位限制在实际返回数量内
        final_slots = {}  # type: Dict[str, int]
        unused = 0

        for p in allocations:
            actual = actual_counts.get(p, 0)
            assigned = initial_slots.get(p, 0)
            if actual < assigned:
                final_slots[p] = actual
                unused += assigned - actual
            else:
                final_slots[p] = assigned

        # 将未使用的槽位重新分配给有剩余结果的平台
        while unused > 0:
            # 找出有剩余容量的平台（实际返回数 > 当前分配槽位）
            eligible = [
                p for p in allocations
                if actual_counts.get(p, 0) > final_slots[p]
            ]
            if not eligible:
                break

            # 按搜索数量比例分配未使用的槽位
            total_search_eligible = sum(
                allocations[p].search_count for p in eligible
            )
            if total_search_eligible == 0:
                break

            distributed = 0
            for p in eligible:
                share = int(math.floor(
                    unused * allocations[p].search_count / total_search_eligible
                ))
                # 不超过该平台的剩余容量
                capacity = actual_counts.get(p, 0) - final_slots[p]
                add = min(share, capacity)
                final_slots[p] += add
                distributed += add

            if distributed == 0:
                # floor 分配后仍有余数，按搜索数量降序逐个补 1
                sorted_eligible = sorted(
                    eligible,
                    key=lambda p: allocations[p].search_count,
                    reverse=True,
                )
                for p in sorted_eligible:
                    if unused <= 0:
                        break
                    capacity = actual_counts.get(p, 0) - final_slots[p]
                    if capacity > 0:
                        final_slots[p] += 1
                        unused -= 1
                        distributed += 1
                if distributed == 0:
                    break
            else:
                unused -= distributed

        return final_slots
