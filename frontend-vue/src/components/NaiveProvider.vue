<template>
  <NLoadingBarProvider>
    <NDialogProvider>
      <NNotificationProvider>
        <NMessageProvider>
          <NaiveProviderBridge />
          <slot></slot>
        </NMessageProvider>
      </NNotificationProvider>
    </NDialogProvider>
  </NLoadingBarProvider>
</template>

<script setup lang="ts">
import {defineComponent, onMounted} from "vue"
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

const NaiveProviderBridge = defineComponent({
  name: 'NaiveProviderBridge',
  setup() {
    const loadingBar = useLoadingBar()
    const dialog = useDialog()
    const message = useMessage()
    const notification = useNotification()

    onMounted(() => {
      window.$loadingBar = loadingBar
      window.$dialog = dialog
      window.$message = message
      window.$notification = notification
    })

    return () => null
  },
})
</script>
