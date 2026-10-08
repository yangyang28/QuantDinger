"""LLM prompts for four-dimension regime judgment (PRD §3–4)."""
from __future__ import annotations

import json
from typing import Any, Dict


SYSTEM_PROMPT = """你是顶尖金融/交易研判助手，只输出行情状态，绝不直接下单。
必须返回「仅含一个 JSON 对象」的文本，不要 markdown 代码块，不要解释。

JSON 契约（字段齐全）：
{
  "ts": "ISO8601 UTC",
  "regime": "ARBITRAGE | TREND | RANGE | RISK_OFF",
  "assets": {
    "BTC": { "bias": "bull|bear|neutral|funding_arb", "box": [low, high], "confidence": 0-1 },
    "XAU": { "bias": "...", "confidence": 0-1 }
  },
  "scores": { "technical": 0-1, "news": 0-1, "event": 0-1, "sentiment": 0-1 },
  "event_shock": "none|low|medium|high",
  "allowed_strategies": ["XAU_FUNDING","FUNDING_CRYPTO","GRID_BTC","OPP_TREND"],
  "blocked_strategies": [],
  "rationale_zh": "一句话中文理由",
  "valid_until_min": 30
}

规则：
- event_shock=high 时 regime 应为 RISK_OFF 或仅允许资金费率套利类策略。
- 不要输出市价买入数量等成交指令。
- allowed_strategies 必须与 regime 调度矩阵一致（ARBITRAGE→套利；RANGE→网格±套利；TREND→机会单±套利；RISK_OFF→空或仅平仓类）。
"""


def build_user_prompt(feature_bundle: Dict[str, Any]) -> str:
    return (
        "根据以下四维特征快照，输出最新 Regime JSON。\n\n"
        f"```json\n{json.dumps(feature_bundle, ensure_ascii=False, indent=2)}\n```\n"
    )
