import axios from 'axios'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:5000'

const request = axios.create({
  baseURL: API_BASE,
  timeout: 30000,
})

// Inject auth token into every request
request.interceptors.request.use(config => {
  const token = (window as any).__MONITOR_API_TOKEN__ || ''
  if (token) {
    // For GET, add as query param; for POST, add as header
    if (config.method === 'get') {
      config.params = { ...config.params, api_token: token }
    } else {
      config.headers.Authorization = `Bearer ${token}`
    }
  }
  return config
})

export default request