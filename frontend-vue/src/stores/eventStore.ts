import { defineStore } from 'pinia'
import { ref, shallowRef } from 'vue'

interface EventHandlers {
  [type: string]: (data: unknown) => void
}

export const useEventStore = defineStore('event', () => {
  const handles = ref<EventHandlers>({}) as EventHandlers
  // Use shallowRef for EventSource to avoid deep reactivity overhead
  const eventSourceRef = shallowRef<EventSource | null>(null)
  const reconnectAttempt = ref(0)

  const init = (token: string) => {
    // Close existing connection before creating new one
    eventSourceRef.value?.close()

    const url = `/api/res-events?api_token=${encodeURIComponent(token)}`
    const es = new EventSource(url)

    es.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data)
        // Go send() wraps as {type, data} — not {event, data}
        const eventType = msg.type || msg.event
        // Double-unwrap: Go's send() data field may itself contain a JSON string or object
        const eventData = msg.data?.data || msg.data
        const handler = handles.value[eventType]
        if (handler) {
          handler(eventData)
        } else {
          console.warn(`[eventStore] No handler for event: ${eventType}`)
        }
      } catch (err) {
        console.error('[eventStore] Failed to parse SSE message:', err)
      }
    }

    es.onerror = () => {
      console.error('[eventStore] SSE error, reconnecting...')
      es.close()
      // Exponential back-off: min(30s, 1s * 2^attempt)
      const delay = Math.min(30_000, 1000 * Math.pow(2, reconnectAttempt.value))
      reconnectAttempt.value++
      setTimeout(() => init(token), delay)
    }

    eventSourceRef.value = es
    reconnectAttempt.value = 0
  }

  const addHandle = (type: string, handler: (data: unknown) => void) => {
    if (handles.value[type]) {
      console.warn(`[eventStore] Overwriting existing handler for: ${type}`)
    }
    handles.value[type] = handler
  }

  const removeHandle = (type: string) => {
    delete handles.value[type]
  }

  const dispose = () => {
    eventSourceRef.value?.close()
    eventSourceRef.value = null
  }

  return { init, addHandle, removeHandle, dispose, handles }
})