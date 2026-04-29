# Resource Sniffer Vue Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate resource sniffer frontend from res-downloader Vue to ytdlp-batch-downloader Vue SPA, replacing the legacy `monitor_web/` resources page. Go proxy stays as subprocess, Python Flask serves as API gateway.

**Architecture:**
- `frontend-vue/` — new Vue 3 SPA project (source)
- `frontend-vue/dist/` — Vite build output, Flask serves as static files
- `monitor_web/` — backup only, not deleted until Phase 4
- Event pipeline: Go WS → Python WS client → Flask SSE → Browser EventSource

**Tech Stack:** Vue 3.4 + Vite 5 + Naive UI 2.38.2 + Pinia + Tailwind + TypeScript + vue-i18n

---

## Phase 0: Project Setup & Source File Acquisition

**Goal:** Create `frontend-vue/` project structure and copy source files from res-downloader.

### 0.1 — Create frontend-vue directory structure

**Files:**
- Create: `frontend-vue/package.json`
- Create: `frontend-vue/vite.config.ts`
- Create: `frontend-vue/tailwind.config.js`
- Create: `frontend-vue/postcss.config.js`
- Create: `frontend-vue/tsconfig.json`
- Create: `frontend-vue/index.html`
- Create: `frontend-vue/src/vite-env.d.ts`

- [ ] **Step 1: Create frontend-vue/package.json with locked versions**

```json
{
  "name": "frontend-vue",
  "version": "1.0.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vue-tsc && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "vue": "3.4.0",
    "naive-ui": "2.38.2",
    "pinia": "2.1.0",
    "vue-router": "4.3.0",
    "vue-i18n": "9.10.0",
    "axios": "1.6.0",
    "video.js": "8.10.0",
    "flv.js": "0.8.0"
  },
  "devDependencies": {
    "@vitejs/plugin-vue": "5.0.0",
    "vite": "5.2.0",
    "tailwindcss": "3.4.0",
    "postcss": "8.4.0",
    "autoprefixer": "10.4.0",
    "typescript": "5.4.0",
    "vue-tsc": "2.0.0"
  }
}
```

- [ ] **Step 2: Create vite.config.ts**

```typescript
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src')
    }
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true
      }
    }
  },
  build: {
    outDir: 'dist',
    assetsDir: 'static'
  }
})
```

