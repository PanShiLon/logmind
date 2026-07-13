<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import LogExplorer from '../components/LogExplorer.vue'

// ── 直查页：只调 /api/logs/more（不经过 LLM），实时刷新 ──
const logData = ref({ total: 0, entries: [], took_ms: 0 })
const explorerRef = ref(null)
const loading = ref(false)
const errorMsg = ref('')

// 控件状态
const keyword = ref('')
const level = ref('')            // '' | ERROR | WARN | INFO | DEBUG
const rangeMin = ref(60)         // 时间窗（分钟）
const autoRefresh = ref(false)
const refreshSec = ref(5)
const lastUpdated = ref('')

const PAGE = 100
let timer = null

function rangeToISO() {
  const end = new Date()
  const start = new Date(end.getTime() - rangeMin.value * 60 * 1000)
  return { start_time: start.toISOString(), end_time: end.toISOString() }
}

async function fetchLogs(offset = 0) {
  loading.value = true
  errorMsg.value = ''
  const { start_time, end_time } = rangeToISO()
  try {
    const resp = await fetch('/api/logs/more', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query: keyword.value.trim(),
        level: level.value || null,
        start_time,
        end_time,
        offset,
        limit: PAGE,
      }),
    })
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const data = await resp.json()
    if (offset === 0) {
      logData.value = { total: data.total, entries: data.entries || [], took_ms: data.took_ms }
    } else {
      logData.value = {
        total: data.total,
        entries: [...logData.value.entries, ...(data.entries || [])],
        took_ms: data.took_ms,
      }
    }
    lastUpdated.value = new Date().toLocaleTimeString()
  } catch (e) {
    errorMsg.value = `查询失败：${e.message}（确认 Loki 在跑、config.yaml 是 loki 模式）`
  } finally {
    loading.value = false
    explorerRef.value?.onLoadComplete?.()
  }
}

function onLoadMore(offset) {
  fetchLogs(offset)
}

function applyFilters() {
  fetchLogs(0)
}

// 自动刷新：每 refreshSec 秒重拉第一页
function setupTimer() {
  if (timer) { clearInterval(timer); timer = null }
  if (autoRefresh.value) {
    timer = setInterval(() => fetchLogs(0), refreshSec.value * 1000)
  }
}
watch([autoRefresh, refreshSec], setupTimer)

// 主题（与 ChatView 一致）
const isDark = ref(localStorage.getItem('logmind-theme') !== 'light')
watch(isDark, v => {
  document.documentElement.setAttribute('data-theme', v ? 'dark' : 'light')
  localStorage.setItem('logmind-theme', v ? 'dark' : 'light')
}, { immediate: true })

onMounted(() => fetchLogs(0))
onUnmounted(() => { if (timer) clearInterval(timer) })
</script>

<template>
  <div class="explorer-view">
    <!-- 顶部工具条 -->
    <header class="ev-header">
      <div class="ev-title">
        <span class="ev-logo">📑</span>
        <span>日志直查</span>
        <span class="ev-badge" title="此页不调用 LLM，日志只在 你↔后端↔Loki 之间">🔒 不经过 AI</span>
      </div>
      <nav class="ev-nav">
        <span class="ev-updated" v-if="lastUpdated">更新于 {{ lastUpdated }}</span>
        <button class="ev-theme" @click="isDark = !isDark">{{ isDark ? '☀️' : '🌙' }}</button>
        <router-link class="ev-link" to="/chat">💬 AI 分析</router-link>
        <router-link class="ev-link" to="/http">🛰️ 接口测试</router-link>
        <router-link class="ev-link" to="/config">⚙️ 配置</router-link>
      </nav>
    </header>

    <!-- 控件区 -->
    <div class="ev-controls">
      <div class="ev-ctrl">
        <label>级别</label>
        <select v-model="level" @change="applyFilters">
          <option value="">全部级别</option>
          <option value="ERROR">只看错误</option>
          <option value="WARN">只看警告</option>
          <option value="INFO">INFO</option>
          <option value="DEBUG">DEBUG</option>
        </select>
      </div>
      <div class="ev-ctrl">
        <label>时间窗</label>
        <select v-model.number="rangeMin" @change="applyFilters">
          <option :value="15">最近 15 分钟</option>
          <option :value="60">最近 1 小时</option>
          <option :value="360">最近 6 小时</option>
          <option :value="1440">最近 24 小时</option>
        </select>
      </div>
      <div class="ev-ctrl ev-ctrl-search">
        <input
          v-model="keyword"
          placeholder="搜索关键词（支持正则），回车查询…"
          spellcheck="false"
          @keyup.enter="applyFilters"
        />
      </div>
      <button class="ev-search-btn" @click="applyFilters" :disabled="loading">
        {{ loading ? '查询中…' : '查询' }}
      </button>
      <div class="ev-ctrl ev-ctrl-auto">
        <label class="ev-switch">
          <input type="checkbox" v-model="autoRefresh" />
          <span>实时刷新</span>
        </label>
        <select v-model.number="refreshSec" v-if="autoRefresh" class="ev-refresh-sec">
          <option :value="5">5s</option>
          <option :value="10">10s</option>
          <option :value="30">30s</option>
        </select>
        <span class="ev-live-dot" v-if="autoRefresh" />
      </div>
    </div>

    <!-- 错误提示 -->
    <div class="ev-error" v-if="errorMsg">{{ errorMsg }}</div>

    <!-- 日志浏览器 -->
    <div class="ev-body">
      <LogExplorer ref="explorerRef" :data="logData" @load-more="onLoadMore" />
      <div class="ev-empty" v-if="!logData.entries.length && !loading">
        当前时间窗内无日志。试试放宽时间窗，或确认服务在产生日志。
      </div>
    </div>
  </div>
