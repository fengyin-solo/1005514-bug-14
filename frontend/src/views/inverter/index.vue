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
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <section v-if="editing" class="edit-panel">
      <header class="edit-head">
        <h3>逆变器详情：{{ editing['逆变器编号'] }}</h3>
        <span class="edit-status">运行状态：{{ editing['运行状态'] }}</span>
      </header>
      <form class="filter-bar" @submit.prevent="saveEdit">
        <label v-for="field in editableFields" :key="field" class="filter-item">
          <span>{{ field }}</span>
          <input v-model="editForm[field]" />
        </label>
        <button class="btn primary" type="submit">保存修改</button>
        <button class="btn ghost" type="button" @click="closeEdit">取消</button>
      </form>
    </section>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="openEdit(row)">编辑</button>
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
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
const actions = ["降容保护", "升级高温报警", "安排检修"]
const editableFields = ["逆变器编号", "品牌型号", "额定功率", "输入电压范围", "所属阵列", "运行温度", "日均发电量"]
const statuses = ["正常运行", "降容运行", "高温报警", "待检修"]
const stats = [{"label": "在线逆变器", "value": 0}, {"label": "降容台数", "value": 0}, {"label": "报修台数", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const noticeMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const editing = ref<Row | null>(null)
const editForm = ref<Record<string, string>>({})

function readMessage(payload: unknown, fallback: string): string {
  if (payload && typeof payload === 'object') {
    const body = payload as Record<string, unknown>
    if (typeof body.message === 'string' && body.message) return body.message
    if (typeof body.detail === 'string' && body.detail) return body.detail
  }
  return fallback
}

function buildQuery(): string {
  const params = new URLSearchParams()
  const keyword = (filters.value['逆变器编号'] ?? '').trim()
  if (keyword) params.set('keyword', keyword)
  return params.toString()
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  const query = buildQuery()
  window.open(query ? `${ENDPOINT}/export?${query}` : `${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '逆变器登记入口尚未接入审批流'
}

async function openEdit(row: Row) {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    const payload: unknown = await response.json().catch(() => null)
    if (!response.ok) {
      throw new Error(readMessage(payload, '逆变器详情读取失败'))
    }
    const detail = payload as Row
    editing.value = detail
    editForm.value = Object.fromEntries(
      editableFields.map((field) => [field, String(detail[field] ?? '')]),
    )
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '逆变器详情读取失败'
  }
}

function closeEdit() {
  editing.value = null
  editForm.value = {}
}

async function saveEdit() {
  if (!editing.value) return
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${editing.value.id}`, {
      method: 'PUT',
      body: JSON.stringify({ values: editForm.value }),
    })
    const payload: unknown = await response.json().catch(() => null)
    if (!response.ok || !(payload as { ok?: boolean } | null)?.ok) {
      throw new Error(readMessage(payload, '逆变器资料保存失败，请稍后重试'))
    }
    noticeMessage.value = readMessage(payload, '逆变器资料已保存')
    closeEdit()
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '逆变器资料保存失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload: unknown = await response.json().catch(() => null)
    if (!response.ok || !(payload as { ok?: boolean } | null)?.ok) {
      throw new Error(readMessage(payload, '逆变器监视动作未生效，请稍后重试'))
    }
    noticeMessage.value = readMessage(payload, '逆变器监视动作已生效')
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '逆变器监视操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = buildQuery()
  try {
    const response = await request(query ? `${ENDPOINT}?${query}` : ENDPOINT)
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
