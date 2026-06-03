<template>
  <div class="email-pipeline-page">
    <div class="page-header">
      <div>
        <div class="page-title">{{ t('emailPipeline.title') }}</div>
        <div class="page-desc">{{ t('emailPipeline.desc') }}</div>
      </div>
      <div class="page-actions">
        <NButton tertiary :loading="refreshingAll" @click="refreshAll(false)">
          {{ t('emailPipeline.refreshAll') }}
        </NButton>
      </div>
    </div>

    <div class="card email-pipeline-hero">
      <div class="email-pipeline-hero__content">
        <div class="email-pipeline-hero__eyebrow">{{ t('emailPipeline.heroEyebrow') }}</div>
        <div class="email-pipeline-hero__title">{{ t('emailPipeline.heroTitle') }}</div>
        <div class="email-pipeline-hero__desc">{{ t('emailPipeline.heroDesc') }}</div>
      </div>
      <div class="email-pipeline-metrics">
        <div class="email-pipeline-metric">
          <span class="email-pipeline-metric__label">{{ t('emailPipeline.metrics.accounts') }}</span>
          <strong>{{ accounts.length }}</strong>
        </div>
        <div class="email-pipeline-metric">
          <span class="email-pipeline-metric__label">{{ t('emailPipeline.metrics.messages') }}</span>
          <strong>{{ messageTotal }}</strong>
        </div>
        <div class="email-pipeline-metric">
          <span class="email-pipeline-metric__label">{{ t('emailPipeline.metrics.targets') }}</span>
          <strong>{{ targets.length }}</strong>
        </div>
        <div class="email-pipeline-metric">
          <span class="email-pipeline-metric__label">{{ t('emailPipeline.metrics.variants') }}</span>
          <strong>{{ variants.length }}</strong>
        </div>
      </div>
    </div>

    <div class="card outlook-email-card">
      <div class="outlook-email-card__main">
        <div class="card-title">
          <div class="card-title-icon email-pipeline-icon" aria-hidden="true">OE</div>
          <span>{{ t('emailPipeline.accounts.outlookPrimaryTitle') }}</span>
        </div>
        <div class="outlook-email-card__desc">{{ t('emailPipeline.accounts.outlookPrimaryDesc') }}</div>
        <div class="outlook-email-card__facts">
          <div>
            <span>{{ t('emailPipeline.accounts.outlookPrimaryEndpoint') }}</span>
            <strong>http://127.0.0.1:5000</strong>
          </div>
          <div>
            <span>{{ t('emailPipeline.accounts.outlookPrimaryFolder') }}</span>
            <strong>all</strong>
          </div>
          <div>
            <span>{{ t('emailPipeline.accounts.outlookPrimaryProtocols') }}</span>
            <strong>IMAP / OAuth / Graph</strong>
          </div>
        </div>
      </div>
      <div class="outlook-email-card__actions">
        <NButton type="primary" @click="openAccountModal()">
          {{ t('emailPipeline.accounts.addOutlookEmail') }}
        </NButton>
        <NButton tertiary @click="loadAccounts(false)">
          {{ t('emailPipeline.refreshSection') }}
        </NButton>
      </div>
    </div>

    <div class="card gmail-oauth-card">
      <div class="gmail-oauth-card__main">
        <div class="card-title">
          <div class="card-title-icon email-pipeline-icon" aria-hidden="true">G</div>
          <span>{{ t('emailPipeline.accounts.oauthTitle') }}</span>
        </div>
        <div class="gmail-oauth-card__desc">{{ t('emailPipeline.accounts.oauthDesc') }}</div>
        <div class="gmail-oauth-tags">
          <NTag :type="gmailOAuthStatus?.configured ? 'success' : 'warning'" :bordered="false">
            {{ gmailOAuthStatus?.configured ? t('emailPipeline.accounts.oauthConfigured') : t('emailPipeline.accounts.oauthNotConfigured') }}
          </NTag>
          <NTag :type="!selectedGmailAuthAccountId ? 'default' : gmailOAuthStatus?.read_authorized ? 'success' : 'default'" :bordered="false">
            {{ !selectedGmailAuthAccountId ? t('emailPipeline.accounts.readPending') : gmailOAuthStatus?.read_authorized ? t('emailPipeline.accounts.readAuthorized') : t('emailPipeline.accounts.readMissing') }}
          </NTag>
          <NTag :type="!selectedGmailAuthAccountId ? 'default' : gmailOAuthStatus?.send_authorized ? 'success' : 'default'" :bordered="false">
            {{ !selectedGmailAuthAccountId ? t('emailPipeline.accounts.sendPending') : gmailOAuthStatus?.send_authorized ? t('emailPipeline.accounts.sendAuthorized') : t('emailPipeline.accounts.sendMissing') }}
          </NTag>
        </div>
        <div class="gmail-oauth-meta">
          <span>{{ t('emailPipeline.accounts.redirectUri') }}: {{ gmailOAuthStatus?.redirect_uri || '—' }}</span>
          <span>{{ t('emailPipeline.accounts.scopes') }}: {{ scopeText(gmailOAuthStatus?.scopes) }}</span>
        </div>
      </div>
      <div class="gmail-oauth-actions">
        <NSelect
          v-model:value="selectedGmailAuthAccountId"
          :options="gmailAccountOptions"
          clearable
          :placeholder="t('emailPipeline.accounts.selectGmailAccount')"
          @update:value="() => loadGmailOAuthStatus(true)"
        />
        <NButton
          type="primary"
          :disabled="!gmailOAuthStatus?.configured"
          :loading="loadingGmailOAuthStatus || gmailOAuthStarting"
          @click="startGmailOAuth()"
        >
          {{ t('emailPipeline.accounts.authorizeGmail') }}
        </NButton>
        <RouterLink
          v-if="!gmailOAuthStatus?.configured"
          to="/settings-hub/ai"
          class="gmail-oauth-settings-link"
        >
          {{ t('emailPipeline.accounts.openOAuthSettings') }}
        </RouterLink>
      </div>
      <NAlert v-if="!gmailOAuthStatus?.configured" type="warning" :bordered="false" class="section-alert">
        {{ t('emailPipeline.accounts.oauthConfigHint') }}
      </NAlert>
      <NAlert v-else-if="!gmailAccountOptions.length" type="info" :bordered="false" class="section-alert">
        {{ t('emailPipeline.accounts.oauthAccountHint') }}
      </NAlert>
    </div>

    <div class="card">
      <div class="card-header">
        <div class="card-title">
          <div class="card-title-icon email-pipeline-icon" aria-hidden="true">邮</div>
          <span>{{ t('emailPipeline.accounts.title') }}</span>
        </div>
        <div class="actions">
          <NButton tertiary :loading="loadingAccounts" @click="loadAccounts(false)">
            {{ t('emailPipeline.refreshSection') }}
          </NButton>
          <NButton type="primary" @click="openAccountModal()">
            {{ t('emailPipeline.accounts.add') }}
          </NButton>
        </div>
      </div>

      <NAlert v-if="accountsError" type="warning" :bordered="false" class="section-alert">
        {{ accountsError }}
      </NAlert>

      <div class="section-toolbar">
        <NInput
          v-model:value="accountSearch"
          clearable
          :placeholder="t('emailPipeline.accounts.searchPlaceholder')"
        />
        <NSelect
          v-model:value="accountStatusFilter"
          :options="accountStatusOptions"
          clearable
          :placeholder="t('emailPipeline.accounts.statusFilter')"
        />
      </div>

      <div v-if="filteredAccounts.length" class="table-wrap">
        <NDataTable
          class="app-sticky-table"
          :columns="accountColumns"
          :data="filteredAccounts"
          :bordered="false"
          :row-key="(row: EmailAccount) => row.id"
          :scroll-x="1480"
          :max-height="520"
          striped
        />
      </div>
      <NEmpty v-else :description="t('emailPipeline.accounts.empty')" />
    </div>

    <div class="card">
      <div class="card-header">
        <div class="card-title">
          <div class="card-title-icon email-pipeline-icon" aria-hidden="true">信</div>
          <span>{{ t('emailPipeline.messages.title') }}</span>
        </div>
        <div class="actions">
          <NButton tertiary :loading="loadingMessages" @click="loadMessages(false)">
            {{ t('emailPipeline.refreshSection') }}
          </NButton>
          <NButton
            type="primary"
            :disabled="!checkedMessageIds.length"
            :loading="batchGenerating"
            @click="runBatchGenerate"
          >
            {{ t('emailPipeline.messages.batchGenerate') }}
          </NButton>
        </div>
      </div>

      <NAlert v-if="messagesError" type="warning" :bordered="false" class="section-alert">
        {{ messagesError }}
      </NAlert>

      <div class="section-toolbar section-toolbar--dense">
        <NSelect
          v-model:value="messageFilters.accountId"
          :options="accountSelectOptions"
          clearable
          :placeholder="t('emailPipeline.messages.accountFilter')"
        />
        <NSelect
          v-model:value="messageFilters.status"
          :options="messageStatusOptions"
          clearable
          :placeholder="t('emailPipeline.messages.statusFilter')"
        />
        <NInput
          v-model:value="messageFilters.q"
          clearable
          :placeholder="t('emailPipeline.messages.searchPlaceholder')"
          @keyup.enter="loadMessages(false)"
        />
        <NCheckboxGroup v-model:value="batchGeneratePlatforms" class="platform-checks">
          <NSpace size="small">
            <NCheckbox
              v-for="option in targetPlatformOptions"
              :key="String(option.value)"
              :value="String(option.value)"
            >
              {{ option.label }}
            </NCheckbox>
          </NSpace>
        </NCheckboxGroup>
      </div>

      <div v-if="messages.length" class="table-wrap">
        <NDataTable
          class="app-sticky-table"
          :columns="messageColumns"
          :data="messages"
          :bordered="false"
          :row-key="(row: EmailMessage) => row.id"
          :checked-row-keys="checkedMessageIds"
          :row-selection="messageRowSelection"
          :scroll-x="1700"
          :max-height="620"
          striped
        />
      </div>
      <NEmpty v-else :description="t('emailPipeline.messages.empty')" />

      <div class="section-pagination">
        <span>{{ t('emailPipeline.messages.total', { n: messageTotal }) }}</span>
        <NPagination
          v-model:page="messagePage"
          v-model:page-size="messagePageSize"
          :item-count="messageTotal"
          :page-sizes="[10, 20, 50, 100]"
          show-size-picker
          @update:page="loadMessages(true)"
          @update:page-size="handleMessagePageSizeChange"
        />
      </div>
    </div>

    <div class="card">
      <div class="card-header">
        <div class="card-title">
          <div class="card-title-icon email-pipeline-icon" aria-hidden="true">台</div>
          <span>{{ t('emailPipeline.targets.title') }}</span>
        </div>
        <div class="actions">
          <NButton tertiary :loading="loadingTargets" @click="loadTargets(false)">
            {{ t('emailPipeline.refreshSection') }}
          </NButton>
        </div>
      </div>

      <NAlert v-if="targetsError" type="warning" :bordered="false" class="section-alert">
        {{ targetsError }}
      </NAlert>

      <div v-if="targets.length" class="table-wrap">
        <NDataTable
          class="app-sticky-table"
          :columns="targetColumns"
          :data="targets"
          :bordered="false"
          :row-key="(row: ContentTarget) => row.id"
          :scroll-x="1180"
          :max-height="400"
          striped
        />
      </div>
      <NEmpty v-else :description="t('emailPipeline.targets.empty')" />
    </div>

    <div class="card">
      <div class="card-header">
        <div class="card-title">
          <div class="card-title-icon email-pipeline-icon" aria-hidden="true">稿</div>
          <span>{{ t('emailPipeline.variants.title') }}</span>
        </div>
        <div class="actions">
          <NButton tertiary :loading="loadingVariants" @click="loadVariants(false)">
            {{ t('emailPipeline.refreshSection') }}
          </NButton>
        </div>
      </div>

      <NAlert v-if="variantsError" type="warning" :bordered="false" class="section-alert">
        {{ variantsError }}
      </NAlert>

      <div class="section-toolbar section-toolbar--dense">
        <NSelect
          v-model:value="variantFilters.platform"
          :options="variantPlatformOptions"
          clearable
          :placeholder="t('emailPipeline.variants.platformFilter')"
        />
        <NInput
          v-model:value="variantFilters.sourceId"
          clearable
          :placeholder="t('emailPipeline.variants.sourceFilter')"
          @keyup.enter="loadVariants(false)"
        />
        <NSwitch v-model:value="variantFilters.includeBody" />
        <span class="switch-label">{{ t('emailPipeline.variants.includeBody') }}</span>
      </div>

      <div v-if="variants.length" class="table-wrap">
        <NDataTable
          class="app-sticky-table"
          :columns="variantColumns"
          :data="variants"
          :bordered="false"
          :row-key="(row: ContentVariant) => row.id"
          :scroll-x="1360"
          :max-height="520"
          striped
        />
      </div>
      <NEmpty v-else :description="t('emailPipeline.variants.empty')" />
    </div>

    <NModal
      v-model:show="showAccountModal"
      :block-scroll="false"
      preset="card"
      :title="editingAccount ? t('emailPipeline.accounts.edit') : t('emailPipeline.accounts.add')"
      style="width: min(860px, 96vw)"
      :mask-closable="false"
    >
      <NForm :model="accountForm" label-placement="top">
        <div class="form-grid">
          <NFormItem :label="t('emailPipeline.accounts.fields.provider')">
            <NSelect v-model:value="accountForm.provider" :options="providerOptions" />
          </NFormItem>
          <NFormItem :label="t('emailPipeline.accounts.fields.status')">
            <NSelect v-model:value="accountForm.status" :options="accountStatusOptions" />
          </NFormItem>
          <NFormItem :label="t('emailPipeline.accounts.fields.displayName')">
            <NInput v-model:value="accountForm.display_name" />
          </NFormItem>
          <NFormItem :label="t('emailPipeline.accounts.fields.emailAddress')">
            <NInput v-model:value="accountForm.email_address" />
          </NFormItem>
          <div v-if="accountForm.provider === 'gmail'" class="wide">
            <NAlert type="info" :bordered="false" class="section-alert">
              {{ t('emailPipeline.accounts.oauthFormHint') }}
            </NAlert>
          </div>
          <NFormItem v-if="accountForm.provider === 'imap'" :label="t('emailPipeline.accounts.fields.imapHost')">
            <NInput v-model:value="accountForm.imap_host" />
          </NFormItem>
          <NFormItem v-if="accountForm.provider === 'imap'" :label="t('emailPipeline.accounts.fields.imapPort')">
            <NInputNumber v-model:value="accountForm.imap_port" :show-button="false" style="width: 100%" />
          </NFormItem>
          <NFormItem v-if="accountForm.provider === 'imap'" :label="t('emailPipeline.accounts.fields.imapSecurity')">
            <NSelect v-model:value="accountForm.imap_security" :options="securityOptions" />
          </NFormItem>
          <NFormItem v-if="accountForm.provider === 'imap'" :label="t('emailPipeline.accounts.fields.imapUsername')">
            <NInput v-model:value="accountForm.imap_username" />
          </NFormItem>
          <NFormItem v-if="accountForm.provider === 'imap'" :label="t('emailPipeline.accounts.fields.imapPassword')">
            <NInput
              v-model:value="imapPasswordInput"
              type="password"
              show-password-on="click"
              :placeholder="secretPlaceholder(editingAccount?.has_imap_password)"
            />
          </NFormItem>
          <NFormItem v-if="accountForm.provider === 'imap'" :label="t('emailPipeline.accounts.fields.smtpHost')">
            <NInput v-model:value="accountForm.smtp_host" />
          </NFormItem>
          <NFormItem v-if="accountForm.provider === 'imap'" :label="t('emailPipeline.accounts.fields.smtpPort')">
            <NInputNumber v-model:value="accountForm.smtp_port" :show-button="false" style="width: 100%" />
          </NFormItem>
          <NFormItem v-if="accountForm.provider === 'imap'" :label="t('emailPipeline.accounts.fields.smtpSecurity')">
            <NSelect v-model:value="accountForm.smtp_security" :options="securityOptions" />
          </NFormItem>
          <NFormItem v-if="accountForm.provider === 'imap'" :label="t('emailPipeline.accounts.fields.smtpUsername')">
            <NInput v-model:value="accountForm.smtp_username" />
          </NFormItem>
          <NFormItem v-if="accountForm.provider === 'imap'" :label="t('emailPipeline.accounts.fields.smtpPassword')">
            <NInput
              v-model:value="smtpPasswordInput"
              type="password"
              show-password-on="click"
              :placeholder="secretPlaceholder(editingAccount?.has_smtp_password)"
            />
          </NFormItem>
          <NFormItem v-if="accountForm.provider === 'outlook_email'" :label="t('emailPipeline.accounts.fields.outlookEmailBaseUrl')">
            <NInput v-model:value="accountForm.outlook_email_base_url" placeholder="http://127.0.0.1:5000" />
          </NFormItem>
          <NFormItem v-if="accountForm.provider === 'outlook_email'" :label="t('emailPipeline.accounts.fields.outlookEmailApiKey')">
            <NInput
              v-model:value="outlookEmailApiKeyInput"
              type="password"
              show-password-on="click"
              :placeholder="secretPlaceholder(editingAccount?.has_outlook_email_api_key)"
            />
          </NFormItem>
          <NFormItem v-if="accountForm.provider === 'outlook_email'" :label="t('emailPipeline.accounts.fields.outlookEmailRemoteEmail')">
            <NInput v-model:value="accountForm.outlook_email_remote_email" />
          </NFormItem>
          <NFormItem v-if="accountForm.provider === 'outlook_email'" :label="t('emailPipeline.accounts.fields.outlookEmailFolder')">
            <NSelect v-model:value="accountForm.outlook_email_folder" :options="outlookEmailFolderOptions" />
          </NFormItem>
          <NFormItem v-if="accountForm.provider === 'outlook_email'" :label="t('emailPipeline.accounts.fields.outlookEmailSubjectContains')">
            <NInput v-model:value="accountForm.outlook_email_subject_contains" />
          </NFormItem>
          <NFormItem v-if="accountForm.provider === 'outlook_email'" :label="t('emailPipeline.accounts.fields.outlookEmailFromContains')">
            <NInput v-model:value="accountForm.outlook_email_from_contains" />
          </NFormItem>
          <NFormItem v-if="accountForm.provider === 'outlook_email'" :label="t('emailPipeline.accounts.fields.outlookEmailKeyword')">
            <NInput v-model:value="accountForm.outlook_email_keyword" />
          </NFormItem>
          <NFormItem :label="t('emailPipeline.accounts.fields.syncMode')">
            <NSelect v-model:value="accountForm.sync_mode" :options="syncModeOptions" />
          </NFormItem>
          <NFormItem :label="t('emailPipeline.accounts.fields.pollInterval')">
            <NInputNumber v-model:value="accountForm.poll_interval_seconds" :show-button="false" style="width: 100%" />
          </NFormItem>
          <NFormItem :label="t('emailPipeline.accounts.fields.maxMessages')">
            <NInputNumber v-model:value="accountForm.max_messages_per_sync" :show-button="false" style="width: 100%" />
          </NFormItem>
          <NFormItem v-if="accountForm.provider !== 'outlook_email'" :label="t('emailPipeline.accounts.fields.includeSpamTrash')">
            <NSwitch v-model:value="accountForm.include_spam_trash" />
          </NFormItem>
        </div>
      </NForm>
      <template #footer>
        <div class="modal-footer">
          <NButton @click="showAccountModal = false">{{ t('common.cancel') }}</NButton>
          <NButton type="primary" :loading="savingAccount" @click="saveAccount">
            {{ t('common.submit') }}
          </NButton>
        </div>
      </template>
    </NModal>

    <NDrawer v-model:show="showMessageDrawer" :block-scroll="false" width="min(920px, 96vw)" placement="right">
      <NDrawerContent :title="t('emailPipeline.messages.detailTitle')">
        <template v-if="messageDetail">
          <div class="drawer-stack">
            <div class="detail-block">
              <div class="detail-block__title">{{ messageDetail.subject || t('emailPipeline.messages.untitled') }}</div>
              <div class="detail-meta">
                <span>{{ messageDetail.from_addr || '—' }}</span>
                <span>{{ formatDateTime(messageDetail.received_at) }}</span>
                <NTag size="small" :bordered="false" :type="messageStatusType(messageDetail.processing_status)">
                  {{ processingStatusText(messageDetail.processing_status) }}
                </NTag>
              </div>
            </div>

            <div class="detail-block">
              <div class="detail-label">{{ t('emailPipeline.messages.body') }}</div>
              <div class="detail-body">{{ messageDetail.body_text || messageDetail.snippet || '—' }}</div>
            </div>

            <div class="detail-block">
              <div class="detail-label">{{ t('emailPipeline.messages.classification') }}</div>
              <NCode :code="prettyJson(messageDetail.classification)" language="json" />
            </div>

            <div v-if="generatedTaskIds[messageDetail.id]" class="detail-block detail-block--task">
              <div class="detail-label">{{ t('emailPipeline.messages.articleTask') }}</div>
              <div class="detail-body">{{ generatedTaskIds[messageDetail.id] }}</div>
            </div>

            <div v-if="messageDetail.attachments?.length" class="detail-block">
              <div class="detail-label">{{ t('emailPipeline.messages.attachments') }}</div>
              <div class="attachment-list">
                <div v-for="(attachment, index) in messageDetail.attachments" :key="attachmentKey(attachment, index)" class="attachment-item">
                  <strong>{{ attachment.filename || '—' }}</strong>
                  <span>{{ attachment.content_type || '—' }}</span>
                  <span>{{ formatBytes(attachment.size) }}</span>
                </div>
              </div>
            </div>

            <div class="detail-block">
              <div class="detail-label">{{ t('emailPipeline.messages.generatePlatforms') }}</div>
              <NCheckboxGroup v-model:value="messageGeneratePlatforms">
                <NSpace size="small">
                  <NCheckbox
                    v-for="option in targetPlatformOptions"
                    :key="String(option.value)"
                    :value="String(option.value)"
                  >
                    {{ option.label }}
                  </NCheckbox>
                </NSpace>
              </NCheckboxGroup>
            </div>

            <div class="drawer-actions">
              <NButton tertiary :loading="detailCleaning" @click="runClean(messageDetail.id, true)">
                {{ t('emailPipeline.messages.clean') }}
              </NButton>
              <NButton tertiary :loading="detailClassifying" @click="runClassify(messageDetail.id, true)">
                {{ t('emailPipeline.messages.classify') }}
              </NButton>
              <NButton tertiary :loading="detailReprocessing" @click="runReprocess(messageDetail.id, true)">
                {{ t('emailPipeline.messages.reprocess') }}
              </NButton>
              <NButton tertiary :loading="detailIgnoring" @click="runIgnore(messageDetail.id, true)">
                {{ t('emailPipeline.messages.ignore') }}
              </NButton>
              <NButton type="primary" :loading="detailGenerating" @click="runGenerate(messageDetail.id, messageGeneratePlatforms, true)">
                {{ t('emailPipeline.messages.generate') }}
              </NButton>
            </div>
          </div>
        </template>
        <NEmpty v-else :description="t('emailPipeline.messages.detailEmpty')" />
      </NDrawerContent>
    </NDrawer>

    <NModal
      v-model:show="showTargetModal"
      :block-scroll="false"
      preset="card"
      :title="t('emailPipeline.targets.edit')"
      style="width: min(760px, 96vw)"
      :mask-closable="false"
    >
      <NForm :model="targetForm" label-placement="top">
        <div class="form-grid">
          <NFormItem :label="t('emailPipeline.targets.fields.displayName')">
            <NInput v-model:value="targetForm.display_name" />
          </NFormItem>
          <NFormItem :label="t('emailPipeline.targets.fields.publishMode')">
            <NSelect v-model:value="targetForm.publish_mode" :options="publishModeOptions" />
          </NFormItem>
          <NFormItem :label="t('emailPipeline.targets.fields.enabled')">
            <NSwitch v-model:value="targetForm.enabled" />
          </NFormItem>
          <div class="wide">
            <NFormItem :label="t('emailPipeline.targets.fields.outputContract')">
              <NInput
                v-model:value="targetForm.output_contract_text"
                type="textarea"
                :autosize="{ minRows: 8, maxRows: 14 }"
              />
            </NFormItem>
          </div>
          <div class="wide">
            <NFormItem :label="t('emailPipeline.targets.fields.promptProfile')">
              <NInput
                v-model:value="targetForm.prompt_profile_text"
                type="textarea"
                :autosize="{ minRows: 6, maxRows: 12 }"
              />
            </NFormItem>
          </div>
        </div>
      </NForm>
      <template #footer>
        <div class="modal-footer">
          <NButton @click="showTargetModal = false">{{ t('common.cancel') }}</NButton>
          <NButton type="primary" :loading="savingTarget" @click="saveTarget">
            {{ t('common.submit') }}
          </NButton>
        </div>
      </template>
    </NModal>

    <NDrawer v-model:show="showVariantDrawer" :block-scroll="false" width="min(960px, 96vw)" placement="right">
      <NDrawerContent :title="t('emailPipeline.variants.detailTitle')">
        <template v-if="variantDetail">
          <div class="drawer-stack">
            <div class="detail-meta">
              <span>#{{ variantDetail.id }}</span>
              <span>{{ variantDetail.platform }}</span>
              <span>{{ variantDetail.source_type }} / {{ variantDetail.source_id }}</span>
              <NTag size="small" :bordered="false" :type="variantStatusType(variantDetail.status)">
                {{ variantStatusText(variantDetail.status) }}
              </NTag>
            </div>

            <NForm :model="variantForm" label-placement="top">
              <NFormItem :label="t('emailPipeline.variants.fields.title')">
                <NInput v-model:value="variantForm.title" />
              </NFormItem>
              <NFormItem :label="t('emailPipeline.variants.fields.summary')">
                <NInput v-model:value="variantForm.summary" type="textarea" :autosize="{ minRows: 3, maxRows: 6 }" />
              </NFormItem>
              <NFormItem :label="t('emailPipeline.variants.fields.status')">
                <NSelect v-model:value="variantForm.status" :options="variantStatusOptions" />
              </NFormItem>
              <NFormItem :label="t('emailPipeline.variants.fields.body')">
                <NInput v-model:value="variantForm.body" type="textarea" :autosize="{ minRows: 14, maxRows: 24 }" />
              </NFormItem>
            </NForm>

            <div class="detail-block">
              <div class="detail-label">{{ t('emailPipeline.variants.fields.metadata') }}</div>
              <NCode :code="prettyJson(variantDetail.metadata)" language="json" />
            </div>

            <div class="detail-block">
              <div class="detail-label">{{ t('emailPipeline.variants.fields.quality') }}</div>
              <NCode :code="prettyJson(variantDetail.quality)" language="json" />
            </div>

            <div class="drawer-actions">
              <NButton tertiary :loading="exportingVariant === 'markdown'" @click="exportVariant('markdown')">
                {{ t('emailPipeline.variants.exportMarkdown') }}
              </NButton>
              <NButton tertiary :loading="exportingVariant === 'json'" @click="exportVariant('json')">
                {{ t('emailPipeline.variants.exportJson') }}
              </NButton>
              <NButton
                v-if="variantDetail.platform === 'wechat'"
                tertiary
                :loading="creatingWechatDraft"
                @click="pushWechatDraft"
              >
                {{ t('emailPipeline.variants.wechatDraft') }}
              </NButton>
              <NButton type="primary" :loading="savingVariant" @click="saveVariant">
                {{ t('common.submit') }}
              </NButton>
            </div>
          </div>
        </template>
        <NEmpty v-else :description="t('emailPipeline.variants.detailEmpty')" />
      </NDrawerContent>
    </NDrawer>
  </div>
