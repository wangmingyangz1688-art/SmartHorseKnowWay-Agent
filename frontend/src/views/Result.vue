<template>
  <div class="result-page" v-if="plan">
    <!-- 图片放大预览遮罩 -->
    <div class="lightbox" v-if="lightboxImage" @click="lightboxImage = null">
      <div class="lightbox-content">
        <img :src="lightboxImage" alt="preview" />
        <button class="lightbox-close" @click.stop="lightboxImage = null">✕</button>
      </div>
    </div>

    <!-- ===== 顶部摘要卡片 ===== -->
    <!-- 2026-06-04: 顶部改成美团式订单摘要，压缩信息密度并弱化大面积渐变 -->
    <section class="summary-card">
      <div class="summary-shell">
        <div class="summary-topbar">
          <button class="back-btn" @click="goBack">← 重新规划</button>
          <!-- 2026-06-04: 展示后端规则质检状态，让规划质量闭环在结果页可见 -->
          <span class="summary-status" :class="{ warn: qualityReport && !qualityReport.passed }">
            {{ qualityStatusText }}
          </span>
        </div>

        <div class="summary-header">
          <div>
            <h1 class="summary-title">
              <span class="emoji">📋</span> {{ plan.city }}活动方案
            </h1>
            <p class="summary-subtitle">
              {{ plan.group_summary || (plan.group_type === 'family' ? '家庭出行' : '本地活动') }}
            </p>
          </div>
          <span class="summary-badge" :class="plan.group_type">
            {{ plan.group_type === 'family' ? '家庭' : '朋友/个人' }}
          </span>
        </div>

        <div class="summary-meta">
          <div class="meta-item">
            <span class="meta-icon">📍</span>
            <span>{{ plan.city }}{{ plan.district ? ' · ' + plan.district : '' }}</span>
          </div>
          <div class="meta-item">
            <span class="meta-icon">📅</span>
            <span>{{ formatDate(plan.date) }}</span>
          </div>
          <div class="meta-item">
            <span class="meta-icon">⏰</span>
            <span>{{ plan.start_time }} — {{ plan.end_time }}</span>
          </div>
          <div class="meta-item" v-if="plan.weather_summary">
            <span class="meta-icon">🌤️</span>
            <span>{{ plan.weather_summary }}</span>
          </div>
          <!-- 2026-06-04: 展示后端从接到 POST 到返回结果的耗时 -->
          <div class="meta-item timing" v-if="serverTimingText">
            <span class="meta-icon">⚙️</span>
            <span>后端耗时 {{ serverTimingText }}</span>
          </div>
          <div class="meta-item quality" v-if="qualityReport">
            <span class="meta-icon">✅</span>
            <span>质检 {{ qualityReport.score }}分 · {{ qualityIssueText }}</span>
          </div>
        </div>

        <!-- 2026-06-04: 当规则质检发现问题时，顶部给轻量提示，不打断用户查看方案 -->
        <div class="quality-banner" v-if="qualityReport && !qualityReport.passed">
          <span>⚠️</span>
          <span>{{ topQualityIssue }}</span>
        </div>

        <!-- 2026-06-04: 展示本次 Graph Memory RAG 命中的偏好，增强记忆系统可解释性 -->
        <div class="memory-hit-banner" v-if="memoryHitText">
          <span class="memory-hit-icon">🧠</span>
          <span>本次参考了你的偏好：{{ memoryHitText }}</span>
        </div>

        <!-- 总体提示 -->
        <div class="tips-banner" v-if="plan.overall_tips">
          <span class="tips-icon">💡</span>
          <span>{{ plan.overall_tips }}</span>
        </div>
      </div>
    </section>

    <!-- 2026-06-04: 新增美团式一键执行确认条，让可执行闭环在首屏附近就能被看到 -->
    <section class="checkout-strip" v-if="hasExecutableActions">
      <div class="checkout-main">
        <div class="checkout-title-row">
          <span class="checkout-icon">⚡</span>
          <div>
            <h2>确认后，一键安排</h2>
            <p>{{ executionPreviewText }}</p>
          </div>
        </div>
        <div class="checkout-stats">
          <span>{{ executableActionCount }} 项待执行</span>
          <span v-if="executableActionCost > 0">预计 ¥{{ executableActionCost }}</span>
          <span>{{ allActionsExecuted ? '已完成' : 'Mock 下单演示' }}</span>
        </div>
      </div>
      <button
        class="checkout-primary-btn"
        :disabled="isExecuting || allActionsExecuted"
        @click="executeAllActions"
      >
        <template v-if="isExecuting">
          <span class="spinner dark"></span>
          <span>安排中...</span>
        </template>
        <template v-else-if="allActionsExecuted">
          <span>✅ 已全部搞定</span>
        </template>
        <template v-else>
          <span>确认并一键安排</span>
        </template>
      </button>
    </section>

    <!-- 2026-06-05: 比赛异常覆盖展示，明确说明无座/无票/冲突/天气不适合时的自动处理策略。 -->
    <section class="exception-strip" v-if="exceptionStrategies.length">
      <div class="exception-head">
        <span>🛟 异常预案</span>
        <small>{{ exceptionStrategies.length }} 类覆盖</small>
      </div>
      <div class="exception-list">
        <div
          v-for="item in exceptionStrategies"
          :key="item.type"
          class="exception-item"
          :class="{ active: item.active }"
        >
          <strong>{{ item.title }}</strong>
          <span>{{ item.strategy }}</span>
        </div>
      </div>
    </section>

    <!-- 2026-06-04: 概览区改成两列信息卡，地图从大模块压缩为路线卡 -->
    <section class="overview-grid" v-if="plan.budget || mapPoints.length >= 2">
      <!-- ===== 预算概览 ===== -->
      <div class="budget-card" v-if="plan.budget">
        <div class="budget-total">
          <span class="budget-label">预估总费用</span>
          <span class="budget-amount">¥{{ plan.budget.total || 0 }}</span>
        </div>
        <div class="budget-breakdown">
          <div class="budget-item" v-if="plan.budget.activities > 0">
            <span class="budget-dot play"></span>
            <span class="budget-name">玩乐</span>
            <span class="budget-val">¥{{ plan.budget.activities }}</span>
          </div>
          <div class="budget-item" v-if="plan.budget.dining > 0">
            <span class="budget-dot eat"></span>
            <span class="budget-name">餐饮</span>
            <span class="budget-val">¥{{ plan.budget.dining }}</span>
          </div>
          <div class="budget-item" v-if="plan.budget.transportation > 0">
            <span class="budget-dot transport"></span>
            <span class="budget-name">交通</span>
            <span class="budget-val">¥{{ plan.budget.transportation }}</span>
          </div>
          <div class="budget-item" v-if="plan.budget.extras > 0">
            <span class="budget-dot extra"></span>
            <span class="budget-name">其他</span>
            <span class="budget-val">¥{{ plan.budget.extras }}</span>
          </div>
        </div>
      </div>

      <!-- ===== 地图路线 ===== -->
      <div class="map-section compact" v-if="mapPoints.length >= 2">
        <div class="compact-section-head">
          <h2>🗺️ 路线预览</h2>
          <span>{{ mapPoints.length }} 个点位</span>
        </div>
        <PlanMap :points="mapPoints" :city="plan.city" />
      </div>
    </section>

    <!-- ===== 时间轴 ===== -->
    <section class="timeline-section">
      <!-- 2026-06-04: 时间轴标题改成产品化路线清单文案，弱化报告感 -->
      <div class="section-heading-row">
        <div>
          <h2 class="section-title">🗓️ 今日路线</h2>
          <p class="section-desc compact">按时间顺序安排，确认后可直接执行预约、购票和排队查询。</p>
        </div>
        <span class="section-count">{{ plan.timeline.length }} 步</span>
      </div>

      <div class="timeline">
        <div
          v-for="(item, index) in plan.timeline"
          :key="index"
          class="timeline-item"
          :class="item.activity_type"
        >
          <!-- 时间轴左侧：时间 + 图标 -->
          <div class="timeline-left">
            <div class="timeline-time">{{ item.start_time }}</div>
            <div class="timeline-icon" :class="item.activity_type">
              {{ getActivityIcon(item.activity_type) }}
            </div>
            <div class="timeline-line" v-if="index < plan.timeline.length - 1"></div>
          </div>

          <!-- 时间轴右侧：内容卡片 -->
          <div class="timeline-card" :class="item.activity_type">

            <!-- 交通类型 -->
            <template v-if="item.activity_type === 'transport'">
              <div class="transport-card">
                <div class="transport-info">
                  <span class="transport-mode">{{ getTransportEmoji(item.transportation) }} {{ item.transportation || '前往' }}</span>
                  <span class="transport-duration" v-if="item.travel_minutes">约 {{ item.travel_minutes }} 分钟</span>
                </div>
                <div class="transport-title">{{ item.title }}</div>
              </div>
            </template>

            <!-- 玩乐/用餐/其他类型 -->
            <template v-else>
              <!-- 图片轮播区域 -->
              <div class="card-image" v-if="item.image_url || (venuePhotos[item.venue_name] && venuePhotos[item.venue_name].length > 0)">
                <!-- 单张图片 -->
                <img
                  v-if="item.image_url"
                  :src="item.image_url"
                  :alt="item.venue_name || item.title"
                  @error="handleImageError($event, item)"
                  loading="lazy"
                  @click="lightboxImage = item.image_url"
                />
                <!-- 多张图片轮播 -->
                <template v-else-if="venuePhotos[item.venue_name] && venuePhotos[item.venue_name].length > 0">
                  <img
                    :src="venuePhotos[item.venue_name][currentPhotoIndex[item.venue_name] || 0]"
                    :alt="item.venue_name || item.title"
                    @error="handleImageError($event, item)"
                    loading="lazy"
                    @click="lightboxImage = venuePhotos[item.venue_name][currentPhotoIndex[item.venue_name] || 0]"
                  />
                  <!-- 左右切换箭头 -->
                  <button
                    v-if="venuePhotos[item.venue_name].length > 1"
                    class="carousel-arrow carousel-prev"
                    @click.stop="prevPhoto(item.venue_name)"
                  >&#8249;</button>
                  <button
                    v-if="venuePhotos[item.venue_name].length > 1"
                    class="carousel-arrow carousel-next"
                    @click.stop="nextPhoto(item.venue_name)"
                  >&#8250;</button>
                  <!-- 指示点 -->
                  <div class="carousel-dots" v-if="venuePhotos[item.venue_name].length > 1">
                    <span
                      v-for="(_, idx) in venuePhotos[item.venue_name]"
                      :key="idx"
                      class="carousel-dot"
                      :class="{ active: (currentPhotoIndex[item.venue_name] || 0) === idx }"
                      @click.stop="currentPhotoIndex[item.venue_name] = idx"
                    />
                  </div>
                  <!-- 图片计数 -->
                  <div class="carousel-count" v-if="venuePhotos[item.venue_name].length > 1">
                    {{ (currentPhotoIndex[item.venue_name] || 0) + 1 }} / {{ venuePhotos[item.venue_name].length }}
                  </div>
                </template>
                <div class="card-type-badge" :class="item.activity_type">
                  {{ getActivityLabel(item.activity_type) }}
                </div>
              </div>

              <!-- 无图片时的占位 -->
              <div class="card-image placeholder" v-else>
                <div class="placeholder-content">
                  <span class="placeholder-icon">{{ getActivityIcon(item.activity_type) }}</span>
                  <span class="placeholder-text">{{ item.venue_name || item.title }}</span>
                </div>
                <div class="card-type-badge" :class="item.activity_type">
                  {{ getActivityLabel(item.activity_type) }}
                </div>
              </div>

              <!-- 卡片主体 -->
              <div class="card-body">
                <!-- 2026-06-04: 商户卡式标题区，突出场所名、价格和可执行状态 -->
                <div class="merchant-head">
                  <div>
                    <h3 class="card-title">{{ item.title }}</h3>
                    <p class="merchant-subtitle" v-if="item.venue_name">{{ item.venue_name }}</p>
                  </div>
                  <div class="merchant-side">
                    <div class="merchant-price" v-if="item.estimated_cost > 0">
                      ¥{{ item.estimated_cost }}
                    </div>
                    <div class="merchant-price free" v-else-if="item.activity_type === 'play'">
                      免费
                    </div>
                    <!-- 2026-06-04: 新增单站换一个入口，用户不满意某站时可带约束重新规划 -->
                    <button
                      class="replace-btn"
                      type="button"
                      :disabled="isReplanning"
                      @click="replanWithoutItem(item)"
                    >
                      {{ isReplanning ? '重想中' : '换一个' }}
                    </button>
                  </div>
                </div>
                <p class="card-desc" v-if="item.description">{{ item.description }}</p>

                <!-- 场所信息 -->
                <div class="card-venue" v-if="item.venue_name">
                  <div class="venue-name">{{ item.venue_name }}</div>
                  <div class="venue-address" v-if="item.venue_address">{{ item.venue_address }}</div>
                </div>

                <!-- 时间和费用 -->
                <div class="card-meta">
                  <span class="meta-tag time">
                    🕐 {{ item.start_time }} - {{ item.end_time }}
                  </span>
                  <span class="meta-tag cost" v-if="item.estimated_cost > 0">
                    💰 ¥{{ item.estimated_cost }}
                  </span>
                  <span class="meta-tag cost free" v-else-if="item.activity_type === 'play'">
                    🆓 免费
                  </span>
                </div>

                <!-- 标签 -->
                <div class="card-tags" v-if="item.tags && item.tags.length">
                  <span class="tag" v-for="tag in item.tags" :key="tag">{{ tag }}</span>
                </div>

                <!-- 餐厅专属信息 -->
                <div class="restaurant-info" v-if="item.activity_type === 'eat'">
                  <div class="rest-features" v-if="item.restaurant_features && item.restaurant_features.length">
                    <span class="rest-feature" v-for="f in item.restaurant_features" :key="f">✅ {{ f }}</span>
                  </div>
                  <div class="rest-meta">
                    <span v-if="item.party_size">👥 {{ item.party_size }}人用餐</span>
                    <span v-if="item.queue_status" class="queue-status" :class="getQueueClass(item.queue_status)">
                      {{ item.queue_status }}
                    </span>
                  </div>
                  <!-- 实时查排队按钮 -->
                  <button
                    class="check-queue-btn"
                    @click="checkQueue(item)"
                    :disabled="queueLoading[item.venue_name]"
                  >
                    {{ queueLoading[item.venue_name] ? '查询中...' : '🔄 实时查排队' }}
                  </button>
                  <div class="queue-result" v-if="queueResults[item.venue_name]">
                    <span :class="queueResults[item.venue_name].queue_length === 0 ? 'good' : 'warn'">
                      {{ queueResults[item.venue_name].message }}
                    </span>
                  </div>
                </div>

                <!-- 可预订标识 -->
                <div class="booking-hint" v-if="item.booking_available">
                  <span class="booking-icon">📞</span>
                  <span>可{{ item.booking_type === 'restaurant' ? '预约订座' : '在线购票' }}</span>
                </div>

                <!-- 2026-06-04: 自然语言反馈入口，用户原话会被后端解析成三层记忆并同步 Neo4j -->
                <div class="memory-feedback">
                  <button
                    class="feedback-toggle"
                    type="button"
                    @click="toggleFeedback(item)"
                  >
                    {{ feedbackOpen[itemKey(item)] ? '收起反馈' : '反馈这条推荐' }}
                  </button>
                  <div class="feedback-panel" v-if="feedbackOpen[itemKey(item)]">
                    <textarea
                      v-model="feedbackDrafts[itemKey(item)]"
                      class="feedback-input"
                      rows="2"
                      placeholder="比如：这个餐厅太贵了，不适合孩子，下次别推荐这种"
                    ></textarea>
                    <div class="feedback-actions">
                      <button
                        class="feedback-chip"
                        type="button"
                        v-for="chip in feedbackChips(item)"
                        :key="chip"
                        @click="appendFeedbackChip(item, chip)"
                      >
                        {{ chip }}
                      </button>
                      <button
                        class="feedback-submit"
                        type="button"
                        :disabled="feedbackSubmitting[itemKey(item)] || !feedbackDrafts[itemKey(item)]?.trim()"
                        @click="submitItemFeedback(item)"
                      >
                        {{ feedbackSubmitting[itemKey(item)] ? '提交中' : feedbackStatus[itemKey(item)] || '提交反馈' }}
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </template>
          </div>
        </div>
      </div>
    </section>

    <!-- ===== 可执行动作 ===== -->
    <section class="actions-section" v-if="plan.executable_actions && plan.executable_actions.length">
      <!-- 2026-06-04: 将普通动作列表改成美团式订单确认模块，强调“确认方案 -> 自动预约/购票/下单” -->
      <div class="actions-header">
        <div>
          <h2 class="section-title">⚡ 待确认操作</h2>
          <p class="section-desc">确认方案后，系统会按下面的清单自动完成 Mock 预约和下单</p>
        </div>
        <div class="actions-total">
          <span>待执行</span>
          <strong>{{ executableActionCount }}</strong>
          <span>项</span>
        </div>
      </div>

      <div class="checkout-contact" v-if="!allActionsExecuted">
        <div class="checkout-contact-title">
          <span>👤</span>
          <strong>联系人信息</strong>
        </div>
        <div class="contact-row">
          <input
            v-model="contactName"
            type="text"
            class="contact-input"
            placeholder="联系人姓名"
          />
          <input
            v-model="contactPhone"
            type="tel"
            class="contact-input"
            placeholder="联系人电话（可选，Mock 可留空）"
          />
        </div>
      </div>

      <div class="actions-list">
        <div
          v-for="action in plan.executable_actions"
          :key="action.action_id"
          class="action-card"
          :class="{
            optional: action.is_optional,
            processing: getActionState(action).status === 'processing',
            executed: getActionState(action).status === 'success',
            failed: getActionState(action).status === 'failed'
          }"
        >
          <div class="action-left">
            <span class="action-icon">{{ getActionIcon(action.action_type) }}</span>
            <div class="action-info">
              <div class="action-desc">{{ action.description }}</div>
              <div class="action-type-label">{{ getActionLabel(action.action_type) }}</div>
            </div>
          </div>
          <div class="action-right">
            <span class="action-cost" v-if="action.estimated_cost > 0">¥{{ action.estimated_cost }}</span>
            <span class="action-optional-tag" v-if="action.is_optional">可选</span>

            <!-- 2026-06-04: 订单式状态流转展示，覆盖 待确认 -> 执行中 -> 成功/失败 -->
            <div class="action-result" v-if="getActionState(action).status !== 'pending'">
              <span
                class="result-badge"
                :class="getActionState(action).status === 'success' ? 'success' : getActionState(action).status === 'processing' ? 'processing' : 'fail'"
              >
                {{ getActionStatusText(action) }}
              </span>
              <span class="result-msg" v-if="getActionState(action).confirmation_code">
                确认码: {{ getActionState(action).confirmation_code }}
              </span>
              <span class="result-msg" v-else-if="getActionState(action).order_id">
                订单号: {{ getActionState(action).order_id }}
              </span>
            </div>

            <!-- 单独执行按钮 -->
            <button
              v-else
              class="action-exec-btn"
              :class="action.action_type"
              @click="executeSingleAction(action)"
              :disabled="isExecuting"
            >
              {{ getActionBtnText(action.action_type) }}
            </button>
          </div>

          <div class="order-timeline" v-if="getActionState(action).status !== 'pending'">
            <div
              v-for="node in getActionTimeline(action)"
              :key="`${action.action_id}-${node.status}`"
              class="order-node"
              :class="{ done: node.done, processing: node.status === 'processing' && getActionState(action).status === 'processing', failed: node.status === 'failed' }"
            >
              <span class="order-dot"></span>
              <span class="order-text">{{ node.text }}</span>
              <span class="order-time" v-if="node.time">{{ formatActionTime(node.time) }}</span>
            </div>
          </div>

          <!-- 2026-06-04: 失败后支持重试和改用备选，补齐订单异常处理闭环 -->
          <div class="retry-panel" v-if="getActionState(action).status === 'failed'">
            <p class="retry-reason" v-if="getActionState(action).fallback_reason">
              {{ getActionState(action).fallback_reason }}
            </p>
            <div class="retry-actions">
              <button
                class="retry-btn secondary"
                :disabled="isExecuting"
                @click="retryAction(action)"
              >
                重试
              </button>
              <button
                class="retry-btn primary"
                v-if="getActionState(action).fallback_action"
                :disabled="isExecuting"
                @click="useFallbackAction(action)"
              >
                改用备选
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- 全部执行 -->
      <div class="batch-execute" v-if="!allActionsExecuted">
        <button
          class="batch-exec-btn"
          :disabled="isExecuting"
          @click="executeAllActions"
        >
          <template v-if="isExecuting">
            <span class="spinner"></span>
            <span>正在预约和下单...</span>
          </template>
          <template v-else>
            <span>🚀 确认方案，一键全部执行</span>
          </template>
        </button>
      </div>

      <!-- 执行摘要 -->
      <div class="exec-summary" v-if="executionSummary">
        <div class="summary-content" :class="executionAllSuccess ? 'success' : 'partial'">
          <h4>{{ executionAllSuccess ? '🎉 全部搞定！' : '⚠️ 部分完成' }}</h4>
          <p>{{ executionSummary }}</p>
        </div>
      </div>
    </section>

    <!-- ===== 分享区域 ===== -->
    <section class="share-section">
      <h2 class="section-title">💬 分享给同伴</h2>

      <div class="share-tabs">
        <button
          class="share-tab"
          :class="{ active: shareTab === 'short' }"
          @click="shareTab = 'short'"
        >
          📱 微信消息
        </button>
        <button
          class="share-tab"
          :class="{ active: shareTab === 'detailed' }"
          @click="shareTab = 'detailed'"
        >
          📋 详细版
        </button>
      </div>

      <div class="share-content">
        <div class="share-text-box" v-if="shareTab === 'short'">
          <pre class="share-text">{{ shareShortText }}</pre>
        </div>
        <div class="share-text-box" v-else>
          <pre class="share-text">{{ shareDetailedText }}</pre>
        </div>
        <button class="copy-btn" @click="copyShareText">
          {{ copySuccess ? '✅ 已复制' : '📋 复制文案' }}
        </button>
      </div>
    </section>

    <!-- ===== 底部操作栏 ===== -->
    <div class="bottom-bar">
      <button class="bottom-btn secondary" @click="goBack">
        ← 重新规划
      </button>
      <button
        class="bottom-btn primary"
        v-if="plan.executable_actions && plan.executable_actions.length && !allActionsExecuted"
        :disabled="isExecuting"
        @click="executeAllActions"
      >
        {{ isExecuting ? '安排中...' : '⚡ 确认并一键安排' }}
      </button>
      <!-- 2026-06-04: 底部增加整体重新思考入口，补齐“这套方案不满意”的交互 -->
      <button
        class="bottom-btn rethink"
        v-if="!isExecuting"
        :disabled="isReplanning"
        @click="rethinkWholePlan"
      >
        {{ isReplanning ? '重新思考中...' : '换一套方案' }}
      </button>
      <button class="bottom-btn primary" v-else @click="copyShareText">
        💬 复制分享
      </button>
    </div>
  </div>

  <!-- ===== 无方案时 ===== -->
  <div class="empty-state" v-else>
    <div class="empty-content">
      <span class="empty-icon">🤔</span>
      <h2>暂无活动方案</h2>
      <p>请先在首页生成一个活动方案</p>
      <button class="empty-btn" @click="goBack">去首页</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import PlanMap from '@/components/PlanMap.vue'

