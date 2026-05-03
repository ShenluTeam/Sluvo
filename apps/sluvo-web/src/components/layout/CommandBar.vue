<template>
  <header class="libtv-topbar" @click.stop @pointerdown.stop @dblclick.stop.prevent>
    <div class="libtv-topbar__left">
      <button class="libtv-brand-button" type="button" aria-label="返回主页" @click="$emit('go-home')">
        <span class="libtv-logo-mark" />
        <strong class="libtv-logo-text">Sluvo</strong>
      </button>
      <span class="libtv-divider" />
      <input
        v-if="editingTitle"
        ref="titleInput"
        v-model="draftTitle"
        class="libtv-project-title-input"
        aria-label="项目名称"
        @blur="commitTitle"
        @keydown.enter.stop.prevent="commitTitle"
        @keydown.esc.stop.prevent="cancelTitleEdit"
      />
      <button
        v-else
        class="libtv-project-title"
        type="button"
        aria-label="双击重命名"
        @click.stop
        @pointerdown.stop
        @dblclick.stop.prevent="startTitleEdit"
      >
        {{ title }}
      </button>
    </div>

    <div class="libtv-topbar__right">
      <button class="top-pill top-pill--skills" type="button">Sluvo Skills</button>
      <span class="top-save-status" :class="`is-${saveStatus}`">{{ saveStatusLabel }}</span>
      <button class="top-icon-button" type="button" aria-label="保存" @click="$emit('save')">
        <Save :size="20" />
      </button>
      <button class="top-icon-button" type="button" aria-label="分享">
        <Share2 :size="20" />
      </button>
      <button class="top-icon-button top-icon-button--notice" type="button" aria-label="通知">
        <Bell :size="20" />
      </button>
      <button class="top-pill top-pill--cyan" type="button">
        <Store :size="20" />
        会员超市
      </button>
      <button class="top-pill top-pill--member" type="button">
        <span class="top-pill__sale">限时 39 折</span>
        <Gem :size="19" />
        会员特惠
        <Star :size="15" />
        {{ pointsLabel }}
      </button>

      <div class="top-account" @click.stop>
        <button class="top-avatar" type="button" :aria-label="`账户：${displayName}`" @click="toggleAccountPanel">
          {{ userInitial }}
        </button>

        <section v-if="accountPanelVisible" class="top-account-panel">
          <div class="top-account-card">
            <span class="top-account-avatar">{{ userInitial }}</span>
            <div class="top-account-identity">
              <strong>{{ displayName }}</strong>
              <span>
                UUID
                <button type="button" title="复制 UUID" @click="copyUserId">
                  <Copy :size="13" />
                </button>
                <i />
                Access key
                <ChevronRight :size="14" />
              </span>
            </div>
          </div>

          <div class="top-member-card">
            <div>
              <strong>{{ membershipLabel }}</strong>
              <span>活跃权益 · {{ benefitLabel }}</span>
            </div>
            <button type="button">开通会员</button>
          </div>

          <div class="top-quota-card">
            <button type="button">
              <span>灵感值余额 {{ pointsLabel }} 点</span>
              <ChevronRight :size="14" />
            </button>
            <small>永久 {{ permanentPointsLabel }} 点 | 临时 {{ temporaryPointsLabel }} 点</small>
            <button class="top-quota-card__action" type="button">充值</button>
          </div>

          <div class="top-quota-card">
            <span>存储空间</span>
            <strong>{{ storageLabel }}</strong>
            <button class="top-quota-card__action" type="button">管理资产</button>
          </div>

          <nav class="top-account-menu">
            <button type="button"><UserPlus :size="20" />创建团队</button>
            <button type="button"><CreditCard :size="20" />订阅与开发票</button>
            <button type="button"><Sun :size="20" />模式切换 <span><Moon :size="15" /></span></button>
            <button type="button"><Settings :size="20" />AI 水印设置</button>
            <button type="button" @click="logout"><LogOut :size="20" />退出登录</button>
          </nav>
        </section>
      </div>
    </div>
  </header>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import {
  Bell,
  ChevronRight,
  Copy,
  CreditCard,
  Gem,
  LogOut,
  Moon,
  Save,
  Settings,
  Share2,
  Store,
  Star,
  Sun,
  UserPlus,
} from 'lucide-vue-next'
import { fetchCurrentUser, fetchUserDashboard } from '../../api/authApi'

const props = defineProps({
  title: {
    type: String,
    default: '未命名'
  },
  saveStatus: {
    type: String,
    default: 'idle'
  }
})

