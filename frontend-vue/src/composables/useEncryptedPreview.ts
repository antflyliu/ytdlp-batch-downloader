import { shallowRef, onBeforeUnmount } from 'vue'

let sourceBuffer: SourceBuffer | null = null

export function useEncryptedPreview() {
  const mediaSource = shallowRef<MediaSource | null>(null)
  const playerRef = shallowRef<HTMLVideoElement | null>(null)

  const dispose = () => {
    if (sourceBuffer) {
      try { sourceBuffer.abort() } catch {}
      sourceBuffer = null
    }
    if (mediaSource.value) {
      try { mediaSource.value.endOfStream() } catch {}
    }
    if (playerRef.value && playerRef.value.src) {
      URL.revokeObjectURL(playerRef.value.src)
    }
    mediaSource.value = null
  }

  onBeforeUnmount(dispose)

  return { mediaSource, playerRef, dispose, sourceBuffer }
}