const router = useRouter()

// ============================================================================
// 方案数据
// ============================================================================

const plan = ref<any>(null)
const originalRequest = ref<any>(null)

// ============================================================================
// UI 状态
// ============================================================================

const shareTab = ref<'short' | 'detailed'>('short')
const copySuccess = ref(false)
const contactName = ref('用户')
const contactPhone = ref('')
const isExecuting = ref(false)
const executedActions = reactive<Record<string, any>>({})
const executionSummary = ref('')
const executionAllSuccess = ref(false)
const queueLoading = reactive<Record<string, boolean>>({})
const queueResults = reactive<Record<string, any>>({})
const venuePhotos = reactive<Record<string, string[]>>({})  // 2026-06-03 改造：存储多张图片
const lightboxImage = ref<string | null>(null)
const currentPhotoIndex = reactive<Record<string, number>>({})  // 每个场所当前显示的图片索引
// 2026-06-04: 自然语言反馈状态，用于把用户原话沉淀进记忆系统
const feedbackOpen = reactive<Record<string, boolean>>({})
const feedbackDrafts = reactive<Record<string, string>>({})
const feedbackSubmitting = reactive<Record<string, boolean>>({})
const feedbackStatus = reactive<Record<string, string>>({})
// 2026-06-04: 用户不满意某站时，支持带反馈约束重新规划整条路线
const isReplanning = ref(false)

