<template>
  <a-form-model
    ref="form"
    :model="form"
    :rules="rules"
    :label-col="{ span: 8 }"
    :wrapper-col="{ span: 14 }"
  >
    <a-alert
      type="info"
      show-icon
      style="margin-bottom: 16px;"
      :message="$t('trading-bot.htxEarnHedge.configHint')"
    />

    <a-form-model-item :label="$t('trading-bot.htxEarnHedge.spotCapital')" prop="spotUsdt">
      <a-input-number
        v-model="form.spotUsdt"
        :min="10"
        :step="10"
        style="width: 100%"
        :placeholder="$t('trading-bot.htxEarnHedge.capitalPh')"
        @change="onSpotChange"
      />
      <div class="field-hint">{{ $t('trading-bot.htxEarnHedge.spotCapitalHint') }}</div>
    </a-form-model-item>

    <a-form-model-item :label="$t('trading-bot.htxEarnHedge.contractCapital')" prop="perpNotionalUsdt">
      <a-input-number
        v-model="form.perpNotionalUsdt"
        :min="10"
        :step="10"
        style="width: 100%"
        :placeholder="$t('trading-bot.htxEarnHedge.capitalPh')"
        @change="onPerpChange"
      />
      <div class="field-hint">{{ $t('trading-bot.htxEarnHedge.contractCapitalHint') }}</div>
    </a-form-model-item>

    <a-form-model-item :label="$t('trading-bot.htxEarnHedge.sync1to1')">
      <a-switch v-model="form.sync1to1" @change="onSyncToggle" />
      <span class="switch-text">{{ $t('trading-bot.htxEarnHedge.sync1to1Hint') }}</span>
    </a-form-model-item>

    <div class="align-preview">
      <div class="align-preview__title">{{ $t('trading-bot.htxEarnHedge.alignPreview') }}</div>
      <div class="align-preview__row">
        <span>{{ $t('trading-bot.htxEarnHedge.alignedNotional') }}</span>
        <strong>{{ formatMoney(alignedNotional) }}</strong>
      </div>
      <div class="align-preview__row">
        <span>{{ $t('trading-bot.htxEarnHedge.estSpotFee') }}</span>
        <strong class="fee">≈ {{ formatMoney(estSpotFee) }}</strong>
      </div>
      <div class="align-preview__row">
        <span>{{ $t('trading-bot.htxEarnHedge.estPerpFee') }}</span>
        <strong class="fee">≈ {{ formatMoney(estPerpFee) }}</strong>
      </div>
      <div class="align-preview__row">
        <span>{{ $t('trading-bot.htxEarnHedge.estTotalFee') }}</span>
        <strong class="fee">≈ {{ formatMoney(estTotalFee) }}</strong>
      </div>
      <div class="align-preview__row">
        <span>{{ $t('trading-bot.htxEarnHedge.estMargin') }}</span>
        <strong>{{ formatMoney(estMargin) }}</strong>
      </div>
      <div class="field-hint" style="margin-top: 8px;">{{ $t('trading-bot.htxEarnHedge.feePreviewHint') }}</div>
    </div>

    <a-form-model-item :label="$t('trading-bot.htxEarnHedge.leverage')" prop="leverage">
      <a-input-number
        v-model="form.leverage"
        :min="1"
        :max="20"
        :step="1"
        style="width: 100%"
        @change="emit"
      />
    </a-form-model-item>
    <a-form-model-item :label="$t('trading-bot.htxEarnHedge.preRedeemPct')" prop="preRedeemPct">
      <a-input-number
        v-model="form.preRedeemPct"
        :min="0.1"
        :max="5"
        :step="0.05"
        :precision="2"
        style="width: 100%"
        :formatter="v => `${v}%`"
        :parser="v => v.replace('%', '')"
        @change="emit"
      />
      <div class="field-hint">{{ $t('trading-bot.htxEarnHedge.preRedeemPctHint') }}</div>
    </a-form-model-item>
    <a-form-model-item :label="$t('trading-bot.htxEarnHedge.tickIntervalSec')" prop="tickIntervalSec">
      <a-input-number
        v-model="form.tickIntervalSec"
        :min="5"
        :max="300"
        :step="5"
        style="width: 100%"
        @change="emit"
      />
    </a-form-model-item>
  </a-form-model>
