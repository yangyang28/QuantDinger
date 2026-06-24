// Script-strategy template catalog.
//
// Templates `trendFollowing`, `martingale`, `grid` and `dca` were intentionally
// removed because the "Trading Bot" page already offers wizard-based versions
// of the same four strategies (see `views/trading-bot/components/botScriptTemplates.js`).
//
// Signal-style templates (`meanReversion`, `breakout`, `rsiMeanReversion`, `macdCross`, etc.)
// were also removed — those belong in Indicator IDE + Indicator Signal Strategy.
// i18n labels under `trading-assistant.template.*` are kept for legacy display.
//
// What stays here are the "stateful" templates that genuinely cannot be
// expressed as a single-indicator signal strategy: trailing stops, scale-in
// ladders, take-profit ladders, etc.
const TEMPLATE_DEFINITIONS = [
  {
    key: 'trailingStop',
    icon: '🪤',
    accent: 'violet',
    code: `"""
Trailing Stop Strategy
Enter on EMA crossover, manage exits with a hard stop and a trailing stop
that arms only after a minimum profit threshold is reached.
"""

def on_init(ctx):
    ctx.fast_period = ctx.param('fast_period', 10)
    ctx.slow_period = ctx.param('slow_period', 30)
    ctx.position_pct = ctx.param('position_pct', 0.8)
    ctx.hard_stop_pct = ctx.param('hard_stop_pct', 0.025)
    ctx.trailing_stop_pct = ctx.param('trailing_stop_pct', 0.015)
    ctx.trailing_arm_pct = ctx.param('trailing_arm_pct', 0.02)
    ctx.peak_price = 0.0
    ctx.trailing_armed = False

def _ema(values, period):
    k = 2.0 / (period + 1)
    e = float(values[0])
    for v in values[1:]:
        e = float(v) * k + e * (1 - k)
    return e

def on_bar(ctx, bar):
    bars = ctx.bars(ctx.slow_period + 5)
    if len(bars) < ctx.slow_period:
        return
    closes = [b['close'] for b in bars]
    prev_fast = _ema(closes[:-1], ctx.fast_period)
    prev_slow = _ema(closes[:-1], ctx.slow_period)
    fast = _ema(closes, ctx.fast_period)
    slow = _ema(closes, ctx.slow_period)
    cross_up = prev_fast <= prev_slow and fast > slow
    price = bar['close']

    if not ctx.position and cross_up:
        qty = (ctx.equity * ctx.position_pct) / price
        ctx.open_long(amount=qty, price=price)
        ctx.peak_price = price
        ctx.trailing_armed = False
        ctx.log(f"BUY at {price:.2f}")
        return

    if ctx.position and ctx.position['side'] == 'long':
        entry = ctx.position['entry_price']
        ctx.peak_price = max(ctx.peak_price, price)
        pnl_pct = (price - entry) / entry

        if pnl_pct <= -ctx.hard_stop_pct:
            ctx.close_position()
            ctx.log(f"HARD STOP at {price:.2f} ({pnl_pct*100:.2f}%)")
            return

        if not ctx.trailing_armed and pnl_pct >= ctx.trailing_arm_pct:
            ctx.trailing_armed = True
            ctx.log(f"Trailing armed at {price:.2f}")

        if ctx.trailing_armed:
            trail_stop = ctx.peak_price * (1 - ctx.trailing_stop_pct)
            if price <= trail_stop:
                ctx.close_position()
                ctx.log(f"TRAILING STOP at {price:.2f} (peak {ctx.peak_price:.2f})")
`,
    params: [
      { name: 'fast_period', type: 'integer', default: 10, min: 2, max: 120, step: 1 },
      { name: 'slow_period', type: 'integer', default: 30, min: 5, max: 240, step: 1 },
      { name: 'position_pct', type: 'percent', default: 80, min: 5, max: 100, step: 1 },
      { name: 'hard_stop_pct', type: 'percent', default: 2.5, min: 0.1, max: 50, step: 0.1 },
      { name: 'trailing_stop_pct', type: 'percent', default: 1.5, min: 0.1, max: 50, step: 0.1 },
      { name: 'trailing_arm_pct', type: 'percent', default: 2, min: 0.1, max: 50, step: 0.1 }
    ]
  },
  {
    key: 'scaleInOnDip',
    icon: '🪜',
    accent: 'teal',
    code: `"""
Scale-in on dip Strategy
Build a position in tranches as price keeps falling below the entry,
then exit with a take-profit measured against the average cost.
"""

def on_init(ctx):
    ctx.entry_pct = ctx.param('entry_pct', 0.25)
    ctx.dip_step_pct = ctx.param('dip_step_pct', 0.02)
    ctx.max_layers = ctx.param('max_layers', 4)
    ctx.take_profit_pct = ctx.param('take_profit_pct', 0.04)
    ctx.hard_stop_pct = ctx.param('hard_stop_pct', 0.10)
    ctx.entry_anchor = 0.0
    ctx.layers = 0
    ctx.avg_cost = 0.0

def _trigger_open(ctx, bar):
    bars = ctx.bars(20)
    if len(bars) < 5:
        return False
    return bar['close'] < bars[-2]['close']

def on_bar(ctx, bar):
    price = bar['close']

    if not ctx.position:
        if _trigger_open(ctx, bar):
            qty = (ctx.equity * ctx.entry_pct) / price
            ctx.open_long(amount=qty, price=price)
            ctx.entry_anchor = price
            ctx.layers = 1
            ctx.avg_cost = price
            ctx.log(f"OPEN layer 1 at {price:.2f}")
        return

    if ctx.position['side'] != 'long':
        return

    entry = ctx.position['entry_price']
    pnl_pct = (price - entry) / entry

    if pnl_pct <= -ctx.hard_stop_pct:
        ctx.close_position()
        ctx.layers = 0
        ctx.log(f"HARD STOP at {price:.2f}")
        return

    next_trigger = ctx.entry_anchor * (1 - ctx.dip_step_pct * ctx.layers)
    if ctx.layers < ctx.max_layers and price <= next_trigger:
        qty = (ctx.equity * ctx.entry_pct) / price
        ctx.add_long(amount=qty, price=price)
        ctx.layers += 1
        ctx.avg_cost = (ctx.avg_cost * (ctx.layers - 1) + price) / ctx.layers
        ctx.log(f"SCALE IN layer {ctx.layers} at {price:.2f}, avg {ctx.avg_cost:.2f}")
        return

    if ctx.avg_cost > 0 and price >= ctx.avg_cost * (1 + ctx.take_profit_pct):
        ctx.close_position()
        ctx.log(f"TAKE PROFIT at {price:.2f} (avg {ctx.avg_cost:.2f})")
        ctx.layers = 0
`,
    params: [
      { name: 'entry_pct', type: 'percent', default: 25, min: 1, max: 100, step: 1 },
      { name: 'dip_step_pct', type: 'percent', default: 2, min: 0.1, max: 50, step: 0.1 },
      { name: 'max_layers', type: 'integer', default: 4, min: 1, max: 10, step: 1 },
      { name: 'take_profit_pct', type: 'percent', default: 4, min: 0.1, max: 100, step: 0.1 },
      { name: 'hard_stop_pct', type: 'percent', default: 10, min: 0.5, max: 90, step: 0.5 }
    ]
  },
  {
    key: 'takeProfitLadder',
    icon: '🎯',
    accent: 'amber',
    code: `"""
Take-Profit Ladder Strategy
Enter on EMA crossover, then partially close the position at three
ascending take-profit levels. A hard stop protects the runner.
"""

def on_init(ctx):
    ctx.fast_period = ctx.param('fast_period', 10)
    ctx.slow_period = ctx.param('slow_period', 30)
    ctx.position_pct = ctx.param('position_pct', 0.9)
    ctx.tp1_pct = ctx.param('tp1_pct', 0.02)
    ctx.tp2_pct = ctx.param('tp2_pct', 0.05)
    ctx.tp3_pct = ctx.param('tp3_pct', 0.10)
    ctx.tp1_close = ctx.param('tp1_close', 0.4)
    ctx.tp2_close = ctx.param('tp2_close', 0.4)
    ctx.hard_stop_pct = ctx.param('hard_stop_pct', 0.03)
    ctx.tp_hits = 0
    ctx.original_qty = 0.0

def _ema(values, period):
    k = 2.0 / (period + 1)
    e = float(values[0])
    for v in values[1:]:
        e = float(v) * k + e * (1 - k)
    return e

def on_bar(ctx, bar):
    bars = ctx.bars(ctx.slow_period + 5)
    if len(bars) < ctx.slow_period:
        return
    closes = [b['close'] for b in bars]
    prev_fast = _ema(closes[:-1], ctx.fast_period)
    prev_slow = _ema(closes[:-1], ctx.slow_period)
    fast = _ema(closes, ctx.fast_period)
    slow = _ema(closes, ctx.slow_period)
    cross_up = prev_fast <= prev_slow and fast > slow
    price = bar['close']

    if not ctx.position and cross_up:
        qty = (ctx.equity * ctx.position_pct) / price
        ctx.open_long(amount=qty, price=price)
        ctx.original_qty = qty
        ctx.tp_hits = 0
        ctx.log(f"BUY at {price:.2f}, qty {qty:.4f}")
        return

    if not (ctx.position and ctx.position['side'] == 'long'):
        return

    entry = ctx.position['entry_price']
    pnl_pct = (price - entry) / entry

    if pnl_pct <= -ctx.hard_stop_pct:
        ctx.close_position()
        ctx.tp_hits = 0
        ctx.log(f"HARD STOP at {price:.2f}")
        return

    if ctx.tp_hits == 0 and pnl_pct >= ctx.tp1_pct:
        sell_qty = ctx.original_qty * ctx.tp1_close
        ctx.close_long(amount=sell_qty, price=price)
        ctx.tp_hits = 1
        ctx.log(f"TP1 at {price:.2f}, closed {ctx.tp1_close*100:.0f}%")
    elif ctx.tp_hits == 1 and pnl_pct >= ctx.tp2_pct:
        sell_qty = ctx.original_qty * ctx.tp2_close
        ctx.close_long(amount=sell_qty, price=price)
        ctx.tp_hits = 2
        ctx.log(f"TP2 at {price:.2f}, closed {ctx.tp2_close*100:.0f}%")
    elif ctx.tp_hits == 2 and pnl_pct >= ctx.tp3_pct:
        ctx.close_position()
        ctx.tp_hits = 3
        ctx.log(f"TP3 at {price:.2f}, runner closed")
`,
    params: [
      { name: 'fast_period', type: 'integer', default: 10, min: 2, max: 120, step: 1 },
      { name: 'slow_period', type: 'integer', default: 30, min: 5, max: 240, step: 1 },
      { name: 'position_pct', type: 'percent', default: 90, min: 5, max: 100, step: 1 },
      { name: 'tp1_pct', type: 'percent', default: 2, min: 0.1, max: 100, step: 0.1 },
      { name: 'tp2_pct', type: 'percent', default: 5, min: 0.1, max: 100, step: 0.1 },
      { name: 'tp3_pct', type: 'percent', default: 10, min: 0.1, max: 200, step: 0.1 },
      { name: 'tp1_close', type: 'percent', default: 40, min: 5, max: 100, step: 1 },
      { name: 'tp2_close', type: 'percent', default: 40, min: 5, max: 100, step: 1 },
      { name: 'hard_stop_pct', type: 'percent', default: 3, min: 0.1, max: 50, step: 0.1 }
    ]
  }
]

