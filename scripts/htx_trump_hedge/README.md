# HTX TRUMP 对冲脚本（独立，不依赖 QuantDinger）

100% TRUMP 活期质押 + USDT 永续空单；**不挂止损**；mark 距强平价 ≤0.5% 时预赎回；被强平后市价卖现货并扫尾平仓。

## 策略逻辑

```text
deploy:  现货买入 TRUMP → 100% 申购活期 → 开 2x 空
run:     轮询 mark / 强平价 / 持仓
         ≤0.5% 强平距离 → 100% 赎回（PRE_REDEEMED）
         持仓骤降 / 强平 → 卖现货 + 平空（或 FALLBACK 赎回后卖）
         RECONCILING 循环直到 spot/earn/perp 清零
```

## 环境

```bash
cd scripts/htx_trump_hedge
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
copy config.example.yaml config.yaml
copy .env.example .env
# 编辑 .env 填入 HTX_API_KEY / HTX_API_SECRET
```

API 权限：现货交易、合约交易、赚币读写。HTX 合约账户建议 **联合保证金（V5）**。

## 命令

```bash
# 建仓（买现货、全质押、开空）
python main.py deploy --config config.yaml

# 常驻守护
python main.py run --config config.yaml

# 查看状态
python main.py status --config config.yaml

# 人工紧急全退
python main.py emergency-exit --config config.yaml
```

## 配置要点

| 项 | 说明 |
|----|------|
| `thresholds.pre_redeem_pct` | 距强平 0.5% 预赎回 |
| `thresholds.emergency_redeem_pct` | 0.25% 仍未赎回则紧急赎 |
| `thresholds.maintenance_pre_redeem_pct` | UTC+8 0 点维护窗内用 1% 提前赎 |
| `latency.poll_interval_critical_sec` | 接近强平时 100ms 轮询 |

## 风险

- 1～2 秒为设计目标，非 HTX SLA；跳空可能走 `LIQUIDATED_FALLBACK`。
- 真实资金请先小额度试跑 `deploy` → `status` → `emergency-exit` 测耗时。
- 勿将 `.env` / `config.yaml`（含密钥）提交 git。

## 目录

```text
htx/           HTX REST 签名与接口
strategy/      deploy、exit_fsm、reconcile、state
main.py        CLI 入口
```
