<template>
  <div style="--wails-draggable:no-drag" class="grid grid-cols-3 gap-1.5">
    <n-icon
        size="30"
        style="color:var(--accent);background:rgba(201,100,66,0.12)"
        class="rounded-full flex items-center justify-center p-1.5 cursor-pointer transition-colors hover:bg-[rgba(201,100,66,0.2)]"
        @click="action('down')"
    >
      <DownloadOutline/>
    </n-icon>

    <n-icon
        size="28"
        style="color:var(--error);background:rgba(220,80,60,0.12)"
        class="rounded-full flex items-center justify-center p-1.5 cursor-pointer transition-colors hover:bg-[rgba(220,80,60,0.2)]"
        @click="action('delete')"
    >
      <TrashOutline/>
    </n-icon>

    <NPopover placement="bottom" trigger="hover">
      <template #trigger>
        <NIcon size="30" style="color:var(--accent);background:rgba(201,100,66,0.12)" class="rounded-full flex items-center justify-center p-2 cursor-pointer transition-colors hover:bg-[rgba(201,100,66,0.2)]">
          <GridSharp/>
        </NIcon>
      </template>
      <div class="flex flex-col">
        <div class="flex items-center justify-start p-1.5 cursor-pointer" v-if="row.Status === 'running' || row.Status === 'pending'" @click="action('cancel')">
          <n-icon
              size="28"
              style="color:var(--error);background:rgba(220,80,60,0.12)"
              class="rounded-full flex items-center justify-center p-1.5 cursor-pointer transition-colors hover:bg-[rgba(220,80,60,0.2)]"
          >
            <CloseOutline/>
          </n-icon>
          <span class="ml-1">{{ t("index.cancel_down") }}</span>
        </div>

        <div class="flex items-center justify-start p-1.5 cursor-pointer" @click="action('copy')">
          <n-icon
              size="28"
              style="color:var(--accent);background:rgba(201,100,66,0.12)"
              class="rounded-full flex items-center justify-center p-1.5 cursor-pointer transition-colors hover:bg-[rgba(201,100,66,0.2)]"
          >
            <LinkOutline/>
          </n-icon>
          <span class="ml-1">{{ t("index.copy_link") }}</span>
        </div>

        <div class="flex items-center justify-start p-1.5 cursor-pointer" v-if="row.Classify !== 'live' && row.Classify !== 'm3u8'" @click="action('open')">
          <n-icon
              size="28"
              style="color:var(--accent);background:rgba(201,100,66,0.12)"
              class="rounded-full flex items-center justify-center p-1.5 cursor-pointer transition-colors hover:bg-[rgba(201,100,66,0.2)]"
          >
            <GlobeOutline/>
          </n-icon>
          <span class="ml-1">{{ t("index.open_link") }}</span>
        </div>

        <div class="flex items-center justify-start p-1.5 cursor-pointer" v-if="row.DecodeKey" @click="action('decode')">
          <n-icon
              size="28"
              style="color:var(--accent);background:rgba(201,128,66,0.12)"
              class="rounded-full flex items-center justify-center p-1.5 cursor-pointer transition-colors hover:bg-[rgba(201,128,66,0.2)]"
          >
            <LockOpenSharp/>
          </n-icon>
          <span class="ml-1">{{ t("index.video_decode") }}</span>
        </div>

        <div class="flex items-center justify-start p-1.5 cursor-pointer" @click="action('json')">
          <n-icon
              size="28"
              style="color:var(--accent);background:rgba(201,100,66,0.12)"
              class="rounded-full flex items-center justify-center p-1.5 cursor-pointer transition-colors hover:bg-[rgba(201,100,66,0.2)]"
          >
            <CopyOutline/>
          </n-icon>
          <span class="ml-1">{{ t("index.copy_data") }}</span>
        </div>
      </div>
    </NPopover>
  </div>
</template>

<script setup lang="ts">
import {useI18n} from 'vue-i18n'
import {
  DownloadOutline,
  CopyOutline,
  GlobeOutline,
  LockOpenSharp,
  LinkOutline,
  GridSharp,
  CloseOutline,
  TrashOutline
} from "@vicons/ionicons5"

const {t} = useI18n()
const props = defineProps<{
  row: any,
  index: number,
}>()

const emits = defineEmits(["action"])

const action = (type: string) => {
  if (type === 'down' && (props.row.Classify === 'live' || props.row.Classify === 'm3u8')) {
    window?.$message?.error(t("index.download_no_tip"))
    return
  }
  emits('action', props.row, props.index, type)
}

</script>