function escapeForRegExp (value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/** UI stores percent params as 0–100 (e.g. 80 = 80%). Code uses 0–1 ratios. */
export function normalizePercentParamValue (raw) {
  const n = Number(raw)
  if (!Number.isFinite(n)) return null
  if (n > 0 && n <= 1) return n * 100
  return n
}

export function percentParamToRatio (value) {
  const n = normalizePercentParamValue(value)
  if (n == null) return 0
  return n / 100
}

function parsePythonLiteral (raw) {
  const text = String(raw == null ? '' : raw).trim()
  if (!text) return ''
  if (text === 'True') return true
  if (text === 'False') return false
  if (text === 'None') return null
  const quote = text[0]
  if ((quote === '"' || quote === "'") && text[text.length - 1] === quote) {
    return text.slice(1, -1)
  }
  const n = Number(text)
  return Number.isFinite(n) ? n : text
}

function isPercentParamName (name, value) {
  const key = String(name || '').toLowerCase()
  if (/(pct|percent|ratio|allocation|weight|position|take_profit|stop|arm|entry)/.test(key)) {
    return typeof value === 'number'
  }
  return false
}

function inferParamType (name, value) {
  if (typeof value === 'boolean') return 'boolean'
  if (isPercentParamName(name, value)) return 'percent'
  if (Number.isInteger(value)) return 'integer'
  if (typeof value === 'number') return 'number'
  return 'text'
}

function inferParamDefaults (name, value, type) {
  if (type === 'percent') {
    return {
      default: normalizePercentParamValue(value) ?? 0,
      min: 0,
      max: 100,
      step: 0.1
    }
  }
  if (type === 'integer') {
    const lowerName = String(name || '').toLowerCase()
    return {
      default: Number.isFinite(value) ? value : 1,
      min: lowerName.includes('period') || lowerName.includes('window') ? 1 : undefined,
      max: lowerName.includes('period') || lowerName.includes('window') ? 500 : undefined,
      step: 1
    }
  }
  if (type === 'number') {
    return {
      default: Number.isFinite(value) ? value : 0,
      step: 0.1
    }
  }
  return { default: value == null ? '' : value }
}

export function extractScriptParamsFromCode (code) {
  const source = String(code || '')
  const pattern = /ctx\.param\(\s*['"]([^'"]+)['"]\s*,\s*([^)\n]+)\)/g
  const seen = new Set()
  const params = []
  let match
  while ((match = pattern.exec(source)) !== null) {
    const name = String(match[1] || '').trim()
    if (!name || seen.has(name)) continue
    seen.add(name)
    const parsed = parsePythonLiteral(match[2])
    const type = inferParamType(name, parsed)
    params.push({
      name,
      type,
      ...inferParamDefaults(name, parsed, type)
    })
  }
  if (!params.length) return null
  return {
    key: '__code_params__',
    inferred: true,
    params
  }
}

