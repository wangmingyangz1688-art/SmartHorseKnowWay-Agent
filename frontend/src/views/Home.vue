<template>
  <div class="home-page">
    <!-- ===== 顶部 Hero ===== -->
    <section class="hero">
      <!-- 2026-06-04: 将记忆身份挪到首页右上角，做成本地生活账号入口 -->
      <div class="hero-account">
        <span class="memory-icon">🧠</span>
        <span class="account-label">记忆身份</span>
        <input
          v-model="memoryUserId"
          class="memory-user-input"
          type="text"
          maxlength="32"
          placeholder="demo_user"
          @blur="persistMemoryUser"
        />
      </div>
      <div class="hero-content">
        <div class="hero-pill">本地生活 Agent · 附近快排</div>
        <h1 class="hero-title">
          今天怎么安排？
        </h1>
        <p class="hero-subtitle">
          像点外卖一样，把玩乐、吃饭、预约和分享一次搞定
        </p>
      </div>
    </section>

    <!-- ===== 主表单区域 ===== -->
    <section class="form-section">
      <div class="form-card">
        <!-- 2026-06-04: 首页主卡片改成本地生活下单式入口，弱化工具表单感 -->
        <div class="order-card-head">
          <div>
            <span class="order-badge">今日推荐</span>
            <h2>输入一句话，马上生成可执行路线</h2>
          </div>
          <span class="order-city-hint">{{ orderLocationHint }}</span>
        </div>

        <div class="mode-switch" role="tablist" aria-label="规划模式">
          <button
            class="mode-option"
            :class="{ active: planningMode === 'nearby_quick' }"
            type="button"
            role="tab"
            :aria-selected="planningMode === 'nearby_quick'"
            @click="switchPlanningMode('nearby_quick')"
          >
            <span class="mode-icon">📍</span>
            <span>
              <strong>附近快排</strong>
              <small>一句话 + 当前位置</small>
            </span>
          </button>
          <button
            class="mode-option"
            :class="{ active: planningMode === 'detailed' }"
            type="button"
            role="tab"
            :aria-selected="planningMode === 'detailed'"
            @click="switchPlanningMode('detailed')"
          >
            <span class="mode-icon">🧭</span>
            <span>
              <strong>精细规划</strong>
              <small>手动填写条件</small>
            </span>
          </button>
        </div>

        <!-- 2026-06-04: 新增执行模式开关，保留深度多智能体，同时提供比赛 Demo 更稳的极速生成 -->
        <div class="execution-switch" aria-label="执行模式">
          <button
            class="execution-option"
            :class="{ active: executionMode === 'fast' }"
            type="button"
            @click="executionMode = 'fast'"
          >
            <span class="execution-icon">⚡</span>
            <span>
              <strong>极速生成</strong>
              <small>真实 POI 候选池，地图更准</small>
            </span>
          </button>
          <button
            class="execution-option"
            :class="{ active: executionMode === 'agent' }"
            type="button"
            @click="executionMode = 'agent'"
          >
            <span class="execution-icon">🧠</span>
            <span>
              <strong>深度思考</strong>
              <small>保留多智能体搜索链路</small>
            </span>
          </button>
        </div>

        <!-- 1. 自然语言输入 -->
        <div class="input-group main-input">
          <label class="input-label">💬 {{ messageInputLabel }}</label>
          <textarea
            v-model="form.message"
            class="message-input"
            :placeholder="currentPlaceholder"
            rows="3"
            maxlength="500"
            @focus="isInputFocused = true"
            @blur="isInputFocused = false"
            @keydown.tab.prevent="fillCurrentPlaceholder"
          ></textarea>
          <div class="input-helper-row">
            <span class="tab-hint">按 Tab 填入推荐句</span>
            <span class="char-count">{{ form.message.length }}/500</span>
          </div>
        </div>

        <div class="quick-panel" v-if="planningMode === 'nearby_quick'">
          <div class="quick-panel-copy">
            <strong>一句话说清楚你想做什么</strong>
            <span>AI 会自动识别同行人、时间、饮食限制和活动偏好，优先安排附近 3-5 公里内的方案。</span>
          </div>
          <div class="input-row quick-location-row">
            <div class="input-group flex-1">
              <label class="input-label">📍 所在城市 <span class="optional">(定位后可自动识别)</span></label>
              <input
                v-model="form.city"
                type="text"
                class="text-input"
                placeholder="定位后自动填，也可手动输入"
              />
            </div>
            <div class="input-group flex-1">
              <label class="input-label">🏘️ 附近区域 <span class="optional">(选填)</span></label>
              <input
                v-model="form.district"
                type="text"
                class="text-input"
                placeholder="如：朝阳区 / 三里屯"
              />
            </div>
            <div class="input-group locate-group">
              <label class="input-label">当前位置 <span class="optional">(选填)</span></label>
              <button
                class="locate-btn"
                type="button"
                :disabled="isLocating"
                @click="useCurrentLocation"
              >
                <span v-if="isLocating" class="mini-spinner"></span>
                <span v-else>⌖</span>
                {{ isLocating ? '定位中' : quickLocation ? '已定位' : '使用定位' }}
              </button>
            </div>
          </div>
          <p class="location-status" :class="{ success: !!quickLocation }">
            {{ locationStatus }}
          </p>
        </div>

        <!-- 2. 快速场景按钮 -->
        <div class="input-group" v-if="planningMode === 'detailed'">
          <label class="input-label">⚡ 快速选择场景</label>
          <div class="scenario-buttons">
            <button
              v-for="scenario in scenarios"
              :key="scenario.id"
              class="scenario-btn"
              :class="{ active: selectedScenario === scenario.id }"
              @click="selectScenario(scenario)"
            >
              <span class="scenario-emoji">{{ scenario.emoji }}</span>
              <span class="scenario-text">{{ scenario.label }}</span>
            </button>
          </div>
        </div>

        <template v-if="planningMode === 'detailed'">
          <!-- 3. 基本信息行 -->
          <div class="input-row">
            <div class="input-group flex-1">
              <label class="input-label">📍 城市</label>
              <input
                v-model="form.city"
                type="text"
                class="text-input"
                placeholder="如：北京"
              />
            </div>
            <div class="input-group flex-1">
              <label class="input-label">🏘️ 区域 <span class="optional">(选填)</span></label>
              <input
                v-model="form.district"
                type="text"
                class="text-input"
                placeholder="如：朝阳区"
              />
            </div>
            <div class="input-group flex-1">
              <label class="input-label">📅 日期</label>
              <input
                v-model="form.date"
                type="date"
                class="text-input"
              />
            </div>
          </div>

          <div class="input-row">
            <div class="input-group flex-1">
              <label class="input-label">⏰ 开始时间</label>
              <select v-model="form.start_time" class="text-input">
                <option v-for="t in timeOptions" :key="t" :value="t">{{ t }}</option>
              </select>
            </div>
            <div class="input-group flex-1">
              <label class="input-label">⏳ 可用时长</label>
              <select v-model="form.duration_hours" class="text-input">
                <option :value="2">2 小时</option>
                <option :value="3">3 小时</option>
                <option :value="4">4 小时</option>
                <option :value="5">5 小时</option>
                <option :value="6">6 小时</option>
                <option :value="8">8 小时</option>
              </select>
            </div>
            <div class="input-group flex-1">
              <label class="input-label">💰 预算上限 <span class="optional">(选填)</span></label>
              <input
                v-model.number="form.budget_limit"
                type="number"
                class="text-input"
                placeholder="如：500"
                min="0"
                step="100"
              />
            </div>
          </div>
        </template>

        <!-- 4. 群体信息（可折叠） -->
        <div class="collapsible-section" v-if="planningMode === 'detailed'">
          <button class="collapse-toggle" @click="showGroupInfo = !showGroupInfo">
            <span>👥 群体详细信息</span>
            <span class="optional-tag">选填，也可在上面的描述中说明</span>
            <span class="arrow" :class="{ expanded: showGroupInfo }">▾</span>
          </button>

          <transition name="slide">
            <div v-if="showGroupInfo" class="collapse-content">
              <div class="input-row">
                <div class="input-group flex-1">
                  <label class="input-label">群体类型</label>
                  <div class="radio-group">
                    <label class="radio-item" :class="{ active: form.group_type === 'family' }">
                      <input type="radio" v-model="form.group_type" value="family" />
                      <span>👨‍👩‍👧 家庭</span>
                    </label>
                    <label class="radio-item" :class="{ active: form.group_type === 'friends' }">
                      <input type="radio" v-model="form.group_type" value="friends" />
                      <span>👫 朋友</span>
                    </label>
                  </div>
                </div>
              </div>

              <!-- 家庭场景 -->
              <template v-if="form.group_type === 'family'">
                <div class="input-row">
                  <div class="input-group flex-1">
                    <label class="input-label">有小孩吗？</label>
                    <div class="radio-group">
                      <label class="radio-item small" :class="{ active: form.group_info.has_children }">
                        <input type="radio" :value="true" v-model="form.group_info.has_children" />
                        <span>有</span>
                      </label>
                      <label class="radio-item small" :class="{ active: !form.group_info.has_children }">
                        <input type="radio" :value="false" v-model="form.group_info.has_children" />
                        <span>没有</span>
                      </label>
                    </div>
                  </div>
                  <div class="input-group flex-1" v-if="form.group_info.has_children">
                    <label class="input-label">孩子年龄</label>
                    <input
                      v-model="childrenAgesText"
                      type="text"
                      class="text-input"
                      placeholder="如：5 或 3,7（多个用逗号分隔）"
                    />
                  </div>
                  <div class="input-group flex-1">
                    <label class="input-label">有老人吗？</label>
                    <div class="radio-group">
                      <label class="radio-item small" :class="{ active: form.group_info.has_elderly }">
                        <input type="radio" :value="true" v-model="form.group_info.has_elderly" />
                        <span>有</span>
                      </label>
                      <label class="radio-item small" :class="{ active: !form.group_info.has_elderly }">
                        <input type="radio" :value="false" v-model="form.group_info.has_elderly" />
                        <span>没有</span>
                      </label>
                    </div>
                  </div>
                </div>
              </template>

              <!-- 朋友场景 -->
              <template v-if="form.group_type === 'friends'">
                <div class="input-row">
                  <div class="input-group flex-1">
                    <label class="input-label">总人数</label>
                    <input
                      v-model.number="friendsCount"
                      type="number"
                      class="text-input"
                      placeholder="如：4"
                      min="2"
                      max="20"
                    />
                  </div>
                  <div class="input-group flex-1">
                    <label class="input-label">性别比例 <span class="optional">(选填)</span></label>
                    <input
                      v-model="form.group_info.gender_split"
                      type="text"
                      class="text-input"
                      placeholder="如：2男2女"
                    />
                  </div>
                </div>
              </template>

              <!-- 通用：饮食限制 -->
              <div class="input-group">
                <label class="input-label">🥗 饮食限制 <span class="optional">(选填，可多选)</span></label>
                <div class="tag-selector">
                  <button
                    v-for="tag in dietaryTags"
                    :key="tag"
                    class="tag-btn"
                    :class="{ active: form.group_info.dietary_restrictions.includes(tag) }"
                    @click="toggleDietaryTag(tag)"
                  >
                    {{ tag }}
                  </button>
                </div>
              </div>
            </div>
          </transition>
        </div>

        <!-- 5. 提交按钮 -->
        <div class="submit-section">
          <button
            class="submit-btn"
            :class="{ loading: isSubmitting }"
            :disabled="!canSubmit || isSubmitting"
            @click="handleSubmit"
          >
            <template v-if="isSubmitting">
              <span class="spinner"></span>
              <span>{{ progressMessage || '正在规划中...' }}</span>
            </template>
            <template v-else>
              <span>🚀 帮我安排！</span>
            </template>
          </button>
          <p class="submit-hint" v-if="!canSubmit">
            {{ submitHint }}
          </p>
        </div>

      </div>
    </section>

    <!-- ===== 功能亮点 ===== -->
    <section class="features-section">
      <h2 class="section-title">✨ 我能做什么</h2>
      <div class="features-grid">
        <div class="feature-card" v-for="f in features" :key="f.title">
          <span class="feature-emoji">{{ f.emoji }}</span>
          <h3>{{ f.title }}</h3>
          <p>{{ f.desc }}</p>
        </div>
      </div>
    </section>

    <!-- ===== 示例场景 ===== -->
    <section class="examples-section">
      <h2 class="section-title">💡 不知道怎么说？试试这些</h2>
      <div class="examples-grid">
        <button
          v-for="example in examples"
          :key="example.text"
          class="example-card"
          @click="useExample(example)"
        >
          <span class="example-emoji">{{ example.emoji }}</span>
          <p class="example-text">{{ example.text }}</p>
          <span class="example-tag">{{ example.tag }}</span>
        </button>
      </div>
    </section>

    <!-- ===== 进度浮层（流式模式时） ===== -->
    <transition name="fade">
      <div class="progress-overlay" v-if="isSubmitting">
        <div class="progress-card">
          <h3>🤖 AI 正在为你规划...</h3>
          <div class="progress-bar-container">
            <div class="progress-bar" :style="{ width: progressPercent + '%' }"></div>
          </div>
          <p class="progress-step">{{ progressMessage }}</p>
          <div class="progress-steps-list">
            <div
              v-for="step in progressSteps"
              :key="step.step"
              class="progress-step-item"
              :class="{ done: step.done, active: step.active }"
            >
              <span class="step-icon">{{ step.done ? '✅' : step.active ? '⏳' : '⬜' }}</span>
              <span>{{ step.label }}</span>
            </div>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()

