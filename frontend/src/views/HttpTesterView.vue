<script setup>
import { ref, computed, reactive, watch, onMounted } from 'vue'
import hljs from 'highlight.js/lib/core'
import json from 'highlight.js/lib/languages/json'
import xml from 'highlight.js/lib/languages/xml'
import 'highlight.js/styles/atom-one-dark.css'
import { parseCurl } from '../utils/parseCurl'

hljs.registerLanguage('json', json)
hljs.registerLanguage('xml', xml)

const METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS']
const HISTORY_KEY = 'logmind-http-history'

// ── 请求编辑区 ──
const method = ref('GET')
const url = ref('')
const headers = ref([{ key: '', value: '', on: true }])
const params = ref([{ key: '', value: '', on: true }])
const body = ref('')
const timeout = ref(20)
const reqTab = ref('params')   // params | headers | body
const hasBody = computed(() => !['GET', 'HEAD'].includes(method.value))

// ── 响应 ──
const loading = ref(false)
const resp = ref(null)
const errorMsg = ref('')
const respTab = ref('body')    // body | headers
const copied = ref(false)

// ── curl 弹层 ──
const showCurl = ref(false)
const curlText = ref('')
const curlErr = ref('')

// ── 设置面板（白名单/开关）──
const showSettings = ref(false)
const cfg = reactive({ enabled: true, allow_hosts: [] })
const allowInput = ref('')
const cfgSaving = ref(false)
const cfgMsg = ref('')

// ── 请求历史 ──
const history = ref([])
const showHistory = ref(false)

function loadHistory() {
  try { history.value = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]') } catch { history.value = [] }
}
function pushHistory(entry) {
  const list = history.value.filter(h => !(h.method === entry.method && h.url === entry.url))
  list.unshift(entry)
  history.value = list.slice(0, 15)
  localStorage.setItem(HISTORY_KEY, JSON.stringify(history.value))
}
function applyHistory(h) {
  method.value = h.method
  url.value = h.url
  headers.value = h.headers?.length ? h.headers.map(x => ({ ...x })) : [{ key: '', value: '', on: true }]
  body.value = h.body || ''
  syncParamsFromUrl()
  showHistory.value = false
}
function clearHistory() {
  history.value = []
  localStorage.removeItem(HISTORY_KEY)
}

// ── 行编辑辅助 ──
function ensureTrailing(list) {
  const last = list[list.length - 1]
  if (!last || last.key || last.value) list.push({ key: '', value: '', on: true })
}
function removeRow(list, i) {
  list.splice(i, 1)
  if (!list.length) list.push({ key: '', value: '', on: true })
}
watch(headers, l => ensureTrailing(l), { deep: true })
watch(params, l => { ensureTrailing(l); syncUrlFromParams() }, { deep: true })

// ── Params ↔ URL 双向同步 ──
let syncing = false
function syncParamsFromUrl() {
  if (syncing) return
  syncing = true
  try {
    const q = url.value.split('?')[1] || ''
    const rows = []
    if (q) {
      for (const pair of q.split('&')) {
        if (!pair) continue
        const idx = pair.indexOf('=')
        const k = idx === -1 ? pair : pair.slice(0, idx)
        const v = idx === -1 ? '' : pair.slice(idx + 1)
        try { rows.push({ key: decodeURIComponent(k), value: decodeURIComponent(v), on: true }) }
        catch { rows.push({ key: k, value: v, on: true }) }
      }
    }
    rows.push({ key: '', value: '', on: true })
    params.value = rows
  } finally { syncing = false }
}
function syncUrlFromParams() {
  if (syncing) return
  syncing = true
  try {
    const base = url.value.split('?')[0]
    const active = params.value.filter(p => p.on && p.key)
    const qs = active.map(p => `${encodeURIComponent(p.key)}=${encodeURIComponent(p.value)}`).join('&')
    url.value = qs ? `${base}?${qs}` : base
  } finally { syncing = false }
}

// ── 发送 ──
function headersToObject() {
  const obj = {}
  for (const h of headers.value) {
    const k = (h.key || '').trim()
    if (k && h.on !== false) obj[k] = h.value || ''
  }
  return obj
}

async function send() {
  if (!url.value.trim()) { errorMsg.value = '请填写 URL'; return }
  loading.value = true
  errorMsg.value = ''
  resp.value = null
  try {
    const r = await fetch('/api/http/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        method: method.value,
        url: url.value.trim(),
        headers: headersToObject(),
        body: hasBody.value && body.value ? body.value : null,
        timeout: Number(timeout.value) || 20,
      }),
    })
    const data = await r.json()
    if (!r.ok) { errorMsg.value = data.detail || `请求被拒绝（HTTP ${r.status}）`; return }
    if (data.error) { errorMsg.value = data.error; return }
    resp.value = data
    respTab.value = 'body'
    collapsed.value = new Set()
    pushHistory({
      method: method.value, url: url.value.trim(),
      headers: headers.value.filter(h => h.key).map(h => ({ ...h })),
      body: hasBody.value ? body.value : '',
      status: data.status_code, at: new Date().toLocaleTimeString(),
    })
  } catch (e) {
    errorMsg.value = `发送失败：${e.message}`
  } finally {
    loading.value = false
  }
}