const emit = defineEmits(['go-home', 'update:title', 'logout', 'save'])
const editingTitle = ref(false)
const draftTitle = ref(props.title)
const titleInput = ref(null)
const accountPanelVisible = ref(false)
const account = reactive({
  name: '',
  email: '',
  userId: '',
  points: 0,
  permanentPoints: 0,
  temporaryPoints: 0,
  storageUsedGb: 0,
  storageTotalGb: 0,
  membership: '',
  benefitText: ''
})

const displayName = computed(() => account.name || account.email || buildFallbackName())
const userInitial = computed(() => displayName.value.trim().slice(0, 1).toUpperCase() || 'S')
const pointsLabel = computed(() => String(account.points ?? 0))
const permanentPointsLabel = computed(() => String(account.permanentPoints ?? 0))
const temporaryPointsLabel = computed(() => String(account.temporaryPoints ?? 0))
const membershipLabel = computed(() => account.membership || '未开通会员')
const benefitLabel = computed(() => account.benefitText || (account.membership ? '会员权益生效中' : '暂无会员权益'))
const storageLabel = computed(() => `${formatGb(account.storageUsedGb)} /${formatGb(account.storageTotalGb)}`)
const saveStatusLabel = computed(() => {
  const labels = {
    idle: '已同步',
    dirty: '待保存',
    saving: '保存中',
    saved: '已保存',
    conflict: '有冲突',
    error: '保存失败',
    loading: '加载中'
  }
  return labels[props.saveStatus] || labels.idle
})

watch(
  () => props.title,
  (nextTitle) => {
    if (!editingTitle.value) draftTitle.value = nextTitle
  }
)

onMounted(() => {
  readLocalAccount()
  refreshRemoteAccount()
  document.addEventListener('pointerdown', handleDocumentPointerDown, true)
  window.addEventListener('click', closeAccountPanel)
  window.addEventListener('storage', handleStorage)
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', handleDocumentPointerDown, true)
  window.removeEventListener('click', closeAccountPanel)
  window.removeEventListener('storage', handleStorage)
})

function startTitleEdit() {
  draftTitle.value = props.title
  editingTitle.value = true
  nextTick(() => {
    titleInput.value?.focus?.()
    titleInput.value?.select?.()
  })
}

function commitTitle() {
  if (!editingTitle.value) return
  const nextTitle = draftTitle.value.trim() || '未命名'
  editingTitle.value = false
  emit('update:title', nextTitle)
  if (nextTitle !== props.title) {
    nextTick(() => emit('save'))
  }
}

function cancelTitleEdit() {
  draftTitle.value = props.title
  editingTitle.value = false
}

function handleDocumentPointerDown(event) {
  if (!editingTitle.value) return
  const target = event.target instanceof Node ? event.target : null
  if (target && titleInput.value?.contains?.(target)) return
  commitTitle()
}

function toggleAccountPanel() {
  accountPanelVisible.value = !accountPanelVisible.value
}

function closeAccountPanel() {
  accountPanelVisible.value = false
}

function handleStorage(event) {
  if (['shenlu_token', 'shenlu_nickname', 'shenlu_email'].includes(event.key)) {
    readLocalAccount()
    refreshRemoteAccount()
  }
}

function readLocalAccount() {
  account.name = localStorage.getItem('shenlu_nickname') || ''
  account.email = localStorage.getItem('shenlu_email') || ''
}

async function refreshRemoteAccount() {
  if (!localStorage.getItem('shenlu_token')) return
  try {
    const [user, dashboard] = await Promise.allSettled([fetchCurrentUser(), fetchUserDashboard()])
    if (user.status === 'fulfilled') mergeUserPayload(user.value)
    if (dashboard.status === 'fulfilled') mergeDashboardPayload(dashboard.value)
  } catch {
    // Local token remains the source of truth for whether the user is logged in.
  }
}

function mergeUserPayload(payload) {
  const user = payload?.user || payload?.data || payload || {}
  account.name = user.nickname || user.name || user.username || user.wechat_name || user.display_name || account.name
  account.email = user.email || account.email
  account.userId = user.uuid || user.user_id || user.id || account.userId
  mergePointFields(user)
  mergeStoragePayload(user.storage)
  account.membership = normalizeMembershipLabel(user.membership_name || user.membership || user.vip_name) || account.membership
  account.benefitText = normalizeBenefitLabel(user.membership || user.benefits || user.benefit_text) || account.benefitText
}

function mergeDashboardPayload(payload) {
  const data = payload?.dashboard || payload?.data || payload || {}
  mergePointFields(data.points_summary || data.pointsSummary || data)
  mergeStoragePayload(data.storage || data.storage_summary || data.storageSummary || data)
  account.membership =
    normalizeMembershipLabel(data.membership_name || data.membership || data.standalone_membership || data.team_membership) ||
    account.membership
  account.benefitText = normalizeBenefitLabel(data.membership || data.benefits || data.benefit_text) || account.benefitText
}