</template>

<style scoped>
.explorer-view {
  min-height: 100vh;
  background: var(--bg-app, #0a0c12);
  color: #e2e8f0;
  padding: 0 0 40px;
}
.ev-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 24px;
  border-bottom: 1px solid var(--border-log, #1e2535);
  position: sticky; top: 0; z-index: 10;
  background: var(--bg-app, #0a0c12);
}
.ev-title { display: flex; align-items: center; gap: 10px; font-size: 16px; font-weight: 700; }
.ev-logo { font-size: 20px; }
.ev-badge {
  font-size: 11px; font-weight: 600;
  background: rgba(34,197,94,.12); color: #22c55e;
  border: 1px solid rgba(34,197,94,.3);
  border-radius: 999px; padding: 3px 10px; margin-left: 6px;
}
.ev-nav { display: flex; align-items: center; gap: 14px; }
.ev-updated { font-size: 11px; color: #64748b; }
.ev-theme { background: none; border: none; cursor: pointer; font-size: 16px; }
.ev-link { color: #60a5fa; text-decoration: none; font-size: 13px; }
.ev-link:hover { text-decoration: underline; }

.ev-controls {
  display: flex; align-items: center; gap: 14px;
  padding: 14px 24px; flex-wrap: wrap;
  border-bottom: 1px solid var(--border-log, #1e2535);
}
.ev-ctrl { display: flex; align-items: center; gap: 6px; }
.ev-ctrl label { font-size: 12px; color: #94a3b8; font-weight: 600; white-space: nowrap; }
.ev-ctrl select, .ev-ctrl input {
  background: rgba(255,255,255,.06); border: 1px solid #2d3748;
  border-radius: 6px; color: #e2e8f0; padding: 6px 10px; font-size: 13px; outline: none;
}
.ev-ctrl select:focus, .ev-ctrl input:focus { border-color: #3b82f6; }
.ev-ctrl-search { flex: 1; min-width: 220px; }
.ev-ctrl-search input { width: 100%; }
.ev-search-btn {
  background: #3b82f6; color: #fff; border: none; border-radius: 6px;
  padding: 7px 18px; font-size: 13px; font-weight: 600; cursor: pointer;
}
.ev-search-btn:hover:not(:disabled) { background: #2563eb; }
.ev-search-btn:disabled { opacity: .6; cursor: not-allowed; }
.ev-ctrl-auto { gap: 8px; }
.ev-switch { display: flex; align-items: center; gap: 6px; cursor: pointer; }
.ev-switch input { width: auto; }
.ev-refresh-sec { padding: 4px 6px !important; }
.ev-live-dot {
  width: 8px; height: 8px; border-radius: 50%; background: #22c55e;
  animation: pulse 1.2s ease-in-out infinite;
}
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: .3; } }

.ev-error {
  margin: 14px 24px; padding: 10px 14px;
  background: rgba(239,68,68,.1); border: 1px solid rgba(239,68,68,.3);
  color: #fca5a5; border-radius: 6px; font-size: 13px;
}
.ev-body { padding: 8px 24px; }
.ev-empty { text-align: center; color: #64748b; padding: 40px; font-size: 14px; }

[data-theme="light"] .explorer-view { background: #f8fafc; color: #1e293b; }
[data-theme="light"] .ev-header { background: #f8fafc; border-color: #e2e8f0; }
[data-theme="light"] .ev-controls { border-color: #e2e8f0; }
[data-theme="light"] .ev-ctrl select, [data-theme="light"] .ev-ctrl input {
  background: #fff; border-color: #cbd5e0; color: #1e293b;
}
</style>