</template>

<script>
const SPOT_FEE = 0.002
const PERP_FEE = 0.0005

export default {
  name: 'HtxEarnHedgeConfig',
  props: {
    value: { type: Object, default: () => ({}) },
    initialCapital: { type: Number, default: null },
    marketType: { type: String, default: 'swap' }
  },
  data () {
    const spot = this.value.spotUsdt != null ? this.value.spotUsdt : 2000
    const perp = this.value.perpNotionalUsdt != null ? this.value.perpNotionalUsdt : spot
    return {
      form: {
        spotUsdt: spot,
        perpNotionalUsdt: perp,
        sync1to1: this.value.sync1to1 !== false,
        leverage: this.value.leverage != null ? this.value.leverage : 2,
        preRedeemPct: this.value.preRedeemPct != null ? this.value.preRedeemPct : 0.5,
        tickIntervalSec: this.value.tickIntervalSec != null ? this.value.tickIntervalSec : 10
      },
      rules: {
        spotUsdt: [{ required: true, type: 'number', min: 10, message: this.$t('trading-bot.htxEarnHedge.capitalReq'), trigger: 'change' }],
        perpNotionalUsdt: [{ required: true, type: 'number', min: 10, message: this.$t('trading-bot.htxEarnHedge.capitalReq'), trigger: 'change' }],
        leverage: [{ required: true, type: 'number', min: 1, trigger: 'change' }]
      }
    }
  },
  computed: {
    alignedNotional () {
      const a = parseFloat(this.form.spotUsdt || 0)
      const b = parseFloat(this.form.perpNotionalUsdt || 0)
      if (!(a > 0) || !(b > 0)) return Math.max(a, b) || 0
      return Math.min(a, b)
    },
    estSpotFee () {
      return this.alignedNotional * SPOT_FEE
    },
    estPerpFee () {
      return this.alignedNotional * PERP_FEE
    },
    estTotalFee () {
      return this.estSpotFee + this.estPerpFee
    },
    estMargin () {
      const lev = Math.max(1, parseFloat(this.form.leverage || 1))
      return (parseFloat(this.form.perpNotionalUsdt || 0) || 0) / lev
    }
  },
  methods: {
    onSpotChange () {
      if (this.form.sync1to1 && this.form.spotUsdt != null) {
        this.form.perpNotionalUsdt = this.form.spotUsdt
      }
      this.emit()
    },
    onPerpChange () {
      if (this.form.sync1to1 && this.form.perpNotionalUsdt != null) {
        this.form.spotUsdt = this.form.perpNotionalUsdt
      }
      this.emit()
    },
    onSyncToggle (on) {
      if (on && this.form.spotUsdt != null) {
        this.form.perpNotionalUsdt = this.form.spotUsdt
      }
      this.emit()
    },
    emit () {
      this.$emit('input', { ...this.form })
      this.$emit('change', { ...this.form })
    },
    formatMoney (v) {
      const n = parseFloat(v || 0)
      if (!isFinite(n)) return '—'
      return `${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} U`
    },
    validate () {
      return new Promise((resolve, reject) => {
        this.$refs.form.validate(valid => {
          valid ? resolve(this.form) : reject(new Error('validation failed'))
        })
      })
    }
  },
  mounted () {
    this.emit()
  }
}
</script>

<style lang="less" scoped>
.field-hint {
  margin-top: 4px;
  font-size: 12px;
  color: #8c8c8c;
  line-height: 1.45;
}
.switch-text {
  margin-left: 10px;
  color: #595959;
  font-size: 13px;
}
.align-preview {
  margin: 0 0 18px;
  padding: 12px 14px;
  border-radius: 10px;
  background: linear-gradient(135deg, rgba(15, 118, 110, 0.06), rgba(15, 28, 46, 0.04));
  border: 1px solid rgba(15, 118, 110, 0.14);
}
.align-preview__title {
  font-weight: 650;
  margin-bottom: 8px;
  color: #0f1c2e;
}
.align-preview__row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 4px 0;
  font-size: 13px;
  color: #595959;
  strong {
    color: #0f1c2e;
    font-variant-numeric: tabular-nums;
  }
  .fee { color: #b45309; }
}
</style>