// ============================================================================
// 计算属性
// ============================================================================

// 2026-06-04: 结果页首屏执行闭环所需的聚合信息
const hasExecutableActions = computed(() => {
  return !!plan.value?.executable_actions?.length
})

const executableActionCount = computed(() => {
  return plan.value?.executable_actions?.length || 0
})

const executableActionCost = computed(() => {
  return (plan.value?.executable_actions || []).reduce(
    (sum: number, action: any) => sum + (Number(action.estimated_cost) || 0),
    0
  )
})

const executionPreviewText = computed(() => {
  const actions = plan.value?.executable_actions || []
  if (!actions.length) return '当前方案没有需要自动执行的动作'
  const labels = actions.map((action: any) => getActionLabel(action.action_type))
  const uniqueLabels = Array.from(new Set(labels))
  return `将自动处理：${uniqueLabels.join('、')}`
})

const exceptionStrategies = computed(() => {
  // 2026-06-05: 展示后端返回的异常覆盖策略，便于比赛 Demo 说明系统不是失败即终止。
  return plan.value?.exception_strategies || []
})

// 2026-06-04: 后端计时和规则质检结果展示
const serverTimingText = computed(() => {
  const timing = plan.value?.server_timing
  if (!timing?.duration_seconds && !timing?.duration_ms) return ''
  const seconds = Number(timing.duration_seconds || (timing.duration_ms / 1000))
  if (Number.isNaN(seconds)) return ''
  return seconds >= 10 ? `${seconds.toFixed(1)} 秒` : `${seconds.toFixed(2)} 秒`
})

const qualityReport = computed(() => plan.value?.quality_report || null)

const qualityStatusText = computed(() => {
  if (!qualityReport.value) return 'AI 已生成可执行方案'
  return qualityReport.value.passed ? '规则质检已通过' : '规则质检需复核'
})

const qualityIssueText = computed(() => {
  if (!qualityReport.value) return ''
  const errors = qualityReport.value.error_count || 0
  const warnings = qualityReport.value.warning_count || 0
  if (!errors && !warnings) return '无明显问题'
  return `${errors} 个错误 / ${warnings} 个提醒`
})

const topQualityIssue = computed(() => {
  const firstIssue = qualityReport.value?.issues?.[0]
  if (!firstIssue) return '方案存在需要复核的规则问题'
  return `${firstIssue.message}${firstIssue.repair_hint ? `，建议：${firstIssue.repair_hint}` : ''}`
})

const memoryHitText = computed(() => {
  const labels = plan.value?.memory_context?.used_labels || []
  return labels.slice(0, 6).join('、')
})

const allActionsExecuted = computed(() => {
  if (!plan.value?.executable_actions?.length) return true
  return plan.value.executable_actions.every(
    (a: any) => getActionState(a).status === 'success'
  )
})

// 2026-06-04: 订单式执行状态工具函数
function getActionState(action: any) {
  return executedActions[action.action_id] || {
    status: 'pending',
    status_text: '待确认',
    success: false,
    timeline: [
      { status: 'pending', text: '待确认', done: false },
      { status: 'processing', text: '执行中', done: false },
      { status: 'success', text: '成功/失败', done: false },
    ],
  }
}

function getActionStatusText(action: any) {
  const state = getActionState(action)
  if (state.status === 'processing') return '⏳ 执行中'
  if (state.status === 'success') return '✅ 成功'
  if (state.status === 'failed') return '❌ 失败'
  return state.status_text || '待确认'
}

function getActionTimeline(action: any) {
  return getActionState(action).timeline || []
}

function formatActionTime(value: string) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value.slice(11, 19)
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function itemKey(item: any) {
  return `${item.order || 0}_${item.activity_type}_${item.venue_name || item.title || 'item'}`
}

function toggleFeedback(item: any) {
  const key = itemKey(item)
  feedbackOpen[key] = !feedbackOpen[key]
}

function feedbackChips(item: any) {
  if (item.activity_type === 'eat') {
    return ['太贵了', '排队久', '口味喜欢', '太油腻', '适合聊天', '下次别推']
  }
  if (item.activity_type === 'play') {
    return ['喜欢这个', '太远了', '太累了', '适合孩子', '不适合孩子', '下次别推']
  }
  return ['喜欢', '不合适', '太赶了', '很放松', '下次别推']
}

function appendFeedbackChip(item: any, chip: string) {
  const key = itemKey(item)
  const current = feedbackDrafts[key] || ''
  feedbackDrafts[key] = current ? `${current}，${chip}` : chip
}

function inferFeedbackEventType(text: string) {
  if (/(喜欢|不错|合适|满意|可以|适合)/.test(text)) return 'like'
  if (/(不喜欢|不合适|太远|太贵|太累|太吵|别推|不要|油腻|排队)/.test(text)) return 'dislike'
  return 'feedback'
}

function memoryFeedbackTags(item: any) {
  // 2026-06-05: 反馈只提交用户可感知标签，过滤“真实POI”等内部技术标记，避免污染记忆系统。
  const blocked = new Set(['真实POI', '交通'])
  return (item.tags || []).filter((tag: string) => tag && !blocked.has(tag))
}

