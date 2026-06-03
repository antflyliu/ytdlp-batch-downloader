from __future__ import annotations

from copy import deepcopy
from typing import Any

PLATFORM_DISPLAY_NAMES = {
    "wechat": "微信公众号",
    "xiaohongshu": "小红书",
    "toutiao": "今日头条",
    "baijiahao": "百度百家号",
    "juejin": "掘金",
    "zhihu": "知乎",
    "x": "X / Twitter",
    "reddit": "Reddit",
}


PLATFORM_STRATEGIES: dict[str, dict[str, Any]] = {
    "wechat": {
        "publish_mode": "draft",
        "output_contract": {
            "max_chars": 6000,
            "format": "long_article",
            "editorial_focus": "深度结构化解读",
            "required_sections": ["标题", "导语", "背景", "关键细节", "影响分析", "行动建议"],
        },
        "prompt_profile": {
            "platform_role": "公众号深度编辑",
            "audience": "关注行业、技术和产品趋势的中文读者",
            "tone": "稳健、克制、信息密度高",
            "structure": "先给结论，再拆背景、细节、影响和可执行建议",
            "review_checklist": ["事实核验", "来源授权", "AIGC 标识", "标题不过度夸张"],
        },
        "style_guidance": ["用清晰小标题组织长文", "避免标题党", "保留可追溯来源和边界"],
    },
    "xiaohongshu": {
        "publish_mode": "export",
        "output_contract": {
            "max_chars": 1000,
            "format": "note",
            "editorial_focus": "轻量知识卡片",
            "required_sections": ["开头钩子", "正文要点", "封面图文案", "标签"],
        },
        "prompt_profile": {
            "platform_role": "小红书知识笔记策划",
            "audience": "希望快速理解信息价值和操作方法的泛知识用户",
            "tone": "直接、有画面感、少术语",
            "structure": "用钩子开头，拆成 3-5 个可截图的要点",
            "review_checklist": ["事实核验", "体验真实性", "平台原生表达", "避免绝对化承诺"],
        },
        "style_guidance": ["封面图文案", "正文适合分卡片", "标签聚焦场景和主题"],
    },
    "toutiao": {
        "publish_mode": "export",
        "output_contract": {
            "max_chars": 5000,
            "format": "search_friendly_article",
            "editorial_focus": "新闻化解读",
            "required_sections": ["事件概述", "关键细节", "影响分析", "信息来源"],
        },
        "prompt_profile": {
            "platform_role": "资讯编辑",
            "audience": "关注热点和实用信息的中文读者",
            "tone": "客观、通俗、避免煽动",
            "structure": "先解释发生了什么，再说明为什么重要",
            "review_checklist": ["事实核验", "敏感词替换", "来源完整", "避免夸大"],
        },
        "style_guidance": ["标题包含核心事实", "段落短", "避免未经证实口吻"],
    },
    "baijiahao": {
        "publish_mode": "export",
        "output_contract": {
            "max_chars": 5000,
            "format": "search_friendly_article",
            "editorial_focus": "搜索友好解读",
            "required_sections": ["摘要", "背景", "细节", "结论"],
        },
        "prompt_profile": {
            "platform_role": "搜索内容编辑",
            "audience": "通过搜索进入的泛知识读者",
            "tone": "清楚、稳健、少情绪词",
            "structure": "围绕关键词组织解释型文章",
            "review_checklist": ["事实核验", "SEO 关键词自然度", "平台规则", "AIGC 标识"],
        },
        "style_guidance": ["关键词自然出现", "结论明确", "减少口语化跳跃"],
    },
    "juejin": {
        "publish_mode": "export",
        "output_contract": {
            "max_chars": 6000,
            "format": "technical_article",
            "editorial_focus": "工程实践复盘",
            "required_sections": ["问题", "方案与细节", "验证与坑点", "参考"],
        },
        "prompt_profile": {
            "platform_role": "技术社区作者",
            "audience": "开发者、架构师和工程团队",
            "tone": "技术准确、可复现、不营销",
            "structure": "围绕问题、实现、验证和坑点组织",
            "review_checklist": ["技术事实核验", "命令或代码可复现", "边界条件", "引用来源"],
        },
        "style_guidance": ["保留工程细节", "避免空泛观点", "明确验证方法"],
    },
    "zhihu": {
        "publish_mode": "export",
        "output_contract": {
            "max_chars": 6000,
            "format": "answer_or_article",
            "editorial_focus": "观点论证",
            "required_sections": ["核心观点", "依据", "反例或边界", "结论"],
        },
        "prompt_profile": {
            "platform_role": "知乎答主",
            "audience": "希望看到推理过程和边界讨论的读者",
            "tone": "理性、可辩护、少口号",
            "structure": "先回答，再用依据和边界支撑",
            "review_checklist": ["事实核验", "逻辑链完整", "引用来源", "避免带节奏"],
        },
        "style_guidance": ["提出明确判断", "解释为什么", "主动写出不确定性"],
    },
    "x": {
        "publish_mode": "export",
        "output_contract": {
            "max_items": 8,
            "max_chars_per_item": 260,
            "format": "thread",
            "editorial_focus": "短线程",
            "required_sections": ["首条结论", "分条证据", "行动或讨论问题"],
        },
        "prompt_profile": {
            "platform_role": "英文/双语短线程作者",
            "audience": "快速扫读技术与行业动态的读者",
            "tone": "清楚、克制、有信息增量",
            "structure": "每条只表达一个信息点，首条给结论",
            "review_checklist": ["事实核验", "字符长度", "链接可用", "避免断章取义"],
        },
        "style_guidance": ["每条独立可读", "少形容词", "结尾给讨论问题"],
    },
    "reddit": {
        "publish_mode": "export",
        "output_contract": {
            "max_chars": 4000,
            "format": "discussion_post",
            "editorial_focus": "社区讨论",
            "required_sections": ["背景", "关键问题", "个人观察", "讨论问题"],
        },
        "prompt_profile": {
            "platform_role": "Reddit 社区讨论发起者",
            "audience": "偏好真实问题和实践讨论的社区用户",
            "tone": "坦诚、具体、避免营销",
            "structure": "给上下文，说明困惑或经验，最后提问",
            "review_checklist": ["事实核验", "社区规则", "非推广口吻", "问题足够具体"],
        },
        "style_guidance": ["避免公关稿语气", "用问题引导讨论", "说明自己的实践语境"],
    },
}


DEFAULT_CONTENT_TARGETS = [
    (
        platform,
        PLATFORM_DISPLAY_NAMES.get(platform, platform),
        strategy["publish_mode"],
        strategy["output_contract"],
        strategy["prompt_profile"],
    )
    for platform, strategy in PLATFORM_STRATEGIES.items()
]


def get_platform_strategy(platform: str) -> dict[str, Any]:
    key = str(platform or "").strip()
    strategy = PLATFORM_STRATEGIES.get(key)
    if not strategy:
        strategy = {
            "publish_mode": "export",
            "output_contract": {"format": "article", "editorial_focus": "通用内容改写"},
            "prompt_profile": {
                "platform_role": "内容编辑",
                "audience": "目标平台读者",
                "tone": "清晰、准确",
                "structure": "标题、摘要、正文、发布前检查",
                "review_checklist": ["事实核验", "来源授权", "平台规则", "AIGC 标识"],
            },
            "style_guidance": ["保持信息准确", "适配平台语气", "保留审核边界"],
        }
    return deepcopy(strategy)
