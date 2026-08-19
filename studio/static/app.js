const state = { project: null, filter: 'all' }

const statusMeta = {
  pending: ['待确认', 'warning'],
  approved: ['已确认', 'good'],
  changes_requested: ['需调整', 'danger'],
  review: ['待审核', 'warning'],
  missing: ['无视频', ''],
  stale: ['已过期', 'warning'],
  generating: ['生成中', 'warning'],
  failed: ['失败', 'danger'],
}

const $ = (selector, root = document) => root.querySelector(selector)

function mediaUrl(path) {
  if (!path) return ''
  return `/media/${path.split('/').map(encodeURIComponent).join('/')}`
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  })
  let payload = null
  try { payload = await response.json() } catch { payload = null }
  if (!response.ok) throw new Error(payload?.detail || `请求失败：${response.status}`)
  return payload
}

function toast(message, error = false) {
  const node = $('#toast')
  node.textContent = message
  node.className = `toast show${error ? ' error' : ''}`
  window.clearTimeout(toast.timer)
  toast.timer = window.setTimeout(() => { node.className = 'toast' }, 2600)
}

function selectedVersion(segment) {
  const versions = segment.versions || []
  return versions.find((version) => version.id === segment.selected_version_id) || versions[0] || null
}

function badge(status, prefix) {
  const [label, tone] = statusMeta[status] || [status || '未知', '']
  return `<span class="status-badge ${tone}">${prefix}${label}</span>`
}

function filteredSegments() {
  const segments = state.project?.segments || []
  if (state.filter === 'pending') return segments.filter(s => s.image_status !== 'approved' || ['missing', 'review', 'generating'].includes(s.video_status))
  if (state.filter === 'approved') return segments.filter(s => s.image_status === 'approved' && s.video_status === 'approved')
  if (state.filter === 'issues') return segments.filter(s => s.image_status === 'changes_requested' || ['stale', 'failed'].includes(s.video_status))
  return segments
}

function storyboardMedia(segment) {
  if (segment.image_path) {
    return `<img src="${mediaUrl(segment.image_path)}" alt="${segment.id} 分镜图" loading="lazy" />`
  }
  const version = selectedVersion(segment)
  if (version?.video_path) {
    return `<video src="${mediaUrl(version.video_path)}#t=0.2" muted preload="metadata" aria-label="${segment.id} 临时首帧预览"></video>`
  }
  return `<div class="missing-media">尚未导入分镜图<br />接入 Runner 后将在这里显示关键帧</div>`
}

function videoReview(segment) {
  const versions = segment.versions || []
  if (!versions.length) return ''
  const current = selectedVersion(segment)
  const options = versions.map(v => `<option value="${v.id}" ${v.id === current?.id ? 'selected' : ''}>${v.label}</option>`).join('')
  return `
    <div class="video-review">
      <div class="version-row">
        <span class="field-label">视频候选</span>
        <select data-role="version-select">${options}</select>
        <button class="button button-primary" data-action="select-version" ${segment.image_status === 'approved' ? '' : 'disabled'}>采用版本</button>
      </div>
      <video controls preload="metadata" src="${mediaUrl(current.video_path)}"></video>
      ${segment.stale_reason ? `<p class="stale-note">⚠ ${segment.stale_reason}，现有视频仍保留，可重新生成后再选择。</p>` : ''}
      <div class="attach-row">
        <input class="path-input" data-role="attach-path" placeholder="手动附加：outputs/.../clip.mp4" />
        <button class="button button-ghost" data-action="attach-version">附加版本</button>
      </div>
    </div>`
}

function renderCard(segment) {
  const issue = segment.image_status === 'changes_requested' || ['stale', 'failed'].includes(segment.video_status)
  const canGenerate = segment.image_status === 'approved' && segment.video_status !== 'generating'
  return `
    <article class="segment-card ${issue ? 'issue' : ''}" data-segment-id="${segment.id}">
      <div class="card-heading">
        <div class="card-title-wrap">
          <span class="segment-number">${String(segment.order).padStart(2, '0')}</span>
          <h3>${segment.title || segment.id}</h3>
        </div>
        <div class="status-line">
          ${badge(segment.image_status, '图 · ')}
          ${badge(segment.video_status, '片 · ')}
        </div>
      </div>
      <div class="card-body">
        <div class="storyboard-pane">
          ${storyboardMedia(segment)}
          <div class="storyboard-caption">${segment.image_path ? '关键帧' : '从现有视频提取的临时预览'} · ${segment.duration || '?'}s</div>
        </div>
        <div class="prompt-pane">
          <label class="field-label">视频提示词</label>
          <textarea class="prompt-input" data-role="prompt">${segment.prompt || ''}</textarea>
          <textarea class="notes-input" data-role="notes" placeholder="审核备注，例如：手部动作不自然、需要更近景…">${segment.notes || ''}</textarea>
          <div class="prompt-footer">
            <span class="hint">保存提示词后，已采用视频会标记为过期</span>
            <button class="button button-secondary" data-action="save">保存</button>
          </div>
        </div>
      </div>
      <div class="card-actions">
        <button class="button button-primary" data-action="approve-image">确认分镜</button>
        <button class="button button-danger" data-action="flag-image">需要调整</button>
        <button class="button button-secondary" data-action="generate" ${canGenerate ? '' : 'disabled'}>${(segment.versions || []).length ? '重新生成' : '生成视频'}</button>
      </div>
      ${videoReview(segment)}
    </article>`
}