// ============================================================================
// 表单数据
// ============================================================================

const form = reactive({
  message: '',
  city: '',
  district: '',
  date: '',
  start_time: '14:00',
  duration_hours: 4,
  group_type: '',
  budget_limit: null as number | null,
  group_info: {
    has_children: false,
    children_ages: [] as number[],
    has_elderly: false,
    dietary_restrictions: [] as string[],
    gender_split: '',
  },
})

// ============================================================================
// UI 状态
// ============================================================================

const isInputFocused = ref(false)
const showGroupInfo = ref(false)
const selectedScenario = ref('')
const isSubmitting = ref(false)
const progressMessage = ref('')
const progressPercent = ref(0)
const childrenAgesText = ref('')
const friendsCount = ref(4)
const planningMode = ref<'nearby_quick' | 'detailed'>('nearby_quick')
// 2026-06-04: 执行模式独立于规划入口；附近快排默认极速，精细规划可切深度思考
const executionMode = ref<'fast' | 'agent'>('fast')
const isLocating = ref(false)
const quickLocation = ref<{ longitude: number; latitude: number } | null>(null)
const locationStatus = ref('可以授权浏览器定位；定位成功后城市会自动识别，识别失败也能按坐标规划。')
// 2026-06-04: 轻量记忆身份，先用本地存储替代完整登录系统
const memoryUserId = ref('demo_user')

