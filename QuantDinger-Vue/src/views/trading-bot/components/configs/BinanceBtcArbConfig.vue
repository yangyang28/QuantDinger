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
      :message="$t('trading-bot.binanceBtcArb.configHint')"
    />

    <a-form-model-item :label="$t('trading-bot.binanceBtcArb.spotCapital')" prop="spotUsdt">
      <a-input-number
        v-model="form.spotUsdt"
        :min="10"
        :step="10"
        style="width: 100%"
        @change="onSpotChange"
      />
      <div class="field-hint">{{ $t('trading-bot.binanceBtcArb.spotCapitalHint') }}</div>
    </a-form-model-item>

    <a-form-model-item :label="$t('trading-bot.binanceBtcArb.contractCapital')" prop="perpNotionalUsdt">
      <a-input-number
        v-model="form.perpNotionalUsdt"
        :min="10"
        :step="10"
        style="width: 100%"
        @change="onPerpChange"
      />
      <div class="field-hint">{{ $t('trading-bot.binanceBtcArb.contractCapitalHint') }}</div>
    </a-form-model-item>

    <a-form-model-item :label="$t('trading-bot.binanceBtcArb.sync1to1')">
      <a-switch v-model="form.sync1to1" @change="onSyncToggle" />
      <span class="switch-text">{{ $t('trading-bot.binanceBtcArb.sync1to1Hint') }}</span>
    </a-form-model-item>

    <div class="align-preview">
      <div class="align-preview__title">{{ $t('trading-bot.binanceBtcArb.alignPreview') }}</div>
      <div class="align-preview__row">
        <span>{{ $t('trading-bot.binanceBtcArb.alignedNotional') }}</span>
        <strong>{{ formatMoney(alignedNotional) }}</strong>
      </div>
      <div class="align-preview__row">
        <span>{{ $t('trading-bot.binanceBtcArb.estTotalFee') }}</span>
        <strong class="fee">≈ {{ formatMoney(estTotalFee) }}</strong>
      </div>
      <div class="align-preview__row">
        <span>{{ $t('trading-bot.binanceBtcArb.estMargin') }}</span>
        <strong>{{ formatMoney(estMargin) }}</strong>
      </div>
    </div>

    <a-form-model-item :label="$t('trading-bot.binanceBtcArb.leverage')" prop="leverage">
      <a-input-number v-model="form.leverage" :min="1" :max="20" :step="1" style="width: 100%" @change="emit" />
    </a-form-model-item>
    <a-form-model-item :label="$t('trading-bot.binanceBtcArb.preExitPct')" prop="preExitPct">
      <a-input-number
        v-model="form.preExitPct"
        :min="0.1"
        :max="5"
        :step="0.05"
        :precision="2"
        style="width: 100%"
        :formatter="v => `${v}%`"
        :parser="v => v.replace('%', '')"
        @change="emit"
      />
      <div class="field-hint">{{ $t('trading-bot.binanceBtcArb.preExitPctHint') }}</div>
    </a-form-model-item>
    <a-form-model-item :label="$t('trading-bot.binanceBtcArb.tickIntervalSec')" prop="tickIntervalSec">
      <a-input-number v-model="form.tickIntervalSec" :min="5" :max="300" :step="5" style="width: 100%" @change="emit" />
    </a-form-model-item>
  </a-form-model>
</template>

<script>
const SPOT_FEE = 0.001
const PERP_FEE = 0.0005

export default {
  name: 'BinanceBtcArbConfig',
  props: {
    value: { type: Object, default: () => ({}) },
    initialCapital: { type: Number, default: null },
    marketType: { type: String, default: 'swap' }
  },
  data () {
    const spot = this.value.spotUsdt != null ? this.value.spotUsdt : 2000
    return {
      form: {
        spotUsdt: spot,
        perpNotionalUsdt: this.value.perpNotionalUsdt != null ? this.value.perpNotionalUsdt : spot,
        sync1to1: this.value.sync1to1 !== false,
        leverage: this.value.leverage != null ? this.value.leverage : 2,
        preExitPct: this.value.preExitPct != null ? this.value.preExitPct : 0.5,
        tickIntervalSec: this.value.tickIntervalSec != null ? this.value.tickIntervalSec : 10
      },
      rules: {
        spotUsdt: [{ required: true, type: 'number', min: 10, message: this.$t('trading-bot.binanceBtcArb.capitalReq'), trigger: 'change' }],
        perpNotionalUsdt: [{ required: true, type: 'number', min: 10, message: this.$t('trading-bot.binanceBtcArb.capitalReq'), trigger: 'change' }],
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
    estTotalFee () {
      return this.alignedNotional * (SPOT_FEE + PERP_FEE)
    },
    estMargin () {
      const lev = Math.max(1, parseFloat(this.form.leverage || 1))
      return (parseFloat(this.form.perpNotionalUsdt || 0) || 0) / lev
    }
  },
  methods: {
    onSpotChange () {
      if (this.form.sync1to1 && this.form.spotUsdt != null) this.form.perpNotionalUsdt = this.form.spotUsdt
      this.emit()
    },
    onPerpChange () {
      if (this.form.sync1to1 && this.form.perpNotionalUsdt != null) this.form.spotUsdt = this.form.perpNotionalUsdt
      this.emit()
    },
    onSyncToggle (on) {
      if (on && this.form.spotUsdt != null) this.form.perpNotionalUsdt = this.form.spotUsdt
      this.emit()
    },
    emit () {
      this.$emit('input', { ...this.form })
      this.$emit('change', { ...this.form })
    },
    formatMoney (v) {
      const n = parseFloat(v || 0)
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
  mounted () { this.emit() }
}
</script>

<style lang="less" scoped>
.field-hint { margin-top: 4px; font-size: 12px; color: #8c8c8c; line-height: 1.45; }
.switch-text { margin-left: 10px; color: #595959; font-size: 13px; }
.align-preview {
  margin: 0 0 18px; padding: 12px 14px; border-radius: 10px;
  background: linear-gradient(135deg, rgba(180, 83, 9, 0.06), rgba(15, 28, 46, 0.03));
  border: 1px solid rgba(180, 83, 9, 0.16);
}
.align-preview__title { font-weight: 650; margin-bottom: 8px; color: #0f1c2e; }
.align-preview__row {
  display: flex; justify-content: space-between; gap: 12px; padding: 4px 0; font-size: 13px; color: #595959;
  strong { color: #0f1c2e; }
  .fee { color: #b45309; }
}
</style>
