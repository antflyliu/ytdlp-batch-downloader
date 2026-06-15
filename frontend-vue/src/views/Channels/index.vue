<template>
  <div>
    <div class="page-header">
      <div>
        <div class="page-title">{{ t('channels.tabTitle') }}</div>
        <div class="page-desc">解析微信视频号 SPH 分享链接 → 立即下载</div>
      </div>
    </div>

    <NTabs v-model:value="activeTab" type="line" animated>
      <NTabPane name="single" :tab="t('channels.tabSingle')">
        <SingleParse />
      </NTabPane>
      <NTabPane name="batch" :tab="t('channels.tabQueue')">
        <BatchQueue />
      </NTabPane>
      <NTabPane name="history" :tab="t('channels.tabHistory')">
        <ParseHistory />
      </NTabPane>
      <NTabPane name="cookie" :tab="t('channels.tabCookie')">
        <CookieStatus />
      </NTabPane>
    </NTabs>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { NTabPane, NTabs } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import CookieStatus from './CookieStatus.vue'
import ParseHistory from './ParseHistory.vue'
import BatchQueue from './BatchQueue.vue'
import SingleParse from './SingleParse.vue'

const { t } = useI18n()
const activeTab = ref('single')
</script>
