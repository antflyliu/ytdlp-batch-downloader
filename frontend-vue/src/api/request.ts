import axios from 'axios'

/**
 * 默认同源：页面与 API 由同一 MonitorHandler 提供（如 monitor_ui.py --port 4999）。
 * 仅当需要固定跨端口时再设置 VITE_API_BASE（例如独立运行 python -m server --port 5000）。
 */
const API_BASE = import.meta.env.VITE_API_BASE || ''

/** 占位导出：Monitor HTTP API 已不做 Bearer 或查询参数鉴权 */
export function _getToken(): string {
  return ''
}

/** 占位：不再持久化 Monitor API token */
export function _saveToken(_token: string): void {}

const request = axios.create({
  baseURL: API_BASE,
  timeout: 30000,
})

export default request
