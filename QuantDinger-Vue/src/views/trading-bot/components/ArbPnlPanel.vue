<template>
  <div class="arb-pnl" :class="{ 'arb-pnl--dark': isDark }">
    <div class="arb-pnl__hero">
      <div class="arb-pnl__hero-top">
        <div class="arb-pnl__brand">
          <div class="arb-pnl__mark">QD</div>
          <div>
            <div class="arb-pnl__product">QuantDinger · Funding Arb</div>
            <div class="arb-pnl__strategy">
              {{ strategyName || '—' }}
              <span v-if="panel.symbol" class="arb-pnl__sym">{{ panel.symbol }}</span>
            </div>
          </div>
        </div>
        <div class="arb-pnl__hero-actions">
          <span class="arb-pnl__live" :class="{ 'is-ok': liveOk, 'is-bad': !liveOk }">
            <i class="arb-pnl__pulse" />
            {{ liveOk ? $t('trading-bot.arbPnl.live') : $t('trading-bot.arbPnl.stale') }}
          </span>
          <a-button size="small" class="arb-pnl__refresh" :loading="loading" @click="load">
            <a-icon type="reload" />
          </a-button>
          <slot name="actions" />
        </div>
      </div>

      <div class="arb-pnl__hero-metrics">
        <div class="arb-pnl__total">
          <div class="arb-pnl__total-label">{{ $t('trading-bot.arbPnl.totalPnl') }}</div>
          <div class="arb-pnl__total-value" :class="pnlTone(rt.total_pnl_usdt)">
            {{ formatSignedMoney(rt.total_pnl_usdt) }}
          </div>
          <div class="arb-pnl__total-sub">
            <span>{{ $t('trading-bot.arbPnl.asOf') }} {{ formatAsOf(panel.as_of) }}</span>
            <span v-if="rt.return_on_capital_pct != null">
              · ROI {{ formatPct(rt.return_on_capital_pct / 100) }}
            </span>
          </div>
        </div>
        <div class="arb-pnl__split">
          <div class="arb-pnl__chip">
            <span>{{ $t('trading-bot.arbPnl.unrealized') }}</span>
            <strong :class="pnlTone(rt.unrealized_pnl_usdt)">{{ formatSignedMoney(rt.unrealized_pnl_usdt) }}</strong>
          </div>
          <div class="arb-pnl__chip">
            <span>{{ $t('trading-bot.arbPnl.funding') }}</span>
            <strong :class="pnlTone(rt.cumulative_funding_est)">{{ formatSignedMoney(rt.cumulative_funding_est) }}</strong>
          </div>
          <div class="arb-pnl__chip">
            <span>{{ $t('trading-bot.arbPnl.realized') }}</span>
            <strong :class="pnlTone(rt.realized_pnl_usdt)">{{ formatSignedMoney(rt.realized_pnl_usdt) }}</strong>
          </div>
        </div>
      </div>
    </div>

    <div class="arb-pnl__grid">
      <div class="arb-pnl__card arb-pnl__card--proj">
        <div class="arb-pnl__card-head">
          <h4>{{ $t('trading-bot.arbPnl.projectionTitle') }}</h4>
          <a-tag color="orange">{{ $t('trading-bot.arbPnl.estimateTag') }}</a-tag>
        </div>
        <div class="arb-pnl__proj-row">
          <div>
            <div class="arb-pnl__muted">{{ $t('trading-bot.arbPnl.estMonthly') }}</div>
            <div class="arb-pnl__proj-val" :class="pnlTone(proj.estimated_monthly_usdt)">
              {{ formatSignedMoney(proj.estimated_monthly_usdt) }}
            </div>
          </div>
          <div>
            <div class="arb-pnl__muted">{{ $t('trading-bot.arbPnl.estYearly') }}</div>
            <div class="arb-pnl__proj-val" :class="pnlTone(proj.estimated_yearly_usdt)">
              {{ formatSignedMoney(proj.estimated_yearly_usdt) }}
            </div>
          </div>
          <div>
            <div class="arb-pnl__muted">{{ $t('trading-bot.arbPnl.fundingApr') }}</div>
            <div class="arb-pnl__proj-val">{{ formatPct((proj.funding_apr_pct || 0) / 100) }}</div>
          </div>
        </div>
        <div v-if="proj.run_rate_monthly_usdt != null" class="arb-pnl__runrate">
          {{ $t('trading-bot.arbPnl.runRate') }}:
          {{ formatSignedMoney(proj.run_rate_monthly_usdt) }} / mo ·
          {{ formatSignedMoney(proj.run_rate_yearly_usdt) }} / yr
        </div>
        <p class="arb-pnl__disclaimer">{{ proj.disclaimer || $t('trading-bot.arbPnl.disclaimer') }}</p>
      </div>

      <div class="arb-pnl__card">
        <div class="arb-pnl__card-head">
          <h4>{{ $t('trading-bot.arbPnl.positionTitle') }}</h4>
          <a-tag :color="statusColor">{{ statusLabel }}</a-tag>
        </div>
        <div class="arb-pnl__kv">
          <div><span>{{ $t('trading-bot.hedgeArb.fundingRate') }}</span><b>{{ formatFundingRate(rt.funding_rate) }}</b></div>
          <div><span>{{ $t('trading-bot.hedgeArb.basisPct') }}</span><b>{{ formatBasisPct(rt.basis_pct) }}</b></div>
          <div><span>{{ $t('trading-bot.hedgeArb.spotQty') }}</span><b>{{ formatQty(rt.spot_qty) }}</b></div>
          <div><span>{{ $t('trading-bot.hedgeArb.perpQty') }}</span><b>{{ formatQty(rt.perp_qty) }}</b></div>
          <div><span>{{ $t('trading-bot.arbPnl.spotNotional') }}</span><b>{{ formatMoney(rt.spot_notional_usdt) }}</b></div>
          <div><span>{{ $t('trading-bot.arbPnl.perpNotional') }}</span><b>{{ formatMoney(rt.perp_notional_usdt) }}</b></div>
          <div><span>{{ $t('trading-bot.hedgeArb.driftPct') }}</span><b>{{ formatBasisPct(rt.notional_drift_pct) }}</b></div>
          <div>
            <span>{{ $t('trading-bot.hedgeArb.qtyDriftPct') }}</span>
            <b>
              {{ formatBasisPct(rt.qty_drift_pct) }}
              <a-tag v-if="rt.qty_matched" color="green" size="small" style="margin-left:6px;">
                {{ $t('trading-bot.hedgeArb.qtyMatched') }}
              </a-tag>
            </b>
          </div>
        </div>
      </div>
    </div>

    <div class="arb-pnl__card arb-pnl__ledger">
      <div class="arb-pnl__card-head">
        <h4>{{ $t('trading-bot.arbPnl.ledgerTitle') }}</h4>
        <span class="arb-pnl__muted">{{ $t('trading-bot.arbPnl.ledgerHint') }}</span>
      </div>
      <a-table
        :columns="columns"
        :data-source="trades"
        :loading="loading"
        :pagination="{ pageSize: 8, size: 'small' }"
        size="small"
        rowKey="rowKey"
        :scroll="{ x: 960 }"
        :locale="{ emptyText: $t('trading-bot.arbPnl.emptyTrades') }"
      >
        <template slot="time" slot-scope="text">
          {{ formatTime(text) }}
        </template>
        <template slot="leg" slot-scope="text">
          <a-tag :color="text === 'spot' ? 'blue' : text === 'perp' ? 'geekblue' : 'default'">
            {{ legLabel(text) }}
          </a-tag>
        </template>
        <template slot="source" slot-scope="text, record">
          <div class="arb-pnl__src">
            <strong>{{ record.source_label || text }}</strong>
            <span class="arb-pnl__muted">{{ record.pnl_source }}</span>
          </div>
        </template>
        <template slot="side" slot-scope="text">
          <span :class="['arb-pnl__side', String(text).toLowerCase()]">{{ text || '—' }}</span>
        </template>
        <template slot="pnl" slot-scope="text">
          <span :class="pnlTone(text)">{{ formatSignedMoney(text) }}</span>
        </template>
      </a-table>
    </div>
  </div>
