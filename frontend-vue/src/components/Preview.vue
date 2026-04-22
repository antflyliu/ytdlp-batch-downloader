<template>
  <NModal
      :show="showModal"
      :on-update:show="changeShow"
      preset="card"
      class="w-[540px] h-auto"
      :title="t('index.preview')"
      display-directive="show"
      :on-after-enter="onAfterEnter"
      :on-after-leave="onAfterLeave"
  >
    <div class="flex justify-center w-full h-[80vh]">
      <video
          class="video-js vjs-default-skin w-full h-full"
          ref="videoPlayerRef"
          controls
          preload="auto"
      ></video>
    </div>
  </NModal>
</template>

<script setup lang="ts">
import { ref } from "vue"
import "video.js/dist/video-js.css"
import videojs from "video.js"
import flvjs from "flv.js"
import axios from "axios"
import { useI18n } from 'vue-i18n'
// @ts-ignore
import { getDecryptionArray } from '@/assets/js/decrypt.js'
import { useEncryptedPreview } from '@/composables/useEncryptedPreview'
import type Player from "video.js/dist/types/player"

const { t } = useI18n()
const videoPlayerRef = ref<HTMLElement | null>(null)
const { mediaSource, playerRef, dispose, sourceBuffer: sb } = useEncryptedPreview()

let player: Player | null = null
let flvPlayer: flvjs.Player | null = null
let isLoading = false
let isOver = false
let startByte = 0
const chunkSize = 5 * 1024 * 1024
let endByte = startByte + chunkSize - 1
let decodeArr: any = null
let rowUrl = ''

const API_BASE = 'http://127.0.0.1:5000'
const getToken = () => sessionStorage.getItem('monitor_api_token') || ''

const props = defineProps<{
  showModal: boolean
  previewRow: any
}>()
const emit = defineEmits(["update:showModal"])

const changeShow = (value: boolean) => emit("update:showModal", value)

const onAfterEnter = () => {
  playerRef.value = videoPlayerRef.value as HTMLVideoElement
  if (props.previewRow.DecodeKey) {
    playVideoWithoutTotalLength()
  } else if (props.previewRow.Classify === "live") {
    playFlvStream()
  } else {
    setupVideoJsPlayer()
  }
}

const onAfterLeave = () => {
  dispose()
  if (props.previewRow.Classify === "live" && flvPlayer) {
    flvPlayer.unload()
    flvPlayer.detachMediaElement()
    flvPlayer.destroy()
    flvPlayer = null
  } else if (player) {
    player.pause()
  }
  if (startByte) {
    videoPlayerRef.value?.pause()
    videoPlayerRef.value?.removeEventListener("seeking", handleSeeking)
    videoPlayerRef.value?.removeEventListener("timeupdate", handleTimeupdate)
  }
}

const buildUrlWithParams = (url: string) => {
  const parsedUrl = new URL(url)
  const queryParams = parsedUrl.searchParams
  if (queryParams.has("encfilekey") && queryParams.has("token")) {
    return `${parsedUrl.origin}${parsedUrl.pathname}?encfilekey=${queryParams.get("encfilekey")}&token=${queryParams.get("token")}`
  }
  return url
}

const playFlvStream = () => {
  try {
    if (!flvjs.isSupported() || !videoPlayerRef.value) return

    flvPlayer = flvjs.createPlayer({
      type: "flv",
      url: `${API_BASE}/api/preview?url=` + encodeURIComponent(props.previewRow.Url)
    })
    flvPlayer.attachMediaElement(videoPlayerRef.value)
    flvPlayer.load()
    flvPlayer.play()
  } catch (e) {
    // silent fail
  }
}

const setupVideoJsPlayer = () => {
  if (!videoPlayerRef.value) return

  if (!player) {
    player = videojs(videoPlayerRef.value, {
      controls: true,
      autoplay: false,
      preload: "auto",
    })
  }

  player.src({
    src: `${API_BASE}/api/preview?url=` + encodeURIComponent(props.previewRow.Url),
    type: props.previewRow.ContentType,
    withCredentials: true,
  })
  player.play()
}

const playVideoWithoutTotalLength = () => {
  rowUrl = `${API_BASE}/api/preview?url=` + encodeURIComponent(buildUrlWithParams(props.previewRow.Url))
  mediaSource.value = new MediaSource()
  if (videoPlayerRef.value) {
    videoPlayerRef.value.src = URL.createObjectURL(mediaSource.value)
    videoPlayerRef.value.play()
  }
  isOver = false
  startByte = 0
  endByte = startByte + chunkSize - 1
  decodeArr = getDecryptionArray(props.previewRow.DecodeKey)
  sb.value = null
  mediaSource.value.addEventListener("sourceopen", () => {
    sb.value = mediaSource.value!.addSourceBuffer('video/mp4; codecs="avc1.42E01E, mp4a.40.2"')
    downloadChunk()
  })

  videoPlayerRef.value?.addEventListener("seeking", handleSeeking)
  videoPlayerRef.value?.addEventListener("timeupdate", handleTimeupdate)
}

const handleSeeking = () => {
  if (!videoPlayerRef.value) return
  const currentTime = videoPlayerRef.value.currentTime
  const bufferedEnd = videoPlayerRef.value.buffered.end(videoPlayerRef.value.buffered.length - 1)

  if (currentTime > bufferedEnd && !isLoading && !isOver) {
    downloadChunk()
  }
}

const handleTimeupdate = () => {
  if (videoPlayerRef.value && videoPlayerRef.value.buffered.length > 0) {
    const bufferedEnd = videoPlayerRef.value.buffered.end(videoPlayerRef.value.buffered.length - 1)
    const timeToEnd = bufferedEnd - videoPlayerRef.value.currentTime

    if (timeToEnd < 10 && !isLoading && !isOver) {
      downloadChunk()
    }
  }
}

const downloadChunk = () => {
  if (sb.value?.updating) return

  isLoading = true
  try {
    axios.get(rowUrl, {
      headers: {
        Range: `bytes=${startByte}-${endByte}`,
        Authorization: `Bearer ${getToken()}`
      },
      responseType: 'arraybuffer'
    })
      .then(response => {
        let chunk = new Uint8Array(response.data)

        for (let i = 0; i < chunk.byteLength && startByte + i < decodeArr.length; i++) {
          chunk[i] ^= decodeArr[startByte + i]
        }

        startByte = endByte + 1
        endByte = startByte + chunkSize - 1

        if (sb.value && !sb.value.updating) {
          sb.value.appendBuffer(chunk)
        } else {
          console.error("SourceBuffer is updating, cannot append buffer right now.")
        }
        isLoading = false
        if (response.data.byteLength === 0) {
          isOver = true
          mediaSource.value?.endOfStream()
        }
      })
      .catch(() => {
        isLoading = false
        isOver = true
      })
  } catch (e) {
    isLoading = false
    isOver = true
  }
}
</script>