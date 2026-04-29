import { shallowRef, onBeforeUnmount } from 'vue'

export function useEncryptedPreview() {
  const mediaSource = shallowRef<MediaSource | null>(null)
  const playerRef = shallowRef<HTMLVideoElement | null>(null)
  const sourceBuffer = shallowRef<SourceBuffer | null>(null)

  const dispose = () => {
    if (sourceBuffer.value) {
      try { sourceBuffer.value.abort() } catch {}
      sourceBuffer.value = null
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