// 2026-06-04: 后端新增并行上下文获取和规则质检后，前端进度同步升级为 7 步
const progressSteps = ref([
  { step: 1, label: '理解需求与场景', done: false, active: false },
  { step: 2, label: '并行搜索附近场所', done: false, active: false },
  { step: 3, label: '汇总天气和可用性', done: false, active: false },
  { step: 4, label: '生成活动方案', done: false, active: false },
  { step: 5, label: '规则质检', done: false, active: false },
  { step: 6, label: '语义质检预留', done: false, active: false },
  { step: 7, label: '整理可执行方案', done: false, active: false },
])

// ============================================================================
// 常量数据
// ============================================================================

const scenarios = [
  { id: 'family_child', emoji: '👨‍👩‍👧', label: '带娃出游', groupType: 'family', message: '想带老婆孩子出去玩几个小时，' },
  { id: 'family_couple', emoji: '💑', label: '二人约会', groupType: 'family', message: '想和老婆/老公出去约会，' },
  { id: 'friends_hangout', emoji: '👫', label: '朋友聚会', groupType: 'friends', message: '想和几个朋友出去玩，' },
  { id: 'friends_party', emoji: '🎉', label: '生日派对', groupType: 'friends', message: '朋友过生日，想安排一下，' },
  { id: 'solo', emoji: '🧘', label: '一个人逛', groupType: 'friends', message: '今天想自己出去走走，' },
  { id: 'family_elderly', emoji: '👴', label: '带父母', groupType: 'family', message: '想带爸妈出去逛逛，别太累，' },
]

const dietaryTags = [
  '减肥', '素食', '清真', '海鲜过敏', '花生过敏',
  '乳糖不耐', '无辣', '低糖', '儿童餐', '老人软食',
]

const timeOptions = [
  '09:00', '09:30', '10:00', '10:30', '11:00', '11:30',
  '12:00', '12:30', '13:00', '13:30', '14:00', '14:30',
  '15:00', '15:30', '16:00', '16:30', '17:00', '17:30',
  '18:00',
]

const features = [
  { emoji: '🧠', title: '一句话理解需求', desc: '自然语言输入，AI 自动识别群体类型、偏好和约束' },
  { emoji: '📍', title: '真实场所推荐', desc: '基于高德地图搜索附近真实的公园、展览、餐厅' },
  { emoji: '📋', title: '完整时间轴', desc: '生成 4~6 小时的精确时间轴，包含交通和费用' },
  { emoji: '📞', title: '一键预约下单', desc: '确认方案后直接预约餐厅、买门票、送蛋糕鲜花' },
  { emoji: '💬', title: '分享给同伴', desc: '自动生成口语化的分享文案，复制发给老婆/朋友' },
  { emoji: '🌤️', title: '天气感知', desc: '自动查询当日天气，下雨天推荐室内活动' },
]

