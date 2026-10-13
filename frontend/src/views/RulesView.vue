<script setup lang="ts">
/* 规则管理: 巡检/诊断规则 CRUD, 版本化热加载, 平台级 rule:manage 权限控制 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { get, post, put, del, apiError } from '@/api/http'
import { fmtTime } from '@/parser/types'
import { useRbacStore } from '@/stores/rbac'

const rbac = useRbacStore()
const canManage = computed(() => rbac.hasPerm('rule:manage'))
const route = useRoute()
const router = useRouter()

interface RuleRow {
  id: number
  name: string
  description: string
  matchType: 'keyword' | 'regex' | 'threshold' | 'script'
  pattern: string
  threshold: Record<string, any>
  scriptPath: string
  scriptParams: Record<string, any>
  scriptTimeout: number
  severity: 'info' | 'warn' | 'error' | 'critical'
  logType: string
  serverType: string
  enabled: boolean
  priority: number
  version: number
  isBuiltin: boolean
  createdAt: string
}

const MATCH_LABEL: Record<RuleRow['matchType'], string> = {
  keyword: '关键字', regex: '正则', threshold: '阈值', script: '脚本',
}
const MATCH_BADGE: Record<RuleRow['matchType'], string> = {
  keyword: 'o-badge--outline', regex: 'o-badge--primary', threshold: 'o-badge--warning',
  script: 'o-badge--brand',
}
const SEV_LABEL: Record<RuleRow['severity'], string> = { info: '提示', warn: '警告', error: '错误', critical: '严重' }
const SEV_BADGE: Record<RuleRow['severity'], string> = {
  info: 'o-badge--grey', warn: 'o-badge--warning', error: 'o-badge--danger', critical: 'o-badge--danger',
}
const OPS = ['>', '>=', '<', '<=', '==', '!=']

const rules = ref<RuleRow[]>([])
const loading = ref(false)
const loadErr = ref('')
const scriptOptions = ref<{ path: string; doc: string }[]>([])

async function load() {
  loading.value = true
  loadErr.value = ''
  try {
    rules.value = await get<RuleRow[]>('/rules')
  } catch (e) {
    loadErr.value = apiError(e)
  } finally {
    loading.value = false
  }
}
onMounted(() => {
  load()
  if (canManage.value) {
    get<{ path: string; doc: string }[]>('/rules/scripts')
      .then(l => { scriptOptions.value = l })
      .catch(() => { /* 脚本目录为空或不可用时保持空建议 */ })
  }
  applyPrefill()
})

/* ---------- 编辑弹窗 ---------- */
const showEdit = ref(false)
const editingId = ref<number | null>(null)
const saveErr = ref('')
const saving = ref(false)

const emptyForm = () => ({
  name: '',
  description: '',
  match_type: 'keyword' as RuleRow['matchType'],
  pattern: '',
  threshold: { metric: '', op: '>', value: 0 },
  script_path: '',
  script_params: '',
  script_timeout: 5,
  severity: 'warn' as RuleRow['severity'],
  log_type: '',
  server_type: '',
  enabled: true,
  priority: 100,
})
const form = reactive(emptyForm())

function openEdit(row?: RuleRow) {
  saveErr.value = ''
  editingId.value = row?.id ?? null
  Object.assign(form, emptyForm(), row ? {
    name: row.name, description: row.description, match_type: row.matchType,
    pattern: row.pattern, threshold: { ...row.threshold }, severity: row.severity,
    log_type: row.logType, server_type: row.serverType, enabled: row.enabled,
    priority: row.priority,
    script_path: row.scriptPath || '',
    script_params: row.scriptParams && Object.keys(row.scriptParams).length
      ? JSON.stringify(row.scriptParams, null, 2) : '',
    script_timeout: row.scriptTimeout ?? 5,
  } : {})
  showEdit.value = true
}

function pickMatch(t: RuleRow['matchType']) {
  form.match_type = t
}

