<script setup>
import { ref, nextTick, onMounted, computed, watch } from 'vue'
import LogTable from '../components/LogTable.vue'
import ChartWidget from '../components/ChartWidget.vue'
import { marked } from 'marked'
import hljs from 'highlight.js'

marked.setOptions({
  highlight(code, lang) {
    if (lang && hljs.getLanguage(lang)) {
      return hljs.highlight(code, { language: lang }).value
    }
    return hljs.highlightAuto(code).value
  },
  breaks: true,
  gfm: true,
})

// ── 状态 ──────────────────────────────────────────────────────────────────────
const messages = ref([])
const inputText = ref('')
const loading = ref(false)
const chatBody = ref(null)

const sessions = ref([])
const currentSessionId = ref(null)

const serverStatuses = ref([])   // [{name, host, status}]
const timeChip = ref('')         // 选中的时间快捷
const dsStats = ref(null)        // 数据源统计

// ── 常量 ──────────────────────────────────────────────────────────────────────
const CAPABILITY_GROUPS = [
  {
    intent: 'query',
    label: '日志查询',
    color: '#3b82f6',
    desc: '自然语言搜索，无需写 KQL / DSL',
    cards: [
      { icon: '🔴', label: '查最近 ERROR', prompt: '查一下所有服务最近 1 小时的 ERROR 日志' },
      { icon: '🔍', label: '关键词搜索', prompt: '搜索包含 NullPointerException 的日志' },
      { icon: '🖥️', label: '按服务查询', prompt: '查一下支付服务今天的 WARN 和 ERROR 日志' },
    ],
  },
  {
    intent: 'analyze',
    label: '分析诊断',
    color: '#8b5cf6',
    desc: '异常检测、趋势分析、根因定位',
    cards: [
      { icon: '📈', label: '错误趋势', prompt: '分析一下最近 24 小时错误趋势，是否在加剧？' },
      { icon: '🏆', label: '服务排名', prompt: '所有服务里 ERROR 最多的是哪个？给我排个名' },
      { icon: '🔬', label: '深入分析异常', prompt: '深入分析 NullPointerException，首次出现时间和频率' },
    ],
  },
  {
    intent: 'dashboard',
    label: '数据图表',
    color: '#10b981',
    desc: '一句话生成 ECharts 可视化图表',
    cards: [
      { icon: '📊', label: '各服务错误分布', prompt: '画一张今天各服务 ERROR 数量的柱状图' },
      { icon: '📉', label: 'ERROR 趋势折线图', prompt: '画出过去 24 小时 ERROR 日志的趋势折线图' },
      { icon: '🥧', label: '错误级别占比', prompt: '用饼图展示今天各日志级别的数量占比' },
    ],
  },
]

const TIME_CHIPS = ['最近 1 小时', '最近 6 小时', '今天', '昨天']

const INTENT_LABEL = { query: '日志查询', analyze: '趋势分析', dashboard: '数据图表' }
const INTENT_COLOR = { query: '#3b82f6', analyze: '#8b5cf6', dashboard: '#10b981' }

// ── 工具函数 ──────────────────────────────────────────────────────────────────
function parseLogLines(text) {
  const lines = text.split('\n').filter(l => l.trim())
  const entries = []
  for (const line of lines) {
    const m = line.match(/^\[(.+?)\]\s+\[(\w+)\]\s+\[(.+?)\]\s+(.*)$/)
    if (m) entries.push({ timestamp: m[1], level: m[2], source: m[3], message: m[4] })
  }
  return entries
}

async function scrollToBottom() {
  await nextTick()
  if (chatBody.value) chatBody.value.scrollTop = chatBody.value.scrollHeight
}

