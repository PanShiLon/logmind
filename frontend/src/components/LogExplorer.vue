<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  data: { type: Object, default: () => ({ total: 0, entries: [] }) }
})

const emit = defineEmits(['load-more'])

const levelFilter = ref('ALL')
const sourceFilter = ref('ALL')
const expandedIdx = ref(-1)
const searchText = ref('')
const loadingMore = ref(false)

const LEVEL_COLORS = {
  ERROR: '#ef4444',
  WARN: '#f59e0b',
  INFO: '#22c55e',
  DEBUG: '#3b82f6',
  UNKNOWN: '#94a3b8',
}

const allEntries = computed(() => props.data.entries || [])

const sourceList = computed(() => {
  const set = new Set()
  for (const e of allEntries.value) {
    if (e.source) set.add(e.source)
  }
  return Array.from(set).sort()
})

const levelCounts = computed(() => {
  const counts = {}
  for (const e of allEntries.value) {
    counts[e.level] = (counts[e.level] || 0) + 1
  }
  return counts
})

const filteredEntries = computed(() => {
  let list = allEntries.value
  if (levelFilter.value !== 'ALL') {
    list = list.filter(e => e.level === levelFilter.value)
  }
  if (sourceFilter.value !== 'ALL') {
    list = list.filter(e => e.source === sourceFilter.value)
  }
  if (searchText.value.trim()) {
    const q = searchText.value.trim().toLowerCase()
    list = list.filter(e =>
      (e.message || '').toLowerCase().includes(q) ||
      (e.source || '').toLowerCase().includes(q) ||
      (e.timestamp || '').toLowerCase().includes(q)
    )
  }
  return list
})

const isFiltered = computed(() => filteredEntries.value.length !== allEntries.value.length)

const levelBarData = computed(() => {
  const total = allEntries.value.length
  if (!total) return []
  const order = ['ERROR', 'WARN', 'INFO', 'DEBUG', 'UNKNOWN']
  return order
    .filter(lv => levelCounts.value[lv])
    .map(lv => ({
      level: lv,
      count: levelCounts.value[lv],
      pct: ((levelCounts.value[lv] / total) * 100).toFixed(1),
      color: LEVEL_COLORS[lv],
    }))
})

function toggleRow(idx) {
  expandedIdx.value = expandedIdx.value === idx ? -1 : idx
}

function setLevelFilter(lv) {
  levelFilter.value = levelFilter.value === lv ? 'ALL' : lv
  expandedIdx.value = -1
}

function resetFilters() {
  levelFilter.value = 'ALL'
  sourceFilter.value = 'ALL'
  searchText.value = ''
  expandedIdx.value = -1
}

function parseDetail(message) {
  if (!message) return null
  const detail = {}
  // 【请求地址】：xxx
  const reqMatch = message.match(/【请求地址】[：:]\s*(https?:\/\/\S+)/)
  if (reqMatch) detail.url = reqMatch[1]
  // 【请求方式】：xxx
  const methodMatch = message.match(/【请求方式】[：:]\s*(\S+)/)
  if (methodMatch) detail.method = methodMatch[1]
  // 【请求参数】：xxx 或 【请求 Body】：xxx
  const bodyMatch = message.match(/【请求[参数Body body]+】[：:]\s*([\s\S]*?)(?=\n【|$)/)
  if (bodyMatch) detail.reqBody = bodyMatch[1].trim().substring(0, 500)
  // 【异常信息】：xxx 或 【错误信息】：xxx
  const errMatch = message.match(/【[异常错误]信息】[：:]\s*([\s\S]*?)(?=\n【|$)/)
  if (errMatch) detail.error = errMatch[1].trim().substring(0, 800)
  // 【响应结果】：xxx 或 【响应内容】：xxx
  const respMatch = message.match(/【响应[结果内容]+】[：:]\s*([\s\S]*?)(?=\n【|$)/)
  if (respMatch) detail.resp = respMatch[1].trim().substring(0, 500)
  // stackTrace / Exception 提取
  if (!detail.error) {
    const stMatch = message.match(/((?:[a-zA-Z_$][\w.]*(?:Exception|Error|Throwable))[^\n]*(?:\n\s+at [^\n]+)*)/)
    if (stMatch) detail.error = stMatch[1].substring(0, 800)
  }
  // HTTP URL 通用提取
  if (!detail.url) {
    const urlMatch = message.match(/(https?:\/\/\S+)/)
    if (urlMatch) detail.url = urlMatch[1]
  }
  return Object.keys(detail).length > 0 ? detail : null
}

