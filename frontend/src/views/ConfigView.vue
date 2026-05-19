<template>
  <div class="config-page">
    <div class="config-header">
      <a href="/" class="back-btn">← 返回对话</a>
      <h2>数据源配置</h2>
      <p class="subtitle">配置后点击「测试连接」验证，通过后保存生效</p>
    </div>

    <div class="tab-bar">
      <button
        v-for="t in tabs"
        :key="t.key"
        :class="['tab-btn', { active: activeTab === t.key }]"
        @click="activeTab = t.key"
      >
        {{ t.label }}
        <span v-if="activeTab === t.key" class="active-badge">当前</span>
      </button>
    </div>
    <p class="mode-tip">三种模式互斥，保存时以当前选中的模式为准。</p>

    <!-- SSH Tab -->
    <div v-if="activeTab === 'ssh'" class="tab-panel">
      <div class="section-title">SSH 服务器列表</div>
      <div v-for="(srv, i) in ssh.servers" :key="i" class="server-card">
        <div class="card-header">
          <span>服务器 {{ i + 1 }}</span>
          <button class="del-btn" @click="ssh.servers.splice(i, 1)" v-if="ssh.servers.length > 1">删除</button>
        </div>
        <div class="form-grid">
          <label>名称 <input v-model="srv.name" placeholder="e.g. payment-service" /></label>
          <label>主机 <input v-model="srv.host" placeholder="192.168.1.10" /></label>
          <label>端口 <input v-model.number="srv.port" type="number" placeholder="22" /></label>
          <label>用户名 <input v-model="srv.username" placeholder="root" /></label>
          <label>密码 <input v-model="srv.password" type="password" placeholder="留空则用密钥" /></label>
          <label>私钥路径 <input v-model="srv.private_key_path" placeholder="~/.ssh/id_rsa（可选）" /></label>
        </div>
        <div class="log-paths-row">
          <label>日志路径（每行一个）</label>
          <textarea
            :value="srv.log_paths.join('\n')"
            @input="srv.log_paths = $event.target.value.split('\n').filter(Boolean)"
            placeholder="/var/log/app/app.log&#10;/var/log/app/error.log"
            rows="3"
          />
        </div>
        <div class="test-row">
          <button class="test-btn" @click="testSSH(i)" :disabled="testing === `ssh-${i}`">
            {{ testing === `ssh-${i}` ? '测试中...' : '测试连接' }}
          </button>
          <span v-if="testResults[`ssh-${i}`]" :class="['test-result', testResults[`ssh-${i}`].ok ? 'ok' : 'fail']">
            {{ testResults[`ssh-${i}`].message }}
          </span>
        </div>
      </div>
      <button class="add-btn" @click="addServer">+ 添加服务器</button>
    </div>

    <!-- Elasticsearch Tab -->
    <div v-if="activeTab === 'es'" class="tab-panel">
      <div class="form-grid">
        <label class="full">
          ES 地址（每行一个）
          <textarea
            :value="es.hosts.join('\n')"
            @input="es.hosts = $event.target.value.split('\n').filter(Boolean)"
            placeholder="http://192.168.1.100:9200"
            rows="3"
          />
        </label>
        <label>用户名 <input v-model="es.username" placeholder="elastic" /></label>
        <label>密码 <input v-model="es.password" type="password" placeholder="留空则无鉴权" /></label>
        <label>索引名 <input v-model="es.index" placeholder="app-logs-*" /></label>
        <label class="checkbox-label">
          <input type="checkbox" v-model="es.verify_certs" />
          验证 SSL 证书
        </label>
      </div>
      <div class="test-row">
        <button class="test-btn" @click="testES" :disabled="testing === 'es'">
          {{ testing === 'es' ? '测试中...' : '测试连接' }}
        </button>
        <span v-if="testResults['es']" :class="['test-result', testResults['es'].ok ? 'ok' : 'fail']">
          {{ testResults['es'].message }}
        </span>
      </div>

      <!-- ES 数据预览 -->
      <div v-if="esPreview" class="es-preview">
        <div class="preview-title">
          数据预览
          <span class="preview-refresh" @click="loadESPreview" title="刷新">↻</span>
        </div>
        <div v-if="esPreviewLoading" class="preview-loading">加载中...</div>
        <div v-else-if="!esPreview.ok" class="preview-error">{{ esPreview.message }}</div>
        <div v-else>
          <div class="preview-stats">
            <div class="stat-card">
              <div class="stat-value">{{ esPreview.total?.toLocaleString() }}</div>
              <div class="stat-label">总日志量</div>
            </div>
            <div class="stat-card error">
              <div class="stat-value">{{ esPreview.error_count?.toLocaleString() }}</div>
              <div class="stat-label">ERROR 条数</div>
            </div>
            <div class="stat-card warn">
              <div class="stat-value">{{ esPreview.error_ratio }}%</div>
              <div class="stat-label">ERROR 占比</div>
            </div>
          </div>
          <div v-if="esPreview.services?.length" class="preview-service-list">
            <div class="service-list-title">服务列表（Top {{ esPreview.services.length }}）</div>
            <div class="service-table">
              <div class="service-row header-row">
                <span>服务名</span>
                <span>日志量</span>
                <span>占比</span>
              </div>
              <div v-for="svc in esPreview.services" :key="svc.name" class="service-row">
                <span class="svc-name">{{ svc.name }}</span>
                <span>{{ svc.count.toLocaleString() }}</span>
                <span>
                  <div class="bar-wrap">
                    <div class="bar-fill" :style="{ width: Math.round(svc.count / esPreview.total * 100) + '%' }"></div>
                    <span class="bar-pct">{{ Math.round(svc.count / esPreview.total * 100) }}%</span>
                  </div>
                </span>
              </div>
            </div>
          </div>
          <div v-else class="preview-empty">未检测到 service 字段，请确认索引 mapping</div>
        </div>
      </div>
    </div>

    <!-- DuckDB Tab -->
    <div v-if="activeTab === 'duckdb'" class="tab-panel">
      <div class="form-grid">
        <label class="full">
          数据库文件路径
          <input v-model="duckdb.db_path" placeholder="./data/logmind.db" />
        </label>
      </div>
      <div class="test-row">
        <button class="test-btn" @click="testDuckDB" :disabled="testing === 'duckdb'">
          {{ testing === 'duckdb' ? '测试中...' : '测试连接' }}
        </button>
        <span v-if="testResults['duckdb']" :class="['test-result', testResults['duckdb'].ok ? 'ok' : 'fail']">
          {{ testResults['duckdb'].message }}
        </span>
      </div>
    </div>

    <!-- LLM 配置 -->
    <div class="section-divider" />
    <div class="section-title">LLM 配置</div>
    <div class="form-grid">
      <label>
        Provider
        <select v-model="llm.provider" @change="onProviderChange">
          <option v-for="p in LLM_PROVIDERS" :key="p.key" :value="p.key">{{ p.label }}</option>
        </select>
      </label>
      <label v-if="llm.provider === 'custom'">
        自定义 Provider 名称
        <input v-model="llm.custom_provider" placeholder="e.g. ollama" />
      </label>
      <label>
        API Key
        <div class="input-eye">
          <span class="eye-lock">🔒</span>
          <input v-model="llm.api_key" :type="showApiKey ? 'text' : 'password'" placeholder="sk-xxxx" />
          <button type="button" class="eye-btn" @click="showApiKey = !showApiKey" tabindex="-1">
            <svg v-if="!showApiKey" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>
            </svg>
            <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/><path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/><line x1="1" y1="1" x2="23" y2="23"/>
            </svg>
          </button>
        </div>
      </label>
      <label>模型 <input v-model="llm.model" :placeholder="llm.provider === 'custom' ? 'e.g. llama3' : ''" /></label>
      <label>Base URL <input v-model="llm.base_url" :placeholder="llm.provider === 'custom' ? 'http://localhost:11434/v1' : ''" /></label>
    </div>
    <div class="test-row" style="margin-bottom: 8px">
      <button class="test-btn" @click="testLLM" :disabled="testing === 'llm'">
        {{ testing === 'llm' ? '测试中...' : '测试连接' }}
      </button>
      <span v-if="testResults['llm']" :class="['test-result', testResults['llm'].ok ? 'ok' : 'fail']">
        {{ testResults['llm'].message }}
      </span>
    </div>

    <div class="action-row">
      <button class="save-btn" @click="saveConfig" :disabled="saving">
        {{ saving ? '保存中...' : '保存配置' }}
      </button>
      <span v-if="saveMsg" :class="['save-result', saveOk ? 'ok' : 'fail']">{{ saveMsg }}</span>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'