async function submitItemFeedback(item: any) {
  const key = itemKey(item)
  const text = (feedbackDrafts[key] || '').trim()
  if (!text || feedbackSubmitting[key]) return

  feedbackSubmitting[key] = true
  feedbackStatus[key] = ''

  try {
    const userId = originalRequest.value?.user_id || localStorage.getItem('activity_memory_user_id') || 'demo_user'
    const scenario = plan.value?.scenario?.primary || plan.value?.memory_context?.scenario || 'unknown'
    const res = await fetch('/api/activity/memory/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_id: userId,
        scenario,
        event_type: inferFeedbackEventType(text),
        target_type: item.activity_type === 'eat' ? 'restaurant' : 'venue',
        target_name: item.venue_name || item.title || '',
        tags: memoryFeedbackTags(item),
        feedback_text: text,
        raw_text: originalRequest.value?.message || '',
      }),
    })
    const data = await res.json()
    if (!res.ok || !data.success) {
      throw new Error(data.detail || data.message || '反馈提交失败')
    }
    feedbackStatus[key] = '已记住'
    feedbackDrafts[key] = ''
    setTimeout(() => {
      feedbackOpen[key] = false
    }, 700)
  } catch (e: any) {
    feedbackStatus[key] = '提交失败'
    console.warn('提交反馈失败:', e)
  } finally {
    feedbackSubmitting[key] = false
  }
}

async function rememberNegativeItem(item: any, text: string) {
  try {
    const userId = originalRequest.value?.user_id || localStorage.getItem('activity_memory_user_id') || 'demo_user'
    const scenario = plan.value?.scenario?.primary || plan.value?.memory_context?.scenario || 'unknown'
    await fetch('/api/activity/memory/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_id: userId,
        scenario,
        event_type: 'dislike',
        target_type: item.activity_type === 'eat' ? 'restaurant' : 'venue',
        target_name: item.venue_name || item.title || '',
        tags: memoryFeedbackTags(item),
        feedback_text: text,
        raw_text: originalRequest.value?.message || '',
      }),
    })
  } catch (e) {
    console.warn('记录换一个反馈失败:', e)
  }
}

async function replanWithoutItem(item: any) {
  if (!originalRequest.value || isReplanning.value) return
  const name = item.venue_name || item.title || '这个地点'
  const reason = item.activity_type === 'eat'
    ? `我不想去${name}吃饭，请换一家更合适的餐厅，避开这个餐厅。`
    : `我不想去${name}，请把这一站换成更适合当前场景的地点，避开这个地点。`

  await rememberNegativeItem(item, reason)
  await replanWithExtraConstraint(reason)
}

async function rethinkWholePlan() {
  if (!originalRequest.value || isReplanning.value) return
  await replanWithExtraConstraint('我对这套方案不太满意，请重新思考一套更贴合当前场景、更少折腾的方案。')
}

async function replanWithExtraConstraint(extra: string) {
  isReplanning.value = true
  try {
    const fallbackExecutionMode = originalRequest.value?.planning_mode === 'nearby_quick' ? 'fast' : 'agent'
    const requestBody = {
      ...originalRequest.value,
      // 2026-06-05: 重新规划时保留执行模式，避免旧结果页请求缺少 execution_mode 后回退到深度 Agent/MCP 链路。
      execution_mode: originalRequest.value?.execution_mode || plan.value?.execution_mode || fallbackExecutionMode,
      message: `${originalRequest.value.message || ''}\n补充要求：${extra}`,
    }
    const newPlan = await requestPlanStream(requestBody)
    plan.value = newPlan
    originalRequest.value = requestBody
    sessionStorage.setItem('activityPlan', JSON.stringify(newPlan))
    sessionStorage.setItem('activityRequest', JSON.stringify(requestBody))
    Object.keys(executedActions).forEach((key) => delete executedActions[key])
    executionSummary.value = ''
    executionAllSuccess.value = false
    await nextTick()
    loadVenuePhotos()
    window.scrollTo({ top: 0, behavior: 'smooth' })
  } catch (e: any) {
    alert(`重新规划失败：${e.message || '未知错误'}`)
  } finally {
    isReplanning.value = false
  }
}

