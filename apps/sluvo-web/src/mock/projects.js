const nodeCatalog = {
  script_episode: {
    label: '剧本',
    accent: 'var(--node-script)',
    icon: '剧'
  },
  asset_table: {
    label: '资产',
    accent: 'var(--node-asset)',
    icon: '资'
  },
  storyboard_table: {
    label: '分镜',
    accent: 'var(--node-storyboard)',
    icon: '分'
  },
  prompt_note: {
    label: '提示词',
    accent: 'var(--node-note)',
    icon: '提'
  },
  image_unit: {
    label: '图片',
    accent: 'var(--node-image)',
    icon: '图'
  },
  video_unit: {
    label: '视频',
    accent: 'var(--node-video)',
    icon: '影'
  },
  media_board: {
    label: '媒体板',
    accent: 'var(--node-board)',
    icon: '板'
  }
}

const projectSeeds = [
  {
    id: 'proj-aurora',
    name: '极光巷口',
    genre: '霓虹短剧',
    updatedAt: '2026-04-24 17:40',
    owner: '北岸工作室',
    description: '包含剧本、角色资产、镜头规划和主视觉图生视频链路。',
    stats: {
      nodes: 8,
      outputs: 17
    }
  },
  {
    id: 'proj-echo',
    name: '灯湾回声',
    genre: '奇幻漫画试播',
    updatedAt: '2026-04-24 15:15',
    owner: '蓝框团队',
    description: '用于连载漫画的创作画布，沉淀可复用场景和提示词模块。',
    stats: {
      nodes: 7,
      outputs: 9
    }
  },
  {
    id: 'proj-pulse',
    name: '脉冲跑者',
    genre: '动作宣传片流程',
    updatedAt: '2026-04-23 21:08',
    owner: '动效实验室',
    description: '从资产到分镜再到视频的快速制作看板。',
    stats: {
      nodes: 6,
      outputs: 11
    }
  }
]

function buildNode(id, type, position, title, body, status, extra = {}) {
  const meta = nodeCatalog[type]

  return {
    id,
    type: 'workflowNode',
    position,
    data: {
      nodeType: type,
      title,
      body,
      status,
      icon: meta.icon,
      kindLabel: meta.label,
      accent: meta.accent,
      tags: extra.tags || [],
      metrics: extra.metrics || [],
      portLabels: extra.portLabels || {
        in: '输入',
        out: '输出'
      },
      details: extra.details || {}
    }
  }
}

