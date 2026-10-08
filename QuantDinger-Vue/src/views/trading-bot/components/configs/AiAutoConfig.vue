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
      :message="$t('trading-bot.aiAuto.configHint')"
    />

    <a-form-model-item :label="$t('trading-bot.aiAuto.humanMode')" prop="humanMode">
      <a-radio-group v-model="form.humanMode" @change="emit">
        <a-radio-button value="observe">{{ $t('trading-bot.aiAuto.modeObserve') }}</a-radio-button>
        <a-radio-button value="confirm">{{ $t('trading-bot.aiAuto.modeConfirm') }}</a-radio-button>
        <a-radio-button value="auto">{{ $t('trading-bot.aiAuto.modeAuto') }}</a-radio-button>
      </a-radio-group>
      <div class="field-hint">{{ $t('trading-bot.aiAuto.humanModeHint') }}</div>
    </a-form-model-item>

    <a-form-model-item :label="$t('trading-bot.aiAuto.useLlm')">
      <a-switch v-model="form.useLlm" @change="emit" />
      <div class="field-hint">{{ $t('trading-bot.aiAuto.useLlmHint') }}</div>
    </a-form-model-item>

    <a-form-model-item :label="$t('trading-bot.aiAuto.enableFundingArb')">
      <a-switch v-model="form.enableFundingArb" @change="emit" />
    </a-form-model-item>
    <a-form-model-item :label="$t('trading-bot.aiAuto.enableOpportunity')">
      <a-switch v-model="form.enableOpportunity" @change="emit" />
    </a-form-model-item>
    <a-form-model-item :label="$t('trading-bot.aiAuto.enableGrid')">
      <a-switch v-model="form.enableGrid" @change="emit" />
    </a-form-model-item>
    <a-form-model-item :label="$t('trading-bot.aiAuto.gridSimOnly')">
      <a-switch v-model="form.gridSimOnly" @change="emit" />
      <div class="field-hint">{{ $t('trading-bot.aiAuto.gridSimOnlyHint') }}</div>
    </a-form-model-item>

    <a-form-model-item :label="$t('trading-bot.aiAuto.fundingNotionalUsdt')" prop="fundingNotionalUsdt">
      <a-input-number
        v-model="form.fundingNotionalUsdt"
        :min="0"
        :step="10"
        style="width: 100%"
        @change="emit"
      />
      <div class="field-hint">{{ $t('trading-bot.aiAuto.fundingNotionalUsdtHint') }}</div>
    </a-form-model-item>

    <a-form-model-item :label="$t('trading-bot.aiAuto.maxDailyLossPct')" prop="maxDailyLossPct">
      <a-input-number
        v-model="form.maxDailyLossPct"
        :min="0.5"
        :max="20"
        :step="0.5"
        :precision="2"
        style="width: 100%"
        :formatter="v => `${v}%`"
        :parser="v => v.replace('%', '')"
        @change="emit"
      />
    </a-form-model-item>

    <a-form-model-item :label="$t('trading-bot.aiAuto.tickIntervalSec')" prop="tickIntervalSec">
      <a-input-number
        v-model="form.tickIntervalSec"
        :min="60"
        :max="86400"
        :step="60"
        style="width: 100%"
        @change="emit"
      />
    </a-form-model-item>

    <a-form-model-item :label="$t('trading-bot.aiAuto.regimeRefreshSec')" prop="regimeRefreshSec">
      <a-input-number
        v-model="form.regimeRefreshSec"
        :min="60"
        :max="86400"
        :step="60"
        style="width: 100%"
        @change="emit"
      />
      <div class="field-hint">{{ $t('trading-bot.aiAuto.regimeRefreshSecHint') }}</div>
    </a-form-model-item>
  </a-form-model>
</template>

<script>
export default {
  name: 'AiAutoConfig',
  props: {
    value: { type: Object, default: () => ({}) },
    initialCapital: { type: Number, default: null },
    marketType: { type: String, default: 'swap' }
  },
  data () {
    return {
      form: {
        humanMode: this.value.humanMode || 'observe',
        useLlm: this.value.useLlm != null ? this.value.useLlm : true,
        enableFundingArb: this.value.enableFundingArb != null ? this.value.enableFundingArb : true,
        enableOpportunity: this.value.enableOpportunity != null ? this.value.enableOpportunity : true,
        enableGrid: this.value.enableGrid != null ? this.value.enableGrid : true,
        gridSimOnly: this.value.gridSimOnly != null ? this.value.gridSimOnly : true,
        fundingNotionalUsdt: this.value.fundingNotionalUsdt != null ? this.value.fundingNotionalUsdt : 0,
        maxDailyLossPct: this.value.maxDailyLossPct != null ? this.value.maxDailyLossPct : 3,
        tickIntervalSec: this.value.tickIntervalSec != null ? this.value.tickIntervalSec : 300,
        regimeRefreshSec: this.value.regimeRefreshSec != null ? this.value.regimeRefreshSec : 900
      },
      rules: {
        humanMode: [{ required: true, message: this.$t('trading-bot.aiAuto.humanModeReq'), trigger: 'change' }],
        tickIntervalSec: [{ required: true, message: this.$t('trading-bot.aiAuto.tickIntervalSecReq'), trigger: 'change' }]
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
