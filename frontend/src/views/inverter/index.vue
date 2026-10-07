<template>
  <section class="page" data-module="inverter">
    <header class="page-head">
      <div>
        <h2>逆变器监视管理</h2>
        <p class="page-desc">维护逆变器，围绕逆变器编号、品牌型号、额定功率、输入电压范围做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记逆变器</button>
        <button class="btn" type="button" @click="exportRows">导出逆变器监视清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>逆变器编号</span>
        <input v-model="keyword" placeholder="按逆变器编号检索" />
      </label>
      <label class="filter-item">
        <span>运行状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <template v-if="column === '额定功率' && editingId === row.id">
              <input v-model="editingPower" class="power-input" placeholder="请输入额定功率" />
              <button class="link" type="button" @click="savePower(row)">保存</button>
              <button class="link" type="button" @click="cancelEdit">取消</button>
            </template>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <button class="link" type="button" @click="startEdit(row)">修改额定功率</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无逆变器监视数据，可先登记逆变器</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条逆变器监视记录</span>
      <span v-if="noticeMessage" class="notice-text">{{ noticeMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/inverter'
const columns = ["逆变器编号", "品牌型号", "额定功率", "输入电压范围", "所属阵列", "运行温度", "日均发电量", "运行状态"]
const actions = ["降容保护", "高温报警", "安排检修"]
const statuses = ["正常运行", "降容运行", "高温报警", "待检修"]
const stats = [{"label": "在线逆变器", "value": 0}, {"label": "降容台数", "value": 0}, {"label": "报修台数", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const noticeMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')
const editingId = ref<number | null>(null)
const editingPower = ref('')

function currentQuery() {
  const query = new URLSearchParams()
  if (keyword.value.trim()) query.set('keyword', keyword.value.trim())
  if (statusFilter.value) query.set('status', statusFilter.value)
  return query.toString()
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  // 导出与列表走同一套过滤条件，保证导出条数与列表总数一致
  const query = currentQuery()
  window.open(`${ENDPOINT}/export${query ? `?${query}` : ''}`, '_blank')
}

function openCreate() {
  errorMessage.value = '逆变器登记入口尚未接入审批流'
}

function startEdit(row: Row) {
  editingId.value = Number(row.id)
  editingPower.value = String(row['额定功率'] ?? '')
  errorMessage.value = ''
  noticeMessage.value = ''
}

function cancelEdit() {
  editingId.value = null
  editingPower.value = ''
}

async function savePower(row: Row) {
  errorMessage.value = ''
  noticeMessage.value = ''
  const value = editingPower.value.trim()
  if (!value) {
    errorMessage.value = '额定功率不能为空'
    return
  }
  try {
    const response = await request(`${ENDPOINT}/${row.id}`, {
      method: 'PUT',
      body: JSON.stringify({ values: { 额定功率: value } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message || payload.detail || '额定功率保存失败')
    }
    noticeMessage.value = payload.message ?? '额定功率已保存'
    cancelEdit()
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '额定功率保存失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  noticeMessage.value = ''
  let remark = ''
  if (action === '降容保护') {
    const input = window.prompt('请填写降容处置结论（将写入检修计划待办事项）')
    if (input === null) return
    remark = input.trim()
  }
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action }, remark }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message || payload.detail || '逆变器监视动作未生效，请稍后重试')
    }
    noticeMessage.value = payload.message ?? `逆变器已${action}`
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '逆变器监视操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = currentQuery()
  try {
    const response = await request(`${ENDPOINT}${query ? `?${query}` : ''}`)
    if (!response.ok) {
      throw new Error('逆变器列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '逆变器监视列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.power-input {
  width: 110px;
  margin-right: 6px;
}
.notice-text {
  color: #067647;
}
</style>
