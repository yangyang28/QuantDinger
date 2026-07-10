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
      :message="$t('trading-bot.hedgeArb.configHint')"
    />
    <a-form-model-item :label="$t('trading-bot.hedgeArb.spotQty')" prop="spotQty">
      <a-input-number
        v-model="form.spotQty"
        :min="0"
        :step="0.001"
        :precision="6"
        style="width: 100%"
        :placeholder="$t('trading-bot.hedgeArb.spotQtyPh')"
        @change="emit"
      />
      <div class="field-hint">{{ $t('trading-bot.hedgeArb.spotQtyHint') }}</div>
    </a-form-model-item>
    <a-form-model-item :label="$t('trading-bot.hedgeArb.perpQty')" prop="perpQty">
      <a-input-number
        v-model="form.perpQty"
        :min="0"
        :step="0.001"
        :precision="6"
        style="width: 100%"
        :placeholder="$t('trading-bot.hedgeArb.perpQtyPh')"
        @change="emit"
      />
      <div class="field-hint">{{ $t('trading-bot.hedgeArb.perpQtyHint') }}</div>
    </a-form-model-item>
    <a-form-model-item :label="$t('trading-bot.hedgeArb.entryFundingRate')" prop="entryFundingRate">
      <a-input-number
        v-model="form.entryFundingRate"
        :min="0"
        :max="5"
        :step="0.001"
        :precision="4"
        style="width: 100%"
        :formatter="v => `${v}%`"
        :parser="v => v.replace('%', '')"
        @change="emit"
      />
      <div class="field-hint">{{ $t('trading-bot.hedgeArb.entryFundingRateHint') }}</div>
    </a-form-model-item>
    <a-form-model-item :label="$t('trading-bot.hedgeArb.exitFundingRate')" prop="exitFundingRate">
      <a-input-number
        v-model="form.exitFundingRate"
        :min="-1"
        :max="5"
        :step="0.001"
        :precision="4"
        style="width: 100%"
        :formatter="v => `${v}%`"
        :parser="v => v.replace('%', '')"
        @change="emit"
      />
    </a-form-model-item>
    <a-form-model-item :label="$t('trading-bot.hedgeArb.maxBasisPct')" prop="maxBasisPct">
      <a-input-number
        v-model="form.maxBasisPct"
        :min="0.01"
        :max="20"
        :step="0.1"
        :precision="2"
        style="width: 100%"
        :formatter="v => `${v}%`"
        :parser="v => v.replace('%', '')"
        @change="emit"
      />
    </a-form-model-item>
    <a-form-model-item :label="$t('trading-bot.hedgeArb.rebalanceThresholdPct')" prop="rebalanceThresholdPct">
      <a-input-number
        v-model="form.rebalanceThresholdPct"
        :min="0.5"
        :max="50"
        :step="0.5"
        :precision="2"
        style="width: 100%"
        :formatter="v => `${v}%`"
        :parser="v => v.replace('%', '')"
        @change="emit"
      />
    </a-form-model-item>
    <a-form-model-item :label="$t('trading-bot.hedgeArb.tickIntervalSec')" prop="tickIntervalSec">
      <a-input-number
        v-model="form.tickIntervalSec"
        :min="60"
        :max="86400"
        :step="60"
        style="width: 100%"
        @change="emit"
      />
      <div class="field-hint">{{ $t('trading-bot.hedgeArb.tickIntervalSecHint') }}</div>
    </a-form-model-item>
    <a-form-model-item :label="$t('trading-bot.hedgeArb.maxHoldHours')">
      <a-input-number
        v-model="form.maxHoldHours"
        :min="0"
        :max="720"
        :step="1"
        style="width: 100%"
        @change="emit"
      />
      <div class="field-hint">{{ $t('trading-bot.hedgeArb.maxHoldHoursHint') }}</div>
    </a-form-model-item>
  </a-form-model>
</template>

<script>
export default {
  name: 'HedgeArbConfig',
  props: {
    value: { type: Object, default: () => ({}) },
    initialCapital: { type: Number, default: null },
    marketType: { type: String, default: 'swap' }
  },
  data () {
    return {
      form: {
        spotQty: this.value.spotQty != null ? this.value.spotQty : 0.001,
        perpQty: this.value.perpQty != null ? this.value.perpQty : 0.001,
        notionalUsdt: this.value.notionalUsdt != null ? this.value.notionalUsdt : 0,
        entryFundingRate: this.value.entryFundingRate != null ? this.value.entryFundingRate : 0.01,
        exitFundingRate: this.value.exitFundingRate != null ? this.value.exitFundingRate : 0,
        maxBasisPct: this.value.maxBasisPct != null ? this.value.maxBasisPct : 0.5,
        rebalanceThresholdPct: this.value.rebalanceThresholdPct != null ? this.value.rebalanceThresholdPct : 2,
        tickIntervalSec: this.value.tickIntervalSec != null ? this.value.tickIntervalSec : 300,
        maxHoldHours: this.value.maxHoldHours != null ? this.value.maxHoldHours : 0
      },
      rules: {
        spotQty: [{ required: true, type: 'number', min: 0.000001, message: this.$t('trading-bot.hedgeArb.spotQtyReq'), trigger: 'change' }],
        perpQty: [{ required: true, type: 'number', min: 0.000001, message: this.$t('trading-bot.hedgeArb.perpQtyReq'), trigger: 'change' }],
        entryFundingRate: [{ required: true, message: this.$t('trading-bot.hedgeArb.entryFundingRateReq'), trigger: 'change' }],
        tickIntervalSec: [{ required: true, message: this.$t('trading-bot.hedgeArb.tickIntervalSecReq'), trigger: 'change' }]
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
  line-height: 1.4;
}
</style>
