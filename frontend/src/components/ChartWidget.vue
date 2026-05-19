<template>
  <div class="chart-wrapper">
    <v-chart class="chart" :option="option" autoresize />
  </div>
</template>

<script setup>
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
} from 'echarts/components'
import VChart from 'vue-echarts'

use([CanvasRenderer, BarChart, LineChart, PieChart, GridComponent, TooltipComponent, LegendComponent, TitleComponent])

const props = defineProps({
  option: {
    type: Object,
    required: true,
  },
})
</script>

<style scoped>
.chart-wrapper {
  width: 100%;
  margin-top: 12px;
  border-radius: 8px;
  overflow: hidden;
  background: #1e2535;
}
.chart {
  width: 100%;
  height: 300px;
}
</style>
