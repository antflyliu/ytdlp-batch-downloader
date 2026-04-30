import {defineStore} from "pinia"
import {ref} from "vue"
import {EventsOn} from "../../wailsjs/runtime"
import {appType} from "@/types/app"

export const useEventStore = defineStore('ws-store', () => {
    const handles = ref<any>({})

    const init = () => {
        EventsOn("event", (res: any) => {
            const data = JSON.parse(res)
            if (handles.value.hasOwnProperty(data.type)) {
                handles.value[data.type](data.data)
            } else {
                console.warn("event: no handler for unknown event type")
            }
        })
    }

    const addHandle = (handle: appType.Handle) => {
        handles.value[handle.type] = handle.event
    }

    return {
        init, addHandle
    }
})