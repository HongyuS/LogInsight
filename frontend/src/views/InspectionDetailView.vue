<script setup lang="ts">
/* 智能巡检详情: 单个巡检任务的执行结果展示 (健康评分 / 检查项结论 / 摘要 / 规则命中) */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { get, apiError } from '@/api/http'
import { fmtTime } from '@/parser/types'

interface InspectionTask {
  id: string
  type: string
  status: 'pending' | 'running' | 'done' | 'failed' | 'cancelled' | 'interrupted'
  filename: string
  name?: string
  progress: number
  error?: string
  createdAt: string
  finishedAt?: string | null
  logSize: number
  creatorName: string
}

interface InspectionFinding {
  checker: string
  passed: boolean
  severity: string
  message: string
}

interface InspectionReport {
  taskId: string
  healthScore: number | null
  summary: string
  findings: InspectionFinding[]
  content: { ruleHits?: number; metricCount?: number }
  llm: boolean
  createdAt?: string | null
}

const STATUS_BADGE: Record<InspectionTask['status'], { label: string; cls: string }> = {
  pending: { label: '排队中', cls: 'o-badge--grey' },
  running: { label: '巡检中', cls: 'o-badge--warning' },
  done: { label: '已完成', cls: 'o-badge--success' },
  failed: { label: '失败', cls: 'o-badge--danger' },
  cancelled: { label: '已取消', cls: 'o-badge--grey' },
  interrupted: { label: '已中断', cls: 'o-badge--danger' },
}

/* 巡检检查项级别 (error/warn/info) → 徽章样式 */
const SEV_BADGE: Record<string, { label: string; cls: string }> = {
  critical: { label: '致命', cls: 'o-badge--danger' },
  error: { label: '错误', cls: 'o-badge--danger' },
  warn: { label: '告警', cls: 'o-badge--warning' },
  warning: { label: '告警', cls: 'o-badge--warning' },
  info: { label: '信息', cls: 'o-badge--success' },
}

const route = useRoute()
const taskId = computed(() => route.params.taskId as string)

const task = ref<InspectionTask | null>(null)
const report = ref<InspectionReport | null>(null)
const noAccess = ref(false)
const notFound = ref(false)
const loadErr = ref('')
const reportPending = ref(false)
let pollTimer: number | undefined

const running = computed(() => !!task.value && ['pending', 'running'].includes(task.value.status))

async function loadTask() {
  loadErr.value = ''
  try {
    task.value = await get<InspectionTask>(`/tasks/${taskId.value}`)
    noAccess.value = false
    notFound.value = false
  } catch (e: any) {
    if (e?.response?.status === 403) noAccess.value = true
    else if (e?.response?.status === 404) notFound.value = true
    else loadErr.value = apiError(e)
  }
}

async function loadReport() {
  try {
    report.value = await get<InspectionReport>(`/tasks/${taskId.value}/report`)
    reportPending.value = false
  } catch (e: any) {
    report.value = null
    reportPending.value = e?.response?.status === 404
  }
}

/* 排队/巡检中每 2s 轮询; 结束后拉取报告 */
function schedulePoll() {
  stopPoll()
  pollTimer = window.setInterval(async () => {
    await loadTask()
    if (!running.value) {
      stopPoll()
      if (task.value?.status === 'done') await loadReport()
    }
  }, 2000)
}
function stopPoll() {
  if (pollTimer) {
    window.clearInterval(pollTimer)
    pollTimer = undefined
  }
}

const findings = computed(() => report.value?.findings ?? [])
const failedCount = computed(() => findings.value.filter((f) => !f.passed).length)
const ruleHits = computed(() => report.value?.content?.ruleHits ?? 0)
const metricCount = computed(() => report.value?.content?.metricCount ?? 0)
const score = computed(() => report.value?.healthScore ?? null)
const scoreCls = computed(() => {
  const s = score.value
  if (s === null) return ''
  return s >= 90 ? 'ok' : s >= 70 ? 'warn' : 'bad'
})

onMounted(async () => {
  await loadTask()
  if (!task.value) return
  if (running.value) schedulePoll()
  else if (task.value.status === 'done') await loadReport()
})
onBeforeUnmount(stopPoll)
</script>