function mergePointFields(source) {
  account.points = pickNumber(source, ['total_points', 'totalPoints', 'points', 'point_balance', 'balance', 'credits'], account.points)
  account.permanentPoints = pickNumber(source, ['permanent_points', 'permanentPoints', 'general_points', 'generalPoints'], account.permanentPoints)
  account.temporaryPoints = pickNumber(source, ['temporary_points', 'temporaryPoints', 'libtv_points', 'libtvPoints'], account.temporaryPoints)

  const total = Number(account.points)
  const permanent = Number(account.permanentPoints)
  const temporary = Number(account.temporaryPoints)
  if ((!Number.isFinite(total) || total === 0) && (permanent || temporary)) {
    account.points = permanent + temporary
  }
}

function mergeStoragePayload(storage) {
  if (!storage || typeof storage !== 'object') return
  const usedBytes = pickNumber(storage, ['used_bytes', 'usedBytes'], null)
  const reservedBytes = pickNumber(storage, ['reserved_bytes', 'reservedBytes'], 0)
  const quotaBytes = pickNumber(storage, ['quota_bytes', 'quotaBytes', 'quota_bytes_snapshot', 'quotaBytesSnapshot'], null)
  account.storageUsedGb = pickNumber(storage, ['storage_used_gb', 'storageUsedGb', 'used_gb', 'usedGb'], account.storageUsedGb)
  account.storageTotalGb = pickNumber(storage, ['storage_total_gb', 'storageTotalGb', 'quota_gb', 'quotaGb'], account.storageTotalGb)
  if (usedBytes !== null) account.storageUsedGb = bytesToGb(usedBytes + reservedBytes)
  if (quotaBytes !== null) account.storageTotalGb = bytesToGb(quotaBytes)
}

function normalizeMembershipLabel(value) {
  const normalized = normalizeMaybeJson(value)
  if (!normalized) return ''
  if (typeof normalized === 'string') return normalized.trim()
  if (typeof normalized !== 'object') return ''

  const direct = normalized.plan_name || normalized.membership_name || normalized.vip_name || normalized.name || normalized.title
  if (typeof direct === 'string' && direct.trim()) return direct.trim()

  const memberships = [normalized.team_membership, normalized.standalone_membership].filter(Boolean)
  const paid = memberships.find((item) => item?.plan_name && item.plan_name !== '免费版')
  const fallback = paid || memberships.find((item) => item?.plan_name)
  return typeof fallback?.plan_name === 'string' ? fallback.plan_name.trim() : ''
}

function normalizeBenefitLabel(value) {
  const normalized = normalizeMaybeJson(value)
  if (!normalized) return ''
  if (typeof normalized === 'string') return normalized.trim()
  if (typeof normalized !== 'object') return ''

  const direct = normalized.benefit_text || normalized.benefitText || normalized.description || normalized.desc
  if (typeof direct === 'string' && direct.trim()) return direct.trim()

  const memberships = [normalized.team_membership, normalized.standalone_membership].filter(Boolean)
  if (memberships.some((item) => item?.effective_priority || item?.effective)) return '会员权益生效中'
  return ''
}

function normalizeMaybeJson(value) {
  if (!value) return null
  if (typeof value !== 'string') return value
  const trimmed = value.trim()
  if (!trimmed.startsWith('{') && !trimmed.startsWith('[')) return trimmed
  try {
    return JSON.parse(trimmed)
  } catch {
    return ''
  }
}

function pickNumber(source, keys, fallback) {
  for (const key of keys) {
    const value = Number(source?.[key])
    if (Number.isFinite(value)) return value
  }
  return fallback
}

function bytesToGb(value) {
  const bytes = Number(value)
  if (!Number.isFinite(bytes) || bytes <= 0) return 0
  return bytes / (1024 * 1024 * 1024)
}

function formatGb(value) {
  const gb = Number(value)
  if (!Number.isFinite(gb) || gb <= 0) return '0G'
  if (gb >= 10 || Number.isInteger(gb)) return `${Math.round(gb)}G`
  return `${gb.toFixed(1).replace(/\.0$/, '')}G`
}

function buildFallbackName() {
  const id = account.userId || localStorage.getItem('shenlu_token') || 'Sluvo'
  return `微信用户${String(id).slice(-6)}`
}

function copyUserId() {
  const value = account.userId || localStorage.getItem('shenlu_token') || ''
  if (value) navigator.clipboard?.writeText(value)
}

function logout() {
  accountPanelVisible.value = false
  localStorage.removeItem('shenlu_token')
  localStorage.removeItem('shenlu_nickname')
  emit('logout')
}
</script>