// 同步主题，避免进入配置页时主题丢失
const theme = localStorage.getItem('logmind-theme') || 'dark'
document.documentElement.setAttribute('data-theme', theme)

const tabs = [
  { key: 'ssh', label: 'SSH 直连' },
  { key: 'es', label: 'Elasticsearch' },
  { key: 'duckdb', label: 'DuckDB' },
]
const activeTab = ref('ssh')

const ssh = reactive({
  servers: [{ name: 'payment-service', host: '192.168.1.10', port: 22, username: 'root', password: '', private_key_path: '', log_paths: ['/var/log/app/app.log', '/var/log/app/error.log'] }],
})
const es = reactive({ hosts: ['http://192.168.1.100:9200'], username: 'elastic', password: '', index: 'app-logs-*', verify_certs: false })
const duckdb = reactive({ db_path: './data/logmind.db' })
const LLM_PROVIDERS = [
  { key: 'kimi',     label: 'Kimi（月之暗面）',  model: 'kimi-k2-0711-preview',  base_url: 'https://api.moonshot.cn/v1' },
  { key: 'deepseek', label: 'DeepSeek',          model: 'deepseek-chat',          base_url: 'https://api.deepseek.com/v1' },
  { key: 'openai',   label: 'OpenAI',            model: 'gpt-4o-mini',            base_url: 'https://api.openai.com/v1' },
  { key: 'qwen',     label: '通义千问（阿里）',   model: 'qwen-turbo',             base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1' },
  { key: 'zhipu',    label: '智谱 GLM',           model: 'glm-4-flash',            base_url: 'https://open.bigmodel.cn/api/paas/v4' },
  { key: 'custom',   label: '自定义',             model: '',                       base_url: '' },
]

const llm = reactive({ provider: 'kimi', custom_provider: '', api_key: '', model: 'kimi-k2-0711-preview', base_url: 'https://api.moonshot.cn/v1' })
const showApiKey = ref(false)

function onProviderChange() {
  const p = LLM_PROVIDERS.find(p => p.key === llm.provider)
  if (p && p.key !== 'custom') {
    llm.model = p.model
    llm.base_url = p.base_url
  } else {
    llm.model = ''
    llm.base_url = ''
    llm.custom_provider = ''
  }
}

const testing = ref(null)
const testResults = reactive({})
const saving = ref(false)
const saveMsg = ref('')
const saveOk = ref(false)
const esPreview = ref(null)
const esPreviewLoading = ref(false)

onMounted(async () => {
  try {
    const res = await fetch('/api/config')
    if (!res.ok) return
    const data = await res.json()
    if (data.llm) {
      Object.assign(llm, data.llm)
      if (!LLM_PROVIDERS.find(p => p.key === llm.provider)) llm.provider = 'custom'
    }
    if (data.servers?.length) {
      ssh.servers = data.servers.map(s => ({
        name: s.name || '', host: s.host || '', port: s.port || 22,
        username: s.username || 'root', password: s.password === '***' ? '' : (s.password || ''),
        private_key_path: s.private_key_path || '', log_paths: s.log_paths || [],
      }))
    }
    if (data.datasource?.type === 'elasticsearch') {
      es.hosts = data.datasource.hosts || ['']
      es.username = data.datasource.username || 'elastic'
      es.password = data.datasource.password === '***' ? '' : (data.datasource.password || '')
      es.index = data.datasource.default_index || 'app-logs-*'
      es.verify_certs = data.datasource.verify_certs ?? false
      activeTab.value = 'es'
    } else if (data.datasource?.type === 'duckdb') {
      duckdb.db_path = data.datasource.db_path || ''
      activeTab.value = 'duckdb'
    }
  } catch {}
})

function addServer() {
  ssh.servers.push({ name: '', host: '', port: 22, username: 'root', password: '', private_key_path: '', log_paths: [] })
}

async function testSSH(i) {
  const srv = ssh.servers[i]
  const key = `ssh-${i}`
  if (!srv.host) { testResults[key] = { ok: false, message: '请填写主机地址' }; return }
  if (!srv.username) { testResults[key] = { ok: false, message: '请填写用户名' }; return }
  if (!srv.password && !srv.private_key_path) { testResults[key] = { ok: false, message: '密码和私钥至少填一个' }; return }
  testing.value = key
  testResults[key] = null
  try {
    const res = await fetch('/api/config/test-connection/ssh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        host: srv.host, port: srv.port, username: srv.username,
        password: srv.password || null, private_key_path: srv.private_key_path || null,
        log_paths: srv.log_paths,
      }),
    })
    testResults[key] = await res.json()
  } catch (e) {
    testResults[key] = { ok: false, message: `请求失败: ${e.message}` }
  } finally {
    testing.value = null
  }
}