<template>
  <div v-if="noAccess" class="o-empty o-card">
    <div class="icon">🔒</div>
    <div>无权查看该巡检任务</div>
    <div class="hint">仅任务创建者、平台管理员或所属团队成员可查看</div>
  </div>
  <div v-else-if="notFound" class="o-empty o-card">
    <div class="icon">📭</div>
    <div>任务不存在或已被删除</div>
  </div>
  <div v-else-if="loadErr" class="o-empty o-card">
    <div class="icon">⚠️</div>
    <div>{{ loadErr }}</div>
  </div>
  <template v-else-if="task">
    <!-- 信息横幅 + 结论概览 -->
    <div class="o-banner">
      <div class="banner-left">
        <router-link to="/inspection" class="back-btn">← 返回智能巡检</router-link>
        <h2>
          {{ task.name || task.filename }}
          <span class="o-badge" :class="STATUS_BADGE[task.status].cls">{{ STATUS_BADGE[task.status].label }}</span>
          <span class="o-badge o-badge--outline">智能巡检</span>
        </h2>
        <div class="meta">
          <span class="o-mono o-text-3">{{ task.filename }}（{{ (task.logSize / 1024).toFixed(1) }} KB）</span>
          <span class="o-text-3">{{ task.creatorName }} · {{ fmtTime(task.createdAt) }}</span>
          <span v-if="task.finishedAt" class="o-text-3">完成于 {{ fmtTime(task.finishedAt) }}</span>
        </div>
      </div>
      <div class="o-banner-stats">
        <div class="o-banner-stat"><b :class="scoreCls">{{ score === null ? '—' : score }}</b><span>健康评分</span></div>
        <div class="o-banner-stat"><b>{{ findings.length }}</b><span>检查项</span></div>
        <div class="o-banner-stat"><b style="color: var(--danger)">{{ failedCount }}</b><span>未通过</span></div>
        <div class="o-banner-stat"><b>{{ ruleHits }}</b><span>规则命中</span></div>
        <div class="o-banner-stat"><b>{{ metricCount }}</b><span>采集指标</span></div>
      </div>
    </div>

    <!-- 巡检中 -->
    <div v-if="running" class="o-card" style="margin-bottom: 16px">
      <div class="o-row" style="gap: 10px">
        <span class="spin" />
        <b>巡检{{ task.status === 'pending' ? '排队中' : '进行中' }}… {{ task.progress }}%</b>
        <span class="o-text-3" style="font-size: 13px">巡检完成后本页将自动刷新展示结果详情</span>
      </div>
    </div>
    <div v-else-if="task.status === 'failed'" class="o-badge o-badge--danger" style="margin-bottom: 16px">
      巡检失败：{{ task.error || '未知错误' }}
    </div>
    <div v-else-if="task.status === 'cancelled' || task.status === 'interrupted'"
         class="o-badge o-badge--grey" style="margin-bottom: 16px">
      巡检已{{ task.status === 'cancelled' ? '取消' : '中断' }}，无结果详情
    </div>

    <!-- 巡检摘要 -->
    <div v-if="report" class="o-card" style="margin-bottom: 16px">
      <div class="o-card__title">
        巡检摘要
        <span class="o-mono o-text-3">{{ report.llm ? 'LLM 智能总结' : '规则引擎总结' }}</span>
      </div>
      <div class="summary">{{ report.summary || '（无摘要）' }}</div>
    </div>

    <!-- 检查项结果 -->
    <div class="o-card">
      <div class="o-card__title">
        检查项结果
        <span class="o-mono o-text-3">{{ findings.length }} 项 · {{ failedCount }} 项未通过</span>
      </div>
      <div class="o-table-wrap">
        <table class="o-table">
          <thead>
            <tr><th>检查项</th><th style="width: 110px">结果</th><th style="width: 90px">级别</th><th>说明</th></tr>
          </thead>
          <tbody>
            <tr v-if="!findings.length">
              <td colspan="4">
                <div class="o-empty" style="padding: 40px 0">
                  <div class="icon">📋</div>
                  <div>{{ reportPending || running ? '巡检结果生成中…' : '暂无检查项结果' }}</div>
                </div>
              </td>
            </tr>
            <tr v-for="f in findings" :key="f.checker">
              <td class="o-mono"><b>{{ f.checker }}</b></td>
              <td>
                <span class="o-badge" :class="f.passed ? 'o-badge--success' : 'o-badge--danger'">
                  {{ f.passed ? '通过' : '未通过' }}
                </span>
              </td>
              <td>
                <span class="o-badge" :class="(SEV_BADGE[f.severity] || SEV_BADGE.info).cls">
                  {{ (SEV_BADGE[f.severity] || SEV_BADGE.info).label }}
                </span>
              </td>
              <td>{{ f.message }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </template>
  <div v-else class="o-empty o-card">任务加载中…</div>
</template>

<style scoped>
.banner-left .back-btn {
  display: inline-block;
  font-size: 13px;
  color: var(--primary);
  background: var(--primary-soft);
  border-radius: var(--radius);
  padding: 2px 10px;
  margin-bottom: 8px;
}
.banner-left .back-btn:hover {
  background: var(--primary-tint);
}
.banner-left h2 {
  font-size: 19px;
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: 10px;
}
.banner-left .meta {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 6px;
  font-size: 12.5px;
  flex-wrap: wrap;
}
.o-banner-stat b.ok { color: var(--success, #00b365); }
.o-banner-stat b.warn { color: var(--warning); }
.o-banner-stat b.bad { color: var(--danger); }
.summary {
  font-size: 13.5px;
  line-height: 1.9;
  color: var(--text-2);
  white-space: pre-wrap;
  background: #fbfcfe;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 16px 20px;
}
.spin {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(30, 111, 255, 0.2);
  border-top-color: #1e6fff;
  border-radius: 50%;
  animation: rot 0.8s linear infinite;
  display: inline-block;
  flex: none;
}
@keyframes rot {
  to { transform: rotate(360deg); }
}
</style>