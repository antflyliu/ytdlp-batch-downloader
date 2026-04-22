import './assets/css/main.css'

import {createApp} from 'vue'
import {createPinia} from 'pinia'
import i18n from './i18n'

import App from './App.vue'
import router from './router'

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)
app.use(router)
app.use(i18n)

// Global error handler
app.config.errorHandler = (err, instance, info) => {
  console.error('[Vue Error]', err, info)
}

app.mount('#app')