function exportLogsCSV(logs) {
  const header = ['timestamp', 'level', 'source', 'message']
  const rows = logs.map(r => header.map(k => `"${(r[k] || '').replace(/"/g, '""')}"`).join(','))
  const csv = [header.join(','), ...rows].join('\n')
  const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `logmind-export-${Date.now()}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

function exportSessionMD() {
  const now = new Date().toISOString().replace('T', ' ').slice(0, 19)
  const lines = [`# LogMind 会话导出`, ``, `> 导出时间：${now}`, ``]
  for (const msg of messages.value) {
    if (msg.role === 'user') {
      lines.push(`## 用户`, ``, msg.content, ``)
    } else {
      lines.push(`## LogMind AI`)
      if (msg.intent) lines.push(``, `*意图：${INTENT_LABEL[msg.intent] || msg.intent}*`)
      lines.push(``, msg.content.replace(/<chart_config>[\s\S]*?<\/chart_config>/g, '').trim(), ``)
      if (msg.logs?.length > 0) {
        lines.push(`### 日志数据 (${msg.logs.length} 条)`, ``)
        lines.push('| 时间 | 级别 | 服务 | 消息 |')
        lines.push('|---|---|---|---|')
        for (const log of msg.logs) {
          const cell = (v) => (v || '').replace(/\|/g, '\\|')
          lines.push(`| ${cell(log.timestamp)} | ${cell(log.level)} | ${cell(log.source)} | ${cell(log.message)} |`)
        }
        lines.push(``)
      }
    }
  }
  const md = lines.join('\n')
  const blob = new Blob([md], { type: 'text/markdown;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `logmind-session-${Date.now()}.md`
  a.click()
  URL.revokeObjectURL(url)
}

function formatTime(iso) {
  const d = new Date(iso), now = new Date(), diff = now - d
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return `${Math.floor(diff / 60000)} 分钟前`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)} 小时前`
  return `${d.getMonth() + 1}/${d.getDate()}`
}

function renderText(text) {
  const stripped = text.replace(/<chart_config>[\s\S]*?<\/chart_config>/g, '').trim()
  return marked.parse(stripped)
}

function extractCharts(text) {
  const charts = []
  const re = /<chart_config>([\s\S]*?)<\/chart_config>/g
  let m
  while ((m = re.exec(text)) !== null) {
    try {
      charts.push(JSON.parse(m[1].trim()))
    } catch {
      // 忽略非法 JSON
    }
  }
  return charts
}

// ── 服务器健康 ────────────────────────────────────────────────────────────────
async function fetchServerHealth() {
  try {
    const res = await fetch('/api/health/servers')
    serverStatuses.value = await res.json()
  } catch {
    // 静默失败，不影响主流程
  }
}

async function fetchDsStats() {
  try {
    const res = await fetch('/api/config/stats')
    const data = await res.json()
    if (data.ok) dsStats.value = data
  } catch {
    // 静默失败
  }
}

// ── 会话管理 ──────────────────────────────────────────────────────────────────
async function fetchSessions() {
  const res = await fetch('/api/sessions')
  sessions.value = await res.json()
}

async function newSession() {
  const res = await fetch('/api/sessions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: '新会话' }),
  })
  const session = await res.json()
  sessions.value.unshift(session)
  currentSessionId.value = session.id
  messages.value = []
}

async function switchSession(id) {
  if (id === currentSessionId.value) return
  currentSessionId.value = id
  const res = await fetch(`/api/sessions/${id}/messages`)
  const data = await res.json()
  messages.value = data.map(m => ({
    role: m.role,
    content: m.content,
    intent: null,
    tools: [],
    logs: m.role === 'assistant' ? parseLogLines(m.content) : [],
    charts: m.role === 'assistant' ? extractCharts(m.content) : [],
    suggestions: [],
  }))
  await scrollToBottom()
}

async function removeSession(id, e) {
  e.stopPropagation()
  await fetch(`/api/sessions/${id}`, { method: 'DELETE' })
  sessions.value = sessions.value.filter(s => s.id !== id)
  if (currentSessionId.value === id) {
    sessions.value.length > 0 ? await switchSession(sessions.value[0].id) : await newSession()
  }
}

async function closeSession() {
  if (!currentSessionId.value) return
  await fetch(`/api/sessions/${currentSessionId.value}/close`, { method: 'POST' })
  const s = sessions.value.find(s => s.id === currentSessionId.value)
  if (s) s.status = 'ended'
}

async function reopenSession(id, e) {
  e.stopPropagation()
  await fetch(`/api/sessions/${id}/reopen`, { method: 'POST' })
  const s = sessions.value.find(s => s.id === id)
  if (s) s.status = 'active'
}

const currentSession = computed(() => sessions.value.find(s => s.id === currentSessionId.value))

// ── 时间 Chip ─────────────────────────────────────────────────────────────────
function selectTimeChip(chip) {
  if (timeChip.value === chip) {
    timeChip.value = ''
    return
  }
  timeChip.value = chip
  if (!inputText.value.trim()) {
    inputText.value = `查一下${chip}的日志`
  }
}

// ── 追问建议生成 ──────────────────────────────────────────────────────────────
function makeSuggestions(userMsg, aiContent) {
  const msg = userMsg.toLowerCase()
  if (msg.includes('error') || msg.includes('错误')) {
    return ['错误发生在哪些时间段？', '最近趋势是否在加剧？']
  }
  if (msg.includes('趋势') || msg.includes('分析')) {
    return ['哪个服务错误最多？', '对比昨天的情况如何？']
  }
  if (msg.includes('连通') || msg.includes('health')) {
    return ['查一下异常服务器的最新日志', '统计今天的 ERROR 总数']
  }
  return ['查最近 1 小时的 ERROR 日志', '分析一下错误趋势']
}

// ── 发送消息 ──────────────────────────────────────────────────────────────────
async function sendMessage(text) {
  const msg = (text || inputText.value).trim()
  if (!msg || loading.value || currentSession.value?.status === 'ended') return

  // 记录历史，去重，最多保留 50 条
  if (inputHistory.value[0] !== msg) {
    inputHistory.value.unshift(msg)
    if (inputHistory.value.length > 50) inputHistory.value.pop()
  }
  historyIndex.value = -1

  inputText.value = ''
  timeChip.value = ''
  messages.value.push({ role: 'user', content: msg })
  loading.value = true
  await scrollToBottom()

  const aiMsg = { role: 'assistant', content: '', intent: null, tools: [], logs: [], suggestions: [], charts: [] }
  messages.value.push(aiMsg)

  try {
    const resp = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: msg, session_id: currentSessionId.value }),
    })

    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })

      const parts = buf.split('\n\n')
      buf = parts.pop()

      for (const part of parts) {
        const line = part.trim()
        if (!line.startsWith('data:')) continue
        const raw = line.slice(5).trim()
        if (!raw) continue
        let evt
        try { evt = JSON.parse(raw) } catch { continue }

        if (evt.type === 'intent') {
          aiMsg.intent = evt.intent
        } else if (evt.type === 'tool_start') {
          aiMsg.tools.push({ name: evt.tool, done: false })
        } else if (evt.type === 'tool_end') {
          const t = [...aiMsg.tools].reverse().find(t => t.name === evt.tool && !t.done)
          if (t) t.done = true
        } else if (evt.type === 'text') {
          aiMsg.content += evt.content
          const parsed = parseLogLines(aiMsg.content)
          if (parsed.length > 0) aiMsg.logs = parsed
          aiMsg.charts = extractCharts(aiMsg.content)
        } else if (evt.type === 'done') {
          aiMsg.suggestions = makeSuggestions(msg, aiMsg.content)
          const session = sessions.value.find(s => s.id === currentSessionId.value)
          if (session && session.title === '新会话') session.title = msg.slice(0, 30)
          break
        }
        await scrollToBottom()
      }
    }
  } catch (e) {
    aiMsg.content = `请求失败：${e.message}`
  } finally {
    loading.value = false
    await scrollToBottom()
  }
}

function handleEnter(e) {
  if (e.shiftKey) return
  e.preventDefault()
  sendMessage()
}

const isEmpty = computed(() => messages.value.length === 0)

// ── 主题 ──────────────────────────────────────────────────────────────────────
const isDark = ref(localStorage.getItem('logmind-theme') !== 'light')
watch(isDark, v => {
  document.documentElement.setAttribute('data-theme', v ? 'dark' : 'light')
  localStorage.setItem('logmind-theme', v ? 'dark' : 'light')
}, { immediate: true })

// ── 历史输入（↑ 键） ──────────────────────────────────────────────────────────
const inputHistory = ref([])
const historyIndex = ref(-1)

function handleKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    sendMessage()
    return
  }
  if (e.key === 'ArrowUp' && !e.shiftKey) {
    if (inputHistory.value.length === 0) return
    e.preventDefault()
    historyIndex.value = Math.min(historyIndex.value + 1, inputHistory.value.length - 1)
    inputText.value = inputHistory.value[historyIndex.value]
    return
  }
  if (e.key === 'ArrowDown' && !e.shiftKey) {
    e.preventDefault()
    if (historyIndex.value <= 0) { historyIndex.value = -1; inputText.value = ''; return }
    historyIndex.value--
    inputText.value = inputHistory.value[historyIndex.value]
  }
}

onMounted(async () => {
  await fetchSessions()
  await fetchServerHealth()
  fetchDsStats()
  if (sessions.value.length > 0) {
    await switchSession(sessions.value[0].id)
  } else {
    await newSession()
  }
})
</script>

<template>
  <div class="chat-layout">

    <!-- 侧边栏 -->
    <aside class="sidebar">
      <div class="logo">
        <span class="logo-icon">◈</span>
        <span class="logo-text">LogMind</span>
        <button class="theme-btn" @click="isDark = !isDark" :title="isDark ? '切换亮色' : '切换暗色'">
          {{ isDark ? '☀️' : '🌙' }}
        </button>
      </div>

      <button class="new-session-btn" @click="newSession">
        <span class="plus">＋</span> 新建会话
      </button>

      <!-- 服务器状态 -->
      <div v-if="serverStatuses.length > 0" class="server-section">
        <div class="section-label">数据源</div>
        <div v-for="s in serverStatuses" :key="s.name" class="server-item">
          <span class="status-dot" :class="s.status === 'ok' ? 'dot-ok' : 'dot-err'"></span>
          <span class="server-name">{{ s.name }}</span>
        </div>
      </div>

      <!-- 会话列表 -->
      <div class="section-label" style="margin-top: 8px">历史会话</div>
      <div class="session-list">
        <div
          v-for="s in sessions"
          :key="s.id"
          :class="['session-item', { active: s.id === currentSessionId, ended: s.status === 'ended' }]"
          @click="switchSession(s.id)"
        >
          <div class="session-title">
            {{ s.title }}
            <span v-if="s.status === 'ended'" class="ended-badge">已结束</span>
          </div>
          <div class="session-meta">
            <span class="session-time">{{ formatTime(s.created_at) }}</span>
            <button v-if="s.status === 'ended'" class="reopen-btn" @click="reopenSession(s.id, $event)">继续</button>
            <button v-else class="del-btn" @click="removeSession(s.id, $event)">✕</button>
          </div>
        </div>
      </div>

      <div class="sidebar-footer">
        <button
          v-if="messages.length > 0"
          class="export-session-btn"
          @click="exportSessionMD"
          title="导出当前会话为 Markdown"
        >
          ↓ 导出会话
        </button>
        <a href="/config" class="config-link">⚙ 数据源配置</a>
      </div>
    </aside>

    <!-- 主区域 -->
    <main class="chat-main">

      <!-- 数据源状态栏 -->
      <div v-if="dsStats" class="ds-stats-bar">
        <span class="ds-stats-type">
          {{ dsStats.type === 'elasticsearch' ? 'ES' : dsStats.type === 'ssh' ? 'SSH' : 'DuckDB' }}
        </span>
        <template v-if="dsStats.type === 'elasticsearch'">
          <span class="ds-stat-item">总计 <b>{{ (dsStats.total || 0).toLocaleString() }}</b> 条</span>
          <span class="ds-stat-sep">·</span>
          <span class="ds-stat-item ds-stat-error">ERROR <b>{{ (dsStats.error_count || 0).toLocaleString() }}</b></span>
          <span class="ds-stat-sep">·</span>
          <span class="ds-stat-item" :class="dsStats.error_ratio > 5 ? 'ds-stat-error' : ''">
            错误率 <b>{{ dsStats.error_ratio }}%</b>
          </span>
        </template>
        <template v-else-if="dsStats.type === 'ssh'">
          <span class="ds-stat-item"><b>{{ dsStats.server_count }}</b> 台服务器</span>
          <span v-if="dsStats.log_path_count" class="ds-stat-sep">·</span>
          <span v-if="dsStats.log_path_count" class="ds-stat-item"><b>{{ dsStats.log_path_count }}</b> 个日志路径</span>
        </template>
        <template v-else-if="dsStats.type === 'duckdb'">
          <span class="ds-stat-item"><b>{{ dsStats.table_count }}</b> 张表</span>
        </template>
        <span class="ds-stats-refresh" @click="fetchDsStats" title="刷新">↻</span>
      </div>

      <div class="chat-body" ref="chatBody">

        <!-- 欢迎页 -->
        <div v-if="isEmpty" class="welcome">
          <div class="welcome-icon">◈</div>
          <div class="welcome-title">LogMind AI 日志分析</div>
          <div class="welcome-sub">用自然语言查询日志、分析异常、生成图表，无需掌握 KQL / DSL</div>

          <!-- 配置入口 banner -->
          <a href="/config" class="config-banner">
            <span class="config-banner-icon">⚙</span>
            <span class="config-banner-text">配置数据源（SSH / Elasticsearch / DuckDB）</span>
            <span class="config-banner-arrow">→</span>
          </a>

          <!-- 能力分组 -->
          <div class="capability-groups">
            <div v-for="group in CAPABILITY_GROUPS" :key="group.intent" class="capability-group">
              <div class="group-header">
                <span class="group-dot" :style="{ background: group.color }"></span>
                <span class="group-label" :style="{ color: group.color }">{{ group.label }}</span>
                <span class="group-desc">{{ group.desc }}</span>
              </div>
              <div class="group-cards">
                <button
                  v-for="card in group.cards"
                  :key="card.label"
                  class="scene-card"
                  :style="{ '--card-accent': group.color }"
                  @click="sendMessage(card.prompt)"
                >
                  <span class="scene-icon">{{ card.icon }}</span>
                  <div class="scene-body">
                    <span class="scene-label">{{ card.label }}</span>
                    <span class="scene-prompt">{{ card.prompt }}</span>
                  </div>
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- 消息列表 -->
        <div v-for="(msg, i) in messages" :key="i" :class="['message', msg.role]">
          <div v-if="msg.role === 'user'" class="bubble user-bubble">
            {{ msg.content }}
          </div>

          <div v-else class="bubble ai-bubble">
            <div v-if="msg.intent" class="intent-tag"
              :style="{ background: INTENT_COLOR[msg.intent] + '22', color: INTENT_COLOR[msg.intent], borderColor: INTENT_COLOR[msg.intent] + '44' }">
              {{ INTENT_LABEL[msg.intent] || msg.intent }}
            </div>

            <div v-if="msg.tools.length > 0" class="tool-list">
              <div v-for="(t, ti) in msg.tools" :key="ti" class="tool-item" :class="{ done: t.done }">
                <span class="tool-icon">{{ t.done ? '✓' : '⟳' }}</span>
                <span>{{ t.name }}</span>
              </div>
            </div>

            <div v-if="msg.logs.length > 0" class="log-section">
              <div class="log-section-header">
                <span class="log-count">{{ msg.logs.length }} 条日志</span>
                <button class="export-btn" @click="exportLogsCSV(msg.logs)" title="导出 CSV">
                  ↓ 导出 CSV
                </button>
              </div>
              <LogTable :entries="msg.logs" />
            </div>

            <div v-if="msg.charts && msg.charts.length > 0" class="chart-section">
              <ChartWidget v-for="(opt, ci) in msg.charts" :key="ci" :option="opt" />
            </div>

            <div v-if="msg.content" class="ai-text" v-html="renderText(msg.content)" />

            <div v-if="!msg.content && loading && i === messages.length - 1" class="typing">
              <span></span><span></span><span></span>
            </div>

            <!-- 追问建议 -->
            <div v-if="msg.suggestions && msg.suggestions.length > 0" class="suggestions">
              <button
                v-for="s in msg.suggestions"
                :key="s"
                class="suggestion-pill"
                @click="sendMessage(s)"
              >→ {{ s }}</button>
            </div>
          </div>
        </div>
      </div>

      <!-- 输入区 -->
      <div class="input-area">
        <!-- 结束会话栏 -->
        <div v-if="currentSession?.status === 'ended'" class="ended-bar">
          <span class="ended-bar-text">会话已结束</span>
          <button class="reopen-bar-btn" @click="reopenSession(currentSessionId.value, $event)">继续对话</button>
        </div>

        <template v-else>
        <!-- 时间快捷 Chip -->
        <div class="time-chips">
          <button
            v-for="chip in TIME_CHIPS"
            :key="chip"
            :class="['time-chip', { active: timeChip === chip }]"
            @click="selectTimeChip(chip)"
          >{{ chip }}</button>
          <button class="close-session-btn" @click="closeSession">结束会话</button>
        </div>

        <div class="input-row">
          <el-input
            v-model="inputText"
            type="textarea"
            :autosize="{ minRows: 1, maxRows: 4 }"
            placeholder="输入问题，例如：查一下支付服务最近 1 小时的 ERROR 日志"
            :disabled="loading"
            @keydown="handleKeydown"
            resize="none"
          />
          <el-button
            type="primary"
            :loading="loading"
            :disabled="!inputText.trim()"
            @click="sendMessage()"
            class="send-btn"
          >发送</el-button>
        </div>
        </template>
      </div>
    </main>
  </div>
</template>

<style scoped>
@import 'highlight.js/styles/github-dark.css';

/* ── ai-text Markdown 渲染 ──────────────────────────────────────────────── */
.ai-text :deep(h1), .ai-text :deep(h2), .ai-text :deep(h3) {
  color: var(--text-primary);
  font-weight: 600;
  margin: 10px 0 4px;
}
.ai-text :deep(h1) { font-size: 17px; }
.ai-text :deep(h2) { font-size: 15px; }
.ai-text :deep(h3) { font-size: 13px; }
.ai-text :deep(p) { margin: 4px 0; line-height: 1.65; }
.ai-text :deep(ul), .ai-text :deep(ol) {
  padding-left: 18px;
  margin: 4px 0;
}
.ai-text :deep(li) { margin: 2px 0; line-height: 1.6; }
.ai-text :deep(code) {
  background: color-mix(in srgb, var(--accent) 12%, transparent);
  border-radius: 4px;
  padding: 1px 5px;
  font-size: 12px;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  color: var(--accent);
}
.ai-text :deep(pre) {
  background: #0d1117;
  border-radius: 8px;
  padding: 12px 14px;
  overflow-x: auto;
  margin: 8px 0;
}
.ai-text :deep(pre code) {
  background: none;
  padding: 0;
  color: inherit;
  font-size: 12px;
}
.ai-text :deep(table) {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  margin: 8px 0;
}
.ai-text :deep(th) {
  background: color-mix(in srgb, var(--accent) 15%, transparent);
  color: var(--text-primary);
  padding: 6px 10px;
  text-align: left;
  font-weight: 600;
  border-bottom: 1px solid var(--border);
}
.ai-text :deep(td) {
  padding: 5px 10px;
  border-bottom: 1px solid color-mix(in srgb, var(--border) 60%, transparent);
  color: var(--text-secondary);
}
.ai-text :deep(tr:hover td) { background: color-mix(in srgb, var(--accent) 5%, transparent); }
.ai-text :deep(blockquote) {
  border-left: 3px solid var(--accent);
  padding: 6px 12px;
  margin: 6px 0;
  color: var(--text-muted);
  background: color-mix(in srgb, var(--accent) 5%, transparent);
  border-radius: 0 6px 6px 0;
}
.ai-text :deep(hr) { border: none; border-top: 1px solid var(--border); margin: 10px 0; }
.ai-text :deep(strong) { color: var(--text-primary); font-weight: 600; }
.ai-text :deep(a) { color: var(--accent); text-decoration: underline; }

/* ── 数据源状态栏 ──────────────────────────────────────────────────────────── */
.ds-stats-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 48px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-sidebar);
  font-size: 12px;
  color: var(--text-muted);
  flex-shrink: 0;
}
.ds-stats-type {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--accent) 30%, transparent);
  padding: 1px 6px;
  border-radius: 4px;
}
.ds-stat-item b { color: var(--text-secondary); font-weight: 600; }
.ds-stat-error b { color: #ef4444; }
.ds-stat-sep { color: var(--border); }
.ds-stats-refresh {
  margin-left: auto;
  cursor: pointer;
  opacity: 0.5;
  font-size: 13px;
  transition: opacity 0.15s;
  user-select: none;
}
.ds-stats-refresh:hover { opacity: 1; }

/* ── 布局 ─────────────────────────────────────────────────────────────────── */
.chat-layout {
  display: flex;
  height: 100vh;
  background: var(--bg-app);
}

/* ── 侧边栏 ───────────────────────────────────────────────────────────────── */
.sidebar {
  width: 224px;
  background: var(--bg-sidebar);
  border-right: 1px solid var(--border);
  padding: 20px 12px 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  flex-shrink: 0;
}

.logo {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  margin-bottom: 2px;
}
.logo-icon { font-size: 20px; color: var(--accent); }
.logo-text  { font-size: 16px; font-weight: 600; color: var(--text-primary); flex: 1; }
.theme-btn {
  background: none;
  border: none;
  font-size: 16px;
  cursor: pointer;
  padding: 2px 4px;
  border-radius: 4px;
  line-height: 1;
  opacity: 0.7;
  transition: opacity 0.15s;
}
.theme-btn:hover { opacity: 1; }

.new-session-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 8px 12px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  color: var(--text-secondary);
  font-size: 13px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}
.new-session-btn:hover { background: var(--bg-msg-ai); color: var(--text-primary); }
.plus { font-size: 15px; line-height: 1; }

.section-label {
  font-size: 10px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.1em;
  padding: 0 6px;
}

/* 服务器状态 */
.server-section { display: flex; flex-direction: column; gap: 4px; }
.server-item {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 4px 8px;
  border-radius: 6px;
}
.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}
.dot-ok  { background: #22c55e; box-shadow: 0 0 5px #22c55e66; }
.dot-err { background: #ef4444; box-shadow: 0 0 5px #ef444466; }
.server-name { font-size: 12px; color: var(--text-muted); }

/* 会话列表 */
.session-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.session-item {
  padding: 8px 10px;
  border-radius: 7px;
  cursor: pointer;
  transition: background 0.12s;
}
.session-item:hover { background: var(--bg-card); }
.session-item.active { background: var(--bg-msg-user); }
.session-item:hover .del-btn { opacity: 1; }

.session-title {
  font-size: 12px;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 2px;
}
.session-item.active .session-title { color: var(--text-primary); }

.session-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.session-time { font-size: 10px; color: var(--text-muted); }

.del-btn {
  background: none;
  border: none;
  color: var(--text-muted);
  font-size: 10px;
  cursor: pointer;
  opacity: 0;
  padding: 1px 4px;
  border-radius: 3px;
  transition: opacity 0.12s, color 0.12s;
  line-height: 1;
}
.del-btn:hover { color: #ef4444; }

/* ── 主区域 ───────────────────────────────────────────────────────────────── */
.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.chat-body {
  flex: 1;
  overflow-y: auto;
  padding: 32px 48px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

/* ── 欢迎页 ───────────────────────────────────────────────────────────────── */
.welcome {
  margin: auto;
  text-align: center;
  max-width: 680px;
  width: 100%;
  padding: 8px 0 24px;
}
.welcome-icon  { font-size: 40px; color: var(--accent); margin-bottom: 12px; }
.welcome-title { font-size: 22px; font-weight: 600; color: var(--text-primary); margin-bottom: 6px; }
.welcome-sub   { font-size: 13px; color: var(--text-muted); margin-bottom: 20px; }

/* 配置入口 banner */
.config-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  background: var(--bg-card);
  border: 1px dashed var(--border);
  border-radius: 8px;
  text-decoration: none;
  color: var(--text-secondary);
  font-size: 13px;
  margin-bottom: 24px;
  transition: border-color 0.15s, color 0.15s;
}
.config-banner:hover { border-color: var(--accent); color: var(--accent); }
.config-banner-icon  { font-size: 15px; }
.config-banner-text  { flex: 1; text-align: left; }
.config-banner-arrow { opacity: 0.5; }

/* 能力分组 */
.capability-groups {
  display: flex;
  flex-direction: column;
  gap: 20px;
  text-align: left;
}

.capability-group {}

.group-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.group-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.group-label {
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}
.group-desc {
  font-size: 11px;
  color: var(--text-muted);
}

.group-cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}

.scene-card {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 14px;
  background: var(--bg-sidebar);
  border: 1px solid var(--border);
  border-left: 3px solid var(--card-accent, var(--border));
  border-radius: 8px;
  cursor: pointer;
  text-align: left;
  transition: background 0.15s, border-color 0.15s, transform 0.1s;
}
.scene-card:hover {
  background: var(--bg-card);
  border-left-color: var(--card-accent, var(--accent));
  transform: translateY(-1px);
}
.scene-icon  { font-size: 16px; margin-top: 1px; flex-shrink: 0; }
.scene-body  { display: flex; flex-direction: column; gap: 3px; }
.scene-label { font-size: 13px; font-weight: 500; color: var(--text-secondary); }
.scene-prompt { font-size: 11px; color: var(--text-muted); line-height: 1.4; }

/* ── 消息气泡 ─────────────────────────────────────────────────────────────── */
.message { display: flex; }
.message.user      { justify-content: flex-end; }
.message.assistant { justify-content: flex-start; }

.bubble {
  max-width: 72%;
  border-radius: 12px;
  padding: 12px 16px;
  font-size: 14px;
  line-height: 1.65;
}

.user-bubble {
  background: var(--accent);
  color: #fff;
  border-bottom-right-radius: 4px;
}

.ai-bubble {
  background: var(--bg-sidebar);
  border: 1px solid var(--border);
  color: var(--text-secondary);
  border-bottom-left-radius: 4px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.intent-tag {
  display: inline-block;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  border: 1px solid;
  font-weight: 500;
  align-self: flex-start;
}

.tool-list { display: flex; flex-direction: column; gap: 4px; }
.tool-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-muted);
}
.tool-item.done { color: #22c55e; }
.tool-icon { font-size: 11px; }

.log-section { margin: 4px 0; }
.log-section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 2px 6px;
}
.log-count { font-size: 11px; color: var(--text-muted); }
.export-btn {
  font-size: 11px;
  padding: 3px 10px;
  border-radius: 5px;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s;
}
.export-btn:hover {
  border-color: var(--accent);
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 8%, transparent);
}
.chart-section { margin: 8px 0; display: flex; flex-direction: column; gap: 8px; }

.ai-text :deep(strong) { color: var(--text-primary); }
.ai-text :deep(h1) { font-size: 16px; font-weight: 700; color: var(--text-primary); margin: 10px 0 4px; }
.ai-text :deep(h2) { font-size: 15px; font-weight: 600; color: var(--text-primary); margin: 8px 0 4px; }
.ai-text :deep(h3) { font-size: 14px; font-weight: 600; color: var(--text-secondary); margin: 6px 0 2px; }
.ai-text :deep(li) { margin-left: 16px; list-style: disc; }
.ai-text :deep(code) {
  background: var(--bg-app);
  border: 1px solid var(--border);
  border-radius: 3px;
  padding: 1px 5px;
  font-size: 12px;
  font-family: 'JetBrains Mono', monospace;
}

/* 追问建议 */
.suggestions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding-top: 4px;
  border-top: 1px solid var(--border);
}
.suggestion-pill {
  background: none;
  border: 1px solid var(--border);
  color: var(--text-muted);
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 20px;
  cursor: pointer;
  transition: border-color 0.15s, color 0.15s;
  white-space: nowrap;
}
.suggestion-pill:hover { border-color: var(--accent); color: #93c5fd; }

/* 打字动画 */
.typing { display: flex; gap: 4px; align-items: center; height: 20px; }
.typing span {
  width: 6px; height: 6px;
  background: #3b82f6;
  border-radius: 50%;
  animation: bounce 1.2s infinite;
}
.typing span:nth-child(2) { animation-delay: 0.2s; }
.typing span:nth-child(3) { animation-delay: 0.4s; }
@keyframes bounce {
  0%, 80%, 100% { transform: translateY(0); opacity: 0.4; }
  40%           { transform: translateY(-6px); opacity: 1; }
}

/* ── 输入区 ───────────────────────────────────────────────────────────────── */
.input-area {
  padding: 12px 48px 20px;
  border-top: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.time-chips {
  display: flex;
  gap: 6px;
}

.time-chip {
  background: none;
  border: 1px solid var(--border);
  color: var(--text-muted);
  font-size: 12px;
  padding: 4px 12px;
  border-radius: 20px;
  cursor: pointer;
  transition: border-color 0.15s, color 0.15s, background 0.15s;
  white-space: nowrap;
}
.time-chip:hover  { border-color: var(--border); color: var(--text-secondary); }
.time-chip.active { border-color: var(--accent); color: #93c5fd; background: var(--bg-msg-user)22; }

.input-row {
  display: flex;
  gap: 10px;
  align-items: flex-end;
}

.input-area :deep(.el-textarea__inner) {
  background: var(--bg-sidebar);
  border-color: var(--border);
  color: var(--text-primary);
  border-radius: 8px;
  font-size: 14px;
}
.input-area :deep(.el-textarea__inner:focus) { border-color: var(--accent); }

.send-btn { height: 36px; border-radius: 8px; flex-shrink: 0; }

/* 结束/继续 */
.session-item.ended .session-title { color: var(--text-muted); }
.session-item.ended.active .session-title { color: var(--text-muted); }

.ended-badge {
  font-size: 9px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  color: var(--text-muted);
  border-radius: 3px;
  padding: 1px 4px;
  margin-left: 4px;
  vertical-align: middle;
}

.reopen-btn {
  background: none;
  border: 1px solid var(--border);
  color: var(--accent);
  font-size: 10px;
  cursor: pointer;
  padding: 1px 6px;
  border-radius: 3px;
  transition: border-color 0.12s, color 0.12s;
  line-height: 1.4;
}
.reopen-btn:hover { border-color: var(--accent); color: #93c5fd; }

.close-session-btn {
  margin-left: auto;
  background: none;
  border: 1px solid var(--border);
  color: var(--text-muted);
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 20px;
  cursor: pointer;
  transition: border-color 0.15s, color 0.15s;
  white-space: nowrap;
}
.close-session-btn:hover { border-color: #ef444466; color: #ef4444; }

.ended-bar {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 12px;
  background: var(--bg-sidebar);
  border: 1px solid var(--border);
  border-radius: 8px;
}
.ended-bar-text { font-size: 13px; color: var(--text-muted); }
.reopen-bar-btn {
  background: none;
  border: 1px solid #3b82f6;
  color: var(--accent);
  font-size: 13px;
  padding: 6px 16px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}
.reopen-bar-btn:hover { background: var(--bg-msg-user)44; color: #93c5fd; }

.sidebar-footer {
  padding-top: 12px;
  border-top: 1px solid var(--border);
  margin-top: 8px;
}

.config-link {
  display: block;
  padding: 8px 10px;
  color: var(--text-muted);
  text-decoration: none;
  font-size: 13px;
  border-radius: 6px;
  transition: all 0.15s;
}
.config-link:hover { background: var(--bg-card); color: var(--text-secondary); }

.export-session-btn {
  display: block;
  width: 100%;
  padding: 8px 10px;
  margin-bottom: 4px;
  color: var(--text-muted);
  font-size: 13px;
  border-radius: 6px;
  border: 1px dashed var(--border);
  background: transparent;
  cursor: pointer;
  text-align: left;
  transition: all 0.15s;
}
.export-session-btn:hover {
  border-color: var(--accent);
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 6%, transparent);
}
</style>
