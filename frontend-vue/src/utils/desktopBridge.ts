export type DesktopCloseAction = 'tray' | 'quit'

export interface DesktopCloseChoice {
  action: DesktopCloseAction
  remember: boolean
}

interface DesktopBridgeApi {
  closeWithChoice?: (action: DesktopCloseAction, remember: boolean) => Promise<unknown> | unknown
  requestClose?: () => Promise<unknown> | unknown
  setLocale?: (locale: string) => Promise<unknown> | unknown
  forceQuit?: () => Promise<unknown> | unknown
}

export function getDesktopBridge(): DesktopBridgeApi | undefined {
  return window.pywebview?.api
}

function isBridgeOk(result: unknown): boolean {
  return !(result && typeof result === 'object' && 'ok' in result && result.ok === false)
}

function dispatchDesktopCloseRequest(): boolean {
  if (!window.__YTDLP_DESKTOP_CLOSE_READY__ || !window.dispatchEvent) {
    return false
  }

  const event = new CustomEvent('desktop-close-request')
  window.dispatchEvent(event)
  return true
}

export async function closeWithDesktopChoice(choice: DesktopCloseChoice): Promise<boolean> {
  const bridge = getDesktopBridge()
  if (!bridge?.closeWithChoice) return false

  try {
    const result = await bridge.closeWithChoice(choice.action, choice.remember)
    return isBridgeOk(result)
  } catch (error) {
    console.warn('[desktop-close] Failed to apply close choice', error)
    return false
  }
}

export async function requestDesktopClose(): Promise<boolean> {
  if (dispatchDesktopCloseRequest()) return true

  const bridge = getDesktopBridge()
  if (!bridge?.requestClose) return false

  try {
    const result = await bridge.requestClose()
    return isBridgeOk(result)
  } catch (error) {
    console.warn('[desktop-close] Failed to request desktop close', error)
    return false
  }
}

export async function setDesktopCloseLocale(locale: string): Promise<boolean> {
  const bridge = getDesktopBridge()
  if (!bridge?.setLocale) return false

  try {
    const result = await bridge.setLocale(locale)
    return isBridgeOk(result)
  } catch (error) {
    console.warn('[desktop-close] Failed to sync desktop close locale', error)
    return false
  }
}

export async function forceQuitDesktop(): Promise<boolean> {
  const bridge = getDesktopBridge()
  if (!bridge?.forceQuit) return false

  try {
    const result = await bridge.forceQuit()
    return isBridgeOk(result)
  } catch (error) {
    console.warn('[desktop-close] Failed to force desktop quit', error)
    return false
  }
}