function render() {
  const project = state.project
  if (!project) return
  $('#project-title').textContent = project.title || '导演审核台'
  $('#episode-title').textContent = project.episode?.title || project.title
  $('#episode-subtitle').textContent = project.episode?.description || ''
  const segments = project.segments || []
  $('#stat-total').textContent = segments.length
  $('#stat-images').textContent = segments.filter(s => s.image_status === 'approved').length
  $('#stat-videos').textContent = segments.filter(s => s.video_status === 'approved').length
  $('#stat-issues').textContent = segments.filter(s => s.image_status === 'changes_requested' || ['stale', 'failed'].includes(s.video_status)).length
  $('#runner-state').textContent = project.runner_configured ? 'Runner 已连接' : 'Runner 未配置 · 审核模式'
  $('#runner-state').classList.toggle('online', project.runner_configured)

  if (project.final_video) {
    $('#final-preview').innerHTML = `<div class="preview-label"><span class="preview-dot"></span>当前成片</div><video controls preload="metadata" src="${mediaUrl(project.final_video)}"></video>`
  } else {
    $('#final-preview').innerHTML = '<div class="missing-media">尚无最终成片</div>'
  }

  const visible = filteredSegments()
  $('#toolbar-summary').textContent = `显示 ${visible.length} / ${segments.length} 段`
  $('#segment-grid').innerHTML = visible.length ? visible.map(renderCard).join('') : '<div class="empty-state">这个筛选条件下没有分段</div>'
}

async function loadProject(silent = false) {
  try {
    state.project = await api('/api/project')
    render()
    if (!silent) toast('项目状态已刷新')
  } catch (error) {
    toast(error.message, true)
  }
}

function cardContext(target) {
  const card = target.closest('.segment-card')
  if (!card) return null
  return { card, segmentId: card.dataset.segmentId }
}

async function handleAction(button) {
  const context = cardContext(button)
  if (!context) return
  const { card, segmentId } = context
  const action = button.dataset.action
  button.disabled = true
  try {
    if (action === 'save') {
      await api(`/api/segments/${segmentId}`, { method: 'PATCH', body: JSON.stringify({ prompt: $('[data-role="prompt"]', card).value, notes: $('[data-role="notes"]', card).value }) })
      toast('提示词和备注已保存')
    } else if (action === 'approve-image') {
      await api(`/api/segments/${segmentId}/approve-image`, { method: 'POST' })
      toast('分镜已确认')
    } else if (action === 'flag-image') {
      await api(`/api/segments/${segmentId}/flag-image`, { method: 'POST' })
      toast('已标记为需要调整')
    } else if (action === 'generate') {
      await api(`/api/segments/${segmentId}/generate`, { method: 'POST' })
      toast('生成任务已提交')
    } else if (action === 'select-version') {
      const versionId = $('[data-role="version-select"]', card).value
      await api(`/api/segments/${segmentId}/select-version`, { method: 'POST', body: JSON.stringify({ version_id: versionId }) })
      toast('已采用该视频版本')
    } else if (action === 'attach-version') {
      const input = $('[data-role="attach-path"]', card)
      if (!input.value.trim()) throw new Error('请填写工作区内的视频相对路径')
      await api(`/api/segments/${segmentId}/versions`, { method: 'POST', body: JSON.stringify({ video_path: input.value.trim() }) })
      toast('视频版本已附加')
    }
    await loadProject(true)
  } catch (error) {
    toast(error.message, true)
  } finally {
    button.disabled = false
  }
}

$('#segment-grid').addEventListener('click', event => {
  const button = event.target.closest('button[data-action]')
  if (button) handleAction(button)
})

$('#segment-grid').addEventListener('change', event => {
  if (!event.target.matches('[data-role="version-select"]')) return
  const context = cardContext(event.target)
  const segment = state.project.segments.find(item => item.id === context.segmentId)
  const version = segment.versions.find(item => item.id === event.target.value)
  const video = $('.video-review video', context.card)
  if (video && version) video.src = mediaUrl(version.video_path)
})

$('#filter-tabs').addEventListener('click', event => {
  const tab = event.target.closest('[data-filter]')
  if (!tab) return
  state.filter = tab.dataset.filter
  document.querySelectorAll('.filter-tab').forEach(node => node.classList.toggle('active', node === tab))
  render()
})

$('#refresh-button').addEventListener('click', () => loadProject())

loadProject(true)
window.setInterval(() => {
  if (state.project?.jobs?.some(job => job.status === 'running')) loadProject(true)
}, 4000)
