-- Apply on existing QuantDinger Postgres (idempotent).
-- Fresh installs already get these from init.sql.

CREATE TABLE IF NOT EXISTS qd_ai_auto_state (
    strategy_id INTEGER PRIMARY KEY REFERENCES qd_strategies_trading(id) ON DELETE CASCADE,
    status VARCHAR(24) NOT NULL DEFAULT 'idle',
    regime VARCHAR(24) NOT NULL DEFAULT 'RISK_OFF',
    human_mode VARCHAR(16) NOT NULL DEFAULT 'observe',
    last_regime_json JSONB DEFAULT '{}'::jsonb,
    last_plan_json JSONB DEFAULT '{}'::jsonb,
    last_error TEXT DEFAULT '',
    kill_switch BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ai_auto_state_regime ON qd_ai_auto_state(regime);

CREATE TABLE IF NOT EXISTS qd_ai_auto_regime_snapshots (
    id BIGSERIAL PRIMARY KEY,
    strategy_id INTEGER NOT NULL REFERENCES qd_strategies_trading(id) ON DELETE CASCADE,
    regime VARCHAR(24) NOT NULL,
    source VARCHAR(24) NOT NULL DEFAULT 'llm',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    features JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ai_auto_regime_sid_ts
    ON qd_ai_auto_regime_snapshots(strategy_id, created_at DESC);

CREATE TABLE IF NOT EXISTS hedge_state (
    id SERIAL PRIMARY KEY,
    pair_id VARCHAR(50) UNIQUE NOT NULL DEFAULT 'BTC_USDT_HEDGE',
    side_status VARCHAR(20) DEFAULT 'IDLE',
    is_hedged BOOLEAN DEFAULT FALSE,
    symbol VARCHAR(20) DEFAULT 'BTC/USDT',
    target_qty NUMERIC(18,8) DEFAULT 0,
    spot_qty NUMERIC(18,8) DEFAULT 0,
    futures_qty NUMERIC(18,8) DEFAULT 0,
    entry_rate NUMERIC(18,8) DEFAULT 0,
    entry_price NUMERIC(18,2) DEFAULT 0,
    spot_filled BOOLEAN DEFAULT FALSE,
    futures_filled BOOLEAN DEFAULT FALSE,
    updated_at TIMESTAMP DEFAULT NOW()
);
INSERT INTO hedge_state (pair_id) VALUES ('BTC_USDT_HEDGE')
ON CONFLICT (pair_id) DO NOTHING;