// ── curl 解析 ──
function applyCurl() {
  curlErr.value = ''
  try {
    const p = parseCurl(curlText.value)
    method.value = p.method
    url.value = p.url
    const hs = Object.entries(p.headers).map(([key, value]) => ({ key, value, on: true }))
    headers.value = hs.length ? [...hs, { key: '', value: '', on: true }] : [{ key: '', value: '', on: true }]
    body.value = p.body || ''
    syncParamsFromUrl()
    showCurl.value = false
    curlText.value = ''
    if (p.body) reqTab.value = 'body'
  } catch (e) { curlErr.value = e.message }
}

// ── 设置面板 ──
async function loadConfig() {
  try {
    const r = await fetch('/api/http/config')
    const d = await r.json()
    cfg.enabled = d.enabled
    cfg.allow_hosts = d.allow_hosts || []
  } catch { /* ignore */ }
}
async function saveConfig() {
  cfgSaving.value = true
  cfgMsg.value = ''
  try {
    const r = await fetch('/api/http/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: cfg.enabled, allow_hosts: cfg.allow_hosts }),
    })
    const d = await r.json()
    cfg.enabled = d.enabled
    cfg.allow_hosts = d.allow_hosts || []
    cfgMsg.value = '已保存'
    setTimeout(() => (cfgMsg.value = ''), 1500)
  } catch (e) { cfgMsg.value = `保存失败：${e.message}` }
  finally { cfgSaving.value = false }
}
function addAllowHost() {
  const h = allowInput.value.trim().toLowerCase()
  if (h && !cfg.allow_hosts.includes(h)) cfg.allow_hosts.push(h)
  allowInput.value = ''
}
function removeAllowHost(h) {
  cfg.allow_hosts = cfg.allow_hosts.filter(x => x !== h)
}

const whitelistLabel = computed(() =>
  cfg.allow_hosts.length ? `白名单 ${cfg.allow_hosts.length} 项` : '白名单未启用'
)