function buildWorkspace(seed) {
  const isAurora = seed.id === 'proj-aurora'
  const isEcho = seed.id === 'proj-echo'

  const nodes = isAurora
    ? [
        buildNode(
          'episode-1',
          'script_episode',
          { x: 80, y: 110 },
          '第 01 集 / 抵达巷口',
          '12 个节拍，3 次场景切换，主角在雨中完成第一次正面对峙。',
          'ready',
          {
            tags: ['分集', '第二稿'],
            metrics: [
              { label: '场景', value: '3' },
              { label: '镜头', value: '12' }
            ],
            details: {
              source: '从分集草稿导入的剧本文本。',
              references: '用于资产抽取和分镜生成。',
              models: '剧本解析 / 故事规划',
              history: '20 分钟前更新'
            }
          }
        ),
        buildNode(
          'assets-1',
          'asset_table',
          { x: 440, y: 60 },
          '角色 + 场景资产表',
          '双主角、巷口场景、机车道具和雨衣版本。',
          'synced',
          {
            tags: ['资产'],
            metrics: [
              { label: '条目', value: '9' },
              { label: '已绑定', value: '7' }
            ],
            details: {
              source: '项目共享资源。',
              references: '已连接到分镜表和图片生成节点。',
              models: '一致性提示词包',
              history: '12 分钟前同步'
            }
          }
        ),
        buildNode(
          'storyboard-1',
          'storyboard_table',
          { x: 430, y: 320 },
          '分镜表 / 巷口剪辑',
          '包含机位备注、镜头意图、时长和演员节奏的镜头列表。',
          'ready',
          {
            tags: ['镜头'],
            metrics: [
              { label: '行数', value: '12' },
              { label: '锁定', value: '4' }
            ],
            details: {
              source: '由后端分镜数据投影出的镜头行。',
              references: '接收角色、场景和风格引用。',
              models: '分镜抽取',
              history: '镜头顺序已由导演确认'
            }
          }
        ),
        buildNode(
          'note-1',
          'prompt_note',
          { x: 60, y: 410 },
          '提示词组 / 雨夜霓虹',
          '强调反光积水、蓝紫色溢光、真实细雨和浅景深。',
          'draft',
          {
            tags: ['提示词'],
            metrics: [{ label: '片段', value: '4' }],
            details: {
              source: '仅存在于画布中的规划备注。',
              references: '供图片和视频节点复用。',
              models: '无',
              history: '已固定为当前场景氛围'
            }
          }
        ),
        buildNode(
          'image-1',
          'image_unit',
          { x: 830, y: 210 },
          '主视觉关键帧生成',
          '为第 03 镜生成海报级画面，并保持角色与机车连续性。',
          'running',
          {
            tags: ['生成'],
            metrics: [
              { label: '模型', value: 'XL-Image' },
              { label: '队列', value: '01' }
            ],
            details: {
              source: '图片生成单元。',
              references: '接收资产、提示词备注和分镜镜头输入。',
              models: 'XL-Image / 风格预设 A',
              history: '当前任务 2 分钟前开始'
            }
          }
        ),
        buildNode(
          'video-1',
          'video_unit',
          { x: 1200, y: 220 },
          '第 03 镜动态生成',
          '将主视觉关键帧转成 5 秒推镜，保留雨丝和车流光感。',
          'idle',
          {
            tags: ['动态'],
            metrics: [
              { label: '时长', value: '5 秒' },
              { label: '帧率', value: '24' }
            ],
            details: {
              source: '视频生成单元。',
              references: '使用图片节点输出作为首帧。',
              models: 'VideoFlow 1.3',
              history: '已准备运行'
            }
          }
        ),
        buildNode(
          'board-1',
          'media_board',
          { x: 1210, y: 470 },
          '审片板 / 输出精选',
          '收集已确认的静帧、动态结果和对比版本，用于导出。',
          'curating',
          {
            tags: ['审片'],
            metrics: [
              { label: '通过', value: '5' },
              { label: '版本', value: '17' }
            ],
            details: {
              source: '媒体输出的画布投影。',
              references: '保存最终选择和导出短名单。',
              models: '无',
              history: '已有 2 个版本标记为终修'
            }
          }
        )
      ]
    : [
        buildNode(
          'episode-2',
          'script_episode',
          { x: 100, y: 150 },
          isEcho ? '试播集 / 抵达灯湾' : '宣传片 / 脉冲启动',
          isEcho
            ? '开篇章节，包含海湾传说揭示和角色登场。'
            : '短动作预告，包含屋顶追逐和品牌揭示。',
          'ready',
          {
            tags: ['分集'],
            metrics: [
              { label: '场景', value: isEcho ? '4' : '2' },
              { label: '镜头', value: isEcho ? '10' : '8' }
            ],
            details: {
              source: '分集源文本。',
              references: '已连接到下游规划节点。',
              models: '故事规划',
              history: '今天更新'
            }
          }
        ),
        buildNode(
          'assets-2',
          'asset_table',
          { x: 450, y: 90 },
          isEcho ? '角色 + 港湾资产' : '主角装备资产',
          isEcho
            ? '守灯人、码头市集、神龛道具和雾气色彩参考。'
            : '主角跑者、城市天际线、跑鞋和能量轨迹道具。',
          'synced',
          {
            tags: ['资产'],
            metrics: [{ label: '条目', value: isEcho ? '11' : '6' }],
            details: {
              source: '共享资源清单。',
              references: '用于分镜和图片生成。',
              models: '一致性提示词包',
              history: '已与项目同步'
            }
          }
        ),
        buildNode(
          'storyboard-2',
          'storyboard_table',
          { x: 450, y: 330 },
          isEcho ? '分镜 / 港湾开场' : '分镜 / 屋顶奔跑',
          isEcho
            ? '以雾气为先的构图、揭示节奏和灯笼倒影。'
            : '高能剪辑，由远景推进到近景，节奏适合广告投放。',
          'ready',
          {
            tags: ['镜头'],
            metrics: [{ label: '行数', value: isEcho ? '10' : '8' }],
            details: {
              source: '分镜镜头表。',
              references: '已绑定资产和生成单元。',
              models: '分镜抽取',
              history: '已准备进入图片生成'
            }
          }
        ),
        buildNode(
          'note-2',
          'prompt_note',
          { x: 80, y: 430 },
          isEcho ? '氛围 / 咸湿海雾' : '动态 / 速度爆发',
          isEcho
            ? '冷月光、琥珀灯笼光、水彩边缘和安静的仪式感。'
            : '强透视、电光点缀、干净广告质感和金属冲刺轨迹。',
          'draft',
          {
            tags: ['提示词'],
            metrics: [{ label: '片段', value: '3' }],
            details: {
              source: '画布内备注。',
              references: '供下游节点共享的提示词胶囊。',
              models: '无',
              history: '本地工作备注'
            }
          }
        ),
        buildNode(
          'image-2',
          'image_unit',
          { x: 840, y: 210 },
          isEcho ? '试播镜头生成' : '宣传主视觉帧',
          isEcho
            ? '生成带雾层和灯笼识别度的电影感开场静帧。'
            : '生成发布主视觉，并在多个版本中锁定跑者身份。',
          isEcho ? 'queued' : 'ready',
          {
            tags: ['生成'],
            metrics: [{ label: '模型', value: 'XL-Image' }],
            details: {
              source: '图片生成单元。',
              references: '接收提示词、镜头和资产引用。',
              models: 'XL-Image',
              history: isEcho ? '正在等待一个上游任务' : '已准备运行'
            }
          }
        ),
        buildNode(
          'board-2',
          'media_board',
          { x: 1180, y: 250 },
          isEcho ? '精选 / 第一章' : '客户看板 / 宣传精选',
          isEcho
            ? '汇总守灯人特写、港湾全景和章节封面候选。'
            : '跟踪静帧和短切片，供相关方审阅。',
          'curating',
          {
            tags: ['审片'],
            metrics: [{ label: '通过', value: isEcho ? '3' : '4' }],
            details: {
              source: '媒体输出审阅板。',
              references: '最终审阅和导出界面。',
              models: '无',
              history: '正在筛选版本'
            }
          }
        )
      ]

  const edges = isAurora
    ? [
        {
          id: 'e-episode-assets',
          source: 'episode-1',
          target: 'assets-1',
          type: 'smoothstep',
          label: '包含',
          markerEnd: 'arrowclosed'
        },
        {
          id: 'e-episode-storyboard',
          source: 'episode-1',
          target: 'storyboard-1',
          type: 'smoothstep',
          label: '包含',
          markerEnd: 'arrowclosed'
        },
        {
          id: 'e-assets-storyboard',
          source: 'assets-1',
          target: 'storyboard-1',
          type: 'smoothstep',
          label: '身份',
          markerEnd: 'arrowclosed'
        },
        {
          id: 'e-note-image',
          source: 'note-1',
          target: 'image-1',
          type: 'smoothstep',
          label: '风格',
          markerEnd: 'arrowclosed'
        },
        {
          id: 'e-storyboard-image',
          source: 'storyboard-1',
          target: 'image-1',
          type: 'smoothstep',
          label: '生成',
          markerEnd: 'arrowclosed'
        },
        {
          id: 'e-assets-image',
          source: 'assets-1',
          target: 'image-1',
          type: 'smoothstep',
          label: '引用',
          markerEnd: 'arrowclosed'
        },
        {
          id: 'e-image-video',
          source: 'image-1',
          target: 'video-1',
          type: 'smoothstep',
          label: '首帧',
          markerEnd: 'arrowclosed'
        },
        {
          id: 'e-video-board',
          source: 'video-1',
          target: 'board-1',
          type: 'smoothstep',
          label: '生成',
          markerEnd: 'arrowclosed'
        }
      ]
    : [
        {
          id: 'e2-episode-assets',
          source: 'episode-2',
          target: 'assets-2',
          type: 'smoothstep',
          label: '包含',
          markerEnd: 'arrowclosed'
        },
        {
          id: 'e2-episode-storyboard',
          source: 'episode-2',
          target: 'storyboard-2',
          type: 'smoothstep',
          label: '包含',
          markerEnd: 'arrowclosed'
        },
        {
          id: 'e2-assets-image',
          source: 'assets-2',
          target: 'image-2',
          type: 'smoothstep',
          label: '引用',
          markerEnd: 'arrowclosed'
        },
        {
          id: 'e2-storyboard-image',
          source: 'storyboard-2',
          target: 'image-2',
          type: 'smoothstep',
          label: '生成',
          markerEnd: 'arrowclosed'
        },
        {
          id: 'e2-note-image',
          source: 'note-2',
          target: 'image-2',
          type: 'smoothstep',
          label: '风格',
          markerEnd: 'arrowclosed'
        },
        {
          id: 'e2-image-board',
          source: 'image-2',
          target: 'board-2',
          type: 'smoothstep',
          label: '生成',
          markerEnd: 'arrowclosed'
        }
      ]

  return {
    project: seed,
    canvas: {
      viewport: isAurora ? { x: 0, y: 0, zoom: 0.87 } : { x: 0, y: 0, zoom: 0.92 },
      nodes,
      edges
    }
  }
}

