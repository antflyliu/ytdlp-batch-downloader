import {createRouter, createWebHashHistory} from 'vue-router'

const routes = [
  {
    path: "/",
    name: "layout",
    component: () => import("@/components/layout/Index.vue"),
    redirect: "/index",
    children: [
      {
        path: "/index",
        name: "index",
        meta: {keepAlive: true},
        component: () => import("@/views/ResourceIndex.vue"),
      },
      {
        path: "/setting",
        name: "setting",
        meta: {keepAlive: false},
        component: () => import("@/views/Settings.vue"),
      },
    ]
  },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes
})

export default router