async function testES() {
  testing.value = 'es'
  testResults['es'] = null
  esPreview.value = null
  try {
    const res = await fetch('/api/config/test-connection/elasticsearch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        hosts: es.hosts.filter(Boolean),
        username: es.username || null,
        password: es.password || null,
        index: es.index,
        verify_certs: es.verify_certs,
      }),
    })
    testResults['es'] = await res.json()
    if (testResults['es'].ok) loadESPreview()
  } catch (e) {
    testResults['es'] = { ok: false, message: `请求失败: ${e.message}` }
  } finally {
    testing.value = null
  }
}

async function loadESPreview() {
  esPreviewLoading.value = true
  esPreview.value = { ok: true }  // 先占位让面板出现
  try {
    const res = await fetch('/api/config/preview/elasticsearch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        hosts: es.hosts.filter(Boolean),
        username: es.username || null,
        password: es.password || null,
        index: es.index,
        verify_certs: es.verify_certs,
      }),
    })
    esPreview.value = await res.json()
  } catch (e) {
    esPreview.value = { ok: false, message: `预览失败: ${e.message}` }
  } finally {
    esPreviewLoading.value = false
  }
}

async function testDuckDB() {
  testing.value = 'duckdb'
  testResults['duckdb'] = null
  try {
    const res = await fetch('/api/config/test-connection/duckdb', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ db_path: duckdb.db_path }),
    })
    testResults['duckdb'] = await res.json()
  } catch (e) {
    testResults['duckdb'] = { ok: false, message: `请求失败: ${e.message}` }
  } finally {
    testing.value = null
  }
}