const examples = [
  {
    emoji: '👨‍👩‍👧',
    text: '今天下午想带老婆孩子出去玩几个小时，孩子5岁，老婆最近在减肥，别离家太远',
    tag: '家庭·亲子',
    city: '北京', district: '朝阳区', group_type: 'family',
  },
  {
    emoji: '👫',
    text: '周六下午4个朋友聚会，2男2女，想吃火锅然后找个地方玩',
    tag: '朋友·聚会',
    city: '上海', district: '静安区', group_type: 'friends',
  },
  {
    emoji: '🎂',
    text: '女朋友下周过生日，想安排一个惊喜下午，吃个好点的餐厅，能不能送个蛋糕到餐厅',
    tag: '约会·生日',
    city: '深圳', district: '南山区', group_type: 'family',
  },
  {
    emoji: '👴',
    text: '带爸妈出去走走，别太累，找个安静的公园逛逛然后吃顿饭',
    tag: '家庭·长辈',
    city: '杭州', district: '西湖区', group_type: 'family',
  },
  {
    emoji: '🧘',
    text: '一个人想去看展览，然后找个安静的咖啡馆坐坐',
    tag: '独处·文艺',
    city: '成都', district: '锦江区', group_type: 'friends',
  },
  {
    emoji: '🎉',
    text: '6个人想找个地方玩剧本杀或密室逃脱，然后吃烧烤',
    tag: '朋友·娱乐',
    city: '广州', district: '天河区', group_type: 'friends',
  },
]

// Placeholder 轮播
const placeholders = [
  '今天下午想带老婆孩子出去玩几个小时，别离家太远...',
  '周末和朋友聚聚，先吃饭再找个地方玩...',
  '女朋友生日，想安排个惊喜下午...',
  '带爸妈出去走走，找个安静舒服的地方...',
  '一个人想去看展，然后找个咖啡馆坐坐...',
]
const placeholderIndex = ref(0)
const currentPlaceholder = computed(() => placeholders[placeholderIndex.value])

function fillCurrentPlaceholder() {
  // 2026-06-05: 输入框支持 Tab 一键填入当前推荐句，方便快速试用比赛 Demo。
  const suggestion = currentPlaceholder.value || ''
  if (!suggestion) return
  const current = form.message.trim()
  if (!current || placeholders.includes(current)) {
    form.message = suggestion
  }
}
const orderLocationHint = computed(() => {
  // 2026-06-04: 附近快排已定位但城市未反查出来时，顶部显示“已定位”而不是继续催填城市。
  if (form.city.trim()) return form.district ? `${form.city} · ${form.district}` : form.city
  if (quickLocation.value) return '已定位'
  return '选择城市'
})
const messageInputLabel = computed(() => (
  planningMode.value === 'nearby_quick' ? '一句话说出你的安排目标' : '告诉我你的想法'
))
const submitHint = computed(() => (
  planningMode.value === 'nearby_quick'
    ? '请至少输入一句需求；可填写城市或使用定位'
    : '请至少输入你的想法和城市'
))

// ============================================================================
// 计算属性
// ============================================================================

const canSubmit = computed(() => {
  // 2026-06-04: 附近快排支持“只输入一句话 + 浏览器定位”，不再强制城市必填。
  if (planningMode.value === 'nearby_quick') {
    return form.message.trim().length > 0 && (form.city.trim().length > 0 || !!quickLocation.value)
  }
  return form.message.trim().length > 0 && form.city.trim().length > 0
})

// ============================================================================
// 方法
// ============================================================================

function selectScenario(scenario: typeof scenarios[0]) {
  if (selectedScenario.value === scenario.id) {
    // 取消选择
    selectedScenario.value = ''
    return
  }

  selectedScenario.value = scenario.id
  form.group_type = scenario.groupType

  // 在已有文字后追加场景前缀（如果输入框为空）
  if (!form.message.trim()) {
    form.message = scenario.message
  }

  // 自动展开群体信息
  if (scenario.groupType === 'family') {
    form.group_info.has_children = scenario.id === 'family_child'
    form.group_info.has_elderly = scenario.id === 'family_elderly'
  }
}

function switchPlanningMode(mode: 'nearby_quick' | 'detailed') {
  planningMode.value = mode
  if (mode === 'nearby_quick') {
    executionMode.value = 'fast'
    showGroupInfo.value = false
    selectedScenario.value = ''
    // 2026-06-05: 附近快排默认回到下午档，避免从精细规划切回后沿用 09:00 这类旧表单时间。
    form.start_time = '14:00'
    if (!form.duration_hours || form.duration_hours < 4) {
      form.duration_hours = 5
    }
  } else {
    executionMode.value = 'agent'
  }
}