// ── 响应展示 ──
const statusClass = computed(() => {
  const s = resp.value?.status_code
  if (!s) return ''
  if (s >= 200 && s < 300) return 'st-2xx'
  if (s >= 300 && s < 400) return 'st-3xx'
  if (s >= 400 && s < 500) return 'st-4xx'
  return 'st-5xx'
})
const contentType = computed(() => {
  const h = resp.value?.headers || {}
  return (h['content-type'] || h['Content-Type'] || '').toLowerCase()
})
const prettyBody = computed(() => {
  const b = resp.value?.body ?? ''
  if (!b) return ''
  if (contentType.value.includes('json') || /^\s*[[{]/.test(b)) {
    try { return JSON.stringify(JSON.parse(b), null, 2) } catch { /* keep raw */ }
  }
  return b
})
const bodyLang = computed(() => {
  if (contentType.value.includes('json') || /^\s*[[{]/.test(resp.value?.body || '')) return 'json'
  if (contentType.value.includes('xml') || contentType.value.includes('html')) return 'xml'
  return null
})
function escapeHtml(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}
function scalarHtml(v) {
  if (v === null) return '<span class="jn">null</span>'
  if (typeof v === 'string') return `<span class="js">"${escapeHtml(v)}"</span>`
  if (typeof v === 'number') return `<span class="jm">${v}</span>`
  if (typeof v === 'boolean') return `<span class="jb">${v}</span>`
  return escapeHtml(String(v))
}
// 把 JSON 值扁平成带层级/折叠信息的行，用于可折叠树渲染
function buildJsonRows(root) {
  const rows = []
  let gid = 0
  function walk(value, keyHtml, depth, comma) {
    if (Array.isArray(value)) {
      const g = gid++
      const open = { indent: depth, keyHtml, open: '[', collapsible: true, groupId: g, comma, childCount: value.length, closeIndex: -1 }
      rows.push(open)
      value.forEach((item, i) => walk(item, null, depth + 1, i < value.length - 1))
      rows.push({ indent: depth, isClose: true, close: ']', comma, groupId: g })
      open.closeIndex = rows.length - 1
    } else if (value && typeof value === 'object') {
      const g = gid++
      const keys = Object.keys(value)
      const open = { indent: depth, keyHtml, open: '{', collapsible: true, groupId: g, comma, childCount: keys.length, closeIndex: -1 }
      rows.push(open)
      keys.forEach((k, i) => walk(value[k], `<span class="jk">"${escapeHtml(k)}"</span>: `, depth + 1, i < keys.length - 1))
      rows.push({ indent: depth, isClose: true, close: '}', comma, groupId: g })
      open.closeIndex = rows.length - 1
    } else {
      rows.push({ indent: depth, keyHtml, valueHtml: scalarHtml(value), comma })
    }
  }
  walk(root, null, 0, false)
  return rows
}

// JSON 可折叠树（非 JSON 返回 null，回退到 hljs 行视图）
const jsonRows = computed(() => {
  const b = resp.value?.body ?? ''
  if (!b) return null
  if (!(contentType.value.includes('json') || /^\s*[[{]/.test(b))) return null
  try { return buildJsonRows(JSON.parse(b)) } catch { return null }
})
const isJsonBody = computed(() => !!jsonRows.value)
const collapsed = ref(new Set())
function toggleFold(gid) {
  const s = new Set(collapsed.value)
  s.has(gid) ? s.delete(gid) : s.add(gid)
  collapsed.value = s
}
function foldAll() {
  const s = new Set()
  ;(jsonRows.value || []).forEach(r => { if (r.open && r.indent >= 1) s.add(r.groupId) })
  collapsed.value = s
}
function unfoldAll() { collapsed.value = new Set() }
const visibleJsonRows = computed(() => {
  const rows = jsonRows.value
  if (!rows) return []
  const ranges = []
  rows.forEach((r, i) => { if (r.open && collapsed.value.has(r.groupId)) ranges.push([i, r.closeIndex]) })
  const out = []
  for (let i = 0; i < rows.length; i++) {
    if (!ranges.some(([s, e]) => i > s && i <= e)) out.push({ row: rows[i], no: i + 1 })
  }
  return out
})

// 非 JSON body：hljs 高亮 + 行号
const bodyLines = computed(() => {
  const code = prettyBody.value
  if (!code) return []
  let html
  if (bodyLang.value) {
    try { html = hljs.highlight(code, { language: bodyLang.value }).value }
    catch { html = escapeHtml(code) }
  } else { html = escapeHtml(code) }
  return html.split('\n')
})
const respHeaderList = computed(() => resp.value ? Object.entries(resp.value.headers) : [])

function fmtBytes(n) {
  if (n == null) return ''
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(2)} MB`
}
async function copyBody() {
  try {
    await navigator.clipboard.writeText(prettyBody.value)
    copied.value = true
    setTimeout(() => (copied.value = false), 1200)
  } catch { /* ignore */ }
}

// ── 主题 ──
const isDark = ref(localStorage.getItem('logmind-theme') !== 'light')
watch(isDark, v => {
  document.documentElement.setAttribute('data-theme', v ? 'dark' : 'light')
  localStorage.setItem('logmind-theme', v ? 'dark' : 'light')
}, { immediate: true })

onMounted(() => {
  document.documentElement.setAttribute('data-theme', isDark.value ? 'dark' : 'light')
  loadHistory()
  loadConfig()
})
</script>

<template>
  <div class="http-view">
    <!-- 顶部 -->
    <header class="ht-header">
      <div class="ht-title">
        <span class="ht-logo">🛰️</span>
        <span>接口测试</span>
        <span class="ht-badge" :class="{ off: !cfg.enabled }" @click="showSettings = true"
              :title="cfg.enabled ? '点开设置面板管理开关与白名单' : '功能已在设置中禁用'">
          {{ cfg.enabled ? '⚠️ 仅本地开发' : '⛔ 已禁用' }} · {{ whitelistLabel }}
        </span>
      </div>
      <nav class="ht-nav">
        <button class="ht-icon-btn" title="设置" @click="showSettings = true">⚙</button>
        <button class="ht-icon-btn" title="主题" @click="isDark = !isDark">{{ isDark ? '☀️' : '🌙' }}</button>
        <router-link class="ht-link" to="/">📑 日志直查</router-link>
        <router-link class="ht-link" to="/chat">💬 AI 分析</router-link>
        <router-link class="ht-link" to="/config">⚙️ 配置</router-link>
      </nav>
    </header>

    <!-- URL 栏 -->
    <div class="ht-urlbar">
      <select v-model="method" class="ht-method" :class="`m-${method}`">
        <option v-for="m in METHODS" :key="m" :value="m">{{ m }}</option>
      </select>
      <input v-model="url" class="ht-url" placeholder="http://localhost:3002/openapi/v1/..."
             spellcheck="false" @blur="syncParamsFromUrl" @keyup.enter="send" />
      <div class="ht-hist-wrap">
        <button class="ht-icon-btn lg" title="历史" @click="showHistory = !showHistory">🕘</button>
        <div v-if="showHistory" class="ht-hist-pop" @click.self="showHistory = false">
          <div class="ht-hist-head">
            <span>最近请求</span>
            <button class="ht-mini" v-if="history.length" @click="clearHistory">清空</button>
          </div>
          <div v-if="!history.length" class="ht-hist-empty">暂无历史</div>
          <button v-for="(h, i) in history" :key="i" class="ht-hist-item" @click="applyHistory(h)">
            <span class="hi-method" :class="`m-${h.method}`">{{ h.method }}</span>
            <span class="hi-url">{{ h.url }}</span>
            <span class="hi-status" :class="h.status >= 400 ? 'bad' : 'ok'">{{ h.status }}</span>
          </button>
        </div>
      </div>
      <button class="ht-ghost" @click="showCurl = true">📋 curl</button>
      <button class="ht-send" :disabled="loading" @click="send">
        <span v-if="loading" class="ht-spin"></span>{{ loading ? '发送中' : '发送' }}
      </button>
    </div>

    <div class="ht-body">
      <!-- 左：请求卡片 -->
      <section class="ht-card ht-req">
        <div class="ht-tabs">
          <button :class="{ act: reqTab === 'params' }" @click="reqTab = 'params'">
            Params <span class="ht-count" v-if="params.filter(p => p.key).length">{{ params.filter(p => p.key).length }}</span>
          </button>
          <button :class="{ act: reqTab === 'headers' }" @click="reqTab = 'headers'">
            Headers <span class="ht-count" v-if="headers.filter(h => h.key).length">{{ headers.filter(h => h.key).length }}</span>
          </button>
          <button :class="{ act: reqTab === 'body' }" :disabled="!hasBody" @click="reqTab = 'body'">
            Body
          </button>
          <div class="ht-tabs-right">
            <label class="ht-timeout">超时 <input v-model.number="timeout" type="number" min="1" max="120" />s</label>
          </div>
        </div>

        <div class="ht-tab-pane">
          <!-- Params -->
          <div v-show="reqTab === 'params'" class="ht-kv">
            <div v-for="(p, i) in params" :key="i" class="ht-kvrow">
              <input type="checkbox" v-model="p.on" class="ht-chk" />
              <input v-model="p.key" placeholder="参数名" spellcheck="false" />
              <input v-model="p.value" placeholder="值" spellcheck="false" />
              <button class="ht-del" @click="removeRow(params, i)">✕</button>
            </div>
          </div>
          <!-- Headers -->
          <div v-show="reqTab === 'headers'" class="ht-kv">
            <div v-for="(h, i) in headers" :key="i" class="ht-kvrow">
              <input type="checkbox" v-model="h.on" class="ht-chk" />
              <input v-model="h.key" placeholder="Header 名，如 Authorization" spellcheck="false" />
              <input v-model="h.value" placeholder="值，如 Bearer sk_..." spellcheck="false" />
              <button class="ht-del" @click="removeRow(headers, i)">✕</button>
            </div>
          </div>
          <!-- Body -->
          <div v-show="reqTab === 'body'">
            <textarea v-if="hasBody" v-model="body" class="ht-body-input"
                      placeholder='{"key": "value"}' spellcheck="false" rows="12" />
            <p v-else class="ht-hint">{{ method }} 请求通常无 Body。</p>
          </div>
        </div>
      </section>

      <!-- 右：响应卡片 -->
      <section class="ht-card ht-resp">
        <div class="ht-error" v-if="errorMsg">{{ errorMsg }}</div>

        <template v-if="resp">
          <!-- 状态栏 -->
          <div class="ht-statusbar">
            <span class="ht-status" :class="statusClass">{{ resp.status_code }}</span>
            <span class="ht-reason" :class="statusClass">{{ resp.reason }}</span>
            <span class="ht-metas">
              <span class="ht-meta"><b>{{ resp.elapsed_ms }}</b> ms</span>
              <span class="ht-meta"><b>{{ fmtBytes(resp.size_bytes) }}</b></span>
              <span class="ht-meta warn" v-if="resp.truncated">已截断</span>
            </span>
          </div>

          <div class="ht-tabs sub">
            <button :class="{ act: respTab === 'body' }" @click="respTab = 'body'">Body</button>
            <button :class="{ act: respTab === 'headers' }" @click="respTab = 'headers'">
              Headers <span class="ht-count">{{ respHeaderList.length }}</span>
            </button>
            <div class="ht-tabs-right">
              <template v-if="respTab === 'body' && isJsonBody">
                <button class="ht-mini" @click="foldAll">折叠全部</button>
                <button class="ht-mini" @click="unfoldAll">展开全部</button>
              </template>
              <button class="ht-mini" v-show="respTab === 'body'" @click="copyBody">
                {{ copied ? '✓ 已复制' : '复制' }}
              </button>
            </div>
          </div>

          <!-- Body -->
          <div v-show="respTab === 'body'" class="ht-code-wrap">
            <!-- JSON：可折叠树 -->
            <div v-if="isJsonBody" class="ht-code">
              <div v-for="item in visibleJsonRows" :key="item.no" class="ht-code-line">
                <span class="ln">{{ item.no }}</span>
                <span class="lc" :style="{ paddingLeft: (item.row.indent * 18 + 16) + 'px' }">
                  <!-- 折叠三角（可折叠行才有） -->
                  <span v-if="item.row.collapsible" class="fold" @click="toggleFold(item.row.groupId)">
                    {{ collapsed.has(item.row.groupId) ? '▶' : '▼' }}
                  </span>
                  <span v-else class="fold-sp"></span>
                  <!-- 闭合行 -->
                  <template v-if="item.row.isClose">
                    <span class="jp">{{ item.row.close }}</span><span class="jp" v-if="item.row.comma">,</span>
                  </template>
                  <!-- 开启行 -->
                  <template v-else-if="item.row.open">
                    <span v-if="item.row.keyHtml" v-html="item.row.keyHtml"></span>
                    <span class="jp">{{ item.row.open }}</span>
                    <template v-if="collapsed.has(item.row.groupId)">
                      <span class="fold-sum"> … {{ item.row.childCount }} {{ item.row.open === '[' ? '项' : '字段' }} </span>
                      <span class="jp">{{ item.row.open === '[' ? ']' : '}' }}</span><span class="jp" v-if="item.row.comma">,</span>
                    </template>
                  </template>
                  <!-- 标量行 -->
                  <template v-else>
                    <span v-if="item.row.keyHtml" v-html="item.row.keyHtml"></span>
                    <span v-html="item.row.valueHtml"></span><span class="jp" v-if="item.row.comma">,</span>
                  </template>
                </span>
              </div>
            </div>
            <!-- 非 JSON：hljs 行号视图 -->
            <div v-else class="ht-code">
              <div v-for="(line, i) in bodyLines" :key="i" class="ht-code-line">
                <span class="ln">{{ i + 1 }}</span>
                <code class="lc" v-html="line || ' '"></code>
              </div>
            </div>
          </div>

          <!-- Headers -->
          <div v-show="respTab === 'headers'" class="ht-rheaders">
            <div v-for="([k, v]) in respHeaderList" :key="k" class="ht-rhrow">
              <span class="hk">{{ k }}</span>
              <span class="hv">{{ v }}</span>
            </div>
          </div>
        </template>

        <div v-else-if="!errorMsg && !loading" class="ht-placeholder">
          <div class="ph-icon">📡</div>
          <p>填好请求点「发送」，或粘一条 curl 解析。</p>
          <p class="ph-sub">响应会显示状态码、耗时、响应头和高亮的 Body。快捷键：URL 栏回车即发送。</p>
        </div>

        <div v-else-if="loading" class="ht-skeleton">
          <div class="sk-bar" style="width: 40%"></div>
          <div class="sk-block"></div>
        </div>
      </section>
    </div>

    <!-- curl 弹层 -->
    <div v-if="showCurl" class="ht-modal-mask" @click.self="showCurl = false">
      <div class="ht-modal">
        <h3>粘贴 curl 命令</h3>
        <textarea v-model="curlText" class="ht-body-input"
                  placeholder="curl 'http://...' -H 'Authorization: Bearer ...'" spellcheck="false" rows="7" />
        <div class="ht-curl-err" v-if="curlErr">{{ curlErr }}</div>
        <div class="ht-modal-btns">
          <button class="ht-ghost" @click="showCurl = false">取消</button>
          <button class="ht-send" @click="applyCurl">解析并填入</button>
        </div>
      </div>
    </div>

    <!-- 设置抽屉 -->
    <div v-if="showSettings" class="ht-modal-mask" @click.self="showSettings = false">
      <div class="ht-drawer">
        <div class="ht-drawer-head">
          <h3>接口测试 · 设置</h3>
          <button class="ht-icon-btn" @click="showSettings = false">✕</button>
        </div>

        <div class="ht-set-row">
          <div>
            <div class="ht-set-title">启用接口测试</div>
            <div class="ht-set-desc">关闭后 /api/http/send 一律拒绝，功能停用。</div>
          </div>
          <label class="ht-switch">
            <input type="checkbox" v-model="cfg.enabled" />
            <span class="ht-slider"></span>
          </label>
        </div>

        <div class="ht-set-block">
          <div class="ht-set-title">Host 白名单</div>
          <div class="ht-set-desc">
            为空 = 只走内置黑名单（拦云元数据地址，其余放行，本地默认）。<br>
            填了 = <b>只放行</b>列表内 host，其余全拒（更严）。
          </div>
          <div class="ht-allow-add">
            <input v-model="allowInput" placeholder="如 localhost 或 api.example.com"
                   spellcheck="false" @keyup.enter="addAllowHost" />
            <button class="ht-ghost" @click="addAllowHost">添加</button>
          </div>
          <div class="ht-chips" v-if="cfg.allow_hosts.length">
            <span v-for="h in cfg.allow_hosts" :key="h" class="ht-chip">
              {{ h }}<button @click="removeAllowHost(h)">✕</button>
            </span>
          </div>
          <p v-else class="ht-hint">当前无白名单，走宽松黑名单模式。</p>
        </div>

        <div class="ht-drawer-foot">
          <span class="ht-cfg-msg" v-if="cfgMsg">{{ cfgMsg }}</span>
          <button class="ht-send" :disabled="cfgSaving" @click="saveConfig">
            {{ cfgSaving ? '保存中…' : '保存' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.http-view { min-height: 100vh; background: var(--bg-app, #0a0c12); color: #e2e8f0; }

/* header */
.ht-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 13px 24px; border-bottom: 1px solid var(--border-log, #1e2535);
  position: sticky; top: 0; z-index: 20; background: var(--bg-app, #0a0c12);
}
.ht-title { display: flex; align-items: center; gap: 10px; font-size: 16px; font-weight: 700; }
.ht-logo { font-size: 20px; }
.ht-badge {
  font-size: 11px; font-weight: 600; cursor: pointer;
  background: rgba(245,158,11,.12); color: #f59e0b; border: 1px solid rgba(245,158,11,.3);
  border-radius: 999px; padding: 3px 11px; margin-left: 4px; transition: all .15s;
}
.ht-badge:hover { background: rgba(245,158,11,.2); }
.ht-badge.off { background: rgba(239,68,68,.12); color: #ef4444; border-color: rgba(239,68,68,.3); }
.ht-nav { display: flex; align-items: center; gap: 12px; }
.ht-icon-btn {
  background: rgba(255,255,255,.05); border: 1px solid #2d3748; color: #cbd5e0;
  width: 30px; height: 30px; border-radius: 7px; cursor: pointer; font-size: 14px;
  display: inline-flex; align-items: center; justify-content: center;
}
.ht-icon-btn:hover { border-color: #3b82f6; color: #60a5fa; }
.ht-icon-btn.lg { width: 34px; height: 34px; }
.ht-link { color: #60a5fa; text-decoration: none; font-size: 13px; }
.ht-link:hover { text-decoration: underline; }

/* URL bar */
.ht-urlbar { display: flex; gap: 8px; padding: 16px 24px 12px; align-items: center; }
.ht-method {
  background: rgba(255,255,255,.06); border: 1px solid #2d3748; border-radius: 8px;
  color: #e2e8f0; padding: 9px 12px; font-size: 13px; font-weight: 700; cursor: pointer; outline: none;
}
.m-GET { color: #22c55e; } .m-POST { color: #f59e0b; } .m-PUT { color: #3b82f6; }
.m-PATCH { color: #a855f7; } .m-DELETE { color: #ef4444; }
.ht-url {
  flex: 1; min-width: 0; background: rgba(255,255,255,.06); border: 1px solid #2d3748;
  border-radius: 8px; color: #e2e8f0; padding: 9px 14px; font-size: 13px; outline: none;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.ht-url:focus { border-color: #3b82f6; box-shadow: 0 0 0 3px rgba(59,130,246,.12); }
.ht-send {
  background: #3b82f6; color: #fff; border: none; border-radius: 8px; padding: 9px 22px;
  font-size: 13px; font-weight: 600; cursor: pointer; white-space: nowrap;
  display: inline-flex; align-items: center; gap: 7px;
}
.ht-send:hover:not(:disabled) { background: #2563eb; }
.ht-send:disabled { opacity: .6; cursor: not-allowed; }
.ht-spin {
  width: 12px; height: 12px; border: 2px solid rgba(255,255,255,.4);
  border-top-color: #fff; border-radius: 50%; animation: spin .7s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
.ht-ghost {
  background: rgba(255,255,255,.06); border: 1px solid #2d3748; color: #cbd5e0;
  border-radius: 8px; padding: 9px 14px; font-size: 12.5px; cursor: pointer; white-space: nowrap;
}
.ht-ghost:hover { border-color: #3b82f6; }

/* history */
.ht-hist-wrap { position: relative; }
.ht-hist-pop {
  position: absolute; top: 40px; right: 0; width: 420px; max-height: 380px; overflow: auto;
  background: var(--bg-app, #0f131c); border: 1px solid #2d3748; border-radius: 10px;
  box-shadow: 0 12px 40px rgba(0,0,0,.5); z-index: 30; padding: 6px;
}
.ht-hist-head { display: flex; justify-content: space-between; align-items: center; padding: 6px 8px; font-size: 12px; color: #94a3b8; }
.ht-hist-empty { padding: 20px; text-align: center; color: #64748b; font-size: 13px; }
.ht-hist-item {
  display: flex; align-items: center; gap: 8px; width: 100%; text-align: left;
  background: none; border: none; color: #cbd5e0; padding: 8px; border-radius: 6px; cursor: pointer;
}
.ht-hist-item:hover { background: rgba(255,255,255,.05); }
.hi-method { font-size: 11px; font-weight: 700; width: 46px; flex-shrink: 0; }
.hi-url { flex: 1; min-width: 0; font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.hi-status { font-size: 11px; font-weight: 700; }
.hi-status.ok { color: #22c55e; } .hi-status.bad { color: #ef4444; }
.ht-mini { background: none; border: 1px solid #2d3748; color: #94a3b8; border-radius: 5px; padding: 2px 9px; font-size: 11px; cursor: pointer; }
.ht-mini:hover { color: #60a5fa; border-color: #3b82f6; }

/* layout */
.ht-body { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; padding: 4px 24px 28px; }
.ht-card {
  background: rgba(255,255,255,.02); border: 1px solid var(--border-log, #1e2535);
  border-radius: 12px; overflow: hidden; display: flex; flex-direction: column;
  min-height: 460px; min-width: 0;
}

/* tabs */
.ht-tabs {
  display: flex; align-items: center; gap: 4px; padding: 6px 10px;
  border-bottom: 1px solid var(--border-log, #1e2535); background: rgba(255,255,255,.02);
}
.ht-tabs.sub { background: none; }
.ht-tabs button {
  background: none; border: none; color: #94a3b8; padding: 7px 12px; font-size: 13px;
  font-weight: 600; cursor: pointer; border-radius: 7px; display: flex; align-items: center; gap: 6px;
}
.ht-tabs button:hover:not(:disabled) { color: #e2e8f0; background: rgba(255,255,255,.04); }
.ht-tabs button.act { color: #60a5fa; background: rgba(59,130,246,.1); }
.ht-tabs button:disabled { opacity: .4; cursor: not-allowed; }
.ht-count { font-size: 10px; background: rgba(96,165,250,.2); color: #60a5fa; border-radius: 999px; padding: 1px 7px; }
.ht-tabs-right { margin-left: auto; display: flex; align-items: center; gap: 8px; }
.ht-timeout { font-size: 12px; color: #94a3b8; display: flex; align-items: center; gap: 5px; }
.ht-timeout input {
  width: 50px; background: rgba(255,255,255,.06); border: 1px solid #2d3748;
  border-radius: 6px; color: #e2e8f0; padding: 3px 8px; font-size: 12px;
}
.ht-tab-pane { padding: 14px; flex: 1; overflow: auto; }

/* key-value rows */
.ht-kv { display: flex; flex-direction: column; gap: 6px; }
.ht-kvrow { display: grid; grid-template-columns: auto 1fr 1.3fr auto; gap: 8px; align-items: center; }
.ht-chk { width: 15px; height: 15px; accent-color: #3b82f6; cursor: pointer; }
.ht-kvrow input[type=text], .ht-kvrow input:not([type]) {
  background: rgba(255,255,255,.05); border: 1px solid #2d3748; border-radius: 7px;
  color: #e2e8f0; padding: 7px 10px; font-size: 12.5px; outline: none;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.ht-kvrow input:focus { border-color: #3b82f6; }
.ht-del { background: none; border: 1px solid transparent; color: #64748b; border-radius: 6px; cursor: pointer; padding: 4px 9px; font-size: 12px; }
.ht-del:hover { color: #ef4444; border-color: #ef4444; }
.ht-body-input {
  width: 100%; background: rgba(0,0,0,.25); border: 1px solid #2d3748; border-radius: 8px;
  color: #e2e8f0; padding: 12px; font-size: 12.5px; outline: none; resize: vertical;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace; line-height: 1.55;
}
.ht-body-input:focus { border-color: #3b82f6; }
.ht-hint { font-size: 12px; color: #64748b; padding: 8px 2px; }

/* status bar */
.ht-statusbar {
  display: flex; align-items: center; gap: 10px; padding: 14px 16px;
  border-bottom: 1px solid var(--border-log, #1e2535);
}
.ht-status { font-size: 20px; font-weight: 800; padding: 2px 12px; border-radius: 8px; }
.ht-reason { font-size: 14px; font-weight: 600; }
.st-2xx { color: #22c55e; } .st-2xx.ht-status { background: rgba(34,197,94,.14); }
.st-3xx { color: #60a5fa; } .st-3xx.ht-status { background: rgba(59,130,246,.14); }
.st-4xx { color: #f59e0b; } .st-4xx.ht-status { background: rgba(245,158,11,.14); }
.st-5xx { color: #ef4444; } .st-5xx.ht-status { background: rgba(239,68,68,.14); }
.ht-metas { margin-left: auto; display: flex; gap: 14px; }
.ht-meta { font-size: 12px; color: #94a3b8; } .ht-meta b { color: #e2e8f0; font-size: 13px; }
.ht-meta.warn { color: #f59e0b; }

/* code w/ line numbers */
.ht-code-wrap { flex: 1; overflow: auto; padding: 4px; }
.ht-code {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12.5px; line-height: 1.6;
}
.ht-code-line { display: flex; }
.ht-code-line:hover { background: rgba(255,255,255,.03); }
.ln {
  user-select: none; text-align: right; width: 42px; flex-shrink: 0; padding-right: 12px;
  color: #4b5563; border-right: 1px solid var(--border-log, #1e2535); margin-right: 12px;
}
.lc { white-space: pre-wrap; word-break: break-word; flex: 1; min-width: 0; }
/* JSON 折叠三角 + token 配色 */
.fold { display: inline-block; width: 14px; margin-left: -16px; color: #64748b; cursor: pointer; user-select: none; font-size: 9px; text-align: center; }
.fold:hover { color: #60a5fa; }
.fold-sp { display: inline-block; width: 14px; margin-left: -16px; }
.fold-sum { color: #64748b; font-style: italic; cursor: pointer; }
.jk { color: #e06c75; }   /* key */
.js { color: #98c379; }   /* string */
.jm { color: #d19a66; }   /* number */
.jb { color: #56b6c2; }   /* boolean */
.jn { color: #c678dd; }   /* null */
.jp { color: #abb2bf; }   /* 括号/逗号 */
[data-theme="light"] .jk { color: #c41d7f; }
[data-theme="light"] .js { color: #0a7d33; }
[data-theme="light"] .jm { color: #b25000; }
[data-theme="light"] .jb { color: #0b7285; }
[data-theme="light"] .jn { color: #862e9c; }
[data-theme="light"] .jp { color: #64748b; }

/* response headers */
.ht-rheaders { flex: 1; overflow: auto; padding: 8px 4px; }
.ht-rhrow { display: grid; grid-template-columns: minmax(120px, 30%) 1fr; gap: 12px; padding: 7px 12px; border-bottom: 1px solid var(--border-log, #1e2535); }
.ht-rhrow .hk { color: #60a5fa; font-size: 12px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; word-break: break-all; }
.ht-rhrow .hv { color: #cbd5e0; font-size: 12px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; word-break: break-all; }

/* placeholder / skeleton / error */
.ht-placeholder { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; color: #64748b; padding: 30px; }
.ph-icon { font-size: 40px; margin-bottom: 12px; opacity: .6; }
.ph-sub { font-size: 12px; margin-top: 6px; color: #4b5563; max-width: 320px; }
.ht-error { margin: 14px; padding: 12px 14px; background: rgba(239,68,68,.1); border: 1px solid rgba(239,68,68,.3); color: #fca5a5; border-radius: 8px; font-size: 13px; word-break: break-all; }
.ht-skeleton { padding: 18px; }
.sk-bar, .sk-block { background: linear-gradient(90deg, rgba(255,255,255,.05), rgba(255,255,255,.1), rgba(255,255,255,.05)); background-size: 200% 100%; animation: shimmer 1.3s infinite; border-radius: 6px; }
.sk-bar { height: 22px; margin-bottom: 14px; } .sk-block { height: 200px; }
@keyframes shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }

/* modal */
.ht-modal-mask { position: fixed; inset: 0; background: rgba(0,0,0,.5); display: flex; align-items: center; justify-content: center; z-index: 100; }
.ht-modal { background: var(--bg-app, #0f131c); border: 1px solid #2d3748; border-radius: 12px; padding: 22px; width: min(560px, 92vw); }
.ht-modal h3 { font-size: 15px; margin-bottom: 14px; }
.ht-curl-err { color: #fca5a5; font-size: 12px; margin-top: 8px; }
.ht-modal-btns { display: flex; justify-content: flex-end; gap: 10px; margin-top: 16px; }

/* drawer */
.ht-drawer {
  position: fixed; top: 0; right: 0; height: 100vh; width: min(440px, 94vw);
  background: var(--bg-app, #0f131c); border-left: 1px solid #2d3748; padding: 22px;
  display: flex; flex-direction: column; box-shadow: -12px 0 40px rgba(0,0,0,.4);
  animation: slideIn .2s ease;
}
@keyframes slideIn { from { transform: translateX(100%); } to { transform: translateX(0); } }
.ht-drawer-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 18px; }
.ht-drawer-head h3 { font-size: 16px; }
.ht-set-row { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 14px 0; border-bottom: 1px solid var(--border-log, #1e2535); }
.ht-set-block { padding: 16px 0; }
.ht-set-title { font-size: 13.5px; font-weight: 600; margin-bottom: 4px; }
.ht-set-desc { font-size: 12px; color: #94a3b8; line-height: 1.6; }
.ht-allow-add { display: flex; gap: 8px; margin: 12px 0; }
.ht-allow-add input { flex: 1; background: rgba(255,255,255,.06); border: 1px solid #2d3748; border-radius: 8px; color: #e2e8f0; padding: 8px 12px; font-size: 12.5px; outline: none; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.ht-allow-add input:focus { border-color: #3b82f6; }
.ht-chips { display: flex; flex-wrap: wrap; gap: 8px; }
.ht-chip { display: inline-flex; align-items: center; gap: 6px; background: rgba(96,165,250,.14); color: #60a5fa; border: 1px solid rgba(96,165,250,.3); border-radius: 999px; padding: 4px 8px 4px 12px; font-size: 12px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.ht-chip button { background: none; border: none; color: #60a5fa; cursor: pointer; font-size: 11px; }
.ht-chip button:hover { color: #ef4444; }
.ht-drawer-foot { margin-top: auto; display: flex; align-items: center; justify-content: flex-end; gap: 12px; padding-top: 16px; border-top: 1px solid var(--border-log, #1e2535); }
.ht-cfg-msg { font-size: 12px; color: #22c55e; }

/* switch */
.ht-switch { position: relative; display: inline-block; width: 42px; height: 24px; flex-shrink: 0; }
.ht-switch input { opacity: 0; width: 0; height: 0; }
.ht-slider { position: absolute; inset: 0; background: #2d3748; border-radius: 999px; cursor: pointer; transition: .2s; }
.ht-slider::before { content: ''; position: absolute; height: 18px; width: 18px; left: 3px; top: 3px; background: #fff; border-radius: 50%; transition: .2s; }
.ht-switch input:checked + .ht-slider { background: #3b82f6; }
.ht-switch input:checked + .ht-slider::before { transform: translateX(18px); }

/* light theme */
[data-theme="light"] .http-view { background: #f8fafc; color: #1e293b; }
[data-theme="light"] .ht-header { background: #f8fafc; border-color: #e2e8f0; }
[data-theme="light"] .ht-card { background: #fff; border-color: #e2e8f0; }
[data-theme="light"] .ht-method, [data-theme="light"] .ht-url, [data-theme="light"] .ht-kvrow input,
[data-theme="light"] .ht-timeout input, [data-theme="light"] .ht-allow-add input, [data-theme="light"] .ht-ghost, [data-theme="light"] .ht-icon-btn {
  background: #fff; border-color: #cbd5e0; color: #1e293b;
}
[data-theme="light"] .ht-body-input { background: #f8fafc; border-color: #cbd5e0; color: #1e293b; }
[data-theme="light"] .ht-modal, [data-theme="light"] .ht-drawer, [data-theme="light"] .ht-hist-pop { background: #fff; border-color: #e2e8f0; }
[data-theme="light"] .ln { color: #94a3b8; }
</style>
