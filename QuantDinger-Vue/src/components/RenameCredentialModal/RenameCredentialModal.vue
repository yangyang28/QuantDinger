<template>
  <a-modal
    :title="$t('profile.exchange.renameTitle')"
    :visible="visible"
    :confirm-loading="saving"
    :ok-text="$t('common.save')"
    :cancel-text="$t('common.cancel')"
    :mask-closable="false"
    width="440px"
    @ok="handleSave"
    @cancel="handleCancel"
  >
    <div v-if="credential" class="rename-cred-meta">
      <span class="rename-cred-exchange">{{ exchangeLabel }}</span>
      <span v-if="credential.api_key_hint" class="rename-cred-hint">{{ credential.api_key_hint }}</span>
    </div>
    <p class="rename-cred-hint-text">{{ $t('profile.exchange.renameHint') }}</p>
    <a-form-item :label="$t('profile.exchange.accountName')" :label-col="{ span: 24 }" :wrapper-col="{ span: 24 }">
      <a-input
        v-model="nameInput"
        :placeholder="$t('profile.exchange.accountNamePlaceholder')"
        :max-length="128"
        allow-clear
        @pressEnter="handleSave"
      />
    </a-form-item>
  </a-modal>
</template>

<script>
import { updateExchangeCredentialName } from '@/api/credentials'
import { getExchangeDisplayName } from '@/utils/exchangeCredential'

export default {
  name: 'RenameCredentialModal',
  props: {
    visible: { type: Boolean, default: false },
    credential: { type: Object, default: null }
  },
  data () {
    return {
      nameInput: '',
      saving: false
    }
  },
  computed: {
    exchangeLabel () {
      if (!this.credential) return ''
      return getExchangeDisplayName(this.credential.exchange_id)
    }
  },
  watch: {
    visible (open) {
      if (open && this.credential) {
        this.nameInput = (this.credential.name && String(this.credential.name).trim()) || ''
      }
      if (!open) {
        this.nameInput = ''
        this.saving = false
      }
    },
    credential: {
      immediate: true,
      handler (cred) {
        if (this.visible && cred) {
          this.nameInput = (cred.name && String(cred.name).trim()) || ''
        }
      }
    }
  },
  methods: {
    handleCancel () {
      this.$emit('update:visible', false)
    },
    async handleSave () {
      if (!this.credential || !this.credential.id) return
      this.saving = true
      try {
        const res = await updateExchangeCredentialName({
          id: this.credential.id,
          name: (this.nameInput || '').trim()
        })
        if (res && res.code === 1) {
          this.$message.success(this.$t('profile.exchange.renameSuccess'))
          this.$emit('update:visible', false)
          this.$emit('success', res.data)
        } else {
          this.$message.error((res && res.msg) || this.$t('profile.exchange.renameFailed'))
        }
      } catch (e) {
        this.$message.error((e && e.message) || this.$t('profile.exchange.renameFailed'))
      } finally {
        this.saving = false
      }
    }
  }
}
</script>

<style lang="less" scoped>
.rename-cred-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
  font-size: 13px;
}
.rename-cred-exchange {
  font-weight: 600;
  color: #1f1f1f;
}
.rename-cred-hint {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  color: #8c8c8c;
}
.rename-cred-hint-text {
  margin: 0 0 12px;
  font-size: 12px;
  color: #8c8c8c;
  line-height: 1.5;
}
</style>
