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
    // Always add as query param — works for both GET and POST
    config.params = { ...config.params, api_token: token }
    // For POST/PUT/DELETE, also add as Authorization header
    if (['post', 'put', 'delete'].includes(config.method?.toLowerCase() || '')) {
      config.headers.Authorization = `Bearer ${token}`
    }
  }
  return config
})

export default request