</template>

<script setup lang="ts">
import { computed, h, onMounted, reactive, ref } from 'vue'
import { NAlert, NButton, NCheckbox, NCheckboxGroup, NCode, NDataTable, NDrawer, NDrawerContent, NEmpty, NForm, NFormItem, NInput, NInputNumber, NModal, NPagination, NSelect, NSpace, NSwitch, NTag, useMessage, type DataTableColumns, type DataTableRowKey } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import emailApi, { type ContentTarget, type ContentVariant, type EmailAccount, type EmailAccountPayload, type EmailAttachment, type EmailMessage, type GmailOAuthStatus } from '@/api/email'

type NullableString = string | null

const { t, te } = useI18n()
const message = useMessage()
const route = useRoute()
const router = useRouter()

const refreshingAll = ref(false)

const accounts = ref<EmailAccount[]>([])
const loadingAccounts = ref(false)
const accountsError = ref('')
const accountSearch = ref('')
const accountStatusFilter = ref<string | null>(null)
const showAccountModal = ref(false)
const editingAccount = ref<EmailAccount | null>(null)
const savingAccount = ref(false)
const accountActionId = ref<number | null>(null)
const accountActionKind = ref('')
const selectedGmailAuthAccountId = ref<number | null>(null)
const gmailOAuthStatus = ref<GmailOAuthStatus | null>(null)
const loadingGmailOAuthStatus = ref(false)
const gmailOAuthStartingId = ref<number | null>(null)
const gmailOAuthStarting = ref(false)

