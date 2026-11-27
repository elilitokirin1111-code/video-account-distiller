"""Human-readable content-pillar normalization for public video metadata."""

from __future__ import annotations

import re
import unicodedata

from video_account_distiller.models import Video

OTHER_PILLAR = "其他主题"

_UNKNOWN_CONTENT_TYPES = frozenset(
    {
        "",
        "-",
        "--",
        "degraded",
        "n/a",
        "na",
        "nan",
        "none",
        "not available",
        "null",
        "other",
        "unclassified",
        "unknown",
        "unspecified",
        "其他",
        "其它",
        "无",
        "未知",
        "未分类",
        "未识别",
    }
)

_CONTENT_TYPE_ALIASES = {
    "banquet": "宴会与庆典",
    "celebration": "宴会与庆典",
    "event": "宴会与庆典",
    "宴会": "宴会与庆典",
    "婚宴": "宴会与庆典",
    "offer": "优惠与活动",
    "promotion": "优惠与活动",
    "campaign": "优惠与活动",
    "activity": "优惠与活动",
    "优惠": "优惠与活动",
    "活动": "优惠与活动",
    "food": "餐饮与菜品",
    "food dining": "餐饮与菜品",
    "dining": "餐饮与菜品",
    "catering": "餐饮与菜品",
    "restaurant": "餐饮与菜品",
    "餐饮": "餐饮与菜品",
    "美食": "餐饮与菜品",
    "菜品": "餐饮与菜品",
    "room": "客房与住宿",
    "rooms": "客房与住宿",
    "accommodation": "客房与住宿",
    "stay": "客房与住宿",
    "客房": "客房与住宿",
    "住宿": "客房与住宿",
    "service": "服务与幕后",
    "service process": "服务与幕后",
    "behind the scenes": "服务与幕后",
    "hotel introduction": "服务与幕后",
    "服务": "服务与幕后",
    "幕后": "服务与幕后",
    "emotion": "节日与情感",
    "family": "节日与情感",
    "festival": "节日与情感",
    "节日": "节日与情感",
    "情感": "节日与情感",
    "education": "知识与教程",
    "how to": "知识与教程",
    "tutorial": "知识与教程",
    "教程": "知识与教程",
    "知识": "知识与教程",
    "daily life": "人物与日常",
    "lifestyle": "人物与日常",
    "vlog": "人物与日常",
    "人物": "人物与日常",
    "日常": "人物与日常",
}