/* 从「智能巡检规则推荐」接纳跳转而来: 打开新增弹窗并预填推荐内容 */
function applyPrefill() {
  const q = route.query
  if (q.prefill !== '1' || !canManage.value) return
  const severity = String(q.severity ?? 'warn')
  saveErr.value = ''
  editingId.value = null
  Object.assign(form, emptyForm(), {
    name: typeof q.name === 'string' ? q.name : '',
    description: typeof q.description === 'string' ? q.description : '',
    match_type: (q.match_type === 'regex' ? 'regex' : 'keyword') as RuleRow['matchType'],
    pattern: typeof q.pattern === 'string' ? q.pattern : '',
    severity: (['info', 'warn', 'error', 'critical'].includes(severity) ? severity : 'warn') as RuleRow['severity'],
  })
  showEdit.value = true
  router.replace({ path: '/rules' })   // 清除 query, 避免刷新重复弹窗
}

async function save() {
  if (!form.name.trim()) {
    saveErr.value = '请填写规则名称'
    return
  }
  if (form.match_type === 'script') {
    if (!form.script_path.trim()) {
      saveErr.value = '请填写脚本路径'
      return
    }
    if (!form.script_path.trim().endsWith('.py')) {
      saveErr.value = '脚本路径必须以 .py 结尾'
      return
    }
  }
  saveErr.value = ''
  saving.value = true
  try {
    const body: Record<string, any> = {
      name: form.name.trim(), description: form.description, match_type: form.match_type,
      severity: form.severity, log_type: form.log_type, server_type: form.server_type,
      enabled: form.enabled, priority: Number(form.priority) || 1,
    }
    if (form.match_type === 'threshold') {
      body.pattern = ''
      body.threshold = { metric: form.threshold.metric, op: form.threshold.op, value: Number(form.threshold.value) }
    } else if (form.match_type === 'script') {
      body.pattern = ''
      body.threshold = {}
      body.script_path = form.script_path.trim()
      body.script_timeout = Number(form.script_timeout) || 0
      body.script_params = {}
      if (form.script_params.trim()) {
        try {
          const parsed = JSON.parse(form.script_params)
          if (typeof parsed !== 'object' || Array.isArray(parsed) || parsed === null) {
            throw new Error('not object')
          }
          body.script_params = parsed
        } catch {
          saveErr.value = '参数需为合法 JSON 对象，如 {"threshold": 3}'
          return
        }
      }
    } else {
      body.pattern = form.pattern
      body.threshold = {}
    }
    if (editingId.value) await put(`/rules/${editingId.value}`, body)
    else await post('/rules', body)
    showEdit.value = false
    await load()
  } catch (e) {
    saveErr.value = apiError(e)
  } finally {
    saving.value = false
  }
}

async function remove(row: RuleRow) {
  if (!window.confirm(`确认删除规则「${row.name}」？`)) return
  loadErr.value = ''
  try {
    await del(`/rules/${row.id}`)
    await load()
  } catch (e) {
    loadErr.value = apiError(e)
  }
}
</script>