const accountForm = reactive({
  provider: 'gmail',
  status: 'active',
  display_name: '',
  email_address: '',
  imap_host: '',
  imap_port: 993,
  imap_security: 'ssl',
  imap_username: '',
  smtp_host: '',
  smtp_port: 465,
  smtp_security: 'ssl',
  smtp_username: '',
  outlook_email_base_url: '',
  outlook_email_remote_email: '',
  outlook_email_folder: 'all',
  outlook_email_subject_contains: '',
  outlook_email_from_contains: '',
  outlook_email_keyword: '',
  sync_mode: 'poll',
  poll_interval_seconds: 300,
  include_spam_trash: false,
  max_messages_per_sync: 20,
})

const imapPasswordInput = ref('')
const smtpPasswordInput = ref('')
const outlookEmailApiKeyInput = ref('')

const messages = ref<EmailMessage[]>([])
const messageTotal = ref(0)
const loadingMessages = ref(false)
const messagesError = ref('')
const checkedMessageIds = ref<number[]>([])
const messageActionId = ref<number | null>(null)
const messageActionKind = ref('')
const batchGenerating = ref(false)
const messageFilters = reactive({
  accountId: null as number | null,
  status: null as string | null,
  q: '',
})
const messagePage = ref(1)
const messagePageSize = ref(20)
const showMessageDrawer = ref(false)
const messageDetail = ref<EmailMessage | null>(null)
const loadingMessageDetail = ref(false)
const detailCleaning = ref(false)
const detailClassifying = ref(false)
const detailReprocessing = ref(false)
const detailIgnoring = ref(false)
const detailGenerating = ref(false)
const messageGeneratePlatforms = ref<string[]>([])
const batchGeneratePlatforms = ref<string[]>([])
const generatedTaskIds = ref<Record<number, string>>({})