async function testLLM() {
  testing.value = 'llm'
  testResults['llm'] = null
  try {
    const res = await fetch('/api/config/test-connection/llm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        provider: llm.provider === 'custom' ? llm.custom_provider : llm.provider,
        api_key: llm.api_key,
        model: llm.model,
        base_url: llm.base_url,
      }),
    })
    testResults['llm'] = await res.json()
  } catch (e) {
    testResults['llm'] = { ok: false, message: `请求失败: ${e.message}` }
  } finally {
    testing.value = null
  }
}

async function saveConfig() {
  saving.value = true
  saveMsg.value = ''

  const dsType = activeTab.value === 'es' ? 'elasticsearch' : activeTab.value

  const llmData = {
    provider: llm.provider === 'custom' ? (llm.custom_provider || 'custom') : llm.provider,
    api_key: llm.api_key,
    model: llm.model,
    base_url: llm.base_url,
  }
  const cfg = { llm: llmData, datasource: { type: dsType } }

  if (dsType === 'ssh') {
    cfg.servers = ssh.servers.map(s => ({
      name: s.name, host: s.host, port: s.port, username: s.username,
      ...(s.password ? { password: s.password } : {}),
      ...(s.private_key_path ? { private_key_path: s.private_key_path } : {}),
      log_paths: s.log_paths,
    }))
  } else if (dsType === 'elasticsearch') {
    cfg.datasource = {
      type: 'elasticsearch',
      hosts: es.hosts.filter(Boolean),
      ...(es.username ? { username: es.username } : {}),
      ...(es.password ? { password: es.password } : {}),
      default_index: es.index,
      verify_certs: es.verify_certs,
    }
  } else if (dsType === 'duckdb') {
    cfg.datasource = { type: 'duckdb', db_path: duckdb.db_path }
  }

  // 转成 YAML 字符串
  const yamlStr = toYaml(cfg)

  try {
    const res = await fetch('/api/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: yamlStr }),
    })
    const data = await res.json()
    if (res.ok) {
      saveOk.value = true
      saveMsg.value = data.message || '保存成功'
    } else {
      saveOk.value = false
      saveMsg.value = data.detail || '保存失败'
    }
  } catch (e) {
    saveOk.value = false
    saveMsg.value = `请求失败: ${e.message}`
  } finally {
    saving.value = false
  }
}

