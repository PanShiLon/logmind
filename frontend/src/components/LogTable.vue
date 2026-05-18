<script setup>
defineProps({
  entries: { type: Array, default: () => [] }
})

const LEVEL_TAG = {
  ERROR: 'danger',
  WARN: 'warning',
  INFO: 'success',
  DEBUG: 'info',
  UNKNOWN: 'info',
}
</script>

<template>
  <div class="log-table-wrap">
    <el-table :data="entries" size="small" :max-height="280" stripe>
      <el-table-column label="时间" prop="timestamp" width="160" />
      <el-table-column label="级别" width="80">
        <template #default="{ row }">
          <el-tag :type="LEVEL_TAG[row.level] || 'info'" size="small">{{ row.level }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="来源" prop="source" width="120" />
      <el-table-column label="消息" prop="message" show-overflow-tooltip />
    </el-table>
  </div>
</template>

<style scoped>
.log-table-wrap {
  border-radius: 6px;
  overflow: hidden;
}
:deep(.el-table) {
  background: #0f1117;
  color: #94a3b8;
  font-size: 12px;
  font-family: 'JetBrains Mono', monospace;
}
:deep(.el-table tr) { background: #0f1117; }
:deep(.el-table--striped .el-table__body tr.el-table__row--striped td) {
  background: #161b27;
}
:deep(.el-table th.el-table__cell) {
  background: #161b27;
  color: #64748b;
  border-color: #1e2535;
}
:deep(.el-table td.el-table__cell) { border-color: #1e2535; }
</style>