const targets = ref<ContentTarget[]>([])
const loadingTargets = ref(false)
const targetsError = ref('')
const showTargetModal = ref(false)
const editingTarget = ref<ContentTarget | null>(null)
const savingTarget = ref(false)
const targetActionId = ref<number | null>(null)
const targetForm = reactive({
  display_name: '',
  publish_mode: 'export',
  enabled: true,
  output_contract_text: '{}',
  prompt_profile_text: '{}',
})

const variants = ref<ContentVariant[]>([])
const loadingVariants = ref(false)
const variantsError = ref('')
const variantFilters = reactive({
  platform: null as string | null,
  sourceId: '',
  includeBody: false,
})
const showVariantDrawer = ref(false)
const variantDetail = ref<ContentVariant | null>(null)
const loadingVariantDetail = ref(false)
const savingVariant = ref(false)
const exportingVariant = ref('')
const creatingWechatDraft = ref(false)
const variantActionId = ref<number | null>(null)
const variantForm = reactive({
  title: '',
  summary: '',
  body: '',
  status: 'draft',
})

const providerOptions = [
  { label: 'outlookEmail', value: 'outlook_email' },
  { label: 'Gmail OAuth', value: 'gmail' },
  { label: 'IMAP / SMTP', value: 'imap' },
]

const securityOptions = [
  { label: 'SSL', value: 'ssl' },
  { label: 'STARTTLS', value: 'starttls' },
]

const outlookEmailFolderOptions = [
  { label: 'All', value: 'all' },
  { label: 'Inbox', value: 'inbox' },
  { label: 'Junk Email', value: 'junkemail' },
  { label: 'Deleted Items', value: 'deleteditems' },
]

const syncModeOptions = computed(() => [
  { label: t('emailPipeline.accounts.syncModes.poll'), value: 'poll' },
])

const accountStatusOptions = computed(() => [
  { label: t('emailPipeline.status.active'), value: 'active' },
  { label: t('emailPipeline.status.paused'), value: 'paused' },
  { label: t('emailPipeline.status.disabled'), value: 'disabled' },
  { label: t('emailPipeline.status.error'), value: 'error' },
])

const messageStatusOptions = computed(() => [
  { label: t('emailPipeline.processing.new'), value: 'new' },
  { label: t('emailPipeline.processing.cleaned'), value: 'cleaned' },
  { label: t('emailPipeline.processing.classified'), value: 'classified' },
  { label: t('emailPipeline.processing.generated'), value: 'generated' },
  { label: t('emailPipeline.processing.ignored'), value: 'ignored' },
  { label: t('emailPipeline.processing.error'), value: 'error' },
])

const publishModeOptions = computed(() => [
  { label: t('emailPipeline.targets.publishModes.export'), value: 'export' },
  { label: t('emailPipeline.targets.publishModes.draft'), value: 'draft' },
  { label: t('emailPipeline.targets.publishModes.direct'), value: 'direct' },
])

const variantStatusOptions = computed(() => [
  { label: t('emailPipeline.variantStatus.draft'), value: 'draft' },
  { label: t('emailPipeline.variantStatus.ready'), value: 'ready' },
  { label: t('emailPipeline.variantStatus.exported'), value: 'exported' },
  { label: t('emailPipeline.variantStatus.published'), value: 'published' },
])

const accountSelectOptions = computed(() => accounts.value.map(item => ({
  label: `${item.display_name} · ${item.email_address}`,
  value: item.id,
})))

const gmailAccountOptions = computed(() => accounts.value
  .filter(item => item.provider === 'gmail')
  .map(item => ({
    label: `${item.display_name} · ${item.email_address}`,
    value: item.id,
  })))

const targetPlatformOptions = computed(() => targets.value
  .filter(item => item.enabled !== false)
  .map(item => ({ label: item.display_name || item.platform, value: item.platform })))

const variantPlatformOptions = computed(() => targets.value.map(item => ({
  label: item.display_name || item.platform,
  value: item.platform,
})))

const filteredAccounts = computed(() => accounts.value.filter((item) => {
  const matchesSearch = !accountSearch.value.trim()
    || `${item.display_name} ${item.email_address} ${item.provider}`.toLowerCase().includes(accountSearch.value.trim().toLowerCase())
  const matchesStatus = !accountStatusFilter.value || item.status === accountStatusFilter.value
  return matchesSearch && matchesStatus
}))

const messageRowSelection = {
  checkedRowKeys: checkedMessageIds.value as DataTableRowKey[],
  onUpdateCheckedRowKeys: (keys: DataTableRowKey[]) => {
    checkedMessageIds.value = keys.map(key => Number(key))
  },
}

const accountColumns = computed<DataTableColumns<EmailAccount>>(() => [
  {
    title: t('emailPipeline.accounts.columns.name'),
    key: 'display_name',
    width: 180,
  },
  {
    title: t('emailPipeline.accounts.columns.email'),
    key: 'email_address',
    width: 220,
  },
  {
    title: t('emailPipeline.accounts.columns.provider'),
    key: 'provider',
    width: 110,
    render: row => h(NTag, {
      bordered: false,
      type: row.provider === 'gmail' ? 'success' : row.provider === 'outlook_email' ? 'warning' : 'info',
    }, {
      default: () => row.provider,
    }),
  },
  {
      title: t('emailPipeline.accounts.columns.status'),
      key: 'status',
      width: 110,
      render: row => h(NTag, { bordered: false, type: accountStatusType(row.status) }, {
      default: () => accountStatusText(row.status),
    }),
  },
  {
    title: t('emailPipeline.accounts.columns.syncMode'),
    key: 'sync_mode',
    width: 110,
    render: row => row.sync_mode || '—',
  },
  {
    title: t('emailPipeline.accounts.columns.lastSync'),
    key: 'last_sync_at',
    width: 180,
    render: row => formatDateTime(row.last_sync_at),
  },
  {
    title: t('emailPipeline.accounts.columns.lastError'),
    key: 'last_error',
    width: 220,
    render: row => row.last_error || '—',
  },
  {
    title: t('emailPipeline.accounts.columns.actions'),
    key: 'actions',
    width: 310,
    fixed: 'right',
    render: row => h('div', { class: 'inline-actions' }, [
      h(NButton, {
        size: 'small',
        tertiary: true,
        onClick: () => openAccountModal(row),
      }, { default: () => t('emailPipeline.accounts.edit') }),
      ...(row.provider === 'gmail'
        ? [
            h(NButton, {
              size: 'small',
              tertiary: true,
              type: 'primary',
              loading: gmailOAuthStartingId.value === row.id,
              onClick: () => startGmailOAuth(row.id),
            }, { default: () => t('emailPipeline.accounts.auth') }),
          ]
        : []),
      h(NButton, {
        size: 'small',
        tertiary: true,
        loading: isAccountAction(row.id, 'test'),
        onClick: () => runAccountAction(row.id, 'test'),
      }, { default: () => t('emailPipeline.accounts.test') }),
      h(NButton, {
        size: 'small',
        tertiary: true,
        loading: isAccountAction(row.id, 'sync'),
        onClick: () => runAccountAction(row.id, 'sync'),
      }, { default: () => t('emailPipeline.accounts.syncNow') }),
      h(NButton, {
        size: 'small',
        tertiary: true,
        loading: isAccountAction(row.id, row.status === 'paused' ? 'resume' : 'pause'),
        onClick: () => runAccountAction(row.id, row.status === 'paused' ? 'resume' : 'pause'),
      }, { default: () => row.status === 'paused' ? t('emailPipeline.accounts.resume') : t('emailPipeline.accounts.pause') }),
      h(NButton, {
        size: 'small',
        tertiary: true,
        type: 'error',
        loading: isAccountAction(row.id, 'delete'),
        onClick: () => runAccountAction(row.id, 'delete'),
      }, { default: () => t('common.delete') }),
    ]),
  },
])

