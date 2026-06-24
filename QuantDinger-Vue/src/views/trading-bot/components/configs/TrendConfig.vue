<template>
  <a-form-model
    ref="form"
    :model="form"
    :rules="rules"
    :label-col="{ span: 8 }"
    :wrapper-col="{ span: 14 }"
  >
    <a-form-model-item :label="$t('trading-bot.trend.maPeriod')" prop="maPeriod">
      <a-input-number
        v-model="form.maPeriod"
        :min="5"
        :max="500"
        :step="1"
        style="width: 100%"
        @change="emit"
      />
    </a-form-model-item>
    <a-form-model-item :label="$t('trading-bot.trend.maType')">
      <a-select v-model="form.maType" @change="emit">
        <a-select-option value="EMA">EMA</a-select-option>
        <a-select-option value="SMA">SMA</a-select-option>
        <a-select-option value="WMA">WMA</a-select-option>
      </a-select>
    </a-form-model-item>
    <a-form-model-item :label="$t('trading-bot.trend.confirmBars')" prop="confirmBars">
      <a-input-number
        v-model="form.confirmBars"
        :min="1"
        :max="10"
        :step="1"
        style="width: 100%"
        @change="emit"
      />
    </a-form-model-item>
    <a-form-model-item :label="$t('trading-bot.trend.positionPct')" prop="positionPct">
      <a-slider
        v-model="form.positionPct"
        :min="5"
        :max="100"
        :step="5"
        :tipFormatter="v => `${v}%`"
        @change="emit"
      />
    </a-form-model-item>
    <a-form-model-item :label="$t('trading-bot.trend.direction')">
      <a-radio-group v-model="form.direction" @change="emit">
        <a-radio value="long">{{ $t('trading-bot.trend.longOnly') }}</a-radio>
        <a-radio value="short" :disabled="isSpotMarket">{{ $t('trading-bot.trend.shortOnly') }}</a-radio>
        <a-radio value="both" :disabled="isSpotMarket">{{ $t('trading-bot.trend.bothSides') }}</a-radio>
      </a-radio-group>
      <div v-if="isSpotMarket" class="direction-hint">Spot only supports long trend bots.</div>
    </a-form-model-item>
    <a-form-model-item :label="trailingTpSwitchLabel">
      <a-switch v-model="form.trailingTpEnabled" @change="emit" />
      <div class="direction-hint">{{ trailingTpSwitchHint }}</div>
    </a-form-model-item>
    <a-form-model-item
      v-if="form.trailingTpEnabled"
      :label="trailingTpActivationLabel"
      prop="trailingTpActivationPct"
    >
      <a-input-number
        v-model="form.trailingTpActivationPct"
        :min="0.1"
        :max="500"
        :step="0.5"
        style="width: 100%"
        :formatter="v => `${v}%`"
        :parser="v => v.replace('%', '')"
        @change="emit"
      />
      <div class="direction-hint">{{ trailingTpActivationHint }}</div>
    </a-form-model-item>
    <a-form-model-item
      v-if="form.trailingTpEnabled"
      :label="trailingTpCallbackLabel"
      prop="trailingTpCallbackPct"
    >
      <a-input-number
        v-model="form.trailingTpCallbackPct"
        :min="0.05"
        :max="50"
        :step="0.1"
        style="width: 100%"
        :formatter="v => `${v}%`"
        :parser="v => v.replace('%', '')"
        @change="emit"
      />
      <div class="direction-hint">{{ trailingTpCallbackHint }}</div>
    </a-form-model-item>
  </a-form-model>
</template>