function toPythonLiteral (value) {
  if (typeof value === 'boolean') {
    return value ? 'True' : 'False'
  }
  if (typeof value === 'number') {
    return Number.isFinite(value) ? String(value) : '0'
  }
  if (value === null || value === undefined) {
    return 'None'
  }
  return `'${String(value).replace(/\\/g, '\\\\').replace(/'/g, "\\'")}'`
}

export const SCRIPT_TEMPLATE_CATALOG = TEMPLATE_DEFINITIONS

export function getScriptTemplateByKey (key) {
  return TEMPLATE_DEFINITIONS.find(item => item.key === key) || null
}

export function buildTemplateParamValues (templateOrKey, overrides = {}) {
  const template = typeof templateOrKey === 'string' ? getScriptTemplateByKey(templateOrKey) : templateOrKey
  if (!template) return {}
  return template.params.reduce((acc, param) => {
    const raw = Object.prototype.hasOwnProperty.call(overrides, param.name)
      ? overrides[param.name]
      : param.default
    if (param.type === 'percent') {
      acc[param.name] = normalizePercentParamValue(raw) ?? param.default
    } else {
      acc[param.name] = raw
    }
    return acc
  }, {})
}

export function buildTemplateCode (templateOrKey, overrides = {}) {
  const template = typeof templateOrKey === 'string' ? getScriptTemplateByKey(templateOrKey) : templateOrKey
  if (!template) return ''
  const values = buildTemplateParamValues(template, overrides)
  return template.params.reduce((code, param) => {
    const stored = values[param.name]
    const codeValue = param.type === 'percent' ? percentParamToRatio(stored) : stored
    const literal = toPythonLiteral(codeValue)
    const pattern = new RegExp(`(ctx\\.param\\(['"]${escapeForRegExp(param.name)}['"],\\s*)([^\\)]+)(\\))`)
    return code.replace(pattern, `$1${literal}$3`)
  }, template.code)
}

export function buildScriptCodeWithParamValues (code, params = [], overrides = {}) {
  return (params || []).reduce((source, param) => {
    if (!param || !param.name) return source
    const stored = Object.prototype.hasOwnProperty.call(overrides, param.name)
      ? overrides[param.name]
      : param.default
    const codeValue = param.type === 'percent' ? percentParamToRatio(stored) : stored
    const literal = toPythonLiteral(codeValue)
    const pattern = new RegExp(`(ctx\\.param\\(\\s*['"]${escapeForRegExp(param.name)}['"]\\s*,\\s*)([^\\)\\n]+)(\\))`)
    return source.replace(pattern, `$1${literal}$3`)
  }, String(code || ''))
}
