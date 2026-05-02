interface Window {
    $loadingBar?: import('naive-ui').LoadingBarProviderInst
    $dialog?: import('naive-ui').DialogProviderInst
    $message?: import('naive-ui').MessageProviderInst
    $notification?: import('naive-ui').NotificationProviderInst
    $baseUrl?: string
    pywebview?: {
        api?: {
            closeWithChoice?: (action: 'tray' | 'quit', remember: boolean) => Promise<unknown> | unknown
            requestClose?: () => Promise<unknown> | unknown
            setLocale?: (locale: string) => Promise<unknown> | unknown
            forceQuit?: () => Promise<unknown> | unknown
        }
    }
    __MONITOR_API_TOKEN__?: string
    __YTDLP_DESKTOP_CLOSE_READY__?: boolean
    __YTDLP_PENDING_DESKTOP_CLOSE__?: boolean
}

declare module '*.vue' {
    import {App, defineComponent} from 'vue'
    const component: ReturnType<typeof defineComponent> & {
        install(app: App): void
    }
    export default component
}