<script>
export default {
  name: 'TrendConfig',
  props: {
    value: { type: Object, default: () => ({}) },
    initialCapital: { type: Number, default: null },
    marketType: { type: String, default: 'swap' }
  },
  data () {
    return {
      form: {
        maPeriod: this.value.maPeriod || 20,
        maType: this.value.maType || 'EMA',
        confirmBars: this.value.confirmBars || 2,
        positionPct: this.value.positionPct || 50,
        direction: this.value.direction || 'long',
        // Trailing take-profit. Disabled by default — the trend bot's exit
        // is driven by MA crossback, this is a *safety boost* that locks in
        // gains when the move runs further than the MA can react.
        trailingTpEnabled: this.value.trailingTpEnabled === true,
        // Activation: how far price has to run from the entry before peak
        // tracking starts. 5% is a reasonable default for crypto on 1h–4h.
        trailingTpActivationPct: this.value.trailingTpActivationPct != null
          ? this.value.trailingTpActivationPct
          : 5,
        // Callback: how much retracement from the peak triggers exit.
        // Keep it well below the activation threshold to avoid immediate exit.
        trailingTpCallbackPct: this.value.trailingTpCallbackPct != null
          ? this.value.trailingTpCallbackPct
          : 1
      },
      rules: {
        maPeriod: [{ required: true, message: this.$t('trading-bot.trend.maPeriodReq'), trigger: 'change' }],
        confirmBars: [{ required: true, message: this.$t('trading-bot.trend.confirmBarsReq'), trigger: 'change' }],
        positionPct: [{ required: true, message: this.$t('trading-bot.trend.positionPctReq'), trigger: 'change' }],
        trailingTpActivationPct: [{
          validator: (rule, value, callback) => {
            if (!this.form.trailingTpEnabled) return callback()
            const v = Number(value)
            if (!Number.isFinite(v) || v <= 0) {
              return callback(new Error(this.isZhLocale ? '请输入有效的激活涨幅' : 'Please enter a valid activation %'))
            }
            callback()
          },
          trigger: 'change'
        }],
        trailingTpCallbackPct: [{
          validator: (rule, value, callback) => {
            if (!this.form.trailingTpEnabled) return callback()
            const v = Number(value)
            if (!Number.isFinite(v) || v <= 0) {
              return callback(new Error(this.isZhLocale ? '请输入有效的回撤比例' : 'Please enter a valid callback %'))
            }
            if (v >= Number(this.form.trailingTpActivationPct || 0)) {
              return callback(new Error(this.isZhLocale
                ? '回撤比例应小于激活涨幅'
                : 'Callback % must be smaller than the activation %'))
            }
            callback()
          },
          trigger: 'change'
        }]
      }
    }
  },
  computed: {
    isSpotMarket () {
      return this.marketType === 'spot'
    },
    isZhLocale () {
      return String(this.$i18n?.locale || '').toLowerCase().startsWith('zh')
    },
    trailingTpSwitchLabel () {
      return this.isZhLocale ? '启用追踪止盈' : 'Trailing Take Profit'
    },
    trailingTpSwitchHint () {
      return this.isZhLocale
        ? '开启后，价格盈利突破激活阈值即开始追踪盈利峰值；当价格从峰值回撤指定比例后立即平仓（独立于均线反转）。'
        : 'When ON, once profit breaks the activation threshold the bot tracks the peak; it exits the moment price retraces by the callback % below (independent of MA crossback).'
    },
    trailingTpActivationLabel () {
      return this.isZhLocale ? '激活涨幅%' : 'Activation Profit %'
    },
    trailingTpActivationHint () {
      return this.isZhLocale
        ? '价格相对入场价的盈利突破此比例后，开始追踪峰值。'
        : 'Tracking starts once price profit (vs entry) crosses this %.'
    },
    trailingTpCallbackLabel () {
      return this.isZhLocale ? '回撤幅度%' : 'Callback %'
    },
    trailingTpCallbackHint () {
      return this.isZhLocale
        ? '激活后，价格从峰值回撤这么多比例时立即平仓。建议设得比激活涨幅小。'
        : 'Once activated, price retracing this much from the peak triggers exit. Keep below the activation %.'
    }
  },
  watch: {
    marketType: {
      immediate: true,
      handler (val) {
        if (val === 'spot' && this.form.direction !== 'long') {
          this.form.direction = 'long'
          this.emit()
        }
      }
    }
  },
  methods: {
    emit () {
      this.$emit('input', { ...this.form })
      this.$emit('change', { ...this.form })
    },
    validate () {
      return new Promise((resolve, reject) => {
        this.$refs.form.validate(valid => {
          valid ? resolve(this.form) : reject(new Error('validation failed'))
        })
      })
    }
  }
}
</script>

<style lang="less" scoped>
.direction-hint {
  margin-top: 6px;
  font-size: 12px;
  color: #8c8c8c;
}
</style>
