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
    <a-form-model-item :label="$t('trading-bot.htxEarnHedge.spotUsdt')" prop="spotUsdt">
      <a-input-number
        v-model="form.spotUsdt"
        :min="10"
        :step="10"
        style="width: 100%"
        @change="emit"
      />
    </a-form-model-item>
    <a-form-model-item :label="$t('trading-bot.htxEarnHedge.perpNotionalUsdt')" prop="perpNotionalUsdt">
      <a-input-number
        v-model="form.perpNotionalUsdt"
        :min="10"
        :step="10"
        style="width: 100%"
        @change="emit"
      />
    </a-form-model-item>
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
export default {
  name: 'HtxEarnHedgeConfig',
  props: {
    value: { type: Object, default: () => ({}) },
    initialCapital: { type: Number, default: null },
    marketType: { type: String, default: 'swap' }
  },
  data () {
    return {
      form: {
        spotUsdt: this.value.spotUsdt != null ? this.value.spotUsdt : 200,
        perpNotionalUsdt: this.value.perpNotionalUsdt != null ? this.value.perpNotionalUsdt : 100,
        leverage: this.value.leverage != null ? this.value.leverage : 2,
        preRedeemPct: this.value.preRedeemPct != null ? this.value.preRedeemPct : 0.5,
        tickIntervalSec: this.value.tickIntervalSec != null ? this.value.tickIntervalSec : 10
      },
      rules: {
        spotUsdt: [{ required: true, type: 'number', min: 10, trigger: 'change' }],
        perpNotionalUsdt: [{ required: true, type: 'number', min: 10, trigger: 'change' }],
        leverage: [{ required: true, type: 'number', min: 1, trigger: 'change' }]
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
.field-hint {
  margin-top: 4px;
  font-size: 12px;
  color: #8c8c8c;
}
</style>
