export const STATUS_LABELS = {
  draft: '草稿',
  idle: '待处理',
  ready: '就绪',
  queued: '排队中',
  running: '生成中',
  synced: '已同步',
  curating: '筛选中',
  succeeded: '已完成',
  failed: '失败'
}

export function getStatusLabel(status) {
  return STATUS_LABELS[status] || status
}
