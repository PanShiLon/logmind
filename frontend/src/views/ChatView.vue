<script setup>
import { ref, nextTick, onMounted } from 'vue'
import LogTable from '../components/LogTable.vue'

const messages = ref([])
const inputText = ref('')
const loading = ref(false)
const chatBody = ref(null)

const SUGGESTIONS = [
  '查一下最近1小时的 ERROR 日志',
  '过去24小时有哪些异常？',
  '分析一下错误趋势，是否在加剧',
  '检查数据源连通性',
]

function parseLogLines(text) {
  const lines = text.split('\n').filter(l => l.trim())
  const entries = []
  for (const line of lines) {
    const m = line.match(/^\[(.+?)\]\s+\[(\w+)\]\s+\[(.+?)\]\s+(.*)$/)
    if (m) {
      entries.push({ timestamp: m[1], level: m[2], source: m[3], message: m[4] })
    }
  }
  return entries
}

async function scrollToBottom() {
  await nextTick()
  if (chatBody.value) {
    chatBody.value.scrollTop = chatBody.value.scrollHeight
  }
}

async function sendMessage(text) {
  const msg = (text || inputText.value).trim()
  if (!msg || loading.value) return

  inputText.value = ''
  messages.value.push({ role: 'user', content: msg })
  loading.value = true
  await scrollToBottom()

  const aiMsg = { role: 'assistant', content: '', intent: null, tools: [], logs: [] }
  messages.value.push(aiMsg)

  try {
    const resp = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: msg }),
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
        } else if (evt.type === 'done') {
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

const INTENT_LABEL = { query: '日志查询', analyze: '趋势分析' }
const INTENT_COLOR = { query: '#3b82f6', analyze: '#8b5cf6' }
const LEVEL_COLOR = { ERROR: '#ef4444', WARN: '#f59e0b', INFO: '#22c55e', DEBUG: '#6b7280', UNKNOWN: '#6b7280' }

function renderText(text) {
  return text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\n/g, '<br>')
}
</script>

<template>
  <div class="chat-layout">
    <aside class="sidebar">
      <div class="logo">
        <span class="logo-icon">◈</span>
        <span class="logo-text">LogMind</span>
      </div>
      <div class="sidebar-section">
        <div class="sidebar-label">快速提问</div>
        <button
          v-for="s in SUGGESTIONS"
          :key="s"
          class="suggestion-btn"
          @click="sendMessage(s)"
        >{{ s }}</button>
      </div>
    </aside>

    <main class="chat-main">
      <div class="chat-body" ref="chatBody">
        <div v-if="messages.length === 0" class="empty-state">
          <div class="empty-icon">◈</div>
          <div class="empty-title">LogMind AI 日志分析</div>
          <div class="empty-sub">用自然语言查询和分析服务器日志</div>
        </div>

        <div
          v-for="(msg, i) in messages"
          :key="i"
          :class="['message', msg.role]"
        >
          <div v-if="msg.role === 'user'" class="bubble user-bubble">
            {{ msg.content }}
          </div>

          <div v-else class="bubble ai-bubble">
            <div v-if="msg.intent" class="intent-tag" :style="{ background: INTENT_COLOR[msg.intent] + '22', color: INTENT_COLOR[msg.intent], borderColor: INTENT_COLOR[msg.intent] + '44' }">
              {{ INTENT_LABEL[msg.intent] || msg.intent }}
            </div>

            <div v-if="msg.tools.length > 0" class="tool-list">
              <div v-for="(t, ti) in msg.tools" :key="ti" class="tool-item" :class="{ done: t.done }">
                <span class="tool-icon">{{ t.done ? '✓' : '⟳' }}</span>
                <span>{{ t.name }}</span>
              </div>
            </div>

            <div v-if="msg.logs.length > 0" class="log-section">
              <LogTable :entries="msg.logs" />
            </div>

    <div v-if="msg.content" class="ai-text" v-html="renderText(msg.content)" />

            <div v-if="!msg.content && loading && i === messages.length - 1" class="typing">
              <span></span><span></span><span></span>
            </div>
          </div>
        </div>
      </div>

      <div class="input-area">
        <el-input
          v-model="inputText"
          type="textarea"
          :autosize="{ minRows: 1, maxRows: 4 }"
          placeholder="输入问题，例如：查一下支付服务最近1小时的 ERROR 日志"
          :disabled="loading"
          @keydown.enter="handleEnter"
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
    </main>
  </div>
</template>

<style scoped>
.chat-layout {
  display: flex;
  height: 100vh;
  background: #0f1117;
}

.sidebar {
  width: 220px;
  background: #161b27;
  border-right: 1px solid #1e2535;
  padding: 20px 12px;
  display: flex;
  flex-direction: column;
  gap: 24px;
  flex-shrink: 0;
}

.logo {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
}
.logo-icon { font-size: 20px; color: #3b82f6; }
.logo-text { font-size: 16px; font-weight: 600; color: #e2e8f0; }

.sidebar-label {
  font-size: 11px;
  color: #4b5563;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin-bottom: 8px;
  padding: 0 8px;
}

.suggestion-btn {
  display: block;
  width: 100%;
  text-align: left;
  background: none;
  border: none;
  color: #94a3b8;
  font-size: 13px;
  padding: 8px;
  border-radius: 6px;
  cursor: pointer;
  line-height: 1.4;
  transition: background 0.15s, color 0.15s;
}
.suggestion-btn:hover { background: #1e2535; color: #e2e8f0; }

.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.chat-body {
  flex: 1;
  overflow-y: auto;
  padding: 24px 32px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.empty-state {
  margin: auto;
  text-align: center;
  color: #4b5563;
}
.empty-icon { font-size: 40px; color: #1e3a5f; margin-bottom: 12px; }
.empty-title { font-size: 18px; color: #64748b; margin-bottom: 6px; }
.empty-sub { font-size: 14px; }

.message { display: flex; }
.message.user { justify-content: flex-end; }
.message.assistant { justify-content: flex-start; }

.bubble {
  max-width: 72%;
  border-radius: 12px;
  padding: 12px 16px;
  font-size: 14px;
  line-height: 1.6;
}

.user-bubble {
  background: #1d4ed8;
  color: #fff;
  border-bottom-right-radius: 4px;
}

.ai-bubble {
  background: #161b27;
  border: 1px solid #1e2535;
  color: #cbd5e1;
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

.tool-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.tool-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #64748b;
}
.tool-item.done { color: #22c55e; }
.tool-icon { font-size: 11px; }

.log-section { margin: 4px 0; }

.ai-text :deep(strong) { color: #e2e8f0; }
.ai-text :deep(code) {
  background: #0f1117;
  border: 1px solid #1e2535;
  border-radius: 3px;
  padding: 1px 5px;
  font-size: 12px;
  font-family: 'JetBrains Mono', monospace;
}

.typing {
  display: flex;
  gap: 4px;
  align-items: center;
  height: 20px;
}
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
  40% { transform: translateY(-6px); opacity: 1; }
}

.input-area {
  padding: 16px 32px 20px;
  border-top: 1px solid #1e2535;
  display: flex;
  gap: 10px;
  align-items: flex-end;
}

.input-area :deep(.el-textarea__inner) {
  background: #161b27;
  border-color: #1e2535;
  color: #e2e8f0;
  border-radius: 8px;
  font-size: 14px;
}
.input-area :deep(.el-textarea__inner:focus) { border-color: #3b82f6; }

.send-btn { height: 36px; border-radius: 8px; flex-shrink: 0; }
</style>