- [ ] **Step 3: Create tsconfig.json, tailwind.config.js, postcss.config.js, index.html**

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "module": "ESNext",
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "preserve",
    "strict": true,
    "noUnusedLocals": false,
    "noUnusedParameters": false,
    "noFallthroughCasesInSwitch": true,
    "baseUrl": ".",
    "paths": {
      "@/*": ["src/*"]
    }
  },
  "include": ["src/**/*.ts", "src/**/*.tsx", "src/**/*.vue"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

- [ ] **Step 4: Create index.html with hash router bootstrap**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Resource Sniffer</title>
</head>
<body>
  <div id="app"></div>
  <script type="module" src="/src/main.ts"></script>
</body>
</html>
```

- [ ] **Step 5: Copy source files from res-downloader**

```bash
cp -r D:/WORKSPACE/video-download-space/res-downloader/frontend/src/views    frontend-vue/src/
cp -r D:/WORKSPACE/video-download-space/res-downloader/frontend/src/components frontend-vue/src/
cp -r D:/WORKSPACE/video-download-space/res-downloader/frontend/src/api     frontend-vue/src/
cp -r D:/WORKSPACE/video-download-space/res-downloader/frontend/src/stores  frontend-vue/src/
cp -r D:/WORKSPACE/video-download-space/res-downloader/frontend/src/types  frontend-vue/src/
cp -r D:/WORKSPACE/video-download-space/res-downloader/frontend/src/assets frontend-vue/src/
cp -r D:/WORKSPACE/video-download-space/res-downloader/frontend/src/router  frontend-vue/src/
cp   D:/WORKSPACE/video-download-space/res-downloader/frontend/src/App.vue   frontend-vue/src/
cp   D:/WORKSPACE/video-download-space/res-downloader/frontend/src/main.ts  frontend-vue/src/
cp   D:/WORKSPACE/video-download-space/res-downloader/frontend/src/i18n.ts  frontend-vue/src/
cp   D:/WORKSPACE/video-download-space/res-downloader/frontend/src/func.ts  frontend-vue/src/
```

- [ ] **Step 6: Install dependencies**

Run: `cd frontend-vue && npm install`
Expected: `node_modules/` created, no errors

- [ ] **Step 7: Verify build**

Run: `cd frontend-vue && npm run build`
Expected: `frontend-vue/dist/index.html` exists

- [ ] **Step 8: Commit Phase 0**

```bash
git add frontend-vue/
git commit -m "feat(res-sniffer): Phase 0 - frontend-vue project setup"
```

---

## Phase 1: Flask Serves Vue SPA + SSE EventSource Integration

**Goal:** Flask serves `frontend-vue/dist/` and `/api/res-events` SSE endpoint works.

### 1.1 — Modify Flask to serve Vue SPA

**Files:**
- Modify: `server/__main__.py` (add Vue SPA fallback routes, before static file routes)

- [ ] **Step 1: Add Vue SPA fallback routes to server/__main__.py**

Add before existing static file handler (`_add_static_file_handler` or similar):

```python
# Vue SPA fallback — all non-API routes return index.html
@app.route('/<path:fallback>')
def vue_spa_fallback(fallback):
    if fallback.startswith('api/'):
        return "Not Found", 404
    return send_from_directory(os.path.join(self._project_root, 'frontend-vue', 'dist'), fallback)

@app.route('/')
def vue_index():
    return send_from_directory(os.path.join(self._project_root, 'frontend-vue', 'dist'), 'index.html')
```

- [ ] **Step 2: Verify Vue SPA is served**

Start Flask, visit http://127.0.0.1:5000/
Expected: Vue index.html loads (not Flask Jinja template)

- [ ] **Step 3: Verify no regression in existing routes**

Run: `curl http://127.0.0.1:5000/api/proxy/status`
Expected: JSON response (proxy status)

### 1.2 — Create Pinia event store with SSE EventSource

**Files:**
- Create: `frontend-vue/src/stores/eventStore.ts`
- Create: `frontend-vue/src/stores/resourceStore.ts`

- [ ] **Step 1: Create eventStore.ts**

```typescript
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
        const eventData = msg.data?.data || msg.data  // double-unwrap for newResources
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

  const addHandle = (type: string, handler: (data: unknown) => void) {
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
```

- [ ] **Step 2: Create resourceStore.ts**

```typescript
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'

export interface MediaInfo {
  Id: string
  Url: string
  UrlSign: string
  CoverUrl?: string
  Size: number
  Domain: string
  Classify: string  // video/audio/image
  Suffix: string
  SavePath?: string
  Status: string
  DecodeKey?: string
  Description?: string
  ContentType?: string
  OtherData?: Record<string, string>
}

export const useResourceStore = defineStore('resource', () => {
  const resources = ref<MediaInfo[]>([])
  const downloadQueue = ref<MediaInfo[]>([])
  const isLoading = ref(false)

  // Filter: video/audio/image/all
  const filter = ref<'all' | 'video' | 'audio' | 'image'>('all')

  const filteredResources = computed(() => {
    if (filter.value === 'all') return resources.value
    return resources.value.filter(r => r.Classify === filter.value)
  })

  const addResources = (newItems: MediaInfo[]) => {
    // Avoid duplicates by UrlSign
    const existingSigns = new Set(resources.value.map(r => r.UrlSign))
    const unique = newItems.filter(item => !existingSigns.has(item.UrlSign))
    resources.value.push(...unique)
    // Cap at 2000 to prevent reactive degradation
    if (resources.value.length > 2000) {
      resources.value.splice(0, resources.value.length - 2000)
    }
  }

  const removeResource = (urlSign: string) => {
    resources.value = resources.value.filter(r => r.UrlSign !== urlSign)
  }

  const setFilter = (f: typeof filter.value) => {
    filter.value = f
  }

  // Persist to localStorage
  const saveToStorage = () => {
    localStorage.setItem('resources_v1', JSON.stringify(resources.value))
  }

  const loadFromStorage = () => {
    const stored = localStorage.getItem('resources_v1')
    if (stored) {
      try {
        resources.value = JSON.parse(stored)
      } catch {
        resources.value = []
      }
    }
  }

  return {
    resources, downloadQueue, isLoading, filter,
    filteredResources, addResources, removeResource,
    setFilter, saveToStorage, loadFromStorage
  }
})
```

- [ ] **Step 3: Wire SSE event to Pinia in App.vue or main.ts**

In `main.ts` or `App.vue` setup:

```typescript
// After Pinia init, load persisted resources and start SSE
resourceStore.loadFromStorage()

// Get token from Flask's injected token (Flask injects into HTML at serve time)
const token = (window as any).__MONITOR_API_TOKEN__ || sessionStorage.getItem('monitor_api_token') || ''

// Register handlers before init
eventStore.addHandle('newResources', (data) => {
  // data is MediaInfo[] from Go's send() data field
  const items = Array.isArray(data) ? data : [data]
  resourceStore.addResources(items)
  resourceStore.saveToStorage()
})

eventStore.addHandle('downloadProgress', (data: any) => {
  // Update download progress UI
  const row = document.querySelector(`[data-url-sign="${data.Id}"]`)
  if (row) {
    // Update progress bar
  }
})

// Start SSE connection
eventStore.init(token)
```

- [ ] **Step 4: Commit Phase 1**

```bash
git add server/__main__.py frontend-vue/src/stores/
git commit -m "feat(res-sniffer): Phase 1 - Flask serves Vue SPA, SSE event store wired"
```

---

## Phase 2: Core Feature Migration

**Goal:** Preview, resource list, and download all functional.

### 2.1 — Migrate and adapt Preview.vue

**Files:**
- Create: `frontend-vue/src/components/Preview.vue` (adapted from res-downloader)
- Modify: `frontend-vue/src/main.ts` (register Preview component globally or import)

- [ ] **Step 1: Adapt Preview.vue for Flask proxy (not Wails runtime)**

Key changes vs res-downloader source:
- Remove `wailsjs/runtime` imports (no Wails in ytdlp)
- Replace `window.$baseUrl` with Flask base URL (configurable, defaults to `http://127.0.0.1:5000`)
- Add `useEncryptedPreview()` composable for MediaSource cleanup
- SourceBuffer abort on navigate away

```typescript
// composables/useEncryptedPreview.ts
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

  return { mediaSource, playerRef, dispose }
}
```

- [ ] **Step 2: Modify api/request.ts to use Flask baseURL**

```typescript
// axios instance configured for Flask proxy
import axios from 'axios'

const request = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || 'http://127.0.0.1:5000',
  timeout: 30000,
})

request.interceptors.request.use(config => {
  const token = sessionStorage.getItem('monitor_api_token')
  if (token) {
    config.params = { ...config.params, api_token: token }
  }
  return config
})

export default request
```

- [ ] **Step 3: Verify preview works for all three modes**
- Normal: video.js loads
- FLV: flv.js plays live stream
- Encrypted: MediaSource streams with XOR decryption

### 2.2 — Migrate ResourceIndex.vue (resource list with filters)

**Files:**
- Create: `frontend-vue/src/views/ResourceIndex.vue`
- Modify: `frontend-vue/src/stores/resourceStore.ts` (add filter logic)

- [ ] **Step 1: Create ResourceIndex.vue with NDataTable + filter pills**

```vue
<template>
  <div class="resource-index">
    <!-- Filter pills -->
    <div class="filter-bar">
      <NButtonGroup>
        <NButton
          v-for="f in ['all', 'video', 'audio', 'image']"
          :key="f"
          :type="filter === f ? 'primary' : 'default'"
          @click="setFilter(f)"
        >
          {{ t(`filter.${f}`) }}
        </NButton>
      </NButtonGroup>
    </div>

    <!-- Resource table -->
    <NDataTable
      :columns="columns"
      :data="filteredResources"
      :pagination="{ pageSize: 20 }"
      :virtual="true"
      row-key="UrlSign"
    />
  </div>
</template>
```

- [ ] **Step 2: Add filter i18n keys**

Add to `frontend-vue/src/i18n.ts`:
```typescript
filter: { all: '全部', video: '视频', audio: '音频', image: '图片' }
```

### 2.3 — Migrate ResourceAction.vue (download/delete buttons)

**Files:**
- Create: `frontend-vue/src/components/ResourceAction.vue`

- [ ] **Step 1: Create ResourceAction.vue with download logic**

```typescript
const handleDownload = async (row: MediaInfo) => {
  try {
    const resp = await axios.post('/api/res/download', {
      url: row.Url,
      savePath: row.SavePath,
      // ... full mediaInfo
    })
    if (resp.data.code === 1) {
      message.success(t('download.success'))
    }
  } catch (e) {
    message.error(t('download.failed'))
  }
}
```

### 2.4 — Download queue with localStorage persistence

**Files:**
- Modify: `frontend-vue/src/stores/resourceStore.ts` (add queue persistence)

- [ ] **Step 1: Persist downloadQueue to localStorage**

```typescript
const saveQueueToStorage = () => {
  localStorage.setItem('download_queue_v1', JSON.stringify(downloadQueue.value))
}

const loadQueueFromStorage = () => {
  const stored = localStorage.getItem('download_queue_v1')
  if (stored) {
    try {
      downloadQueue.value = JSON.parse(stored)
    } catch {}
  }
}

// Call saveQueueToStorage() after every queue mutation
```

- [ ] **Step 2: Commit Phase 2**

```bash
git add frontend-vue/src/components/ frontend-vue/src/views/ frontend-vue/src/composables/ frontend-vue/src/stores/
git commit -m "feat(res-sniffer): Phase 2 - Preview, resource list, download queue"
```

---

## Phase 3: Settings & Download Directory Sync

**Goal:** Settings page saves `SaveDirectory` to Python config.json, Flask syncs to Go.

### 3.1 — Create Settings.vue

**Files:**
- Create: `frontend-vue/src/views/Settings.vue`

- [ ] **Step 1: Create Settings.vue with SaveDirectory persistence**

```vue
<script setup lang="ts">
const saveDirectory = ref('')

const loadSettings = async () => {
  const resp = await axios.get('/api/proxy/config')
  saveDirectory.value = resp.data.SaveDirectory || ''
}

const saveSettings = async () => {
  // Save to Python config.json via Flask
  await axios.post('/api/config', { download_output_path: saveDirectory.value })
  // Flask syncs to Go via POST /api/proxy/config
  await axios.post('/api/proxy/config', { SaveDirectory: saveDirectory.value })
  message.success(t('settings.saved'))
}
</script>
```

### 3.2 — Modify Flask config save to also sync to Go

**Files:**
- Modify: `server/__main__.py` (ensure config save also calls Go proxy config)

- [ ] **Step 1: Verify POST /api/proxy/config forwards SaveDirectory to Go**

In `_api_proxy_config_update()` or wherever config is saved, ensure it forwards to Go's `/api/set-config`.

### 3.3 — ImportJson.vue (batch import)

**Files:**
- Create: `frontend-vue/src/components/ImportJson.vue`

- [ ] **Step 1: Create ImportJson.vue for JSON batch import**

### 3.4 — Commit Phase 3

```bash
git add frontend-vue/src/views/Settings.vue frontend-vue/src/components/ImportJson.vue
git add server/__main__.py
git commit -m "feat(res-sniffer): Phase 3 - Settings, SaveDirectory sync, batch import"
```

---

## Phase 4: Cleanup & Regression

**Goal:** Verify all acceptance criteria, backup old resources.js, no regression.

### 4.1 — Regression testing against acceptance criteria

| # | Criterion | Verification |
|---|-----------|---------------|
| 1 | SSE connects, newResources fires within 1s | Open resources page, observe table |
| 2 | Filter pills (video/audio/image) switch data | Click each filter, verify count changes |
| 3 | Normal preview plays via video.js | Click non-encrypted row, verify player |
| 4 | Encrypted preview decrypts and plays | Click DecodeKey row, verify MediaSource |
| 5 | Download writes to SaveDirectory | Trigger download, verify file exists |
| 6 | localStorage persists resources on refresh | Refresh, verify table repopulated |
| 7 | Download queue persists on refresh | Add to queue, refresh, verify queue |
| 8 | SaveDirectory survives Flask restart | Change path, restart, verify Go has it |

### 4.2 — Backup legacy resources page

- [ ] **Step 1: Rename legacy resources page**

```bash
mv monitor_web/templates/pages/resources.html monitor_web/templates/pages/resources.html.bak
mv monitor_web/js/modules/resources.js monitor_web/js/modules/resources.js.bak
```

### 4.3 — Final commit

```bash
git add -A
git commit -m "feat(res-sniffer): Phase 4 - Complete migration, legacy backed up"
```

---

## File Manifest

| File | Action | Responsibility |
|------|--------|----------------|
| `frontend-vue/package.json` | Create | Project config + locked deps |
| `frontend-vue/vite.config.ts` | Create | Vite build + Flask proxy |
| `frontend-vue/src/stores/eventStore.ts` | Create | SSE EventSource + Pinia |
| `frontend-vue/src/stores/resourceStore.ts` | Create | Resource list + queue + localStorage |
| `frontend-vue/src/composables/useEncryptedPreview.ts` | Create | MediaSource lifecycle |
| `frontend-vue/src/components/Preview.vue` | Adapt | Three-mode preview player |
| `frontend-vue/src/views/ResourceIndex.vue` | Create | NDataTable + filter pills |
| `frontend-vue/src/components/ResourceAction.vue` | Create | Download/delete/action buttons |
| `frontend-vue/src/views/Settings.vue` | Create | SaveDirectory settings |
| `frontend-vue/src/components/ImportJson.vue` | Create | JSON batch import |
| `server/__main__.py` | Modify | Serve Vue SPA + SSE endpoint |
| `monitor_web/templates/pages/resources.html` | Backup | Legacy resources page |
| `monitor_web/js/modules/resources.js` | Backup | Legacy event handler |

## API Route Map (Flask → Go)

| Flask Route | Go Endpoint | Purpose |
|-------------|-------------|---------|
| `GET /api/res-events` | — (Python SSE) | Browser SSE stream |
| `POST /api/res/download` | `GET /api/download` | Trigger download |
| `GET /api/res/preview?url=` | `GET /api/preview?url=` | Non-encrypted preview proxy |
| `GET /api/res/preview/encrypted` | — (browser-side) | Encrypted preview (browser XOR) |
| `POST /api/proxy/config` | `POST /api/set-config` | Sync SaveDirectory to Go |
| `GET /api/proxy/config` | `GET /api/config` | Read Go config |
| `POST /api/proxy/system-proxy` | `POST /api/system-proxy` | System proxy toggle |

---

## Key Behavioral Notes

1. **Event shape**: Go emits `{"type": "newResources", "data": {...}}`. Python broadcasts as-is. Browser double-unwrap: `msg.data?.data`.
2. **EventSource auth**: Pass `?api_token=` since headers unsupported. Flask `_require_auth()` handles it.
3. **SaveDirectory sync**: Python config.json authoritative. Flask pushes to Go on config save. Go only reads from memory.
4. **decrypt.js**: Independent maintenance. Two copies (frontend-vue + monitor_web). No auto-sync.
5. **MediaSource cleanup**: Must call `dispose()` via `useEncryptedPreview()` composable. No relying on GC.