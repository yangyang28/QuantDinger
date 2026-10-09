<template>
  <div class="bot-type-cards">
    <div class="section-header">
      <div>
        <div class="section-kicker">QuantDinger Strategies</div>
        <h3>{{ $t('trading-bot.createNew') }}</h3>
        <p class="section-desc">{{ $t('trading-bot.createNewDesc') }}</p>
      </div>
    </div>

    <div class="cards-grid">
      <div
        v-for="bot in botTypes"
        :key="bot.key"
        class="type-card"
        :class="'type-card--' + bot.key"
        @click="$emit('select', bot.key)"
      >
        <div class="card-top">
          <div class="card-icon" :style="{ background: bot.gradient }">
            <a-icon :type="bot.icon" />
          </div>
          <span class="tag" :class="bot.riskClass">{{ bot.riskLabel }}</span>
        </div>
        <div class="card-body">
          <div class="card-name">{{ bot.name }}</div>
          <div class="card-desc">{{ bot.desc }}</div>
        </div>
        <div class="card-footer">
          <span class="scene">{{ bot.scene }}</span>
          <span class="card-cta">
            {{ $t('trading-bot.ai.startBtn') }}
            <a-icon type="arrow-right" />
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { mapGetters } from 'vuex'

/** Client-facing products only — other bot types remain in codebase but hidden. */
const VISIBLE_BOT_KEYS = ['htx_earn_hedge', 'binance_btc_arb']

export default {
  name: 'BotTypeCards',
  computed: {
    ...mapGetters(['brokerMarketPolicy']),
    botTypeMarkets () {
      return (this.brokerMarketPolicy && this.brokerMarketPolicy.bot_type_markets) || {}
    },
    botTypes () {
      const catalog = {
        htx_earn_hedge: {
          key: 'htx_earn_hedge',
          name: this.$t('trading-bot.type.htx_earn_hedge'),
          desc: this.$t('trading-bot.type.htx_earn_hedgeDesc'),
          icon: 'bank',
          gradient: 'linear-gradient(135deg, #0f766e 0%, #115e59 100%)',
          riskLabel: this.$t('trading-bot.risk.high'),
          riskClass: 'high',
          scene: this.$t('trading-bot.scene.earnHedge')
        },
        binance_btc_arb: {
          key: 'binance_btc_arb',
          name: this.$t('trading-bot.type.binance_btc_arb'),
          desc: this.$t('trading-bot.type.binance_btc_arbDesc'),
          icon: 'transaction',
          gradient: 'linear-gradient(135deg, #b45309 0%, #f59e0b 100%)',
          riskLabel: this.$t('trading-bot.risk.medium'),
          riskClass: 'medium',
          scene: this.$t('trading-bot.scene.binanceBtcArb')
        }
      }
      return VISIBLE_BOT_KEYS.map(key => {
        const b = catalog[key]
        return {
          ...b,
          markets: this.botTypeMarkets[key] || ['Crypto']
        }
      }).filter(Boolean)
    }
  }
}
</script>

<style lang="less" scoped>
.bot-type-cards {
  --ink: #0f1c2e;
  --muted: #5b6b7c;
  --line: rgba(15, 28, 46, 0.08);
  --card: #fff;
  font-family: "IBM Plex Sans", "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
}

.section-header {
  margin-bottom: 18px;
  .section-kicker {
    font-size: 11px;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: #0f766e;
    font-weight: 650;
    margin-bottom: 4px;
  }
  h3 {
    font-size: 20px;
    font-weight: 700;
    margin: 0 0 4px;
    color: var(--ink);
  }
  .section-desc {
    font-size: 13px;
    color: var(--muted);
    margin: 0;
  }
}

.cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
}

.type-card {
  position: relative;
  padding: 22px;
  border-radius: 16px;
  background:
    radial-gradient(600px 180px at 100% 0%, rgba(15, 118, 110, 0.08), transparent 55%),
    var(--card);
  border: 1px solid var(--line);
  cursor: pointer;
  transition: transform 0.22s ease, box-shadow 0.22s ease, border-color 0.22s ease;
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: 196px;

  &:hover {
    transform: translateY(-4px);
    box-shadow: 0 16px 40px rgba(15, 28, 46, 0.1);
    border-color: rgba(15, 118, 110, 0.28);
    .card-cta { color: #0f766e; }
  }

  &--binance_btc_arb {
    background:
      radial-gradient(600px 180px at 100% 0%, rgba(245, 158, 11, 0.12), transparent 55%),
      var(--card);
    &:hover { border-color: rgba(180, 83, 9, 0.35); .card-cta { color: #b45309; } }
  }
}

.card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.card-icon {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 20px;
}

.card-name {
  font-size: 17px;
  font-weight: 700;
  color: var(--ink);
  margin-bottom: 6px;
}

.card-desc {
  font-size: 13px;
  line-height: 1.55;
  color: var(--muted);
}

.card-footer {
  margin-top: auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.scene {
  font-size: 12px;
  color: var(--muted);
  padding: 3px 8px;
  border-radius: 999px;
  background: rgba(15, 28, 46, 0.04);
}

.card-cta {
  font-size: 13px;
  font-weight: 650;
  color: var(--ink);
  display: inline-flex;
  align-items: center;
  gap: 4px;
  transition: color 0.2s;
}

.tag {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  font-weight: 650;
  &.high { background: rgba(180, 35, 24, 0.1); color: #b42318; }
  &.medium { background: rgba(180, 83, 9, 0.12); color: #b45309; }
  &.low { background: rgba(15, 122, 74, 0.1); color: #0f7a4a; }
}
</style>