// 轻量 YAML 序列化（不引入额外依赖）
function toYaml(obj, indent = 0) {
  const pad = '  '.repeat(indent)
  let out = ''
  for (const [k, v] of Object.entries(obj)) {
    if (v === null || v === undefined) continue
    if (Array.isArray(v)) {
      if (v.length === 0) { out += `${pad}${k}: []\n`; continue }
      if (typeof v[0] === 'object') {
        out += `${pad}${k}:\n`
        for (const item of v) out += `${pad}  - \n` + toYaml(item, indent + 2).replace(/^/gm, '  ')
      } else {
        out += `${pad}${k}:\n`
        for (const item of v) out += `${pad}  - ${yamlVal(item)}\n`
      }
    } else if (typeof v === 'object') {
      out += `${pad}${k}:\n` + toYaml(v, indent + 1)
    } else {
      out += `${pad}${k}: ${yamlVal(v)}\n`
    }
  }
  return out
}

function yamlVal(v) {
  if (typeof v === 'boolean') return v ? 'true' : 'false'
  if (typeof v === 'number') return String(v)
  if (typeof v === 'string' && /[:#\[\]{}&*!|>'"%@`,]/.test(v)) return `"${v.replace(/"/g, '\\"')}"`
  return String(v)
}
</script>

<style scoped>
.config-page {
  max-width: 800px;
  margin: 0 auto;
  padding: 28px 24px 48px;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  color: var(--text-primary);
}

/* 返回按钮 */
.back-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--text-muted);
  text-decoration: none;
  margin-bottom: 16px;
  transition: color 0.15s;
}
.back-btn:hover { color: var(--accent); }

.config-header h2 {
  font-size: 20px;
  font-weight: 600;
  margin: 0 0 4px;
  color: var(--text-primary);
}

.subtitle {
  font-size: 13px;
  color: var(--text-muted);
  margin: 0 0 24px;
}

.tab-bar {
  display: flex;
  gap: 4px;
  margin-bottom: 24px;
  border-bottom: 1px solid var(--border);
  padding-bottom: 0;
}

.tab-btn {
  padding: 8px 20px;
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--text-muted);
  font-size: 14px;
  cursor: pointer;
  margin-bottom: -1px;
  transition: all 0.15s;
}
.tab-btn:hover { color: var(--text-secondary); }
.tab-btn.active { color: var(--accent); border-bottom-color: var(--accent); }

.active-badge {
  display: inline-block;
  margin-left: 6px;
  padding: 1px 6px;
  font-size: 10px;
  background: color-mix(in srgb, var(--accent) 15%, transparent);
  color: var(--accent);
  border-radius: 4px;
  vertical-align: middle;
}

.mode-tip {
  font-size: 12px;
  color: var(--text-muted);
  margin: -12px 0 16px;
}

.tab-panel { animation: fadeIn 0.15s ease; }
@keyframes fadeIn { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }

.section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 12px;
}

.server-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 12px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
}

.del-btn {
  background: none;
  border: 1px solid var(--border);
  color: var(--text-muted);
  padding: 2px 10px;
  border-radius: 4px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
}
.del-btn:hover { border-color: #ef4444; color: #ef4444; }

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-bottom: 12px;
}

.form-grid label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12px;
  color: var(--text-muted);
}

.form-grid label.full { grid-column: 1 / -1; }

.form-grid input,
.form-grid textarea,
.form-grid select {
  background: var(--bg-input);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text-primary);
  padding: 8px 10px;
  font-size: 13px;
  outline: none;
  transition: border-color 0.15s;
  font-family: inherit;
}
.form-grid input:focus,
.form-grid textarea:focus,
.form-grid select:focus { border-color: var(--accent); }

.checkbox-label {
  flex-direction: row !important;
  align-items: center;
  gap: 8px !important;
  font-size: 13px !important;
  color: var(--text-secondary) !important;
  cursor: pointer;
}

.log-paths-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 12px;
}

.log-paths-row textarea {
  background: var(--bg-input);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text-primary);
  padding: 8px 10px;
  font-size: 13px;
  outline: none;
  resize: vertical;
  font-family: monospace;
  transition: border-color 0.15s;
}
.log-paths-row textarea:focus { border-color: var(--accent); }

.test-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.test-btn {
  padding: 7px 16px;
  background: color-mix(in srgb, var(--accent) 12%, transparent);
  border: 1px solid var(--accent);
  color: var(--accent);
  border-radius: 6px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}
