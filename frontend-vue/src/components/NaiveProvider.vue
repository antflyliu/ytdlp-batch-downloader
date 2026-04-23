<template>
  <NLoadingBarProvider>
    <NDialogProvider>
      <NNotificationProvider>
        <NMessageProvider>
          <slot></slot>
        </NMessageProvider>
      </NNotificationProvider>
    </NDialogProvider>
  </NLoadingBarProvider>
</template>

<script setup lang="ts">
import {onMounted} from "vue"
import {
  NLoadingBarProvider,
  NDialogProvider,
  NNotificationProvider,
  NMessageProvider,
  useLoadingBar,
  useDialog,
  useMessage,
  useNotification,
} from "naive-ui"

function registerNaiveTools() {
  const loadingBar = useLoadingBar()
  const dialog = useDialog()
  const message = useMessage()
  const notification = useNotification()
  window.$loadingBar = loadingBar
  window.$dialog = dialog
  window.$message = message
  window.$notification = notification
}

onMounted(() => {
  registerNaiveTools()
})
</script>