const messageColumns = computed<DataTableColumns<EmailMessage>>(() => [
  {
    title: t('emailPipeline.messages.columns.subject'),
    key: 'subject',
    width: 260,
    render: row => h('div', { class: 'cell-stack' }, [
      h('strong', null, row.subject || t('emailPipeline.messages.untitled')),
      h('span', { class: 'cell-sub' }, row.snippet || '—'),
    ]),
  },
  {
    title: t('emailPipeline.messages.columns.from'),
    key: 'from_addr',
    width: 180,
    render: row => row.from_addr || '—',
  },
  {
    title: t('emailPipeline.messages.columns.classification'),
    key: 'classification',
    width: 220,
    render: row => {
      const classification = row.classification || {}
      return h('div', { class: 'cell-stack' }, [
        h('span', null, classification.primary_type || '—'),
        h('span', { class: 'cell-sub' }, (classification.recommended_targets || []).join(', ') || '—'),
      ])
    },
  },
  {
      title: t('emailPipeline.messages.columns.status'),
      key: 'processing_status',
      width: 110,
      render: row => h(NTag, { bordered: false, type: messageStatusType(row.processing_status) }, {
      default: () => processingStatusText(row.processing_status),
    }),
  },
  {
    title: t('emailPipeline.messages.columns.receivedAt'),
    key: 'received_at',
    width: 180,
    render: row => formatDateTime(row.received_at),
  },
  {
    title: t('emailPipeline.messages.columns.actions'),
    key: 'actions',
    width: 450,
    fixed: 'right',
    render: row => h('div', { class: 'inline-actions' }, [
      h(NButton, {
        size: 'small',
        tertiary: true,
        loading: loadingMessageDetail.value && messageDetail.value?.id === row.id,
        onClick: () => openMessageDetail(row.id),
      }, { default: () => t('emailPipeline.messages.detail') }),
      h(NButton, {
        size: 'small',
        tertiary: true,
        loading: isMessageAction(row.id, 'clean'),
        onClick: () => runClean(row.id),
      }, { default: () => t('emailPipeline.messages.clean') }),
      h(NButton, {
        size: 'small',
        tertiary: true,
        loading: isMessageAction(row.id, 'classify'),
        onClick: () => runClassify(row.id),
      }, { default: () => t('emailPipeline.messages.classify') }),
      h(NButton, {
        size: 'small',
        tertiary: true,
        loading: isMessageAction(row.id, 'reprocess'),
        onClick: () => runReprocess(row.id),
      }, { default: () => t('emailPipeline.messages.reprocess') }),
      h(NButton, {
        size: 'small',
        tertiary: true,
        loading: isMessageAction(row.id, 'ignore'),
        onClick: () => runIgnore(row.id),
      }, { default: () => t('emailPipeline.messages.ignore') }),
      h(NButton, {
        size: 'small',
        type: 'primary',
        ghost: true,
        loading: isMessageAction(row.id, 'generate'),
        onClick: () => runGenerate(row.id, recommendedPlatforms(row)),
      }, { default: () => t('emailPipeline.messages.generate') }),
    ]),
  },
])

const targetColumns = computed<DataTableColumns<ContentTarget>>(() => [
  {
    title: t('emailPipeline.targets.columns.platform'),
    key: 'platform',
    width: 140,
  },
  {
    title: t('emailPipeline.targets.columns.displayName'),
    key: 'display_name',
    width: 180,
  },
  {
    title: t('emailPipeline.targets.columns.publishMode'),
    key: 'publish_mode',
    width: 120,
  },
  {
    title: t('emailPipeline.targets.columns.enabled'),
    key: 'enabled',
    width: 110,
    render: row => h(NTag, { bordered: false, type: row.enabled ? 'success' : 'default' }, {
      default: () => row.enabled ? t('common.yes') : t('common.no'),
    }),
  },
  {
    title: t('emailPipeline.targets.columns.contract'),
    key: 'output_contract',
    width: 320,
    render: row => summarizeContract(row.output_contract),
  },
  {
    title: t('emailPipeline.targets.columns.actions'),
    key: 'actions',
    width: 120,
    fixed: 'right',
    render: row => h(NButton, {
      size: 'small',
      tertiary: true,
      loading: targetActionId.value === row.id,
      onClick: () => openTargetModal(row),
    }, { default: () => t('emailPipeline.targets.edit') }),
  },
])

const variantColumns = computed<DataTableColumns<ContentVariant>>(() => [
  {
    title: t('emailPipeline.variants.columns.platform'),
    key: 'platform',
    width: 120,
    render: row => h(NTag, { bordered: false, type: row.platform === 'wechat' ? 'success' : 'info' }, {
      default: () => row.platform,
    }),
  },
  {
    title: t('emailPipeline.variants.columns.title'),
    key: 'title',
    width: 260,
    render: row => h('div', { class: 'cell-stack' }, [
      h('strong', null, row.title || '—'),
      h('span', { class: 'cell-sub' }, row.summary || '—'),
    ]),
  },
  {
    title: t('emailPipeline.variants.columns.source'),
    key: 'source_id',
    width: 180,
    render: row => `${row.source_type} / ${row.source_id}`,
  },
  {
    title: t('emailPipeline.variants.columns.status'),
    key: 'status',
    width: 110,
    render: row => h(NTag, { bordered: false, type: variantStatusType(row.status) }, {
      default: () => variantStatusText(row.status),
    }),
  },
  {
    title: t('emailPipeline.variants.columns.quality'),
    key: 'quality',
    width: 180,
    render: row => summarizeQuality(row.quality),
  },
  {
    title: t('emailPipeline.variants.columns.createdAt'),
    key: 'created_at',
    width: 180,
    render: row => formatDateTime(row.created_at),
  },
  {
    title: t('emailPipeline.variants.columns.actions'),
    key: 'actions',
    width: 220,
    fixed: 'right',
    render: row => h('div', { class: 'inline-actions' }, [
      h(NButton, {
        size: 'small',
        tertiary: true,
        loading: loadingVariantDetail.value && variantDetail.value?.id === row.id,
        onClick: () => openVariantDetail(row),
      }, { default: () => t('emailPipeline.variants.detail') }),
      h(NButton, {
        size: 'small',
        tertiary: true,
        loading: isVariantAction(row.id),
        onClick: () => quickExportVariant(row.id),
      }, { default: () => t('emailPipeline.variants.exportShort') }),
    ]),
  },
])

function secretPlaceholder(hasSecret?: boolean) {
  return hasSecret ? t('emailPipeline.accounts.secretSaved') : t('emailPipeline.accounts.secretEmpty')
}

function unwrapPayload<T>(response: any): T {
  const root = response?.data
  if (root && typeof root === 'object' && 'data' in root && root.data !== undefined) {
    return root.data as T
  }
  return root as T
}

function extractList<T>(response: any, candidateKeys: string[]): T[] {
  const payload = unwrapPayload<any>(response)
  if (Array.isArray(payload)) return payload as T[]
  for (const key of candidateKeys) {
    if (Array.isArray(payload?.[key])) return payload[key] as T[]
  }
  if (Array.isArray(payload?.items)) return payload.items as T[]
  if (Array.isArray(payload?.rows)) return payload.rows as T[]
  return []
}

function extractTotal(response: any, fallbackLength: number) {
  const payload = unwrapPayload<any>(response)
  return Number(payload?.total ?? payload?.count ?? fallbackLength)
}

function normalizeError(error: any) {
  return error?.response?.data?.error || error?.response?.data?.message || error?.message || t('emailPipeline.requestFailed')
}

function formatDateTime(value: NullableString | undefined) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString()
}

function formatBytes(value?: number | null) {
  const size = Number(value || 0)
  if (!size) return '0 B'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}

function attachmentKey(attachment: EmailAttachment, index: number) {
  return attachment.id ?? attachment.filename ?? attachment.content_id ?? attachment.content_type ?? `attachment-${index}`
}

function translateStatus(group: 'status' | 'processing' | 'variantStatus', status?: string | null) {
  if (!status) return '—'
  const key = `emailPipeline.${group}.${status}`
  return te(key) ? t(key) : status
}

function accountStatusText(status?: string | null) {
  return translateStatus('status', status)
}

function processingStatusText(status?: string | null) {
  return translateStatus('processing', status)
}

function accountStatusType(status?: string | null) {
  if (status === 'active') return 'success'
  if (status === 'paused') return 'warning'
  if (status === 'error') return 'error'
  return 'default'
}

function messageStatusType(status?: string | null) {
  if (status === 'generated') return 'success'
  if (status === 'classified' || status === 'cleaned') return 'info'
  if (status === 'ignored') return 'warning'
  if (status === 'error') return 'error'
  return 'default'
}

function variantStatusType(status?: string | null) {
  if (status === 'published' || status === 'exported') return 'success'
  if (status === 'ready') return 'info'
  return 'default'
}

function variantStatusText(status?: string | null) {
  return translateStatus('variantStatus', status)
}

function prettyJson(value: unknown) {
  try {
    return JSON.stringify(value ?? {}, null, 2)
  } catch {
    return '{}'
  }
}

function parseJsonText(text: string, fieldLabel: string) {
  try {
    return JSON.parse(text || '{}')
  } catch {
    throw new Error(t('emailPipeline.invalidJson', { field: fieldLabel }))
  }
}