.test-btn:hover:not(:disabled) { background: var(--accent); color: #fff; }
.test-btn:disabled { opacity: 0.5; cursor: default; }

.test-result { font-size: 13px; }
.test-result.ok   { color: #22c55e; }
.test-result.fail { color: #ef4444; }

.add-btn {
  margin-top: 4px;
  background: none;
  border: 1px dashed var(--border);
  color: var(--text-muted);
  padding: 8px 20px;
  border-radius: 6px;
  font-size: 13px;
  cursor: pointer;
  width: 100%;
  transition: all 0.15s;
}
.add-btn:hover { border-color: var(--accent); color: var(--accent); }

.section-divider {
  margin: 28px 0 20px;
  border: none;
  border-top: 1px solid var(--border);
}

.action-row {
  margin-top: 28px;
  display: flex;
  align-items: center;
  gap: 16px;
}

.save-btn {
  padding: 10px 32px;
  background: var(--accent);
  border: none;
  color: #fff;
  border-radius: 6px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: opacity 0.15s;
}
.save-btn:hover:not(:disabled) { opacity: 0.85; }
.save-btn:disabled { opacity: 0.5; cursor: default; }

.save-result { font-size: 13px; }
.save-result.ok   { color: #22c55e; }
.save-result.fail { color: #ef4444; }

.input-eye {
  position: relative;
  display: flex;
  align-items: center;
  background: var(--bg-input);
  border: 1px solid var(--border);
  border-radius: 6px;
  transition: border-color 0.15s;
}
.input-eye:focus-within { border-color: var(--accent); }
.input-eye input {
  flex: 1;
  background: none;
  border: none !important;
  outline: none !important;
  padding: 8px 36px 8px 36px;
  color: var(--text-primary);
}
.eye-lock {
  position: absolute;
  left: 10px;
  font-size: 13px;
  opacity: 0.5;
  pointer-events: none;
}
.eye-btn {
  position: absolute;
  right: 8px;
  background: none;
  border: none;
  cursor: pointer;
  padding: 0;
  color: var(--text-muted);
  display: flex;
  align-items: center;
}
.eye-btn:hover { color: var(--text-secondary); }
/* ES 数据预览 */
.es-preview {
  margin-top: 20px;
  padding: 16px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--bg-input);
}
.preview-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 14px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.preview-refresh {
  cursor: pointer;
  color: var(--accent);
  font-size: 16px;
  line-height: 1;
  transition: transform 0.3s;
}
.preview-refresh:hover { transform: rotate(180deg); }
.preview-loading, .preview-error, .preview-empty {
  font-size: 13px;
  color: var(--text-muted);
  padding: 8px 0;
}
.preview-error { color: #f87171; }
.preview-stats {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}
.stat-card {
  flex: 1;
  padding: 12px;
  border-radius: 8px;
  background: color-mix(in srgb, var(--accent) 8%, transparent);
  border: 1px solid color-mix(in srgb, var(--accent) 20%, transparent);
  text-align: center;
}
.stat-card.error {
  background: color-mix(in srgb, #f87171 8%, transparent);
  border-color: color-mix(in srgb, #f87171 20%, transparent);
}
.stat-card.warn {
  background: color-mix(in srgb, #fbbf24 8%, transparent);
  border-color: color-mix(in srgb, #fbbf24 20%, transparent);
}
.stat-value {
  font-size: 20px;
  font-weight: 700;
  color: var(--text-primary);
}
.stat-card.error .stat-value { color: #f87171; }
.stat-card.warn .stat-value { color: #fbbf24; }
.stat-label {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 4px;
}
.service-list-title {
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 8px;
}
.service-table { display: flex; flex-direction: column; gap: 4px; }
.service-row {
  display: grid;
  grid-template-columns: 1fr 80px 120px;
  align-items: center;
  font-size: 12px;
  padding: 6px 8px;
  border-radius: 6px;
  gap: 8px;
}
.service-row:not(.header-row):hover { background: color-mix(in srgb, var(--accent) 6%, transparent); }
.header-row {
  color: var(--text-muted);
  font-weight: 600;
  font-size: 11px;
  border-bottom: 1px solid var(--border);
  padding-bottom: 8px;
}
.svc-name { color: var(--text-primary); font-weight: 500; }
.bar-wrap { display: flex; align-items: center; gap: 6px; }
.bar-fill {
  height: 6px;
  background: var(--accent);
  border-radius: 3px;
  min-width: 2px;
  max-width: 70px;
  flex-shrink: 0;
}
.bar-pct { color: var(--text-muted); font-size: 11px; white-space: nowrap; }

</style>