const hasMore = computed(() => props.data.total > allEntries.value.length)
const remainCount = computed(() => props.data.total - allEntries.value.length)

function loadMore() {
  if (loadingMore.value || !hasMore.value) return
  loadingMore.value = true
  emit('load-more', allEntries.value.length)
  setTimeout(() => { loadingMore.value = false }, 10000)
}

function onLoadComplete() {
  loadingMore.value = false
}

defineExpose({ onLoadComplete })

function exportCSV() {
  const rows = [['时间', '级别', '来源', '消息']]
  for (const e of filteredEntries.value) {
    rows.push([e.timestamp || '', e.level, e.source, `"${(e.message || '').replace(/"/g, '""')}"`])
  }
  const bom = '﻿'
  const csv = rows.map(r => r.join(',')).join('\n')
  const blob = new Blob([bom + csv], { type: 'text/csv;charset=utf-8' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `logmind-logs-${new Date().toISOString().slice(0, 10)}.csv`
  a.click()
}
</script>

<template>
  <div class="log-explorer" v-if="allEntries.length">
    <!-- 统计栏 -->
    <div class="le-header">
      <div class="le-summary">
        <span class="le-total">{{ data.total?.toLocaleString() }} 条命中</span>
        <span class="le-took" v-if="data.took_ms">（{{ data.took_ms }}ms）</span>
        <span class="le-filtered" v-if="isFiltered">
          · 过滤后 {{ filteredEntries.length }} 条
        </span>
      </div>
      <div class="le-actions">
        <button v-if="isFiltered" class="le-btn le-btn-reset" @click="resetFilters">✕ 重置</button>
        <button class="le-btn" @click="exportCSV" title="导出 CSV">↓ CSV</button>
      </div>
    </div>

    <!-- 级别分布条 -->
    <div class="le-level-bar" v-if="levelBarData.length > 0">
      <div class="le-bar-title">级别分布 <span class="le-bar-hint">（点击可筛选）</span></div>
      <div class="le-bar-track">
        <div
          v-for="item in levelBarData"
          :key="item.level"
          class="le-bar-segment"
          :style="{ width: item.pct + '%', background: item.color }"
          :title="`${item.level}: ${item.count} 条 (${item.pct}%)`"
          @click="setLevelFilter(item.level)"
        />
      </div>
      <div class="le-bar-legend">
        <span
          v-for="item in levelBarData"
          :key="item.level"
          class="le-legend-item"
          :class="{ active: levelFilter === item.level }"
          @click="setLevelFilter(item.level)"
        >
          <span class="le-legend-dot" :style="{ background: item.color }" />
          {{ item.level }}
          <span class="le-legend-count">{{ item.count }}</span>
          <span class="le-legend-pct">({{ item.pct }}%)</span>
        </span>
      </div>
    </div>

    <!-- 过滤条件栏 -->
    <div class="le-filters">
      <div class="le-filter-group" v-if="sourceList.length > 1">
        <label class="le-filter-label">来源</label>
        <select v-model="sourceFilter" class="le-select">
          <option value="ALL">全部服务</option>
          <option v-for="s in sourceList" :key="s" :value="s">{{ s }}</option>
        </select>
      </div>
      <div class="le-filter-group le-filter-search">
        <input
          v-model="searchText"
          class="le-search"
          placeholder="关键词过滤..."
          spellcheck="false"
        />
      </div>
      <div class="le-filter-result">
        {{ filteredEntries.length }} / {{ allEntries.length }}
      </div>
    </div>

    <!-- 日志列表 -->
    <div class="le-list">
      <div
        v-for="(entry, idx) in filteredEntries"
        :key="idx"
        class="le-row"
        :class="{ expanded: expandedIdx === idx }"
      >
        <div class="le-row-main" @click="toggleRow(idx)">
          <span class="le-expand">{{ expandedIdx === idx ? '▾' : '▸' }}</span>
          <span class="le-ts">{{ entry.timestamp || '--' }}</span>
          <span class="le-level" :style="{ color: LEVEL_COLORS[entry.level] || '#94a3b8' }">
            {{ entry.level }}
          </span>
          <span class="le-source">{{ entry.source }}</span>
          <span class="le-msg">{{ entry.message }}</span>
        </div>
        <div class="le-row-detail" v-if="expandedIdx === idx">
          <table class="le-detail-table">
            <tr>
              <td class="le-dk">timestamp</td>
              <td class="le-dv">{{ entry.timestamp }}</td>
            </tr>
            <tr>
              <td class="le-dk">level</td>
              <td class="le-dv">
                <span class="le-level-badge" :style="{ background: LEVEL_COLORS[entry.level] + '22', color: LEVEL_COLORS[entry.level] }">
                  {{ entry.level }}
                </span>
              </td>
            </tr>
            <tr>
              <td class="le-dk">source</td>
              <td class="le-dv">{{ entry.source }}</td>
            </tr>
            <template v-if="parseDetail(entry.message)">
              <tr v-if="parseDetail(entry.message).url">
                <td class="le-dk">request</td>
                <td class="le-dv">
                  <span class="le-method" v-if="parseDetail(entry.message).method">{{ parseDetail(entry.message).method }}</span>
                  <span class="le-url">{{ parseDetail(entry.message).url }}</span>
                </td>
              </tr>
              <tr v-if="parseDetail(entry.message).reqBody">
                <td class="le-dk">req body</td>
                <td class="le-dv le-code-block">{{ parseDetail(entry.message).reqBody }}</td>
              </tr>
              <tr v-if="parseDetail(entry.message).resp">
                <td class="le-dk">response</td>
                <td class="le-dv le-code-block">{{ parseDetail(entry.message).resp }}</td>
              </tr>
              <tr v-if="parseDetail(entry.message).error">
                <td class="le-dk">exception</td>
                <td class="le-dv le-error-block">{{ parseDetail(entry.message).error }}</td>
              </tr>
            </template>
            <tr>
              <td class="le-dk">message</td>
              <td class="le-dv le-msg-full">{{ entry.message }}</td>
            </tr>
          </table>
        </div>
      </div>

      <!-- 无结果 -->
      <div class="le-empty" v-if="filteredEntries.length === 0">
        无匹配结果
        <button class="le-empty-reset" @click="resetFilters">重置过滤</button>
      </div>

      <!-- 加载更多 -->
      <div class="le-more" v-if="hasMore && filteredEntries.length > 0">
        <button class="le-load-more-btn" @click="loadMore" :disabled="loadingMore">
          <template v-if="loadingMore">
            <span class="le-loading-icon">⟳</span> 加载中...
          </template>
          <template v-else>
            ↓ 加载更多（还有 {{ remainCount.toLocaleString() }} 条）
          </template>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.log-explorer {
  background: var(--bg-log-explorer, #0c0e14);
  border: 1px solid var(--border-log, #1e2535);
  border-radius: 8px;
  overflow: hidden;
  font-family: 'JetBrains Mono', 'Menlo', 'Consolas', monospace;
  font-size: 12px;
  margin: 10px 0;
}

.le-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border-log, #1e2535);
  background: var(--bg-log-header, #111520);
}
.le-summary { display: flex; align-items: center; gap: 6px; }
.le-total { color: #e2e8f0; font-weight: 700; font-size: 13px; }
.le-took { color: #64748b; font-size: 11px; }
.le-filtered { color: #f59e0b; font-size: 11px; }
.le-actions { display: flex; align-items: center; gap: 8px; }
.le-btn {
  background: rgba(59,130,246,.15);
  color: #60a5fa;
  border: 1px solid rgba(59,130,246,.3);
  border-radius: 4px;
  padding: 4px 10px;
  font-size: 11px;
  cursor: pointer;
  font-family: inherit;
  transition: background .2s;
}
.le-btn:hover { background: rgba(59,130,246,.25); }
.le-btn-reset {
  background: rgba(239,68,68,.1);
  color: #f87171;
  border-color: rgba(239,68,68,.3);
}
.le-btn-reset:hover { background: rgba(239,68,68,.2); }

/* level bar */
.le-level-bar {
  padding: 8px 14px;
  border-bottom: 1px solid var(--border-log, #1e2535);
  background: var(--bg-log-header, #111520);
}
.le-bar-title {
  font-size: 11px;
  color: #94a3b8;
  font-weight: 600;
  margin-bottom: 6px;
}
.le-bar-hint {
  font-weight: 400;
  color: #4a5568;
  font-size: 10px;
}
.le-bar-track {
  display: flex;
  height: 6px;
  border-radius: 3px;
  overflow: hidden;
  background: rgba(255,255,255,.04);
  margin-bottom: 6px;
}
.le-bar-segment {
  min-width: 3px;
  cursor: pointer;
  transition: opacity .15s;
}
.le-bar-segment:hover { opacity: 0.75; }
.le-bar-legend {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
}
.le-legend-item {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: #94a3b8;
  cursor: pointer;
  transition: color .15s;
  user-select: none;
}
.le-legend-item:hover { color: #e2e8f0; }
.le-legend-item.active { color: #e2e8f0; font-weight: 700; }
.le-legend-dot {
  width: 8px;
  height: 8px;
  border-radius: 2px;
  flex-shrink: 0;
}
.le-legend-count { font-weight: 600; }
.le-legend-pct { color: #4a5568; font-size: 10px; }

/* filters */
.le-filters {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 14px;
  border-bottom: 1px solid var(--border-log, #1e2535);
  background: var(--bg-log-header, #111520);
  flex-wrap: wrap;
}
.le-filter-group {
  display: flex;
  align-items: center;
  gap: 6px;
}
.le-filter-label {
  color: #64748b;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}
.le-select {
  background: rgba(255,255,255,.06);
  border: 1px solid #2d3748;
  border-radius: 4px;
  color: #e2e8f0;
  padding: 3px 8px;
  font-size: 11px;
  font-family: inherit;
  outline: none;
  cursor: pointer;
  min-width: 80px;
}
.le-select:focus { border-color: #3b82f6; }
.le-filter-search { flex: 1; min-width: 120px; }
.le-search {
  background: rgba(255,255,255,.06);
  border: 1px solid #2d3748;
  border-radius: 4px;
  color: #e2e8f0;
  padding: 4px 10px;
  font-size: 11px;
  font-family: inherit;
  width: 100%;
  outline: none;
  transition: border-color .2s;
}
.le-search:focus { border-color: #3b82f6; }
.le-search::placeholder { color: #4a5568; }
.le-filter-result {
  color: #64748b;
  font-size: 11px;
  margin-left: auto;
  white-space: nowrap;
}

/* list */
.le-list {
  max-height: 400px;
  overflow-y: auto;
}
.le-list::-webkit-scrollbar { width: 6px; }
.le-list::-webkit-scrollbar-track { background: transparent; }
.le-list::-webkit-scrollbar-thumb { background: #2d3748; border-radius: 3px; }

.le-row {
  border-bottom: 1px solid rgba(30,37,53,.6);
  transition: background .15s;
}
.le-row:hover { background: rgba(255,255,255,.03); }
.le-row.expanded { background: rgba(59,130,246,.04); }

.le-row-main {
  display: flex;
  align-items: flex-start;
  padding: 7px 14px;
  cursor: pointer;
  gap: 10px;
  line-height: 1.5;
}
.le-expand { color: #4a5568; width: 12px; flex-shrink: 0; user-select: none; }
.le-ts { color: #64748b; width: 135px; flex-shrink: 0; font-size: 11px; }
.le-level { width: 50px; flex-shrink: 0; font-weight: 700; font-size: 11px; }
.le-source { color: #60a5fa; width: 140px; flex-shrink: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.le-msg { color: #cbd5e1; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* expanded detail */
.le-row-detail {
  padding: 6px 14px 12px 36px;
  animation: slideDown .15s ease;
  background: rgba(59,130,246,.02);
  border-top: 1px solid rgba(59,130,246,.1);
}
@keyframes slideDown { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: translateY(0); } }

.le-detail-table {
  width: 100%;
  border-collapse: collapse;
}
.le-detail-table tr { border-bottom: 1px solid rgba(30,37,53,.4); }
.le-detail-table tr:last-child { border-bottom: none; }
.le-dk {
  color: #60a5fa;
  padding: 6px 16px 6px 0;
  width: 90px;
  vertical-align: top;
  font-weight: 600;
}
.le-dv {
  color: #e2e8f0;
  padding: 6px 0;
  word-break: break-all;
}
.le-msg-full {
  white-space: pre-wrap;
  line-height: 1.7;
  background: rgba(0,0,0,.2);
  padding: 8px 12px;
  border-radius: 4px;
  margin-top: 2px;
  max-height: 200px;
  overflow-y: auto;
}
.le-code-block {
  white-space: pre-wrap;
  line-height: 1.5;
  background: rgba(59,130,246,.05);
  border: 1px solid rgba(59,130,246,.15);
  padding: 6px 10px;
  border-radius: 4px;
  margin-top: 2px;
  max-height: 120px;
  overflow-y: auto;
  font-size: 11px;
  word-break: break-all;
}
.le-error-block {
  white-space: pre-wrap;
  line-height: 1.5;
  background: rgba(239,68,68,.06);
  border: 1px solid rgba(239,68,68,.2);
  padding: 6px 10px;
  border-radius: 4px;
  margin-top: 2px;
  max-height: 150px;
  overflow-y: auto;
  font-size: 11px;
  color: #fca5a5;
  word-break: break-all;
}
.le-method {
  display: inline-block;
  background: rgba(59,130,246,.15);
  color: #60a5fa;
  border-radius: 3px;
  padding: 1px 5px;
  font-size: 10px;
  font-weight: 700;
  margin-right: 6px;
}
.le-url {
  color: #93c5fd;
  word-break: break-all;
}
.le-level-badge {
  padding: 2px 8px;
  border-radius: 4px;
  font-weight: 700;
  font-size: 11px;
}

/* empty */
.le-empty {
  text-align: center;
  padding: 20px;
  color: #4a5568;
  font-size: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}
.le-empty-reset {
  background: none;
  border: 1px solid #2d3748;
  color: #60a5fa;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  cursor: pointer;
  font-family: inherit;
}
.le-empty-reset:hover { border-color: #3b82f6; }

/* load more */
.le-more {
  text-align: center;
  padding: 10px;
}
.le-load-more-btn {
  background: rgba(59,130,246,.1);
  color: #60a5fa;
  border: 1px solid rgba(59,130,246,.3);
  border-radius: 6px;
  padding: 8px 20px;
  font-size: 12px;
  cursor: pointer;
  font-family: inherit;
  transition: background .2s, border-color .2s;
}
.le-load-more-btn:hover:not(:disabled) { background: rgba(59,130,246,.2); border-color: #3b82f6; }
.le-load-more-btn:disabled { opacity: 0.6; cursor: not-allowed; }
.le-loading-icon { display: inline-block; animation: spin 1s linear infinite; }
@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

/* light theme */
[data-theme="light"] .log-explorer {
  --bg-log-explorer: #f8fafc;
  --bg-log-header: #f1f5f9;
  --border-log: #e2e8f0;
}
[data-theme="light"] .le-total { color: #1e293b; }
[data-theme="light"] .le-search { background: #fff; border-color: #cbd5e0; color: #1e293b; }
[data-theme="light"] .le-select { background: #fff; border-color: #cbd5e0; color: #1e293b; }
[data-theme="light"] .le-ts { color: #64748b; }
[data-theme="light"] .le-msg { color: #334155; }
[data-theme="light"] .le-dv { color: #1e293b; }
[data-theme="light"] .le-msg-full { background: rgba(0,0,0,.04); }
[data-theme="light"] .le-row:hover { background: rgba(0,0,0,.02); }
[data-theme="light"] .le-row.expanded { background: rgba(59,130,246,.04); }
[data-theme="light"] .le-row-detail { background: rgba(59,130,246,.02); }
[data-theme="light"] .le-list::-webkit-scrollbar-thumb { background: #cbd5e0; }
[data-theme="light"] .le-filter-result { color: #64748b; }
[data-theme="light"] .le-legend-item { color: #475569; }
[data-theme="light"] .le-legend-item.active { color: #1e293b; }
[data-theme="light"] .le-legend-pct { color: #94a3b8; }
</style>