const workspaces = projectSeeds.reduce((acc, seed) => {
  acc[seed.id] = buildWorkspace(seed)
  return acc
}, {})

export const availableNodeTemplates = [
  {
    type: 'script_episode',
    title: '剧本 / 分集',
    description: '故事节拍、对白文本和抽取入口。'
  },
  {
    type: 'asset_table',
    title: '资产表',
    description: '角色、场景和道具清单，保留连续性备注。'
  },
  {
    type: 'storyboard_table',
    title: '分镜表',
    description: '镜头行、机位备注，以及图片和视频生成入口。'
  },
  {
    type: 'prompt_note',
    title: '提示词笔记',
    description: '可复用风格片段、评论和规划备注。'
  },
  {
    type: 'image_unit',
    title: '图片生成节点',
    description: '结合提示词、资产和镜头引用生成静帧。'
  },
  {
    type: 'video_unit',
    title: '视频生成节点',
    description: '将静帧和镜头上下文转成动态输出。'
  },
  {
    type: 'media_board',
    title: '媒体结果看板',
    description: '收集输出，进行审阅、对比和导出。'
  }
]

export function createProjectSummaryList() {
  return projectSeeds.map((project) => ({ ...project }))
}

export function getMockWorkspaceByProjectId(projectId) {
  const workspace = workspaces[projectId] || workspaces['proj-aurora']
  return structuredClone(workspace)
}

export function getNodeTemplate(type) {
  return nodeCatalog[type]
}
