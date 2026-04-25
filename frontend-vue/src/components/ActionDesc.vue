<template>
  <div class="flex items-center">
    <span>
      {{ t('index.operation') }}
    </span>
    <NPopover trigger="hover">
      <template #trigger>
        <NIcon size="18" class="ml-1 text-dim">
          <HelpCircleOutline/>
        </NIcon>
      </template>
      <div class="flex flex-col">
        <div class="flex items-center justify-start p-1.5">
          <n-icon size="28"
                  style="color:var(--accent);background:rgba(201,100,66,0.12)"
                  class="rounded-full flex items-center justify-center p-1.5 cursor-pointer transition-colors hover:bg-[rgba(201,100,66,0.2)]">
            <DownloadOutline/>
          </n-icon>
          <span class="ml-1">{{ t("index.direct_download") }}</span>
        </div>

        <div class="flex items-center justify-start p-1.5">
          <n-icon size="28"
                  style="color:var(--error);background:rgba(220,80,60,0.12)"
                  class="rounded-full flex items-center justify-center p-1.5 cursor-pointer transition-colors hover:bg-[rgba(220,80,60,0.2)]">
            <CloseOutline/>
          </n-icon>
          <span class="ml-1">{{ t("index.cancel_down") }}</span>
        </div>

        <div class="flex items-center justify-start p-1.5">
          <n-icon
              size="28"
              style="color:var(--accent);background:rgba(201,100,66,0.12)"
              class="rounded-full flex items-center justify-center p-1.5 cursor-pointer transition-colors hover:bg-[rgba(201,100,66,0.2)]"
          >
            <LinkOutline/>
          </n-icon>
          <span class="ml-1">{{ t("index.copy_link") }}</span>
        </div>

        <div class="flex items-center justify-start p-1.5">
          <n-icon
              size="28"
              style="color:var(--accent);background:rgba(201,100,66,0.12)"
              class="rounded-full flex items-center justify-center p-1.5 cursor-pointer transition-colors hover:bg-[rgba(201,100,66,0.2)]"
          >
            <GlobeOutline/>
          </n-icon>
          <span class="ml-1">{{ t("index.open_link") }}</span>
        </div>

        <div class="flex items-center justify-start p-1.5">
          <n-icon
              size="28"
              style="color:var(--accent);background:rgba(201,128,66,0.12)"
              class="rounded-full flex items-center justify-center p-1.5 cursor-pointer transition-colors hover:bg-[rgba(201,128,66,0.2)]"
          >
            <LockOpenSharp/>
          </n-icon>
          <span class="ml-1">{{ t("index.video_decode") }}</span>
        </div>

        <div class="flex items-center justify-start p-1.5">
          <n-icon
              size="28"
              style="color:var(--accent);background:rgba(201,100,66,0.12)"
              class="rounded-full flex items-center justify-center p-1.5 cursor-pointer transition-colors hover:bg-[rgba(201,100,66,0.2)]"
          >
            <CopyOutline/>
          </n-icon>
          <span class="ml-1">{{ t("index.copy_data") }}</span>
        </div>

        <div class="flex items-center justify-start p-1.5">
          <n-icon
              size="28"
              style="color:var(--error);background:rgba(220,80,60,0.12)"
              class="rounded-full flex items-center justify-center p-1.5 cursor-pointer transition-colors hover:bg-[rgba(220,80,60,0.2)]"
          >
            <TrashOutline/>
          </n-icon>
          <span class="ml-1">{{ t("index.delete_row") }}</span>
        </div>

        <div class="flex items-center justify-start p-1.5">
          <n-icon
              size="28"
              style="color:var(--accent);background:rgba(201,100,66,0.12)"
              class="rounded-full flex items-center justify-center p-2 cursor-pointer transition-colors hover:bg-[rgba(201,100,66,0.2)]"
          >
            <GridSharp/>
          </n-icon>
          <span class="ml-1">{{ t("index.more_operation") }}</span>
        </div>
      </div>
    </NPopover>
  </div>
</template>
<script setup lang="ts">
import {useI18n} from "vue-i18n"
import {
  CopyOutline,
  DownloadOutline,
  GlobeOutline,
  HelpCircleOutline,
  LinkOutline,
  LockOpenSharp,
  GridSharp,
  CloseOutline,
  TrashOutline
} from "@vicons/ionicons5"

const {t} = useI18n()
</script>