</template>

<script>
import { getHedgeArbPnl } from '@/api/strategy'
import { formatUserDateTime, formatBrowserLocalDateTime, getUserTimezoneFromStorage } from '@/utils/userTime'

export default {
  name: 'ArbPnlPanel',
  props: {
    strategyId: { type: Number, required: true },
    strategyName: { type: String, default: '' },
    isDark: { type: Boolean, default: false },
    autoRefreshMs: { type: Number, default: 10000 }
  },
  data () {
    return {
      loading: false,
      panel: {},
      timer: null
    }
  },
  computed: {
    rt () {
      return this.panel.realtime || {}
    },
    proj () {
      return this.panel.projection || {}
    },
    liveOk () {
      return this.panel.live_data_ok !== false
    },
    statusLabel () {
      const st = String(this.panel.bot_status || 'flat').toLowerCase()
      const map = {
        flat: this.$t('trading-bot.hedgeArb.statusFlat'),
        holding: this.$t('trading-bot.hedgeArb.statusHolding'),
        error: this.$t('trading-bot.hedgeArb.statusError')
      }
      return map[st] || st
    },
    statusColor () {
      const st = String(this.panel.bot_status || 'flat').toLowerCase()
      if (st === 'holding') return 'green'
      if (st === 'error') return 'red'
      return 'default'
    },
    trades () {
      const rows = Array.isArray(this.panel.trades) ? this.panel.trades : []
      return rows.map((r, i) => ({
        ...r,
        rowKey: r.id != null ? String(r.id) : `row-${i}`
      }))
    },
    columns () {
      return [
        {
          title: this.$t('trading-bot.arbPnl.colTime'),
          dataIndex: 'time',
          key: 'time',
          width: 170,
          scopedSlots: { customRender: 'time' }
        },
        {
          title: this.$t('trading-bot.arbPnl.colSource'),
          dataIndex: 'fill_source',
          key: 'source',
          width: 160,
          scopedSlots: { customRender: 'source' }
        },
        {
          title: this.$t('trading-bot.arbPnl.colLeg'),
          dataIndex: 'leg',
          key: 'leg',
          width: 90,
          scopedSlots: { customRender: 'leg' }
        },
        {
          title: this.$t('trading-bot.arbPnl.colSide'),
          dataIndex: 'side',
          key: 'side',
          width: 100,
          scopedSlots: { customRender: 'side' }
        },
        {
          title: this.$t('trading-assistant.table.price'),
          dataIndex: 'price',
          key: 'price',
          width: 110,
          customRender: (v) => this.formatPrice(v)
        },
        {
          title: this.$t('trading-assistant.table.amount'),
          dataIndex: 'amount',
          key: 'amount',
          width: 100,
          customRender: (v) => this.formatQty(v)
        },
        {
          title: this.$t('trading-bot.arbPnl.colPnl'),
          dataIndex: 'net_pnl',
          key: 'pnl',
          width: 120,
          scopedSlots: { customRender: 'pnl' }
        }
      ]
    }
  },
  watch: {
    strategyId: {
      immediate: true,
      handler (id) {
        if (id) {
          this.load()
          this.startTimer()
        }
      }
    }
  },
  beforeDestroy () {
    this.clearTimer()
  },
  methods: {
    startTimer () {
      this.clearTimer()
      if (this.autoRefreshMs > 0) {
        this.timer = setInterval(() => this.load(true), this.autoRefreshMs)
      }
    },
    clearTimer () {
      if (this.timer) {
        clearInterval(this.timer)
        this.timer = null
      }
    },
    async load (silent) {
      if (!this.strategyId) return
      if (!silent) this.loading = true
      try {
        const lang = String(this.$i18n?.locale || 'zh').toLowerCase().startsWith('zh') ? 'zh' : 'en'
        const res = await getHedgeArbPnl(this.strategyId, { lang, limit: 200 })
        if (res && (res.code === 1 || res.code === 200) && res.data) {
          this.panel = res.data
          this.$emit('loaded', res.data)
        }
      } catch (e) {
        if (!silent) {
          this.$message.error(e?.message || this.$t('trading-bot.hedgeArb.actionFail'))
        }
      } finally {
        this.loading = false
      }
    },
    pnlTone (v) {
      const n = parseFloat(v || 0)
      if (n > 0) return 'is-profit'
      if (n < 0) return 'is-loss'
      return ''
    },
    formatSignedMoney (v) {
      const n = parseFloat(v || 0)
      if (!isFinite(n)) return '—'
      const sign = n > 0 ? '+' : n < 0 ? '-' : ''
      return `${sign}$${Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    },
    formatMoney (v) {
      const n = parseFloat(v || 0)
      if (!isFinite(n)) return '—'
      return `$${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    },
    formatPct (ratio) {
      const n = parseFloat(ratio || 0) * 100
      if (!isFinite(n)) return '—'
      return `${n.toFixed(2)}%`
    },
    formatFundingRate (v) {
      const n = parseFloat(v || 0)
      if (!isFinite(n)) return '—'
      return `${(n * 100).toFixed(4)}%`
    },
    formatBasisPct (v) {
      const n = parseFloat(v || 0)
      if (!isFinite(n)) return '—'
      return `${(n * 100).toFixed(3)}%`
    },
    formatQty (v) {
      const n = parseFloat(v || 0)
      if (!isFinite(n) || Math.abs(n) < 1e-12) return '0'
      if (Math.abs(n) >= 1) return n.toFixed(4)
      return n.toPrecision(4)
    },
    formatPrice (v) {
      const n = parseFloat(v || 0)
      if (!isFinite(n) || n === 0) return '—'
      if (n >= 1000) return n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
      if (n >= 1) return n.toFixed(4)
      return n.toPrecision(6)
    },
    formatTime (ts) {
      if (ts == null || ts === '') return '—'
      try {
        const tz = getUserTimezoneFromStorage && getUserTimezoneFromStorage()
        if (tz && formatUserDateTime) return formatUserDateTime(ts, tz)
        if (formatBrowserLocalDateTime) return formatBrowserLocalDateTime(ts)
      } catch (e) { /* fall through */ }
      const d = typeof ts === 'number' ? new Date(ts * (ts < 1e12 ? 1000 : 1)) : new Date(ts)
      if (isNaN(d.getTime())) return String(ts)
      return d.toLocaleString()
    },
    formatAsOf (iso) {
      if (!iso) return '—'
      try {
        return new Date(iso).toLocaleString()
      } catch (e) {
        return iso
      }
    },
    legLabel (leg) {
      if (leg === 'spot') return this.$t('trading-bot.arbPnl.legSpot')
      if (leg === 'perp') return this.$t('trading-bot.arbPnl.legPerp')
      return leg || '—'
    }
  }
}
</script>

<style lang="less" scoped>
.arb-pnl {
  --arb-ink: #0f1c2e;
  --arb-muted: #5b6b7c;
  --arb-line: rgba(15, 28, 46, 0.08);
  --arb-panel: #f7f5f1;
  --arb-card: #ffffff;
  --arb-accent: #0f766e;
  --arb-accent-soft: rgba(15, 118, 110, 0.1);
  --arb-profit: #0f7a4a;
  --arb-loss: #b42318;
  font-family: "IBM Plex Sans", "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
  color: var(--arb-ink);
}

.arb-pnl--dark {
  --arb-ink: #e8eef6;
  --arb-muted: #9aabbd;
  --arb-line: rgba(232, 238, 246, 0.12);
  --arb-panel: #121a24;
  --arb-card: #1a2432;
  --arb-accent: #2dd4bf;
  --arb-accent-soft: rgba(45, 212, 191, 0.12);
  --arb-profit: #34d399;
  --arb-loss: #f87171;
}

.arb-pnl__hero {
  background:
    radial-gradient(1200px 280px at 10% -20%, rgba(15, 118, 110, 0.16), transparent 55%),
    linear-gradient(145deg, #0f1c2e 0%, #16324a 48%, #0f766e 140%);
  color: #f5f7fa;
  border-radius: 16px;
  padding: 20px 22px 18px;
  margin-bottom: 14px;
}

.arb-pnl__hero-top {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 18px;
}

.arb-pnl__brand {
  display: flex;
  gap: 12px;
  align-items: center;
}

.arb-pnl__mark {
  width: 42px;
  height: 42px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  letter-spacing: 0.04em;
  background: rgba(255, 255, 255, 0.12);
  border: 1px solid rgba(255, 255, 255, 0.18);
}

.arb-pnl__product {
  font-size: 12px;
  opacity: 0.78;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.arb-pnl__strategy {
  font-size: 18px;
  font-weight: 650;
  margin-top: 2px;
}

.arb-pnl__sym {
  margin-left: 8px;
  font-size: 13px;
  font-weight: 500;
  opacity: 0.75;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.1);
}

.arb-pnl__hero-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.arb-pnl__live {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.1);
  &.is-ok { color: #a7f3d0; }
  &.is-bad { color: #fecaca; }
}

.arb-pnl__pulse {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
  box-shadow: 0 0 0 0 currentColor;
  animation: arb-pulse 1.8s ease-out infinite;
}

@keyframes arb-pulse {
  0% { box-shadow: 0 0 0 0 rgba(167, 243, 208, 0.55); }
  70% { box-shadow: 0 0 0 8px rgba(167, 243, 208, 0); }
  100% { box-shadow: 0 0 0 0 rgba(167, 243, 208, 0); }
}

.arb-pnl__refresh {
  color: #fff !important;
  border-color: rgba(255, 255, 255, 0.28) !important;
  background: transparent !important;
}

.arb-pnl__hero-metrics {
  display: grid;
  grid-template-columns: minmax(220px, 1.1fr) minmax(260px, 1.4fr);
  gap: 16px;
  align-items: end;
}

@media (max-width: 860px) {
  .arb-pnl__hero-metrics { grid-template-columns: 1fr; }
}

.arb-pnl__total-label {
  font-size: 12px;
  opacity: 0.75;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.arb-pnl__total-value {
  font-family: "IBM Plex Mono", "SF Mono", Consolas, monospace;
  font-size: 36px;
  font-weight: 650;
  line-height: 1.15;
  margin: 4px 0;
  &.is-profit { color: #6ee7b7; }
  &.is-loss { color: #fca5a5; }
}

.arb-pnl__total-sub {
  font-size: 12px;
  opacity: 0.7;
}

.arb-pnl__split {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.arb-pnl__chip {
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 12px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  span { font-size: 11px; opacity: 0.72; }
  strong {
    font-family: "IBM Plex Mono", "SF Mono", Consolas, monospace;
    font-size: 15px;
    font-weight: 600;
    &.is-profit { color: #6ee7b7; }
    &.is-loss { color: #fca5a5; }
  }
}

.arb-pnl__grid {
  display: grid;
  grid-template-columns: 1.15fr 1fr;
  gap: 12px;
  margin-bottom: 12px;
}

@media (max-width: 960px) {
  .arb-pnl__grid { grid-template-columns: 1fr; }
}

.arb-pnl__card {
  background: var(--arb-card);
  border: 1px solid var(--arb-line);
  border-radius: 14px;
  padding: 14px 16px 12px;
}

.arb-pnl__card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 12px;
  h4 {
    margin: 0;
    font-size: 14px;
    font-weight: 650;
    color: var(--arb-ink);
  }
}

.arb-pnl__proj-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 10px;
}

.arb-pnl__proj-val {
  margin-top: 4px;
  font-family: "IBM Plex Mono", "SF Mono", Consolas, monospace;
  font-size: 18px;
  font-weight: 650;
  color: var(--arb-ink);
  &.is-profit { color: var(--arb-profit); }
  &.is-loss { color: var(--arb-loss); }
}

.arb-pnl__runrate {
  font-size: 12px;
  color: var(--arb-muted);
  margin-bottom: 8px;
}

.arb-pnl__disclaimer {
  margin: 0;
  font-size: 11px;
  line-height: 1.5;
  color: var(--arb-muted);
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--arb-accent-soft);
}

.arb-pnl__kv {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px 14px;
  > div {
    display: flex;
    justify-content: space-between;
    gap: 8px;
    padding: 7px 0;
    border-bottom: 1px dashed var(--arb-line);
    span { color: var(--arb-muted); font-size: 12px; }
    b { font-size: 13px; font-weight: 600; text-align: right; }
  }
}

.arb-pnl__ledger {
  margin-top: 0;
}

.arb-pnl__muted {
  color: var(--arb-muted);
  font-size: 12px;
}

.arb-pnl__src {
  display: flex;
  flex-direction: column;
  gap: 2px;
  strong { font-size: 12px; }
}

.arb-pnl__side {
  font-family: "IBM Plex Mono", monospace;
  font-size: 12px;
  text-transform: uppercase;
  &.buy, &.long { color: var(--arb-profit); }
  &.sell, &.short { color: var(--arb-loss); }
}

.is-profit { color: var(--arb-profit) !important; }
.is-loss { color: var(--arb-loss) !important; }
</style>