<template>
  <div class="o-operate-bar">
    <div class="o-operate-left">
      <h2>巡检 / 诊断规则</h2>
      <span class="o-mono o-text-3">规则版本化存储，Worker 感知版本变化后热加载，无需重启</span>
    </div>
    <div class="o-operate-right">
      <button v-permission="'rule:manage'" class="o-btn o-btn--primary" @click="openEdit()">＋ 新增规则</button>
    </div>
  </div>

  <div v-if="loadErr" class="o-mono" style="color: var(--danger); margin-bottom: 12px">⚠ {{ loadErr }}</div>

  <div class="o-card">
    <div class="o-table-wrap">
      <table class="o-table">
        <thead>
          <tr>
            <th>名称</th><th>匹配类型</th><th>匹配内容</th><th>级别</th>
            <th>优先级</th><th>版本</th><th>状态</th><th>更新时间</th><th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="!rules.length && !loading">
            <td colspan="9"><div class="o-empty" style="padding: 48px 0">📭 暂无规则</div></td>
          </tr>
          <tr v-for="r in rules" :key="r.id">
            <td>
              <b>{{ r.name }}</b>
              <span v-if="r.isBuiltin" class="o-badge o-badge--brand" style="margin-left: 6px">内置</span>
              <div v-if="r.description" class="o-text-3 desc">{{ r.description }}</div>
            </td>
            <td><span class="o-badge" :class="MATCH_BADGE[r.matchType]">{{ MATCH_LABEL[r.matchType] }}</span></td>
            <td>
              <span v-if="r.matchType === 'keyword' || r.matchType === 'regex'" class="o-mono pattern">{{ r.pattern || '—' }}</span>
              <span v-else-if="r.matchType === 'threshold'" class="o-mono pattern">
                {{ r.threshold?.metric }} {{ r.threshold?.op }} {{ r.threshold?.value }}
              </span>
              <span v-else class="o-mono pattern">{{ r.scriptPath || '—' }}</span>
            </td>
            <td><span class="o-badge" :class="SEV_BADGE[r.severity]">{{ SEV_LABEL[r.severity] }}</span></td>
            <td class="o-mono">{{ r.priority }}</td>
            <td class="o-mono">v{{ r.version }}</td>
            <td>
              <span class="o-badge" :class="r.enabled ? 'o-badge--success' : 'o-badge--grey'">
                {{ r.enabled ? '启用' : '停用' }}
              </span>
            </td>
            <td class="o-mono o-text-3">{{ fmtTime(r.createdAt) }}</td>
            <td class="actions">
              <template v-if="canManage">
                <button class="o-btn o-btn--text o-btn--sm" @click="openEdit(r)">编辑</button>
                <button class="o-btn o-btn--text o-btn--sm danger" :disabled="r.isBuiltin" @click="remove(r)">删除</button>
              </template>
              <span v-else class="o-text-3">—</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>

  <!-- 新增/编辑弹窗 -->
  <div v-if="showEdit" class="o-modal-mask" @click.self="showEdit = false">
    <div class="o-modal">
      <div class="o-modal__title">{{ editingId ? '编辑规则' : '新增规则' }}</div>
      <div class="o-form-item">
        <label class="o-form-item__label required">名称</label>
        <input v-model="form.name" class="o-input" placeholder="规则名称，如：OOM 错误检测" />
      </div>
      <div class="o-form-item">
        <label class="o-form-item__label">描述</label>
        <textarea v-model="form.description" class="o-textarea" rows="2" placeholder="规则用途说明（可选）"></textarea>
      </div>
      <div class="o-form-item">
        <label class="o-form-item__label required">匹配类型</label>
        <div class="match-chips">
          <button
            v-for="(label, key) in MATCH_LABEL"
            :key="key"
            class="match-chip"
            :class="{ active: form.match_type === key }"
            @click="pickMatch(key)"
          >{{ label }}</button>
        </div>
      </div>
      <div v-if="form.match_type === 'keyword' || form.match_type === 'regex'" class="o-form-item">
        <label class="o-form-item__label required">匹配内容</label>
        <input
          v-model="form.pattern" class="o-input mono-input"
          :placeholder="form.match_type === 'regex' ? '正则表达式，如 ERROR|PANIC' : '关键字，如 Out of memory'"
        />
      </div>
      <template v-else-if="form.match_type === 'threshold'">
        <div class="o-form-item">
          <label class="o-form-item__label required">指标名</label>
          <input v-model="form.threshold.metric" class="o-input mono-input" placeholder="如 cpu.usage" />
        </div>
        <div class="o-form-item">
          <label class="o-form-item__label required">比较符</label>
          <select v-model="form.threshold.op" class="o-select" style="width: 120px">
            <option v-for="op in OPS" :key="op" :value="op">{{ op }}</option>
          </select>
        </div>
        <div class="o-form-item">
          <label class="o-form-item__label required">阈值</label>
          <input v-model.number="form.threshold.value" type="number" class="o-input" style="width: 160px" />
        </div>
      </template>
      <template v-else>
        <div class="o-form-item">
          <label class="o-form-item__label required">脚本路径</label>
          <input
            v-model="form.script_path" class="o-input mono-input" list="rule-script-list"
            placeholder="如 oom_burst.py（相对 rules_scripts/ 目录）"
          />
          <datalist id="rule-script-list">
            <option v-for="s in scriptOptions" :key="s.path" :value="s.path">{{ s.doc }}</option>
          </datalist>
        </div>
        <div class="o-form-item">
          <label class="o-form-item__label">脚本参数</label>
          <textarea
            v-model="form.script_params" class="o-textarea mono-input" rows="3"
            placeholder='JSON 对象，如 {"window_seconds": 60, "threshold": 3}（可选）'
          ></textarea>
        </div>
        <div class="o-form-item">
          <label class="o-form-item__label">超时</label>
          <input v-model.number="form.script_timeout" type="number" min="0" class="o-input" style="width: 120px" />
          <span class="o-mono o-text-3" style="align-self: center; margin-left: 8px">秒，0 表示用全局默认</span>
        </div>
        <div class="o-form-item">
          <span class="o-text-3" style="font-size: 12.5px; line-height: 1.7">
            脚本需定义 <code class="o-mono">check(ctx)</code> 入口函数，返回
            <code class="o-mono">{{ '{' }}findings: [...]{{ '}' }}</code>；由 Worker 以独立子进程执行。
          </span>
        </div>
      </template>
      <div class="o-form-item">
        <label class="o-form-item__label">级别</label>
        <select v-model="form.severity" class="o-select" style="width: 140px">
          <option v-for="(label, key) in SEV_LABEL" :key="key" :value="key">{{ label }}</option>
        </select>
      </div>
      <div class="o-form-item">
        <label class="o-form-item__label">优先级</label>
        <input v-model.number="form.priority" type="number" min="1" max="999" class="o-input" style="width: 120px" />
        <span class="o-mono o-text-3" style="align-self: center; margin-left: 8px">数值越小越先匹配</span>
      </div>
      <div class="o-form-item">
        <label class="o-form-item__label">启用</label>
        <label class="switch">
          <input v-model="form.enabled" type="checkbox" />
          <span>{{ form.enabled ? '启用中' : '已停用' }}</span>
        </label>
      </div>
      <div v-if="saveErr" class="o-mono" style="color: var(--danger); font-size: 12.5px">⚠ {{ saveErr }}</div>
      <div class="o-modal__foot">
        <button class="o-btn" @click="showEdit = false">取消</button>
        <button class="o-btn o-btn--primary" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存' }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.desc {
  font-size: 12px;
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.pattern {
  display: inline-block;
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
  font-size: 12px;
}
.actions {
  white-space: nowrap;
  text-align: right;
}
.actions .danger {
  color: var(--danger);
}
.mono-input {
  font-family: var(--mono);
}
.match-chips {
  display: flex;
  gap: 8px;
}
.match-chip {
  border: 1px solid var(--border);
  background: var(--surface);
  border-radius: var(--radius);
  padding: 7px 18px;
  font: inherit;
  font-size: 13.5px;
  cursor: pointer;
  color: var(--text-2);
}
.match-chip:hover {
  border-color: var(--primary);
  color: var(--primary);
}
.match-chip.active {
  border-color: var(--primary);
  background: var(--primary-soft);
  color: var(--primary);
  font-weight: 600;
}
.switch {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 13.5px;
  color: var(--text-2);
  cursor: pointer;
}
</style>