function summarizeContract(contract?: Record<string, any>) {
  if (!contract || typeof contract !== 'object') return '—'
  return Object.entries(contract)
    .slice(0, 3)
    .map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join('/') : String(value)}`)
    .join(' · ')
}

function summarizeQuality(quality?: Record<string, any>) {
  if (!quality || typeof quality !== 'object') return '—'
  const items = Object.entries(quality)
    .slice(0, 2)
    .map(([key, value]) => `${key}: ${String(value)}`)
  return items.join(' · ') || '—'
}

function scopeText(scopes?: string[] | null) {
  return (scopes || []).join(' · ') || '—'
}

function firstQueryValue(value: unknown) {
  return Array.isArray(value) ? String(value[0] || '') : String(value || '')
}

function handleGmailOAuthReturn() {
  const authResult = firstQueryValue(route.query.gmail_auth)
  if (!authResult) return
  const returnedAccountId = Number(firstQueryValue(route.query.account_id))
  if (Number.isFinite(returnedAccountId) && returnedAccountId > 0) {
    selectedGmailAuthAccountId.value = returnedAccountId
  }
  if (authResult === 'success') {
    message.success(t('emailPipeline.accounts.oauthCallbackSuccess'))
  } else if (authResult === 'failed') {
    message.error(t('emailPipeline.accounts.oauthCallbackFailed'))
  }
  const nextQuery = { ...route.query }
  delete nextQuery.gmail_auth
  delete nextQuery.account_id
  delete nextQuery.reason
  router.replace({ name: 'emailPipeline', query: nextQuery })
}

async function loadGmailOAuthStatus(silent: boolean) {
  loadingGmailOAuthStatus.value = true
  try {
    const response = await emailApi.gmailOAuthStatus({
      account_id: selectedGmailAuthAccountId.value || undefined,
    })
    gmailOAuthStatus.value = unwrapPayload<GmailOAuthStatus>(response)
  } catch (error: any) {
    gmailOAuthStatus.value = null
    if (!silent) message.warning(normalizeError(error))
  } finally {
    loadingGmailOAuthStatus.value = false
  }
}

async function startGmailOAuth(accountId?: number | null) {
  const selectedAccountId = accountId || selectedGmailAuthAccountId.value || null
  if (selectedAccountId) {
    selectedGmailAuthAccountId.value = selectedAccountId
  }
  gmailOAuthStartingId.value = selectedAccountId
  gmailOAuthStarting.value = true
  /** 须在首个 await 之前同步打开，否则浏览器会认为非用户手势，弹窗被拒或顶替当前页 */
  const popupName = '__ytdlp_gmail_oauth__'
  const popupFeatures = 'width=600,height=700,scrollbars=yes'
  let popup: Window | null = null
  try {
    popup = window.open('about:blank', popupName, popupFeatures)
  } catch {
    popup = null
  }
  try {
    const requestPayload = {
      return_to: '/#/email-pipeline',
      ...(selectedAccountId ? { account_id: selectedAccountId } : {}),
    }
    const response = await emailApi.startGmailOAuth(requestPayload)
    const responsePayload = unwrapPayload<any>(response)
    const authorizationUrl = String(responsePayload?.authorization_url || '')
    if (!authorizationUrl) {
      throw new Error(t('emailPipeline.accounts.oauthMissingUrl'))
    }
    if (!popup || popup.closed) {
      throw new Error(t('emailPipeline.accounts.popupBlocked'))
    }
    message.warning(t('emailPipeline.accounts.oauthPopupHint'))
    popup.location.href = authorizationUrl
    // 监听 popup 关闭（用户完成授权后 popup 会被重定向并关闭）
    const pollKey = '__gmail_oauth_poll'
    if ((window as any)[pollKey]) clearInterval((window as any)[pollKey])
    const pollInterval = setInterval(() => {
      if (popup.closed) {
        clearInterval((window as any)[pollKey])
        ;(window as any)[pollKey] = null
        gmailOAuthStartingId.value = null
        gmailOAuthStarting.value = false
        loadGmailOAuthStatus(false)
      }
    }, 800)
    ;(window as any)[pollKey] = pollInterval
  } catch (error: any) {
    try {
      if (popup && !popup.closed) popup.close()
    } catch {
      /* ignore */
    }
    gmailOAuthStartingId.value = null
    gmailOAuthStarting.value = false
    message.error(normalizeError(error))
  }
}

function resetAccountForm() {
  accountForm.provider = 'outlook_email'
  accountForm.status = 'active'
  accountForm.display_name = ''
  accountForm.email_address = ''
  accountForm.imap_host = ''
  accountForm.imap_port = 993
  accountForm.imap_security = 'ssl'
  accountForm.imap_username = ''
  accountForm.smtp_host = ''
  accountForm.smtp_port = 465
  accountForm.smtp_security = 'ssl'
  accountForm.smtp_username = ''
  accountForm.outlook_email_base_url = 'http://127.0.0.1:5000'
  accountForm.outlook_email_remote_email = ''
  accountForm.outlook_email_folder = 'all'
  accountForm.outlook_email_subject_contains = ''
  accountForm.outlook_email_from_contains = ''
  accountForm.outlook_email_keyword = ''
  accountForm.sync_mode = 'poll'
  accountForm.poll_interval_seconds = 300
  accountForm.include_spam_trash = false
  accountForm.max_messages_per_sync = 20
  imapPasswordInput.value = ''
  smtpPasswordInput.value = ''
  outlookEmailApiKeyInput.value = ''
}

function openAccountModal(account?: EmailAccount) {
  resetAccountForm()
  editingAccount.value = account || null
  if (account) {
    accountForm.provider = account.provider || 'gmail'
    accountForm.status = account.status || 'active'
    accountForm.display_name = account.display_name || ''
    accountForm.email_address = account.email_address || ''
    accountForm.imap_host = account.imap_host || ''
    accountForm.imap_port = Number(account.imap_port || 993)
    accountForm.imap_security = account.imap_security || 'ssl'
    accountForm.imap_username = account.imap_username || ''
    accountForm.smtp_host = account.smtp_host || ''
    accountForm.smtp_port = Number(account.smtp_port || 465)
    accountForm.smtp_security = account.smtp_security || 'ssl'
    accountForm.smtp_username = account.smtp_username || ''
    accountForm.outlook_email_base_url = account.outlook_email_base_url || ''
    accountForm.outlook_email_remote_email = account.outlook_email_remote_email || ''
    accountForm.outlook_email_folder = account.outlook_email_folder || 'all'
    accountForm.outlook_email_subject_contains = account.outlook_email_subject_contains || ''
    accountForm.outlook_email_from_contains = account.outlook_email_from_contains || ''
    accountForm.outlook_email_keyword = account.outlook_email_keyword || ''
    accountForm.sync_mode = 'poll'
    accountForm.poll_interval_seconds = Number(account.poll_interval_seconds || 300)
    accountForm.include_spam_trash = Boolean(account.include_spam_trash)
    accountForm.max_messages_per_sync = Number(account.max_messages_per_sync || 20)
  }
  showAccountModal.value = true
}

function buildAccountPayload(): EmailAccountPayload {
  const payload: EmailAccountPayload = {
    provider: accountForm.provider,
    status: accountForm.status,
    display_name: accountForm.display_name.trim(),
    email_address: accountForm.email_address.trim(),
    sync_mode: accountForm.sync_mode,
    poll_interval_seconds: Number(accountForm.poll_interval_seconds || 300),
    include_spam_trash: Boolean(accountForm.include_spam_trash),
    max_messages_per_sync: Number(accountForm.max_messages_per_sync || 20),
  }
  if (accountForm.provider === 'imap') {
    payload.imap_host = accountForm.imap_host.trim() || undefined
    payload.imap_port = Number(accountForm.imap_port || 993)
    payload.imap_security = accountForm.imap_security
    payload.imap_username = accountForm.imap_username.trim() || undefined
    payload.smtp_host = accountForm.smtp_host.trim() || undefined
    payload.smtp_port = Number(accountForm.smtp_port || 465)
    payload.smtp_security = accountForm.smtp_security
    payload.smtp_username = accountForm.smtp_username.trim() || undefined
  }
  if (accountForm.provider === 'outlook_email') {
    payload.outlook_email_base_url = accountForm.outlook_email_base_url.trim() || undefined
    payload.outlook_email_remote_email = accountForm.outlook_email_remote_email.trim() || accountForm.email_address.trim()
    payload.outlook_email_folder = accountForm.outlook_email_folder
    payload.outlook_email_subject_contains = accountForm.outlook_email_subject_contains.trim() || undefined
    payload.outlook_email_from_contains = accountForm.outlook_email_from_contains.trim() || undefined
    payload.outlook_email_keyword = accountForm.outlook_email_keyword.trim() || undefined
  }
  if (accountForm.provider === 'imap' && imapPasswordInput.value.trim()) payload.imap_password = imapPasswordInput.value.trim()
  if (accountForm.provider === 'imap' && smtpPasswordInput.value.trim()) payload.smtp_password = smtpPasswordInput.value.trim()
  if (accountForm.provider === 'outlook_email' && outlookEmailApiKeyInput.value.trim()) {
    payload.outlook_email_api_key = outlookEmailApiKeyInput.value.trim()
  }
  return payload
}

async function saveAccount() {
  if (!accountForm.display_name.trim() || !accountForm.email_address.trim()) {
    message.warning(t('emailPipeline.accounts.requiredHint'))
    return
  }
  savingAccount.value = true
  try {
    const payload = buildAccountPayload()
    if (editingAccount.value?.id) {
      await emailApi.updateAccount(editingAccount.value.id, payload)
    } else {
      await emailApi.createAccount(payload)
    }
    showAccountModal.value = false
    await loadAccounts(true)
    message.success(t('emailPipeline.accounts.saved'))
  } catch (error: any) {
    message.error(normalizeError(error))
  } finally {
    savingAccount.value = false
  }
}

async function loadAccounts(silent: boolean) {
  loadingAccounts.value = true
  accountsError.value = ''
  try {
    const response = await emailApi.listAccounts()
    accounts.value = extractList<EmailAccount>(response, ['accounts', 'items', 'rows'])
    const gmailIds = accounts.value.filter(item => item.provider === 'gmail').map(item => item.id)
    if (selectedGmailAuthAccountId.value && !gmailIds.includes(selectedGmailAuthAccountId.value)) {
      selectedGmailAuthAccountId.value = null
    }
    await loadGmailOAuthStatus(true)
  } catch (error: any) {
    accounts.value = []
    accountsError.value = normalizeError(error)
    if (!silent) message.warning(accountsError.value)
  } finally {
    loadingAccounts.value = false
  }
}

function isAccountAction(id: number, kind: string) {
  return accountActionId.value === id && accountActionKind.value === kind
}

async function runAccountAction(id: number, kind: 'test' | 'sync' | 'pause' | 'resume' | 'delete') {
  accountActionId.value = id
  accountActionKind.value = kind
  try {
    if (kind === 'test') {
      const response = await emailApi.testAccount(id)
      const payload = unwrapPayload<any>(response)
      message.success(payload?.message || t('emailPipeline.accounts.testSuccess'))
    } else if (kind === 'sync') {
      const account = accounts.value.find(item => item.id === id)
      const response = await emailApi.syncNow(id, { max_messages: Number(account?.max_messages_per_sync || 20) })
      const payload = unwrapPayload<any>(response)
      message.success(payload?.message || t('emailPipeline.accounts.syncTriggered'))
      await loadMessages(true)
    } else if (kind === 'pause') {
      await emailApi.pauseAccount(id)
      message.success(t('emailPipeline.accounts.paused'))
    } else if (kind === 'resume') {
      await emailApi.resumeAccount(id)
      message.success(t('emailPipeline.accounts.resumed'))
    } else if (kind === 'delete') {
      await emailApi.deleteAccount(id)
      message.success(t('emailPipeline.accounts.deleted'))
    }
    await loadAccounts(true)
  } catch (error: any) {
    message.error(normalizeError(error))
  } finally {
    accountActionId.value = null
    accountActionKind.value = ''
  }
}

async function loadMessages(silent: boolean) {
  loadingMessages.value = true
  messagesError.value = ''
  try {
    const response = await emailApi.listMessages({
      account_id: messageFilters.accountId,
      status: messageFilters.status,
      q: messageFilters.q.trim() || undefined,
      limit: messagePageSize.value,
      offset: (messagePage.value - 1) * messagePageSize.value,
    })
    messages.value = extractList<EmailMessage>(response, ['messages', 'items', 'rows'])
    messageTotal.value = extractTotal(response, messages.value.length)
  } catch (error: any) {
    messages.value = []
    messageTotal.value = 0
    messagesError.value = normalizeError(error)
    if (!silent) message.warning(messagesError.value)
  } finally {
    loadingMessages.value = false
  }
}

function handleMessagePageSizeChange() {
  messagePage.value = 1
  loadMessages(true)
}

function recommendedPlatforms(row: EmailMessage) {
  const recommended = (row.classification?.recommended_targets || []).map((item: unknown) => String(item))
  return recommended.length ? recommended : targetPlatformOptions.value.map(item => String(item.value)).slice(0, 3)
}

function isMessageAction(id: number, kind: string) {
  return messageActionId.value === id && messageActionKind.value === kind
}

async function openMessageDetail(id: number) {
  showMessageDrawer.value = true
  loadingMessageDetail.value = true
  try {
    const response = await emailApi.getMessage(id)
    const payload = unwrapPayload<any>(response)
    messageDetail.value = payload?.message || payload?.item || payload || null
    if (messageDetail.value) {
      messageGeneratePlatforms.value = recommendedPlatforms(messageDetail.value)
      await hydrateGeneratedTaskId(messageDetail.value.id)
    }
  } catch (error: any) {
    messageDetail.value = null
    message.error(normalizeError(error))
  } finally {
    loadingMessageDetail.value = false
  }
}

function mergeMessage(updated: EmailMessage) {
  messages.value = messages.value.map(item => (item.id === updated.id ? { ...item, ...updated } : item))
  if (messageDetail.value?.id === updated.id) {
    messageDetail.value = { ...messageDetail.value, ...updated }
  }
}

function rememberGeneratedTaskId(messageId: number, taskId: unknown) {
  const value = String(taskId || '')
  if (!value) return
  generatedTaskIds.value = { ...generatedTaskIds.value, [messageId]: value }
}

async function hydrateGeneratedTaskId(messageId: number) {
  if (generatedTaskIds.value[messageId]) return
  try {
    const response = await emailApi.listVariants({
      source_type: 'email_message',
      source_id: String(messageId),
      include_body: false,
    })
    const rows = extractList<ContentVariant>(response, ['variants', 'items', 'rows'])
    const taskId = rows.map(row => String(row.article_task_id || '')).find(Boolean)
    if (taskId) rememberGeneratedTaskId(messageId, taskId)
  } catch {
    // Variant hydration is secondary; the message drawer should still open.
  }
}

async function runClean(id: number, fromDetail = false) {
  messageActionId.value = id
  messageActionKind.value = 'clean'
  detailCleaning.value = fromDetail
  try {
    const response = await emailApi.cleanMessage(id)
    const payload = unwrapPayload<any>(response)
    const updated = (payload?.message || payload?.item || payload) as EmailMessage
    mergeMessage(updated)
    message.success(t('emailPipeline.messages.cleaned'))
    await loadMessages(true)
  } catch (error: any) {
    message.error(normalizeError(error))
  } finally {
    messageActionId.value = null
    messageActionKind.value = ''
    detailCleaning.value = false
  }
}

async function runClassify(id: number, fromDetail = false) {
  messageActionId.value = id
  messageActionKind.value = 'classify'
  detailClassifying.value = fromDetail
  try {
    const response = await emailApi.classifyMessage(id)
    const payload = unwrapPayload<any>(response)
    const updated = (payload?.message || payload?.item || payload) as EmailMessage
    mergeMessage(updated)
    message.success(t('emailPipeline.messages.classified'))
    await loadMessages(true)
  } catch (error: any) {
    message.error(normalizeError(error))
  } finally {
    messageActionId.value = null
    messageActionKind.value = ''
    detailClassifying.value = false
  }
}

async function runReprocess(id: number, fromDetail = false) {
  messageActionId.value = id
  messageActionKind.value = 'reprocess'
  detailReprocessing.value = fromDetail
  try {
    const response = await emailApi.reprocessMessage(id, {
      expand_links: fromDetail,
      max_depth: fromDetail ? 2 : 1,
    })
    const payload = unwrapPayload<any>(response)
    const updated = (payload?.message || payload?.item || payload) as EmailMessage
    mergeMessage(updated)
    message.success(t('emailPipeline.messages.reprocessed'))
    await loadMessages(true)
  } catch (error: any) {
    message.error(normalizeError(error))
  } finally {
    messageActionId.value = null
    messageActionKind.value = ''
    detailReprocessing.value = false
  }
}

async function runIgnore(id: number, fromDetail = false) {
  messageActionId.value = id
  messageActionKind.value = 'ignore'
  detailIgnoring.value = fromDetail
  try {
    await emailApi.ignoreMessage(id)
    if (messageDetail.value?.id === id) {
      messageDetail.value = { ...messageDetail.value, processing_status: 'ignored' }
    }
    await loadMessages(true)
    message.success(t('emailPipeline.messages.ignored'))
  } catch (error: any) {
    message.error(normalizeError(error))
  } finally {
    messageActionId.value = null
    messageActionKind.value = ''
    detailIgnoring.value = false
  }
}

async function runGenerate(id: number, platforms?: string[], fromDetail = false) {
  const selectedPlatforms = (platforms || []).filter(Boolean)
  messageActionId.value = id
  messageActionKind.value = 'generate'
  detailGenerating.value = fromDetail
  try {
    const response = await emailApi.generateVariants(id, {
      platforms: selectedPlatforms.length ? selectedPlatforms : undefined,
      target_lang: 'zh-Hans',
    })
    const payload = unwrapPayload<any>(response)
    rememberGeneratedTaskId(id, payload?.task_id)
    if (messageDetail.value?.id === id) {
      messageDetail.value = { ...messageDetail.value, processing_status: 'generated' }
    }
    variantFilters.sourceId = String(id)
    await Promise.all([loadMessages(true), loadVariants(true)])
    message.success(t('emailPipeline.messages.generated'))
  } catch (error: any) {
    message.error(normalizeError(error))
  } finally {
    messageActionId.value = null
    messageActionKind.value = ''
    detailGenerating.value = false
  }
}

async function runBatchGenerate() {
  if (!checkedMessageIds.value.length) return
  batchGenerating.value = true
  try {
    const response = await emailApi.batchGenerate({
      message_ids: checkedMessageIds.value,
      platforms: batchGeneratePlatforms.value.length ? batchGeneratePlatforms.value : undefined,
      target_lang: 'zh-Hans',
    })
    const payload = unwrapPayload<any>(response)
    const results = Array.isArray(payload?.results) ? payload.results : []
    for (const item of results) {
      const messageId = Number(item?.message_id)
      if (Number.isFinite(messageId) && messageId > 0) {
        rememberGeneratedTaskId(messageId, item?.task_id)
      }
    }
    await Promise.all([loadMessages(true), loadVariants(true)])
    message.success(t('emailPipeline.messages.batchGenerated'))
  } catch (error: any) {
    message.error(normalizeError(error))
  } finally {
    batchGenerating.value = false
  }
}

async function loadTargets(silent: boolean) {
  loadingTargets.value = true
  targetsError.value = ''
  try {
    const response = await emailApi.listTargets()
    targets.value = extractList<ContentTarget>(response, ['targets', 'items', 'rows'])
    if (!batchGeneratePlatforms.value.length) {
      batchGeneratePlatforms.value = targetPlatformOptions.value.map(item => String(item.value)).slice(0, 3)
    }
  } catch (error: any) {
    targets.value = []
    targetsError.value = normalizeError(error)
    if (!silent) message.warning(targetsError.value)
  } finally {
    loadingTargets.value = false
  }
}

function openTargetModal(target: ContentTarget) {
  editingTarget.value = target
  targetActionId.value = target.id
  targetForm.display_name = target.display_name || ''
  targetForm.publish_mode = target.publish_mode || 'export'
  targetForm.enabled = target.enabled !== false
  targetForm.output_contract_text = prettyJson(target.output_contract)
  targetForm.prompt_profile_text = prettyJson(target.prompt_profile)
  showTargetModal.value = true
  targetActionId.value = null
}

async function saveTarget() {
  if (!editingTarget.value) return
  savingTarget.value = true
  try {
    await emailApi.updateTarget(editingTarget.value.id, {
      display_name: targetForm.display_name.trim(),
      publish_mode: targetForm.publish_mode,
      enabled: Boolean(targetForm.enabled),
      output_contract: parseJsonText(targetForm.output_contract_text, t('emailPipeline.targets.fields.outputContract')),
      prompt_profile: parseJsonText(targetForm.prompt_profile_text, t('emailPipeline.targets.fields.promptProfile')),
    })
    showTargetModal.value = false
    await loadTargets(true)
    message.success(t('emailPipeline.targets.saved'))
  } catch (error: any) {
    message.error(normalizeError(error))
  } finally {
    savingTarget.value = false
  }
}

async function loadVariants(silent: boolean) {
  loadingVariants.value = true
  variantsError.value = ''
  try {
    const response = await emailApi.listVariants({
      source_type: 'email_message',
      source_id: variantFilters.sourceId.trim() || undefined,
      platform: variantFilters.platform || undefined,
      include_body: variantFilters.includeBody,
    })
    variants.value = extractList<ContentVariant>(response, ['variants', 'items', 'rows'])
  } catch (error: any) {
    variants.value = []
    variantsError.value = normalizeError(error)
    if (!silent) message.warning(variantsError.value)
  } finally {
    loadingVariants.value = false
  }
}

function isVariantAction(id: number) {
  return variantActionId.value === id
}

async function openVariantDetail(row: ContentVariant) {
  showVariantDrawer.value = true
  loadingVariantDetail.value = true
  variantActionId.value = row.id
  try {
    let detail: ContentVariant = row
    if (!row.body) {
      const response = await emailApi.getVariant(row.id)
      const payload = unwrapPayload<any>(response)
      detail = (payload?.variant || payload?.item || payload) as ContentVariant
    }
    variantDetail.value = detail
    variantForm.title = detail.title || ''
    variantForm.summary = detail.summary || ''
    variantForm.body = detail.body || ''
    variantForm.status = detail.status || 'draft'
  } catch (error: any) {
    variantDetail.value = null
    message.error(normalizeError(error))
  } finally {
    loadingVariantDetail.value = false
    variantActionId.value = null
  }
}

async function saveVariant() {
  if (!variantDetail.value) return
  savingVariant.value = true
  try {
    await emailApi.updateVariant(variantDetail.value.id, {
      title: variantForm.title.trim(),
      summary: variantForm.summary.trim(),
      body: variantForm.body,
      status: variantForm.status,
    })
    await loadVariants(true)
    variantDetail.value = {
      ...variantDetail.value,
      title: variantForm.title.trim(),
      summary: variantForm.summary.trim(),
      body: variantForm.body,
      status: variantForm.status,
    }
    message.success(t('emailPipeline.variants.saved'))
  } catch (error: any) {
    message.error(normalizeError(error))
  } finally {
    savingVariant.value = false
  }
}

async function exportVariant(format: string) {
  if (!variantDetail.value) return
  exportingVariant.value = format
  try {
    const response = await emailApi.exportVariant(variantDetail.value.id, { format })
    const payload = unwrapPayload<any>(response)
    const content = payload?.content || payload?.text || payload?.body
    if (content && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(String(content))
      message.success(t('emailPipeline.variants.copied'))
    } else {
      message.success(payload?.message || t('emailPipeline.variants.exported'))
    }
  } catch (error: any) {
    message.error(normalizeError(error))
  } finally {
    exportingVariant.value = ''
  }
}

async function quickExportVariant(id: number) {
  variantActionId.value = id
  try {
    const response = await emailApi.exportVariant(id, { format: 'markdown' })
    const payload = unwrapPayload<any>(response)
    const content = payload?.content || payload?.text || payload?.body
    if (content && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(String(content))
      message.success(t('emailPipeline.variants.copied'))
    } else {
      message.success(payload?.message || t('emailPipeline.variants.exported'))
    }
  } catch (error: any) {
    message.error(normalizeError(error))
  } finally {
    variantActionId.value = null
  }
}

async function pushWechatDraft() {
  if (!variantDetail.value) return
  creatingWechatDraft.value = true
  try {
    await emailApi.createWechatDraft(variantDetail.value.id)
    message.success(t('emailPipeline.variants.wechatDrafted'))
  } catch (error: any) {
    message.error(normalizeError(error))
  } finally {
    creatingWechatDraft.value = false
  }
}

async function refreshAll(silent: boolean) {
  refreshingAll.value = true
  try {
    await Promise.allSettled([
      loadAccounts(true),
      loadMessages(true),
      loadTargets(true),
      loadVariants(true),
    ])
    if (!silent) message.success(t('emailPipeline.refreshed'))
  } finally {
    refreshingAll.value = false
  }
}

onMounted(() => {
  handleGmailOAuthReturn()
  refreshAll(true)
})
</script>

<style scoped>
.email-pipeline-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.email-pipeline-hero {
  display: grid;
  grid-template-columns: minmax(0, 1.6fr) minmax(320px, 1fr);
  gap: 20px;
  align-items: center;
  background:
    radial-gradient(circle at top right, rgba(201, 100, 66, 0.12), transparent 38%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.7), rgba(250, 249, 245, 0.95));
}

.email-pipeline-hero__eyebrow {
  font-size: 12px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--accent);
  margin-bottom: 8px;
}

.email-pipeline-hero__title {
  font-family: Georgia, serif;
  font-size: 32px;
  line-height: 1.15;
  color: var(--text);
  margin-bottom: 10px;
}

.email-pipeline-hero__desc {
  max-width: 56ch;
  color: var(--text-muted);
  line-height: 1.65;
}

.email-pipeline-metrics {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.email-pipeline-metric {
  padding: 16px;
  background: rgba(255, 255, 255, 0.62);
  border: 1px solid rgba(232, 230, 220, 0.95);
  border-radius: 18px;
  box-shadow: var(--shadow-whisper);
}

.email-pipeline-metric strong {
  display: block;
  margin-top: 6px;
  font-size: 28px;
  font-family: Georgia, serif;
  color: var(--text);
}

.email-pipeline-metric__label {
  font-size: 12px;
  color: var(--text-dim);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.email-pipeline-icon {
  background: rgba(201, 100, 66, 0.14);
  color: var(--accent);
}

.gmail-oauth-card {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(260px, 340px);
  gap: 18px;
  align-items: start;
}

.outlook-email-card {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(220px, 280px);
  gap: 18px;
  align-items: start;
  background: linear-gradient(180deg, rgba(250, 249, 245, 0.96), rgba(255, 255, 255, 0.76));
}

.outlook-email-card__main,
.gmail-oauth-card__main {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
}

.outlook-email-card__desc,
.gmail-oauth-card__desc {
  color: var(--text-muted);
  line-height: 1.6;
}

.outlook-email-card__facts {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.outlook-email-card__facts div {
  min-width: 0;
  padding: 12px;
  background: rgba(245, 244, 237, 0.86);
  border: 1px solid var(--border);
  border-radius: 12px;
}

.outlook-email-card__facts span,
.outlook-email-card__facts strong {
  display: block;
  overflow-wrap: anywhere;
}

.outlook-email-card__facts span {
  margin-bottom: 5px;
  color: var(--text-dim);
  font-size: 12px;
}

.outlook-email-card__facts strong {
  color: var(--text);
  font-size: 13px;
}

.gmail-oauth-tags,
.gmail-oauth-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.outlook-email-card__actions,
.gmail-oauth-actions {
  flex-direction: column;
}

.outlook-email-card__actions {
  display: flex;
  gap: 8px;
}

.gmail-oauth-settings-link {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 34px;
  padding: 0 12px;
  border-radius: 8px;
  background: var(--surface3);
  color: var(--text);
  font-size: 13px;
  font-weight: 600;
  text-decoration: none;
  box-shadow: 0 0 0 1px var(--border);
}

.gmail-oauth-settings-link:hover {
  color: var(--accent);
  box-shadow: 0 0 0 1px rgba(201, 100, 66, 0.35);
}

.gmail-oauth-meta {
  display: grid;
  gap: 6px;
  min-width: 0;
  color: var(--text-dim);
  font-size: 12px;
}

.gmail-oauth-meta span {
  overflow-wrap: anywhere;
}

.section-alert {
  margin-bottom: 12px;
}

.section-toolbar {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.section-toolbar--dense {
  grid-template-columns: minmax(180px, 220px) minmax(180px, 220px) minmax(240px, 1fr) minmax(220px, 1.2fr);
}

.platform-checks {
  display: flex;
  align-items: center;
  min-height: 40px;
  padding: 8px 12px;
  background: rgba(245, 244, 237, 0.9);
  border: 1px solid var(--border);
  border-radius: 14px;
}

.switch-label {
  align-self: center;
  color: var(--text-muted);
}

.section-pagination {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-top: 16px;
  color: var(--text-muted);
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 16px;
}

.form-grid .wide {
  grid-column: 1 / -1;
}

.inline-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.cell-stack {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.cell-sub {
  font-size: 12px;
  color: var(--text-dim);
}

.drawer-stack {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.detail-block {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 16px;
  background: rgba(245, 244, 237, 0.78);
  border: 1px solid var(--border);
  border-radius: 16px;
}

.detail-block--task {
  background: rgba(232, 230, 220, 0.72);
}

.detail-block__title {
  font-family: Georgia, serif;
  font-size: 24px;
  line-height: 1.25;
  color: var(--text);
}

.detail-label {
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-dim);
}

.detail-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
  align-items: center;
  color: var(--text-muted);
  font-size: 13px;
}

.detail-body {
  white-space: pre-wrap;
  line-height: 1.65;
  color: var(--text);
}

.drawer-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.attachment-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.attachment-item {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr) auto;
  gap: 10px;
  padding: 12px 14px;
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid rgba(232, 230, 220, 0.95);
  border-radius: 12px;
  color: var(--text-muted);
}

@media (max-width: 1100px) {
  .email-pipeline-hero,
  .outlook-email-card,
  .gmail-oauth-card {
    grid-template-columns: 1fr;
  }

  .section-toolbar--dense {
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  }
}

@media (max-width: 720px) {
  .email-pipeline-metrics,
  .outlook-email-card__facts,
  .form-grid {
    grid-template-columns: 1fr;
  }

  .section-pagination {
    flex-direction: column;
    align-items: flex-start;
  }

  .attachment-item {
    grid-template-columns: 1fr;
  }
}
</style>