# A category score counts distinct, explicit phrases only. Longer phrases carry more
# weight so a precise signal such as “宝宝宴” wins over a generic word such as “饭”.
# Tuple order is the deterministic tie-breaker for hotel and catering accounts.
_PUBLIC_TEXT_RULES: tuple[tuple[str, dict[str, int]], ...] = (
    (
        "宴会与庆典",
        {
            "宝宝宴": 5,
            "百岁宴": 5,
            "订婚宴": 5,
            "升学宴": 5,
            "婚宴": 4,
            "宴席": 4,
            "酒席": 4,
            "婚礼": 3,
            "新娘": 3,
            "宴会布置": 3,
            "宴会": 2,
            "大喜的日子": 2,
        },
    ),
    (
        "优惠与活动",
        {
            "代金券": 5,
            "代金劵": 5,
            "考生福利": 5,
            "团购": 4,
            "下单": 4,
            "优惠": 4,
            "福利": 3,
            "折扣": 3,
            "特价": 3,
            "预订": 2,
            "活动": 2,
        },
    ),
    (
        "餐饮与菜品",
        {
            "地方特色美食": 5,
            "小食堂": 5,
            "预制菜": 4,
            "家常菜": 4,
            "酒店外摆": 4,
            "宴席菜": 4,
            "新娘餐": 4,
            "餐饮人": 3,
            "美食": 3,
            "菜品": 3,
            "快餐": 3,
            "大厨": 3,
            "鲅鱼": 3,
            "好吃": 2,
            "吃": 1,
            "菜": 1,
            "饭": 1,
        },
    ),
    (
        "客房与住宿",
        {
            "总统套房": 5,
            "家庭房": 4,
            "大床房": 4,
            "双床房": 4,
            "客房": 4,
            "住宿": 4,
            "入住": 3,
            "房型": 3,
            "套房": 3,
            "床品": 3,
            "房间": 2,
        },
    ),
    (
        "服务与幕后",
        {
            "幕后": 5,
            "后厨": 5,
            "服务流程": 5,
            "员工一家亲": 4,
            "接待": 3,
            "准备": 3,
            "细节": 3,
            "停车场": 3,
            "团建": 3,
            "员工": 2,
            "服务": 2,
            "流程": 2,
        },
    ),
    (
        "节日与情感",
        {
            "生日快乐": 5,
            "父亲节": 5,
            "母亲节": 5,
            "毕业快乐": 4,
            "高考祝福": 4,
            "节日快乐": 4,
            "妈妈": 3,
            "父亲": 3,
            "父爱": 3,
            "姐弟": 3,
            "家庭": 3,
            "幸福": 3,
            "生日": 3,
            "祝福": 3,
            "毕业": 2,
            "感恩": 2,
            "家人": 2,
            "爱": 1,
        },
    ),
    (
        "知识与教程",
        {
            "避坑指南": 5,
            "操作步骤": 5,
            "怎么安排": 4,
            "怎么选": 4,
            "如何": 4,
            "教程": 4,
            "攻略": 4,
            "科普": 4,
            "教你": 4,
            "避坑": 3,
            "技巧": 3,
            "知识": 3,
            "应该怎么": 3,
            "步骤": 2,
        },
    ),
    (
        "人物与日常",
        {
            "记录真实生活": 5,
            "记录生活": 4,
            "分享生活": 4,
            "姐弟日常": 4,
            "员工日常": 4,
            "日常": 3,
            "接班人": 3,
            "成长": 2,
            "旅行": 2,
            "在路上": 2,
        },
    ),
)


def _normalized_text(value: object) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip()


def _content_type_key(value: str) -> str:
    return re.sub(r"[\W_]+", " ", value.casefold()).strip()


def _is_meaningful_content_type(value: object) -> bool:
    raw = _normalized_text(value)
    if raw.casefold() in _UNKNOWN_CONTENT_TYPES:
        return False
    compact = re.sub(r"[\s._/\\-]+", "", raw)
    if not compact or compact.isdigit():
        return False
    if re.fullmatch(r"(?:type|category|content|aweme)?\d+", compact.casefold()):
        return False
    return any(character.isalnum() for character in compact)


def _infer_from_explicit_chinese_keywords(text: str) -> str | None:
    scores = [
        (sum(weight for keyword, weight in keywords.items() if keyword in text), pillar)
        for pillar, keywords in _PUBLIC_TEXT_RULES
    ]
    best_score = max((score for score, _pillar in scores), default=0)
    if best_score <= 0:
        return None
    return next(pillar for score, pillar in scores if score == best_score)


def infer_video_content_pillar(video: Video) -> tuple[str, bool]:
    """Return ``(human_readable_pillar, inferred_from_public_text)``.

    The function never inspects media, transcripts, or model output. When the
    crawler's ``content_type`` is a numeric/status placeholder, it conservatively
    derives a broad category from the public title, description, and hashtags.
    """

    content_type = _normalized_text(video.content_type)
    if _is_meaningful_content_type(content_type):
        alias = _CONTENT_TYPE_ALIASES.get(_content_type_key(content_type))
        if alias is not None:
            return alias, False
        inferred_alias = _infer_from_explicit_chinese_keywords(content_type)
        return (inferred_alias or content_type), False

    public_parts: list[str] = []
    seen: set[str] = set()
    for value in (video.title, video.description, *video.hashtags):
        normalized = _normalized_text(value).lstrip("#").strip()
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        public_parts.append(normalized)
    inferred = _infer_from_explicit_chinese_keywords(" ".join(public_parts))
    return inferred or OTHER_PILLAR, True


__all__ = ["OTHER_PILLAR", "infer_video_content_pillar"]