async function reverseGeocodeLocation(location: { longitude: number; latitude: number }) {
  // 2026-06-04: 定位后反查城市/区域，让“已定位”真正成为附近快排的位置来源。
  try {
    const query = new URLSearchParams({
      longitude: String(location.longitude),
      latitude: String(location.latitude),
    })
    const res = await fetch(`/api/map/reverse-geocode?${query.toString()}`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const payload = await res.json()
    const data = payload?.data || {}
    if (data.city && !form.city.trim()) {
      form.city = String(data.city).replace(/市$/, '')
    }
    if (data.district && !form.district.trim()) {
      form.district = String(data.district)
    }
    if (data.city || data.district) {
      locationStatus.value = `已定位到 ${data.city || ''}${data.district ? ' · ' + data.district : ''}，会优先按当前位置附近规划。`
      return
    }
    locationStatus.value = `已获取坐标：${location.longitude}, ${location.latitude}；城市未识别，仍会按坐标附近规划。`
  } catch {
    locationStatus.value = `已获取坐标：${location.longitude}, ${location.latitude}；城市反查失败，仍会按坐标附近规划。`
  }
}

function useCurrentLocation() {
  if (!navigator.geolocation) {
    locationStatus.value = '当前浏览器不支持定位，请手动填写城市和区域。'
    return
  }

  isLocating.value = true
  locationStatus.value = '正在获取当前位置...'

  navigator.geolocation.getCurrentPosition(
    async (position) => {
      quickLocation.value = {
        longitude: Number(position.coords.longitude.toFixed(6)),
        latitude: Number(position.coords.latitude.toFixed(6)),
      }
      locationStatus.value = `已获取当前位置：${quickLocation.value.longitude}, ${quickLocation.value.latitude}，正在识别城市...`
      await reverseGeocodeLocation(quickLocation.value)
      isLocating.value = false
    },
    (error) => {
      const messageMap: Record<number, string> = {
        1: '定位权限被拒绝，可以继续手动填写城市和区域。',
        2: '暂时无法获取位置，可以继续手动填写城市和区域。',
        3: '定位超时，可以继续手动填写城市和区域。',
      }
      locationStatus.value = messageMap[error.code] || '定位失败，可以继续手动填写城市和区域。'
      isLocating.value = false
    },
    {
      enableHighAccuracy: true,
      timeout: 8000,
      maximumAge: 300000,
    }
  )
}

function toggleDietaryTag(tag: string) {
  const idx = form.group_info.dietary_restrictions.indexOf(tag)
  if (idx === -1) {
    form.group_info.dietary_restrictions.push(tag)
  } else {
    form.group_info.dietary_restrictions.splice(idx, 1)
  }
}

function useExample(example: typeof examples[0]) {
  // 2026-06-04: 示例只作为一句话模板，不再强行写入演示城市，避免误导为系统默认城市。
  form.message = example.text
  if (planningMode.value === 'detailed') {
    form.city = example.city
    form.district = example.district
  }
  form.group_type = example.group_type
  selectedScenario.value = ''

  // 滚动到顶部
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

// 解析 childrenAgesText → form.group_info.children_ages
function parseChildrenAges() {
  if (!childrenAgesText.value.trim()) {
    form.group_info.children_ages = []
    return
  }
  form.group_info.children_ages = childrenAgesText.value
    .split(/[,，、\s]+/)
    .map((s) => parseInt(s.trim()))
    .filter((n) => !isNaN(n) && n >= 0 && n <= 18)
}

// ============================================================================
// 提交
// ============================================================================

async function handleSubmit() {
  if (!canSubmit.value || isSubmitting.value) return

  parseChildrenAges()

  isSubmitting.value = true
  progressMessage.value = '🚀 正在启动 AI 规划...'
  progressPercent.value = 0

  // 重置进度步骤
  progressSteps.value.forEach((s) => {
    s.done = false
    s.active = false
  })

  try {
    const requestBody = buildRequestBody()
    console.log('📤 发送请求:', requestBody)

    // 使用 SSE 流式请求
    const response = await fetch('/api/activity/plan/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(requestBody),
    })

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`)
    }

    const reader = response.body?.getReader()
    const decoder = new TextDecoder()

    if (!reader) {
      throw new Error('无法读取响应流')
    }

    let resultPlan: any = null

    while (true) {
      const { value, done } = await reader.read()
      if (done) break

      const text = decoder.decode(value, { stream: true })
      const lines = text.split('\n')

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue

        try {
          const event = JSON.parse(line.slice(6))
          handleSSEEvent(event)

          if (event.type === 'complete' && event.success) {
            resultPlan = event.data
          } else if (event.type === 'error') {
            throw new Error(event.message || '规划失败')
          }
        } catch (parseErr) {
          // 忽略不完整的 JSON 行
          if ((parseErr as Error).message?.includes('规划失败')) {
            throw parseErr
          }
        }
      }
    }

    if (resultPlan) {
      // 存储方案到 sessionStorage，跳转到结果页
      sessionStorage.setItem('activityPlan', JSON.stringify(resultPlan))
      sessionStorage.setItem('activityRequest', JSON.stringify(requestBody))
      router.push({ name: 'Result' })
    } else {
      // 降级：非流式请求
      await handleNonStreamSubmit(requestBody)
    }
  } catch (error: any) {
    console.error('❌ 规划失败:', error)
    alert(`规划失败: ${error.message || '未知错误'}\n\n请检查后端服务是否正常运行。`)
  } finally {
    isSubmitting.value = false
    progressPercent.value = 0
    progressMessage.value = ''
  }
}

async function handleNonStreamSubmit(requestBody: any) {
  progressMessage.value = '⏳ 正在生成方案（非流式模式）...'
  progressPercent.value = 50

  const res = await fetch('/api/activity/plan', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(requestBody),
  })

  if (!res.ok) {
    const errText = await res.text()
    throw new Error(`HTTP ${res.status}: ${errText}`)
  }

  const data = await res.json()

  if (data.success && data.data) {
    sessionStorage.setItem('activityPlan', JSON.stringify(data.data))
    sessionStorage.setItem('activityRequest', JSON.stringify(requestBody))
    router.push({ name: 'Result' })
  } else {
    throw new Error(data.message || '方案生成失败')
  }
}

function handleSSEEvent(event: any) {
  if (event.type === 'progress') {
    progressPercent.value = event.percent || 0
    progressMessage.value = event.message || ''

    const step = event.step
    if (step) {
      progressSteps.value.forEach((s) => {
        if (s.step < step) {
          s.done = true
          s.active = false
        } else if (s.step === step) {
          s.done = false
          s.active = true
        } else {
          s.done = false
          s.active = false
        }
      })

      // 2026-06-04: 进度从 5 步升级为 7 步，完成阈值根据后端 total 动态计算
      const total = event.total || progressSteps.value.length
      const stepThreshold = Math.round((step / total) * 100)
      if (event.percent && event.percent >= stepThreshold) {
        const current = progressSteps.value.find((s) => s.step === step)
        if (current) current.done = true
      }
    }
  }
}

function buildRequestBody() {
  const body: any = {
    user_id: memoryUserId.value.trim() || 'demo_user',
    planning_mode: planningMode.value,
    execution_mode: executionMode.value,
    message: form.message.trim(),
    city: form.city.trim(),
    district: form.district.trim(),
    date: form.date || new Date().toISOString().slice(0, 10),
    start_time: form.start_time,
    duration_hours: form.duration_hours,
    group_type: form.group_type,
  }

  if (form.budget_limit && form.budget_limit > 0) {
    body.budget_limit = form.budget_limit
  }

  if (planningMode.value === 'nearby_quick' && quickLocation.value) {
    body.home_location = quickLocation.value
  }

  // 只在用户填写了群体信息时才传
  if (planningMode.value === 'detailed' && form.group_type) {
    body.group_info = {
      has_children: form.group_info.has_children,
      children_ages: form.group_info.children_ages,
      has_elderly: form.group_info.has_elderly,
      dietary_restrictions: form.group_info.dietary_restrictions,
      gender_split: form.group_info.gender_split,
    }
  }

  return body
}

function persistMemoryUser() {
  const normalized = memoryUserId.value.trim() || 'demo_user'
  memoryUserId.value = normalized
  localStorage.setItem('activity_memory_user_id', normalized)
}

// ============================================================================
// 生命周期
// ============================================================================

onMounted(() => {
  // 设置今天的日期
  form.date = new Date().toISOString().slice(0, 10)
  memoryUserId.value = localStorage.getItem('activity_memory_user_id') || 'demo_user'

  // Placeholder 轮播
  setInterval(() => {
    placeholderIndex.value = (placeholderIndex.value + 1) % placeholders.length
  }, 4000)
})
</script>

<style scoped>
/* ============================================================================
   全局变量
   ============================================================================ */
:root {
  /* 2026-06-04: 首页主色改成美团式橙黄本地生活风格 */
  --primary: #ff6a00;
  --primary-light: #ffb35c;
  --primary-bg: #fff7ed;
  --success: #10b981;
  --warning: #f59e0b;
  --danger: #ef4444;
  --text-primary: #0f172a;
  --text-secondary: #475569;
  --text-muted: #94a3b8;
  --border: #e2e8f0;
  --bg-card: #ffffff;
  --bg-page: #f7f7f7;
  --shadow-sm: 0 1px 3px rgba(0, 0, 0, 0.08);
  --shadow-md: 0 4px 12px rgba(0, 0, 0, 0.1);
  --shadow-lg: 0 10px 30px rgba(0, 0, 0, 0.12);
  --shadow-xl: 0 20px 50px rgba(0, 0, 0, 0.15);
  --radius-sm: 8px;
  --radius-md: 12px;
  --radius-lg: 16px;
}

/* ============================================================================
   页面布局
   ============================================================================ */
.home-page {
  min-height: 100vh;
  background:
    linear-gradient(180deg, #fff7ed 0, #f7f7f7 260px),
    var(--bg-page);
  padding-bottom: 60px;
}

/* ============================================================================
   Hero 区
   ============================================================================ */
.hero {
  /* 2026-06-04: 移除蓝紫 AI 感渐变，换成本地生活橙黄首页头图 */
  background:
    linear-gradient(135deg, #ffd000 0%, #ffb000 45%, #ff6a00 100%);
  padding: 58px 24px 72px;
  text-align: center;
  color: #3f2200;
  position: relative;
  overflow: hidden;
}

.hero::before {
  content: '';
  position: absolute;
  inset: 0;
  background:
    linear-gradient(90deg, rgba(255,255,255,0.22), transparent 55%),
    radial-gradient(circle at 18% 20%, rgba(255,255,255,0.32), transparent 25%);
  opacity: 0.9;
  pointer-events: none;
}

.hero-account {
  position: absolute;
  top: 18px;
  right: 28px;
  z-index: 2;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border: 1px solid rgba(255, 255, 255, 0.62);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.7);
  box-shadow: 0 8px 24px rgba(154, 52, 18, 0.14);
  backdrop-filter: blur(10px);
}

.account-label {
  font-size: 13px;
  font-weight: 800;
  color: #7c2d12;
}

.hero-content {
  position: relative;
  z-index: 1;
}

.hero-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 6px 12px;
  margin-bottom: 12px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.72);
  color: #9a3412;
  font-size: 13px;
  font-weight: 800;
}

.hero-title {
  font-size: 36px;
  font-weight: 800;
  margin-bottom: 10px;
  letter-spacing: 0;
}

.hero-subtitle {
  font-size: 16px;
  opacity: 0.86;
  max-width: 480px;
  margin: 0 auto;
  line-height: 1.6;
}

/* ============================================================================
   表单卡片
   ============================================================================ */
.form-section {
  max-width: 720px;
  margin: -48px auto 0;
  padding: 0 16px;
  position: relative;
  z-index: 10;
}

.form-card {
  background: var(--bg-card);
  border-radius: 12px;
  box-shadow: 0 16px 42px rgba(154, 52, 18, 0.12);
  padding: 18px 18px 22px;
  border: 1px solid rgba(255,255,255,0.9);
  backdrop-filter: blur(10px);
}

.order-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 10px 8px 16px;
}

.order-card-head h2 {
  margin: 6px 0 0;
  font-size: 20px;
  line-height: 1.3;
  color: var(--text-primary);
}

.order-badge {
  display: inline-flex;
  padding: 4px 8px;
  border-radius: 999px;
  background: #fff7ed;
  color: #ea580c;
  font-size: 12px;
  font-weight: 800;
}

.order-city-hint {
  flex: 0 0 auto;
  padding: 8px 12px;
  border-radius: 999px;
  background: #f8fafc;
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 700;
}

.memory-icon {
  display: inline-flex;
  width: 24px;
  height: 24px;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: #fff7ed;
}

.memory-user-input {
  width: 132px;
  height: 32px;
  border: 1px solid rgba(251, 146, 60, 0.8);
  border-radius: 999px;
  padding: 0 12px;
  color: var(--text-primary);
  background: #fff;
  font-weight: 700;
}

.mode-switch {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 18px;
  padding: 4px;
  border: 1px solid #fed7aa;
  border-radius: 10px;
  background: #fff7ed;
}

.mode-option {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 58px;
  padding: 10px 12px;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  text-align: left;
  transition: all 0.2s ease;
}

.mode-option:hover {
  border-color: var(--primary-light);
  background: #ffffff;
}

.mode-option.active {
  border-color: var(--primary);
  background: #ffffff;
  color: #ea580c;
  box-shadow: 0 6px 16px rgba(234, 88, 12, 0.12);
}

.mode-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: var(--radius-sm);
  background: #fff7ed;
  font-size: 18px;
  flex: 0 0 auto;
}

.mode-option strong,
.mode-option small {
  display: block;
}

.mode-option strong {
  font-size: 14px;
  line-height: 1.3;
}

.mode-option small {
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.3;
}

/* 2026-06-04: 执行模式开关做成轻量本地生活服务选项，fast 负责速度和真实 POI，agent 负责深度多智能体 */
.execution-switch {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin: -6px 0 18px;
}

.execution-option {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 50px;
  padding: 10px 12px;
  border: 1px solid #fed7aa;
  border-radius: 8px;
  background: #fffaf4;
  color: var(--text-secondary);
  text-align: left;
  cursor: pointer;
  transition: all 0.2s ease;
}

.execution-option:hover {
  border-color: var(--primary-light);
  background: #ffffff;
}

.execution-option.active {
  border-color: #ff6a00;
  background: linear-gradient(135deg, #fff7ed, #ffffff);
  color: #c2410c;
  box-shadow: 0 6px 16px rgba(234, 88, 12, 0.1);
}

.execution-icon {
  width: 30px;
  height: 30px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  background: #ffedd5;
  flex-shrink: 0;
}

.execution-option strong,
.execution-option small {
  display: block;
}

.execution-option strong {
  font-size: 13px;
  line-height: 1.3;
}

.execution-option small {
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.3;
}

.quick-panel {
  margin-bottom: 20px;
  padding: 16px;
  border: 1px solid #fed7aa;
  border-radius: 10px;
  background: #fff7ed;
}

.quick-panel-copy {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 14px;
}

.quick-panel-copy strong {
  color: var(--text-primary);
  font-size: 14px;
}

.quick-panel-copy span {
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.5;
}

.quick-location-row {
  align-items: flex-end;
  margin-bottom: 0;
}

.locate-group {
  flex: 0 0 124px;
}

.locate-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  width: 100%;
  height: 42px;
  padding: 0 12px;
  border: 2px solid var(--primary);
  border-radius: var(--radius-sm);
  background: white;
  color: var(--primary);
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.2s;
}

.locate-btn:hover:not(:disabled) {
  background: var(--primary);
  color: white;
}

.locate-btn:disabled {
  cursor: wait;
  opacity: 0.7;
}

.mini-spinner {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(59, 130, 246, 0.25);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

.location-status {
  margin: 4px 0 0;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.5;
}

.location-status.success {
  color: var(--success);
  font-weight: 600;
}

/* ============================================================================
   输入组件
   ============================================================================ */
.input-group {
  margin-bottom: 20px;
}

.input-label {
  display: block;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 8px;
}

.input-label .optional {
  font-weight: 400;
  color: var(--text-muted);
  font-size: 12px;
}

.message-input {
  width: 100%;
  padding: 14px 16px;
  border: 2px solid var(--border);
  border-radius: var(--radius-md);
  font-size: 15px;
  line-height: 1.6;
  resize: vertical;
  transition: border-color 0.2s, box-shadow 0.2s;
  font-family: inherit;
  box-sizing: border-box;
}

.message-input:focus {
  outline: none;
  border-color: var(--primary);
  box-shadow: 0 0 0 3px rgba(255, 106, 0, 0.14);
}

.message-input::placeholder {
  color: var(--text-muted);
}

/* 2026-06-05: 输入框底部增加 Tab 填入推荐句提示，降低比赛演示时的输入成本。 */
.input-helper-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 4px;
}

.tab-hint,
.char-count {
  font-size: 12px;
  color: var(--text-muted);
}

.text-input {
  width: 100%;
  padding: 10px 14px;
  border: 2px solid var(--border);
  border-radius: var(--radius-sm);
  font-size: 14px;
  transition: border-color 0.2s;
  font-family: inherit;
  box-sizing: border-box;
  background: white;
}

.text-input:focus {
  outline: none;
  border-color: var(--primary);
  box-shadow: 0 0 0 3px rgba(255, 106, 0, 0.12);
}

.input-row {
  display: flex;
  gap: 16px;
  margin-bottom: 4px;
}

.flex-1 {
  flex: 1;
  min-width: 0;
}

/* ============================================================================
   场景按钮
   ============================================================================ */
.scenario-buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.scenario-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border: 2px solid var(--border);
  border-radius: 999px;
  background: white;
  cursor: pointer;
  transition: all 0.2s;
  font-size: 14px;
  color: var(--text-secondary);
}

.scenario-btn:hover {
  border-color: var(--primary-light);
  color: var(--primary);
  background: var(--primary-bg);
}

.scenario-btn.active {
  border-color: var(--primary);
  background: var(--primary-bg);
  color: var(--primary);
  font-weight: 600;
}

.scenario-emoji {
  font-size: 18px;
}

/* ============================================================================
   可折叠区域
   ============================================================================ */
.collapsible-section {
  margin-bottom: 20px;
}

.collapse-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 12px 16px;
  border: 2px dashed var(--border);
  border-radius: var(--radius-sm);
  background: #fafbfc;
  cursor: pointer;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  transition: all 0.2s;
}

.collapse-toggle:hover {
  border-color: var(--primary-light);
  background: var(--primary-bg);
}

.optional-tag {
  font-weight: 400;
  color: var(--text-muted);
  font-size: 12px;
}

.arrow {
  margin-left: auto;
  transition: transform 0.2s;
  color: var(--text-muted);
}

.arrow.expanded {
  transform: rotate(180deg);
}

.collapse-content {
  padding: 20px 0 0;
}

.slide-enter-active,
.slide-leave-active {
  transition: all 0.3s ease;
  overflow: hidden;
}

.slide-enter-from,
.slide-leave-to {
  max-height: 0;
  opacity: 0;
  padding-top: 0;
}

.slide-enter-to,
.slide-leave-from {
  max-height: 500px;
  opacity: 1;
}

/* ============================================================================
   Radio / Tag 选择器
   ============================================================================ */
.radio-group {
  display: flex;
  gap: 10px;
}

.radio-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 18px;
  border: 2px solid var(--border);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all 0.2s;
  font-size: 14px;
  color: var(--text-secondary);
}

.radio-item input[type='radio'] {
  display: none;
}

.radio-item:hover,
.radio-item.active {
  border-color: var(--primary);
  background: var(--primary-bg);
  color: var(--primary);
}

.radio-item.small {
  padding: 6px 14px;
  font-size: 13px;
}

.tag-selector {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.tag-btn {
  padding: 6px 14px;
  border: 1.5px solid var(--border);
  border-radius: 999px;
  background: white;
  cursor: pointer;
  font-size: 13px;
  color: var(--text-secondary);
  transition: all 0.2s;
}

.tag-btn:hover {
  border-color: var(--primary-light);
  color: var(--primary);
}

.tag-btn.active {
  border-color: var(--primary);
  background: var(--primary);
  color: white;
}

/* ============================================================================
   提交按钮
   ============================================================================ */
.submit-section {
  text-align: center;
  margin-top: 8px;
}

.submit-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  width: 100%;
  padding: 16px 32px;
  border: none;
  border-radius: 10px;
  background: linear-gradient(135deg, #ffb000, #ff6a00);
  color: white;
  font-size: 18px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.3s;
  box-shadow: 0 10px 24px rgba(255, 106, 0, 0.26);
}

.submit-btn:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 14px 30px rgba(255, 106, 0, 0.34);
}

.submit-btn:active:not(:disabled) {
  transform: translateY(0);
}

.submit-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}

.submit-btn.loading {
  background: linear-gradient(135deg, #f97316, #c2410c);
  box-shadow: none;
  cursor: wait;
}

.spinner {
  width: 20px;
  height: 20px;
  border: 3px solid rgba(255, 255, 255, 0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.submit-hint {
  margin-top: 10px;
  font-size: 13px;
  color: var(--text-muted);
}

/* ============================================================================
   功能亮点
   ============================================================================ */
.features-section,
.examples-section {
  max-width: 720px;
  margin: 48px auto 0;
  padding: 0 16px;
}

.section-title {
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary);
  text-align: center;
  margin-bottom: 24px;
}

.features-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

.feature-card {
  background: var(--bg-card);
  border-radius: var(--radius-md);
  padding: 20px 16px;
  text-align: center;
  box-shadow: var(--shadow-sm);
  transition: transform 0.2s, box-shadow 0.2s;
}

.feature-card:hover {
  transform: translateY(-3px);
  box-shadow: var(--shadow-md);
}

.feature-emoji {
  font-size: 32px;
  display: block;
  margin-bottom: 10px;
}

.feature-card h3 {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 6px;
}

.feature-card p {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.5;
}

/* ============================================================================
   示例场景
   ============================================================================ */
.examples-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}

.example-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
  padding: 16px;
  border: 2px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--bg-card);
  cursor: pointer;
  transition: all 0.2s;
  text-align: left;
}

.example-card:hover {
  border-color: var(--primary);
  background: var(--primary-bg);
  transform: translateY(-2px);
  box-shadow: var(--shadow-sm);
}

.example-emoji {
  font-size: 24px;
}

.example-text {
  font-size: 13px;
  color: var(--text-primary);
  line-height: 1.5;
  margin: 0;
}

.example-tag {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 999px;
  background: var(--primary-bg);
  color: var(--primary);
  font-size: 11px;
  font-weight: 600;
}

/* ============================================================================
   进度浮层
   ============================================================================ */
.progress-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 16px;
}

.progress-card {
  background: white;
  border-radius: var(--radius-lg);
  padding: 32px 28px;
  max-width: 420px;
  width: 100%;
  box-shadow: var(--shadow-lg);
  text-align: center;
}

.progress-card h3 {
  font-size: 20px;
  font-weight: 700;
  margin-bottom: 20px;
  color: var(--text-primary);
}

.progress-bar-container {
  width: 100%;
  height: 8px;
  background: #e2e8f0;
  border-radius: 999px;
  overflow: hidden;
  margin-bottom: 16px;
}

.progress-bar {
  height: 100%;
  background: linear-gradient(90deg, #ffd000, #ffb000, #ff6a00);
  border-radius: 999px;
  transition: width 0.5s ease;
}

.progress-step {
  font-size: 14px;
  color: var(--primary);
  font-weight: 600;
  margin-bottom: 20px;
}

.progress-steps-list {
  text-align: left;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.progress-step-item {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 14px;
  color: var(--text-muted);
  transition: color 0.3s;
}

.progress-step-item.done {
  color: var(--success);
}

.progress-step-item.active {
  color: var(--primary);
  font-weight: 600;
}

.step-icon {
  font-size: 16px;
  width: 20px;
  text-align: center;
}

/* ============================================================================
   过渡动画
   ============================================================================ */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* ============================================================================
   响应式
   ============================================================================ */
@media (max-width: 640px) {
  .hero {
    padding: 72px 16px 64px;
  }

  .hero-account {
    left: 12px;
    right: 12px;
    top: 12px;
    justify-content: space-between;
    border-radius: 12px;
  }

  .memory-user-input {
    width: 136px;
  }

  .hero-title {
    font-size: 28px;
  }

  .hero-subtitle {
    font-size: 14px;
  }

  .form-card {
    padding: 20px 16px;
  }

  .order-card-head {
    align-items: flex-start;
    flex-direction: column;
    gap: 10px;
  }

  .mode-switch {
    grid-template-columns: 1fr;
  }

  .execution-switch {
    grid-template-columns: 1fr;
  }

  .quick-location-row {
    align-items: stretch;
  }

  .locate-group {
    flex-basis: auto;
  }

  .input-row {
    flex-direction: column;
    gap: 0;
  }

  .features-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .examples-grid {
    grid-template-columns: 1fr;
  }

  .scenario-buttons {
    gap: 8px;
  }

  .scenario-btn {
    padding: 6px 12px;
    font-size: 13px;
  }
}
</style>
