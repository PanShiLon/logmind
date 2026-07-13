import { createRouter, createWebHistory } from 'vue-router'
import ExplorerView from '../views/ExplorerView.vue'
import ChatView from '../views/ChatView.vue'
import ConfigView from '../views/ConfigView.vue'
import HttpTesterView from '../views/HttpTesterView.vue'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: ExplorerView },   // 落地页：纯直查、实时、零 LLM
    { path: '/chat', component: ChatView },    // AI 分析（按需，会发日志给 LLM）
    { path: '/http', component: HttpTesterView }, // 接口测试：平台内发 HTTP 请求
    { path: '/config', component: ConfigView },
  ],
})