async function requestPlanStream(requestBody: any) {
  const res = await fetch('/api/activity/plan/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(requestBody),
  })
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: ${res.statusText}`)
  }
  const reader = res.body?.getReader()
  if (!reader) {
    throw new Error('无法读取重新规划响应')
  }
  const decoder = new TextDecoder()
  let buffer = ''
  let resultPlan: any = null
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''
    for (const line of lines) {
      const trimmed = line.trim()
      if (!trimmed.startsWith('data: ')) continue
      const event = JSON.parse(trimmed.slice(6))
      if (event.type === 'complete' && event.success) {
        resultPlan = event.data
      }
      if (event.type === 'error') {
        throw new Error(event.message || '重新规划失败')
      }
    }
  }
  if (!resultPlan) {
    throw new Error('未获取到新的活动方案')
  }
  return resultPlan
}

function markActionProcessing(action: any) {
  const now = new Date().toISOString()
  executedActions[action.action_id] = {
    action_id: action.action_id,
    action_type: action.action_type,
    description: action.description,
    status: 'processing',
    status_text: '执行中',
    success: false,
    started_at: now,
    timeline: [
      { status: 'pending', text: '待确认', time: now, done: true },
      { status: 'processing', text: '执行中', time: now, done: true },
      { status: 'success', text: '等待结果', done: false },
    ],
  }
}

// ============================================================================
// 地图点位计算
// ============================================================================

const mapPoints = computed(() => {
  if (!plan.value?.timeline) return []

  const points = plan.value.timeline
    .filter((item: any) => item.activity_type !== 'transport')
    .map((item: any) => {
      const loc = item.venue_location || {}
      // 兼容多种格式：number / string / lng+lat / longitude+latitude
      const lng = parseFloat(loc.longitude ?? loc.lng ?? 0)
      const lat = parseFloat(loc.latitude ?? loc.lat ?? 0)
      return {
        name: item.venue_name || item.title || '',
        lng,
        lat,
        type: item.activity_type as string,
        order: item.order ?? 0,
        hasValidCoords: lng !== 0 && lat !== 0 && !isNaN(lng) && !isNaN(lat),
      }
    })
    .filter((p: { hasValidCoords: boolean }) => p.hasValidCoords)

  console.log('🗺️ 地图点位:', JSON.stringify(points, null, 2))
  return points
})


// ============================================================================
// 分享文案
// ============================================================================

const shareShortText = computed(() => {
  if (!plan.value) return ''

  const p = plan.value
  if (p.share_message) return p.share_message

  const parts: string[] = []
  parts.push(`搞定了！${formatDate(p.date)} ${p.start_time}出发`)

  const activities = (p.timeline || []).filter((i: any) => i.activity_type === 'play')
  const restaurants = (p.timeline || []).filter((i: any) => i.activity_type === 'eat')

  if (activities.length > 0) {
    parts.push(`先去${activities[0].venue_name || activities[0].title}`)
  }
  if (restaurants.length > 0) {
    parts.push(`然后去${restaurants[0].venue_name || restaurants[0].title}吃饭`)
  }
  if (p.budget?.total) {
    parts.push(`预算约¥${p.budget.total}`)
  }

  return parts.join('，') + ' ~'
})

const shareDetailedText = computed(() => {
  if (!plan.value) return ''

  const p = plan.value
  const lines: string[] = [
    `📋 ${p.city}活动安排 (${formatDate(p.date)})`,
    `⏰ ${p.start_time} — ${p.end_time}`,
    '',
  ]

  for (const item of p.timeline || []) {
    if (item.activity_type === 'transport') continue

    const emoji: Record<string, string> = { play: '🎯', eat: '🍽️', extra: '✨' }
    const e = emoji[item.activity_type] || '📍'
    let line = `${e} ${item.start_time}-${item.end_time}  ${item.title}`

    if (item.venue_name && item.venue_name !== item.title) {
      line += `\n   📍 ${item.venue_name}`
    }
    if (item.venue_address) {
      line += `\n   🏠 ${item.venue_address}`
    }
    if (item.estimated_cost > 0) {
      line += `\n   💰 约¥${item.estimated_cost}`
    }
    lines.push(line)
    lines.push('')
  }

  if (p.budget?.total) {
    lines.push(`💰 预估总费用：¥${p.budget.total}`)
  }
  if (p.overall_tips) {
    lines.push(`💡 ${p.overall_tips}`)
  }

  return lines.join('\n')
})

// ============================================================================
// 方法：图标/标签
// ============================================================================

function getActivityIcon(type: string): string {
  const map: Record<string, string> = {
    transport: '🚗',
    play: '🎯',
    eat: '🍽️',
    extra: '✨',
  }
  return map[type] || '📍'
}

function getActivityLabel(type: string): string {
  const map: Record<string, string> = {
    play: '玩乐',
    eat: '用餐',
    extra: '惊喜',
  }
  return map[type] || '活动'
}

function getTransportEmoji(mode: string): string {
  if (!mode) return '🚶'
  if (mode.includes('步行') || mode.includes('走')) return '🚶'
  if (mode.includes('驾车') || mode.includes('开车') || mode.includes('打车')) return '🚗'
  if (mode.includes('公交')) return '🚌'
  if (mode.includes('地铁')) return '🚇'
  if (mode.includes('骑')) return '🚲'
  return '🚗'
}

function getActionIcon(type: string): string {
  const map: Record<string, string> = {
    book_restaurant: '🍽️',
    book_activity: '🎫',
    order_delivery: '🚚',
    check_queue: '🔢',
  }
  return map[type] || '⚡'
}

function getActionLabel(type: string): string {
  const map: Record<string, string> = {
    book_restaurant: '餐厅预约',
    book_activity: '购买门票',
    order_delivery: '配送下单',
    check_queue: '排队查询',
  }
  return map[type] || '操作'
}

function getActionBtnText(type: string): string {
  const map: Record<string, string> = {
    book_restaurant: '预约',
    book_activity: '购票',
    order_delivery: '下单',
    check_queue: '查询',
  }
  return map[type] || '执行'
}

function getQueueClass(status: string): string {
  if (status.includes('无需') || status.includes('直接')) return 'good'
  if (status.includes('约等') && !status.includes('建议')) return 'okay'
  return 'busy'
}

function formatDate(dateStr: string): string {
  if (!dateStr) return ''
  try {
    const d = new Date(dateStr + 'T00:00:00')
    const weekdays = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
    const month = d.getMonth() + 1
    const day = d.getDate()
    const weekday = weekdays[d.getDay()]
    return `${month}月${day}日 ${weekday}`
  } catch {
    return dateStr
  }
}

// ============================================================================
// 方法：图片
// ============================================================================

function handleImageError(event: Event, _item: any) {
  const img = event.target as HTMLImageElement
  img.style.display = 'none'
}

async function loadVenuePhotos() {
  if (!plan.value?.timeline) return

  for (const item of plan.value.timeline) {
    if (item.activity_type === 'transport') continue
    if (item.image_url) continue
    if (!item.venue_name) continue

    try {
      const cityParam = plan.value.city ? `&city=${encodeURIComponent(plan.value.city)}` : ''
      const res = await fetch(`/api/poi/photo?name=${encodeURIComponent(item.venue_name)}${cityParam}`)
      const data = await res.json()
      // 2026-06-03 改造：获取多张图片用于轮播
      if (data.success && data.data?.photo_urls && data.data.photo_urls.length > 0) {
        venuePhotos[item.venue_name] = data.data.photo_urls
        currentPhotoIndex[item.venue_name] = 0
      }
    } catch (e) {
      console.warn(`获取图片失败: ${item.venue_name}`, e)
    }
  }
}

// 轮播控制
function nextPhoto(venueName: string) {
  const photos = venuePhotos[venueName]
  if (!photos || photos.length <= 1) return
  currentPhotoIndex[venueName] = (currentPhotoIndex[venueName] + 1) % photos.length
}

function prevPhoto(venueName: string) {
  const photos = venuePhotos[venueName]
  if (!photos || photos.length <= 1) return
  currentPhotoIndex[venueName] = (currentPhotoIndex[venueName] - 1 + photos.length) % photos.length
}

// ============================================================================
// 方法：排队查询
// ============================================================================

async function checkQueue(item: any) {
  const name = item.venue_name
  if (!name) return

  queueLoading[name] = true
  try {
    const res = await fetch('/api/activity/check-queue', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        restaurant_name: name,
        city: plan.value?.city || '',
      }),
    })
    const data = await res.json()
    if (data.success) {
      queueResults[name] = data.data
    } else {
      queueResults[name] = { message: '查询失败: ' + (data.message || '未知错误'), queue_length: -1 }
    }
  } catch (e: any) {
    queueResults[name] = { message: '查询异常: ' + e.message, queue_length: -1 }
  } finally {
    queueLoading[name] = false
  }
}

// ============================================================================
// 方法：执行动作
// ============================================================================

async function executeSingleAction(action: any) {
  isExecuting.value = true
  markActionProcessing(action)

  try {
    const res = await fetch('/api/activity/execute', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        plan_id: plan.value?.plan_id || 'unknown',
        plan: plan.value,
        action_ids: [action.action_id],
        contact_name: contactName.value || '用户',
        contact_phone: contactPhone.value || '',
      }),
    })

    const data = await res.json()

    if (data.results && data.results.length > 0) {
      executedActions[action.action_id] = data.results[0]
    }
  } catch (e: any) {
    const now = new Date().toISOString()
    executedActions[action.action_id] = {
      action_id: action.action_id,
      action_type: action.action_type,
      description: action.description,
      status: 'failed',
      status_text: '执行异常',
      success: false,
      message: '执行异常: ' + e.message,
      completed_at: now,
      timeline: [
        { status: 'pending', text: '待确认', time: now, done: true },
        { status: 'processing', text: '执行中', time: now, done: true },
        { status: 'failed', text: '执行异常', time: now, done: true },
      ],
    }
  } finally {
    isExecuting.value = false
  }
}

function retryAction(action: any) {
  delete executedActions[action.action_id]
  executeSingleAction(action)
}

function useFallbackAction(action: any) {
  const state = getActionState(action)
  const fallback = state.fallback_action
  if (!fallback || !plan.value?.executable_actions) return

  const index = plan.value.executable_actions.findIndex((item: any) => item.action_id === action.action_id)
  if (index === -1) return

  const normalizedFallback = {
    ...fallback,
    action_id: fallback.action_id || `${action.action_id}_fallback`,
    is_optional: fallback.is_optional ?? action.is_optional,
    estimated_cost: fallback.estimated_cost ?? action.estimated_cost ?? 0,
  }

  plan.value.executable_actions.splice(index, 1, normalizedFallback)
  delete executedActions[action.action_id]
  executeSingleAction(normalizedFallback)
}

async function executeAllActions() {
  if (!plan.value?.executable_actions?.length) return

  isExecuting.value = true
  executionSummary.value = ''

  try {
    const pendingIds = plan.value.executable_actions
      .filter((a: any) => getActionState(a).status !== 'success')
      .map((a: any) => a.action_id)

    if (pendingIds.length === 0) return

    plan.value.executable_actions
      .filter((a: any) => pendingIds.includes(a.action_id))
      .forEach((a: any) => markActionProcessing(a))

    const res = await fetch('/api/activity/execute', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        plan_id: plan.value.plan_id || 'unknown',
        plan: plan.value,
        action_ids: pendingIds,
        contact_name: contactName.value || '用户',
        contact_phone: contactPhone.value || '',
      }),
    })

    const data = await res.json()

    for (const result of data.results || []) {
      executedActions[result.action_id] = result
    }

    executionAllSuccess.value = data.all_success || false
    executionSummary.value = data.summary || data.message || ''

    if (!executionSummary.value) {
      const successCount = (data.results || []).filter((r: any) => r.success).length
      const totalCount = (data.results || []).length
      executionSummary.value = `已完成 ${successCount}/${totalCount} 项操作`
    }
  } catch (e: any) {
    const now = new Date().toISOString()
    for (const action of plan.value.executable_actions || []) {
      if (getActionState(action).status === 'processing') {
        executedActions[action.action_id] = {
          ...getActionState(action),
          status: 'failed',
          status_text: '执行异常',
          success: false,
          message: '执行异常: ' + e.message,
          completed_at: now,
          timeline: [
            { status: 'pending', text: '待确认', time: now, done: true },
            { status: 'processing', text: '执行中', time: now, done: true },
            { status: 'failed', text: '执行异常', time: now, done: true },
          ],
        }
      }
    }
    executionSummary.value = '执行异常: ' + e.message
    executionAllSuccess.value = false
  } finally {
    isExecuting.value = false
  }
}

// ============================================================================
// 方法：分享复制
// ============================================================================

async function copyShareText() {
  const text = shareTab.value === 'short' ? shareShortText.value : shareDetailedText.value

  try {
    await navigator.clipboard.writeText(text)
    copySuccess.value = true
    setTimeout(() => {
      copySuccess.value = false
    }, 2000)
  } catch {
    const textarea = document.createElement('textarea')
    textarea.value = text
    document.body.appendChild(textarea)
    textarea.select()
    document.execCommand('copy')
    document.body.removeChild(textarea)
    copySuccess.value = true
    setTimeout(() => {
      copySuccess.value = false
    }, 2000)
  }
}

// ============================================================================
// 方法：导航
// ============================================================================

function goBack() {
  router.push({ name: 'Home' })
}

// ============================================================================
// 生命周期
// ============================================================================

onMounted(() => {
  const planData = sessionStorage.getItem('activityPlan')
  const requestData = sessionStorage.getItem('activityRequest')

  if (planData) {
    try {
      plan.value = JSON.parse(planData)
      console.log('📋 加载方案:', plan.value)
    } catch (e) {
      console.error('解析方案失败:', e)
    }
  }

  if (requestData) {
    try {
      originalRequest.value = JSON.parse(requestData)
    } catch (e) {
      console.error('解析请求失败:', e)
    }
  }

  nextTick(() => {
    loadVenuePhotos()
  })
})
</script>

<style scoped>
/* ============================================================================
   全局变量
   ============================================================================ */
:root {
  /* 2026-06-04: 结果页整体改成美团式橙色本地生活风格 */
  --primary: #ff6a00;
  --primary-light: #ffb45c;
  --primary-bg: #fff7ed;
  --success: #10b981;
  --success-bg: #ecfdf5;
  --warning: #f59e0b;
  --warning-bg: #fffbeb;
  --danger: #ef4444;
  --text-primary: #111827;
  --text-secondary: #4b5563;
  --text-muted: #9ca3af;
  --border: #edf0f3;
  --bg-card: #ffffff;
  --bg-page: #f5f6f7;
  --shadow-sm: 0 1px 3px rgba(0, 0, 0, 0.08);
  --shadow-md: 0 4px 12px rgba(0, 0, 0, 0.1);
  --shadow-lg: 0 10px 30px rgba(0, 0, 0, 0.12);
  --radius-sm: 8px;
  --radius-md: 12px;
  --radius-lg: 16px;
}

/* ============================================================================
   页面
   ============================================================================ */
.result-page {
  min-height: 100vh;
  background: var(--bg-page);
  padding-bottom: 92px;
}

/* ============================================================================
   摘要卡片
   ============================================================================ */
.summary-card {
  background:
    linear-gradient(180deg, rgba(255, 138, 0, 0.16), rgba(245, 246, 247, 0)),
    #f5f6f7;
  color: var(--text-primary);
  padding: 14px 16px 0;
  position: relative;
}

.summary-shell {
  max-width: 960px;
  margin: 0 auto;
  padding: 16px;
  border-radius: 18px;
  background: #fff;
  box-shadow: var(--shadow-md);
  border: 1px solid rgba(255, 106, 0, 0.08);
}

.summary-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.back-btn {
  background: #f8fafc;
  border: 1px solid var(--border);
  color: var(--text-secondary);
  padding: 7px 12px;
  border-radius: 999px;
  font-size: 13px;
  cursor: pointer;
  transition: background 0.2s;
}

.back-btn:hover {
  background: var(--primary-bg);
  color: var(--primary);
}

.summary-status {
  padding: 4px 10px;
  border-radius: 999px;
  background: #ecfdf5;
  color: #047857;
  font-size: 12px;
  font-weight: 700;
}

.summary-status.warn {
  background: #fff7ed;
  color: #c2410c;
}

.summary-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.summary-title {
  font-size: 22px;
  font-weight: 800;
  letter-spacing: 0;
}

.summary-title .emoji {
  font-size: 24px;
}

.summary-subtitle {
  margin: 4px 0 0;
  color: var(--text-secondary);
  font-size: 13px;
}

.summary-badge {
  padding: 6px 12px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 700;
  background: var(--primary-bg);
  color: var(--primary);
}

.summary-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

.meta-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border-radius: 999px;
  background: #f8fafc;
  font-size: 14px;
  color: var(--text-secondary);
}

.meta-item.timing {
  background: #fff7ed;
  color: #9a3412;
  font-weight: 700;
}

.meta-item.quality {
  background: #ecfdf5;
  color: #047857;
  font-weight: 700;
}

.meta-icon {
  font-size: 16px;
}

.summary-group {
  font-size: 14px;
  color: var(--text-secondary);
  margin-bottom: 12px;
}

.tips-banner {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 12px 14px;
  background: #fff7ed;
  color: #9a3412;
  border-radius: var(--radius-sm);
  font-size: 13px;
  line-height: 1.5;
}

.quality-banner {
  /* 2026-06-04: 规则质检未完全通过时，在摘要区轻量提示首个问题 */
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 10px;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: #fffbeb;
  color: #92400e;
  border: 1px solid #fde68a;
  font-size: 13px;
  line-height: 1.5;
}

/* 2026-06-04: 记忆命中提示，让用户能看到本次方案为什么“更懂我” */
.memory-hit-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: #fff7ed;
  border: 1px solid #fed7aa;
  color: #9a3412;
  font-size: 13px;
  line-height: 1.5;
  font-weight: 700;
}

.memory-hit-icon {
  width: 24px;
  height: 24px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: #ffedd5;
  flex: 0 0 auto;
}

.tips-icon {
  font-size: 16px;
  flex-shrink: 0;
}

/* ============================================================================
   2026-06-04: 美团式一键执行确认条
   ============================================================================ */
.checkout-strip {
  max-width: 960px;
  margin: 12px auto 0;
  padding: 0 16px;
  position: relative;
  z-index: 11;
  display: flex;
  align-items: stretch;
  gap: 12px;
}

.checkout-main {
  flex: 1;
  padding: 16px;
  border-radius: var(--radius-md);
  background: #ffffff;
  box-shadow: var(--shadow-sm);
  border: 1px solid #fed7aa;
}

.checkout-title-row {
  display: flex;
  gap: 12px;
  align-items: center;
}

.checkout-icon {
  width: 40px;
  height: 40px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  border-radius: 12px;
  background: #fff7ed;
  font-size: 20px;
}

.checkout-title-row h2 {
  margin: 0 0 4px;
  font-size: 18px;
  color: var(--text-primary);
}

.checkout-title-row p {
  margin: 0;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.4;
}

.checkout-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.checkout-stats span {
  padding: 4px 10px;
  border-radius: 999px;
  background: #f8fafc;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 600;
}

.checkout-primary-btn {
  min-width: 176px;
  padding: 0 18px;
  border: none;
  border-radius: var(--radius-md);
  background: linear-gradient(135deg, #ff8a00, #ff5a1f);
  color: #fff;
  font-size: 16px;
  font-weight: 800;
  cursor: pointer;
  box-shadow: 0 10px 24px rgba(255, 90, 31, 0.28);
  transition: transform 0.2s, box-shadow 0.2s, opacity 0.2s;
}

.checkout-primary-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 14px 30px rgba(255, 90, 31, 0.34);
}

.checkout-primary-btn:disabled {
  opacity: 0.65;
  cursor: wait;
}

/* 2026-06-05: 异常预案展示，覆盖无座、无票、时间冲突和天气不适合四类比赛故障。 */
.exception-strip {
  max-width: 960px;
  margin: 12px auto 0;
  padding: 14px 16px;
  border-radius: var(--radius-md);
  background: #fff7ed;
  border: 1px solid #fed7aa;
  box-shadow: var(--shadow-sm);
}

.exception-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
  color: #9a3412;
  font-weight: 800;
}

.exception-head small {
  color: #c2410c;
  font-weight: 700;
}

.exception-list {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.exception-item {
  padding: 10px;
  border-radius: 8px;
  background: #fff;
  border: 1px solid #ffedd5;
}

.exception-item.active {
  border-color: #fb923c;
  background: #fff7ed;
}

.exception-item strong {
  display: block;
  margin-bottom: 4px;
  color: var(--text-primary);
  font-size: 13px;
}

.exception-item span {
  display: block;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.45;
}

/* ============================================================================
   预算
   ============================================================================ */
.overview-grid {
  max-width: 960px;
  margin: 12px auto 0;
  padding: 0 16px;
  display: grid;
  grid-template-columns: minmax(280px, 0.8fr) minmax(360px, 1.2fr);
  gap: 12px;
  align-items: stretch;
}

.budget-card {
  background: var(--bg-card);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-sm);
  padding: 16px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 14px;
  border: 1px solid var(--border);
}

.budget-total {
  text-align: left;
  flex-shrink: 0;
}

.budget-label {
  display: block;
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 4px;
}

.budget-amount {
  font-size: 32px;
  font-weight: 800;
  color: var(--primary);
}

.budget-breakdown {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.budget-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  padding: 8px 10px;
  border-radius: var(--radius-sm);
  background: #f8fafc;
  font-size: 14px;
}

.budget-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.budget-dot.play { background: #8b5cf6; }
.budget-dot.eat { background: #f59e0b; }
.budget-dot.transport { background: #3b82f6; }
.budget-dot.extra { background: #10b981; }

.budget-name {
  color: var(--text-secondary);
}

.budget-val {
  font-weight: 600;
  color: var(--text-primary);
}

/* ============================================================================
   地图区域
   ============================================================================ */
.map-section {
  margin: 0;
  padding: 0;
}

.map-section.compact {
  padding: 14px;
  border-radius: var(--radius-md);
  background: #fff;
  box-shadow: var(--shadow-sm);
  border: 1px solid var(--border);
}

.compact-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
}

.compact-section-head h2 {
  margin: 0;
  font-size: 16px;
  color: var(--text-primary);
}

.compact-section-head span {
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 700;
}

.map-legend {
  display: flex;
  gap: 16px;
  justify-content: center;
  margin-top: 12px;
  font-size: 13px;
  color: var(--text-secondary);
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 6px;
}

.legend-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}

.legend-dash {
  width: 20px;
  height: 0;
  border-top: 3px dashed #4f46e5;
}

/* ============================================================================
   时间轴
   ============================================================================ */
.timeline-section {
  max-width: 960px;
  margin: 18px auto 0;
  padding: 0 16px;
}

.section-heading-row {
  /* 2026-06-04: 路线区改成列表页标题行，方便承接美团式商户卡 */
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.section-title {
  font-size: 20px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 0;
}

.section-desc {
  font-size: 14px;
  color: var(--text-secondary);
  margin-top: -12px;
  margin-bottom: 20px;
}

.section-desc.compact {
  margin: 5px 0 0;
  font-size: 13px;
}

.section-count {
  padding: 5px 10px;
  border-radius: 999px;
  background: #fff7ed;
  color: #c2410c;
  font-size: 12px;
  font-weight: 800;
  white-space: nowrap;
}

.timeline {
  position: relative;
}

.timeline-item {
  display: flex;
  gap: 16px;
  margin-bottom: 10px;
}

.timeline-left {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 60px;
  flex-shrink: 0;
}

.timeline-time {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 6px;
  white-space: nowrap;
}

.timeline-icon {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  flex-shrink: 0;
  z-index: 2;
}

.timeline-icon.transport { background: #dbeafe; }
.timeline-icon.play { background: #ede9fe; }
.timeline-icon.eat { background: #fef3c7; }
.timeline-icon.extra { background: #d1fae5; }

.timeline-line {
  width: 2px;
  flex: 1;
  min-height: 20px;
  background: var(--border);
  margin-top: 6px;
}

/* ============================================================================
   时间轴卡片
   ============================================================================ */
.timeline-card {
  flex: 1;
  min-width: 0;
  background: var(--bg-card);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
  border: 1px solid var(--border);
  transition: box-shadow 0.2s, transform 0.2s, border-color 0.2s;
}

.timeline-card:hover {
  box-shadow: var(--shadow-md);
  border-color: #fed7aa;
  transform: translateY(-1px);
}

.timeline-card.transport { border-color: #dbeafe; }
.timeline-card.play { border-color: #ffedd5; }
.timeline-card.eat { border-color: #fed7aa; }
.timeline-card.extra { border-color: #d1fae5; }

/* 交通卡片 */
.transport-card {
  padding: 12px 14px;
  background: linear-gradient(135deg, #f8fbff, #ffffff);
}

.transport-info {
  display: flex;
  align-items: center;
  gap: 12px;
}

.transport-mode {
  font-size: 14px;
  font-weight: 600;
  color: #3b82f6;
}

.transport-duration {
  font-size: 13px;
  color: var(--text-muted);
}

.transport-title {
  font-size: 13px;
  color: var(--text-secondary);
  margin-top: 4px;
}

/* 2026-06-04: 图片区收成商户列表缩略图，不再占据整张卡高度 */
.card-image {
  float: left;
  width: 152px;
  height: 118px;
  max-height: none;
  min-height: 0;
  margin: 14px 0 14px 14px;
  overflow: hidden;
  position: relative;
  background: linear-gradient(135deg, #fff7ed, #f8fafc);
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
}

.card-image img {
  width: 100%;
  height: 100%;
  max-width: none;
  max-height: none;
  object-fit: cover;
  transition: transform 0.3s ease;
  cursor: pointer;
}

.card-image:hover img {
  transform: scale(1.03);
}

/* 轮播箭头 */
.carousel-arrow {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: none;
  background: rgba(0,0,0,0.4);
  color: white;
  font-size: 18px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.2s;
  z-index: 5;
}

.carousel-arrow:hover {
  background: rgba(0,0,0,0.6);
}

.carousel-prev { left: 8px; }
.carousel-next { right: 8px; }

/* 轮播指示点 */
.carousel-dots {
  position: absolute;
  bottom: 8px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  gap: 6px;
  z-index: 5;
}

.carousel-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: rgba(255,255,255,0.5);
  cursor: pointer;
  transition: all 0.2s;
}

.carousel-dot.active {
  background: white;
  width: 20px;
  border-radius: 4px;
}

/* 图片计数 */
.carousel-count {
  position: absolute;
  top: 8px;
  left: 8px;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(0,0,0,0.4);
  color: white;
  font-size: 11px;
  z-index: 5;
}

.card-image.placeholder {
  background: linear-gradient(135deg, #fff7ed, #ffedd5);
}

.placeholder-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.placeholder-icon {
  font-size: 28px;
  opacity: 0.9;
}

.placeholder-text {
  max-width: 120px;
  font-size: 12px;
  line-height: 1.35;
  color: #9a3412;
  text-align: center;
}

.card-type-badge {
  position: absolute;
  top: 7px;
  right: 7px;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  color: white;
  backdrop-filter: blur(4px);
}

.card-type-badge.play { background: rgba(255, 106, 0, 0.92); }
.card-type-badge.eat { background: rgba(245, 158, 11, 0.94); }
.card-type-badge.extra { background: rgba(16, 185, 129, 0.9); }

/* 卡片主体 */
.card-body {
  min-height: 146px;
  padding: 14px 16px 14px 180px;
}

.card-body::after {
  content: "";
  display: block;
  clear: both;
}

.merchant-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 6px;
}

.merchant-head > div:first-child {
  min-width: 0;
}

.merchant-side {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 8px;
  flex: 0 0 auto;
}

.card-title {
  font-size: 17px;
  font-weight: 800;
  color: var(--text-primary);
  margin-bottom: 3px;
  line-height: 1.35;
}

.merchant-subtitle {
  margin: 0;
  font-size: 12px;
  color: var(--text-muted);
}

.merchant-price {
  flex-shrink: 0;
  color: #ff5a1f;
  font-size: 20px;
  font-weight: 900;
  line-height: 1.1;
}

.merchant-price.free {
  padding: 4px 8px;
  border-radius: 999px;
  background: #ecfdf5;
  color: #047857;
  font-size: 12px;
}

/* 2026-06-04: 商户卡新增“换一个”，像本地生活 App 换推荐项一样可协商 */
.replace-btn {
  border: 1px solid #fed7aa;
  background: #fff7ed;
  color: #ea580c;
  border-radius: 999px;
  padding: 6px 12px;
  font-size: 12px;
  font-weight: 800;
  cursor: pointer;
}

.replace-btn:hover:not(:disabled) {
  background: #ffedd5;
  border-color: #fb923c;
}

.replace-btn:disabled {
  opacity: 0.55;
  cursor: wait;
}

.card-desc {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.5;
  margin-bottom: 8px;
}

.card-venue {
  margin-bottom: 8px;
  padding: 8px 10px;
  border-radius: 10px;
  background: #f8fafc;
}

.venue-name {
  font-size: 13px;
  font-weight: 800;
  color: var(--text-primary);
}

.venue-address {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 2px;
}

.card-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
}

.meta-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 500;
}

.meta-tag.time {
  background: #fff7ed;
  color: #9a3412;
}

.meta-tag.cost {
  background: #fff1e6;
  color: #c2410c;
}

.meta-tag.cost.free {
  background: #ecfdf5;
  color: #047857;
}

.tag {
  padding: 3px 9px;
  border-radius: 999px;
  font-size: 11px;
  background: #fff7ed;
  color: #c2410c;
  font-weight: 700;
}

/* 2026-06-04: 覆盖旧标签样式，保证路线卡统一为本地生活橙色体系 */
.timeline-card .tag {
  background: #fff7ed;
  color: #c2410c;
}

.timeline-card .meta-tag.time {
  background: #fff7ed;
  color: #9a3412;
}

.timeline-card .meta-tag.cost {
  background: #fff1e6;
  color: #c2410c;
}

.timeline-card .meta-tag.cost.free {
  background: #ecfdf5;
  color: #047857;
}

/*
  2026-06-04: 保留旧选择器入口，但同步为美团橙色，避免后续覆盖回紫色/灰色。
*/
.meta-tag.time {
  background: #fff7ed;
  color: #9a3412;
}

.meta-tag.cost {
  background: #fff1e6;
  color: #c2410c;
}

.meta-tag.cost.free {
  background: #ecfdf5;
  color: #047857;
}

.card-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 10px;
}

.tag {
  padding: 3px 9px;
  border-radius: 999px;
  font-size: 11px;
  background: #fff7ed;
  color: #c2410c;
  font-weight: 700;
}

/* 餐厅信息 */
.restaurant-info {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed var(--border);
}

.rest-features {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
}

.rest-feature {
  font-size: 12px;
  color: var(--success);
}

.rest-meta {
  display: flex;
  gap: 12px;
  font-size: 13px;
  color: var(--text-secondary);
  margin-bottom: 8px;
}

.queue-status {
  font-weight: 600;
}

.queue-status.good { color: var(--success); }
.queue-status.okay { color: var(--warning); }
.queue-status.busy { color: var(--danger); }

.check-queue-btn {
  padding: 6px 14px;
  border: 1.5px solid var(--border);
  border-radius: var(--radius-sm);
  background: white;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
  color: var(--text-secondary);
}

.check-queue-btn:hover:not(:disabled) {
  border-color: var(--primary);
  color: var(--primary);
  background: var(--primary-bg);
}

.check-queue-btn:disabled {
  opacity: 0.5;
  cursor: wait;
}

.queue-result {
  margin-top: 8px;
  font-size: 13px;
  padding: 8px 12px;
  border-radius: var(--radius-sm);
  background: #f8fafc;
}

.queue-result .good { color: var(--success); }
.queue-result .warn { color: var(--warning); }

/* 可预订 */
.booking-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 10px;
  padding: 8px 12px;
  background: var(--primary-bg);
  border-radius: var(--radius-sm);
  font-size: 13px;
  color: var(--primary);
  font-weight: 500;
}

/* 2026-06-04: 每条推荐支持自然语言反馈，后端解析后进入 SQLite 和 Neo4j 图谱记忆 */
.memory-feedback {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed var(--border);
}

.feedback-toggle {
  border: 0;
  background: transparent;
  color: #ea580c;
  font-weight: 700;
  cursor: pointer;
  padding: 0;
}

.feedback-panel {
  margin-top: 10px;
  padding: 10px;
  border: 1px solid #fed7aa;
  border-radius: var(--radius-sm);
  background: #fff7ed;
}

.feedback-input {
  width: 100%;
  resize: vertical;
  min-height: 52px;
  border: 1px solid #fdba74;
  border-radius: var(--radius-sm);
  padding: 9px 10px;
  font-size: 13px;
  color: var(--text-primary);
  background: #fff;
}

.feedback-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
  align-items: center;
}

.feedback-chip {
  border: 1px solid #fed7aa;
  background: #fff;
  color: #9a3412;
  border-radius: 999px;
  padding: 5px 9px;
  font-size: 12px;
  cursor: pointer;
}

.feedback-submit {
  margin-left: auto;
  border: 0;
  background: #ff6a00;
  color: #fff;
  border-radius: var(--radius-sm);
  padding: 6px 12px;
  font-weight: 800;
  cursor: pointer;
}

.feedback-submit:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

/* ============================================================================
   可执行动作
   ============================================================================ */
.actions-section {
  max-width: 720px;
  margin: 32px auto 0;
  padding: 0 16px;
}

/* 2026-06-04: 美团式执行清单头部，强调待确认和待执行数量 */
.actions-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.actions-header .section-title {
  text-align: left;
  margin-bottom: 6px;
}

.actions-total {
  min-width: 86px;
  padding: 10px 12px;
  border-radius: var(--radius-md);
  background: #fff7ed;
  color: #9a3412;
  text-align: center;
  font-size: 12px;
  font-weight: 700;
}

.actions-total strong {
  display: block;
  margin: 2px 0;
  font-size: 24px;
  line-height: 1;
}

.checkout-contact {
  margin-bottom: 12px;
  padding: 14px;
  border-radius: var(--radius-md);
  background: #ffffff;
  box-shadow: var(--shadow-sm);
  border: 1px solid var(--border);
}

.checkout-contact-title {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 10px;
  color: var(--text-primary);
  font-size: 14px;
}

.actions-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 20px;
}

.action-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  background: var(--bg-card);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-sm);
  border: 1px solid var(--border);
  transition: border-color 0.2s, box-shadow 0.2s;
  flex-wrap: wrap;
}

.action-card:hover {
  border-color: #fed7aa;
  box-shadow: var(--shadow-md);
}

.action-card.optional {
  border: 2px dashed var(--border);
}

.action-card.executed {
  background: #f0fdf4;
  border-color: #bbf7d0;
}

.action-card.processing {
  background: #fff7ed;
  border-color: #fed7aa;
}

.action-card.failed {
  background: #fef2f2;
  border-color: #fecaca;
}

.action-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  min-width: 0;
}

.action-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 38px;
  border-radius: 12px;
  background: #f8fafc;
  font-size: 22px;
  flex-shrink: 0;
}

.action-info {
  min-width: 0;
}

.action-desc {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1.4;
}

.action-type-label {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 2px;
}

.action-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.action-cost {
  font-size: 15px;
  font-weight: 700;
  color: #ea580c;
}

.action-optional-tag {
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  background: #fef3c7;
  color: #b45309;
}

.action-exec-btn {
  padding: 8px 16px;
  border: none;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 700;
  color: white;
  cursor: pointer;
  transition: all 0.2s;
}

.action-exec-btn.book_restaurant { background: #ff8a00; }
.action-exec-btn.book_activity { background: #ff5a1f; }
.action-exec-btn.order_delivery { background: #10b981; }
.action-exec-btn.check_queue { background: #2563eb; }

.action-exec-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  filter: brightness(1.1);
}

.action-exec-btn:disabled {
  opacity: 0.5;
  cursor: wait;
}

.action-result {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
}

.result-badge {
  padding: 4px 12px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
}

.result-badge.success {
  background: var(--success-bg);
  color: var(--success);
}

.result-badge.processing {
  background: #fff7ed;
  color: #c2410c;
}

.result-badge.fail {
  background: #fef2f2;
  color: var(--danger);
}

.result-msg {
  font-size: 11px;
  color: var(--text-muted);
}

/* 2026-06-04: 订单状态流转，展示待确认 -> 执行中 -> 成功/失败 */
.order-timeline {
  width: 100%;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  padding: 10px 0 0 50px;
  border-top: 1px dashed var(--border);
}

.order-node {
  position: relative;
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  color: var(--text-muted);
  font-size: 12px;
}

.order-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: #d1d5db;
  flex-shrink: 0;
}

.order-node.done {
  color: var(--text-secondary);
  font-weight: 700;
}

.order-node.done .order-dot {
  background: var(--success);
}

.order-node.processing .order-dot {
  background: #ff8a00;
  box-shadow: 0 0 0 4px rgba(255, 138, 0, 0.14);
}

.order-node.failed {
  color: var(--danger);
}

.order-node.failed .order-dot {
  background: var(--danger);
}

.order-text {
  white-space: nowrap;
}

.order-time {
  color: var(--text-muted);
  font-weight: 500;
  white-space: nowrap;
}

.retry-panel {
  width: 100%;
  margin-left: 50px;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: #fff7ed;
  border: 1px solid #fed7aa;
}

.retry-reason {
  margin: 0 0 10px;
  color: #9a3412;
  font-size: 13px;
  line-height: 1.5;
}

.retry-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.retry-btn {
  padding: 7px 14px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 800;
  cursor: pointer;
  transition: all 0.2s;
}

.retry-btn.secondary {
  border: 1px solid #fed7aa;
  background: #fff;
  color: #9a3412;
}

.retry-btn.primary {
  border: none;
  background: linear-gradient(135deg, #ff8a00, #ff5a1f);
  color: #fff;
  box-shadow: 0 6px 14px rgba(255, 90, 31, 0.2);
}

.retry-btn:disabled {
  opacity: 0.55;
  cursor: wait;
}

/* 批量执行 */
.batch-execute {
  text-align: center;
  margin-top: 18px;
}

.contact-row {
  display: flex;
  gap: 12px;
  max-width: none;
  margin: 0;
}

.contact-input {
  flex: 1;
  padding: 10px 14px;
  border: 2px solid var(--border);
  border-radius: var(--radius-sm);
  font-size: 14px;
  box-sizing: border-box;
  background: #f8fafc;
}

.contact-input:focus {
  outline: none;
  border-color: var(--primary);
}

.batch-exec-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  width: 100%;
  max-width: none;
  padding: 16px 32px;
  border: none;
  border-radius: var(--radius-md);
  background: linear-gradient(135deg, #ff8a00, #ff5a1f);
  color: white;
  font-size: 17px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.3s;
  box-shadow: 0 8px 20px rgba(255, 90, 31, 0.28);
}

.batch-exec-btn:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 12px 28px rgba(255, 90, 31, 0.34);
}

.batch-exec-btn:disabled {
  opacity: 0.5;
  cursor: wait;
}

.spinner {
  width: 18px;
  height: 18px;
  border: 3px solid rgba(255, 255, 255, 0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

.spinner.dark {
  border-color: rgba(255, 255, 255, 0.35);
  border-top-color: #ffffff;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 执行摘要 */
.exec-summary {
  margin-top: 20px;
}

.summary-content {
  padding: 16px 20px;
  border-radius: var(--radius-md);
  text-align: center;
}

.summary-content.success {
  background: var(--success-bg);
  color: #065f46;
}

.summary-content.partial {
  background: var(--warning-bg);
  color: #78350f;
}

.summary-content h4 {
  font-size: 18px;
  margin-bottom: 6px;
}

.summary-content p {
  font-size: 14px;
  line-height: 1.5;
}

/* ============================================================================
   分享区域
   ============================================================================ */
.share-section {
  max-width: 720px;
  margin: 32px auto 0;
  padding: 0 16px;
}

.share-tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.share-tab {
  padding: 8px 18px;
  border: 2px solid var(--border);
  border-radius: 999px;
  background: white;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
  color: var(--text-secondary);
}

.share-tab.active {
  border-color: var(--primary);
  background: var(--primary-bg);
  color: var(--primary);
  font-weight: 600;
}

.share-content {
  background: var(--bg-card);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}

.share-text-box {
  padding: 20px;
  max-height: 300px;
  overflow-y: auto;
}

.share-text {
  margin: 0;
  font-family: inherit;
  font-size: 14px;
  line-height: 1.7;
  color: var(--text-primary);
  white-space: pre-wrap;
  word-break: break-word;
}

.copy-btn {
  display: block;
  width: 100%;
  padding: 14px;
  border: none;
  border-top: 1px solid var(--border);
  background: #fafbfc;
  font-size: 15px;
  font-weight: 600;
  color: var(--primary);
  cursor: pointer;
  transition: background 0.2s;
}

.copy-btn:hover {
  background: var(--primary-bg);
}

/* ============================================================================
   底部操作栏
   ============================================================================ */
.bottom-bar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  padding: 10px 16px 12px;
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(10px);
  border-top: 1px solid var(--border);
  box-shadow: 0 -8px 26px rgba(15, 23, 42, 0.08);
  z-index: 100;
  max-width: 960px;
  margin: 0 auto;
}

.bottom-btn {
  flex: 1;
  min-width: 160px;
  min-height: 48px;
  padding: 13px 14px;
  border: none;
  border-radius: 999px;
  font-size: 15px;
  font-weight: 800;
  cursor: pointer;
  transition: all 0.2s;
}

/* 2026-06-04: 底部确认栏改为本地生活下单页风格，统一橙色主按钮 */
.bottom-btn.primary {
  background: linear-gradient(135deg, #ff8a00, #ff5a1f);
  color: white;
  box-shadow: 0 8px 18px rgba(255, 90, 31, 0.28);
}

.bottom-btn.primary:hover {
  transform: translateY(-1px);
  box-shadow: 0 10px 22px rgba(255, 90, 31, 0.34);
}

.bottom-btn.secondary {
  background: #f8fafc;
  color: var(--text-secondary);
  border: 1px solid var(--border);
}

.bottom-btn.secondary:hover {
  background: #e2e8f0;
}

.bottom-btn.rethink {
  background: #fff7ed;
  color: #ea580c;
  border: 1px solid #fed7aa;
}

.bottom-btn.rethink:hover:not(:disabled) {
  background: #ffedd5;
}

/* ============================================================================
   空状态
   ============================================================================ */
.empty-state {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-page);
}

.empty-content {
  text-align: center;
  padding: 40px;
}

.empty-icon {
  font-size: 64px;
  display: block;
  margin-bottom: 20px;
}

.empty-content h2 {
  font-size: 22px;
  color: var(--text-primary);
  margin-bottom: 8px;
}

.empty-content p {
  font-size: 15px;
  color: var(--text-secondary);
  margin-bottom: 24px;
}

.empty-btn {
  padding: 12px 32px;
  border: none;
  border-radius: var(--radius-md);
  background: linear-gradient(135deg, #ff8a00, #ff5a1f);
  color: white;
  font-size: 16px;
  font-weight: 700;
  cursor: pointer;
}

/* ============================================================================
   图片放大预览 (Lightbox)
   ============================================================================ */

.lightbox {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.85);
  backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 20px;
  cursor: zoom-out;
  animation: fadeIn 0.2s ease;
}

.lightbox-content {
  position: relative;
  max-width: 90vw;
  max-height: 90vh;
}

.lightbox-content img {
  max-width: 100%;
  max-height: 90vh;
  border-radius: var(--radius-md);
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
}

.lightbox-close {
  position: absolute;
  top: -16px;
  right: -16px;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  border: none;
  background: white;
  color: #333;
  font-size: 20px;
  cursor: pointer;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
  transition: transform 0.2s;
}

.lightbox-close:hover {
  transform: scale(1.1);
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

/* ============================================================================
   响应式
   ============================================================================ */
@media (max-width: 640px) {
  .result-page {
    padding-bottom: 104px;
  }

  .summary-card {
    padding: 10px 10px 0;
  }

  .summary-shell {
    padding: 14px;
    border-radius: 14px;
  }

  .summary-header {
    align-items: flex-start;
  }

  .summary-title {
    font-size: 20px;
  }

  .checkout-strip {
    flex-direction: column;
    margin-top: 10px;
    padding: 0 10px;
  }

  .checkout-primary-btn {
    min-height: 52px;
    width: 100%;
  }

  .exception-strip {
    margin-top: 10px;
    padding: 12px 10px;
  }

  .exception-list {
    grid-template-columns: 1fr;
  }

  .overview-grid {
    grid-template-columns: 1fr;
    padding: 0 10px;
  }

  .map-section.compact :deep(.plan-map),
  .map-section.compact :deep(.map-container) {
    height: 190px;
  }

  .timeline-section,
  .actions-section,
  .share-section {
    padding: 0 10px;
  }

  .section-heading-row {
    align-items: flex-start;
  }

  .actions-header {
    flex-direction: column;
  }

  .actions-total {
    width: 100%;
  }

  .summary-meta {
    flex-direction: column;
    gap: 8px;
  }

  /* 2026-06-04: 小屏回到上图下文，避免商户横卡挤压正文 */
  .card-image {
    float: none;
    width: calc(100% - 24px);
    height: 156px;
    margin: 12px;
    max-height: none;
  }

  .card-image img {
    max-height: none;
  }

  .card-body {
    min-height: 0;
    padding: 0 14px 14px;
  }

  .merchant-head {
    gap: 8px;
  }

  .merchant-price {
    font-size: 17px;
  }

  .timeline-left {
    width: 50px;
  }

  .timeline-time {
    font-size: 12px;
  }

  .action-card {
    flex-direction: column;
    align-items: stretch;
  }

  .action-right {
    justify-content: flex-end;
    margin-top: 8px;
  }

  .order-timeline {
    grid-template-columns: 1fr;
    padding-left: 0;
  }

  .retry-panel {
    margin-left: 0;
  }

  .contact-row {
    flex-direction: column;
  }

  .bottom-bar {
    max-width: 100%;
    padding: 10px;
    gap: 8px;
  }

  .bottom-btn {
    min-height: 46px;
    font-size: 14px;
  }

  .map-legend {
    flex-wrap: wrap;
    gap: 10px;
  }
}
</style>
