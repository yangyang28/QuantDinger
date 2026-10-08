# AI 自动交易模块（`bot_type=ai_auto`）

将 [AI_AUTO_TRADING_PRD.md](./AI_AUTO_TRADING_PRD.md) 接入 QuantDinger：LLM 只产出结构化 Regime JSON，规则引擎负责策略调度与执行。

## 设计对齐

| PRD 原则 | 实现 |
| --- | --- |
| AI 不直接裸下单 | `auto_trading/ai_regime.py` 仅返回 `RegimeDecision`；下单只在 engines |
| 状态机优先 | `ARBITRAGE / TREND / RANGE / RISK_OFF` + 调度矩阵 |
| 硬风控不可覆盖 | `auto_trading/risk.py` + `kill_switch` |
| 人机共驾 | `human_mode`: `observe` / `confirm` / `auto` |
| 可复盘 | `qd_ai_auto_regime_snapshots` 持久化四维特征与决策 |

## 代码位置

```
backend_api_python/app/services/auto_trading/
  schema.py          # Regime JSON 契约
  prompts.py         # 主模型提示词
  features.py        # 四维特征采集
  ai_regime.py       # LLM / 规则回退
  risk.py / router.py
  engines/           # funding_arb → hedge_arb；opportunity 信号；grid 仿真
  orchestrator.py
  runner.py          # TradingExecutor tick 钩子
```

## 启用方式

1. 对已有库执行 `backend_api_python/migrations/ai_auto_trading.sql`（或重建库以应用 `init.sql`）。
2. 创建策略，`trading_config.bot_type = "ai_auto"`（可用模板 `ai_auto`）。
3. 建议先用 `human_mode=observe` + `use_llm=true/false` 跑通日志。
4. `human_mode=auto` 时才会驱动 `hedge_arb` 实盘腿；机会单/网格 MVP 仍以信号/仿真为主。

## API

- `GET /api/strategies/ai-auto/status?id=`
- `POST /api/strategies/ai-auto/tick` body: `{ "id": ..., "force_regime": true }`
- `POST /api/strategies/ai-auto/kill` body: `{ "id": ..., "enabled": true }`

## 表

- `qd_ai_auto_state` — 运行态
- `qd_ai_auto_regime_snapshots` — 研判快照
- `hedge_state` — 对冲对 FSM（与既有 `qd_hedge_arb_state` 并存，兼容运维 SQL）
