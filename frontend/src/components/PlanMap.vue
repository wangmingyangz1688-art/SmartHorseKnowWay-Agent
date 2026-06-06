<template>
  <div class="plan-map-wrapper">
    <div ref="mapContainer" class="map-container"></div>
    <div class="map-tip" v-if="overlappingWarning">
      ⚠️ 部分场所坐标相近，已自动偏移显示。实际位置请以地址为准。
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch, onUnmounted } from 'vue'
import AMapLoader from '@amap/amap-jsapi-loader'

// ============================================================================
// Props
// ============================================================================

interface MapPoint {
  name: string
  lng: number
  lat: number
  type: string
  order: number
}

const props = defineProps<{
  points: MapPoint[]
  city?: string
}>()

// ============================================================================
// 地图实例
// ============================================================================

const mapContainer = ref<HTMLDivElement>()
let mapInstance: any = null
let AMapLib: any = null
let markers: any[] = []
let polyline: any = null
const overlappingWarning = ref(false)

// ============================================================================
// 工具：检测并偏移重叠坐标
// ============================================================================

function deOverlapPoints(points: MapPoint[]): Array<MapPoint & { displayLng: number; displayLat: number }> {
  const THRESHOLD = 0.0005 // 约 50 米内视为重叠
  const OFFSET = 0.003     // 偏移约 300 米，地图上可见

  const result: Array<MapPoint & { displayLng: number; displayLat: number }> = []
  let hasOverlap = false

  for (let i = 0; i < points.length; i++) {
    const p = points[i]
    let displayLng = p.lng
    let displayLat = p.lat

    // 检查是否和前面的点重叠
    const overlapCount = result.filter(
      (prev) =>
        Math.abs(prev.displayLng - p.lng) < THRESHOLD &&
        Math.abs(prev.displayLat - p.lat) < THRESHOLD
    ).length

    if (overlapCount > 0) {
      hasOverlap = true
      // 按圆形方向偏移
      const angle = (overlapCount * Math.PI * 2) / 3 + Math.PI / 6
      displayLng = p.lng + OFFSET * Math.cos(angle)
      displayLat = p.lat + OFFSET * Math.sin(angle)
    }

    result.push({ ...p, displayLng, displayLat })
  }

  overlappingWarning.value = hasOverlap
  return result
}

// ============================================================================
// 初始化地图
// ============================================================================

async function initMap() {
  if (!mapContainer.value) return

  try {
    // @ts-ignore
    window._AMapSecurityConfig = {
      securityJsCode: import.meta.env.VITE_AMAP_SECURITY_CODE || '',
    }

    AMapLib = await AMapLoader.load({
      key: import.meta.env.VITE_AMAP_WEB_JS_KEY || '',
      version: '2.0',
      plugins: ['AMap.Scale'],
    })

    mapInstance = new AMapLib.Map(mapContainer.value, {
      zoom: 13,
      viewMode: '2D',
    })

    if (props.points.length > 0) {
      renderPoints(props.points)
    } else if (props.city) {
      mapInstance.setCity(props.city)
    }
  } catch (e) {
    console.error('❌ 高德地图加载失败:', e)
  }
}

// ============================================================================
// 渲染点位 + 路线
// ============================================================================

function renderPoints(points: MapPoint[]) {
  if (!mapInstance || !AMapLib || points.length === 0) return

  // 清除旧标记
  markers.forEach((m) => mapInstance.remove(m))
  markers = []
  if (polyline) {
    mapInstance.remove(polyline)
    polyline = null
  }

  const typeColorMap: Record<string, string> = {
    play: '#8b5cf6',
    eat: '#f59e0b',
    extra: '#10b981',
  }

  const typeIconMap: Record<string, string> = {
    play: '🎯',
    eat: '🍽️',
    extra: '✨',
  }

  // 处理重叠
  const displayPoints = deOverlapPoints(points)
  const totalPoints = displayPoints.length

  displayPoints.forEach((point, idx) => {
    const lngLat = new AMapLib.LngLat(point.displayLng, point.displayLat)
    const color = typeColorMap[point.type] || '#4f46e5'

    // 自定义标记
    const content = document.createElement('div')
    content.style.cssText = 'cursor:pointer;'
    content.innerHTML = `
      <div style="
        background: ${color};
        color: white;
        border-radius: 50%;
        width: 34px;
        height: 34px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 15px;
        font-weight: bold;
        box-shadow: 0 2px 8px rgba(0,0,0,0.35);
        border: 2.5px solid white;
        position: relative;
      ">${idx + 1}</div>
      <div style="
        font-size: 11px;
        color: #333;
        background: rgba(255,255,255,0.92);
        padding: 2px 6px;
        border-radius: 4px;
        white-space: nowrap;
        text-align: center;
        margin-top: 2px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.15);
        max-width: 120px;
        overflow: hidden;
        text-overflow: ellipsis;
      ">${point.name}</div>
    `

    const marker = new AMapLib.Marker({
      position: lngLat,
      content: content,
      offset: new AMapLib.Pixel(-17, -17),
      // 关键：让编号小的在上层，这样 1 不会被 2 盖住
      zIndex: 200 + (totalPoints - idx),
    })

    // 信息窗体
    const infoWindow = new AMapLib.InfoWindow({
      content: `
        <div style="padding:10px 14px;min-width:160px;">
          <strong>${typeIconMap[point.type] || '📍'} ${point.name}</strong>
          <div style="color:#666;font-size:12px;margin-top:4px;">
            第 ${idx + 1} 站 · ${point.type === 'play' ? '玩乐' : point.type === 'eat' ? '用餐' : '其他'}
          </div>
          ${overlappingWarning.value ? '<div style="color:#f59e0b;font-size:11px;margin-top:4px;">📍 地图位置仅供参考</div>' : ''}
        </div>
      `,
      offset: new AMapLib.Pixel(0, -22),
    })

    marker.on('click', () => {
      infoWindow.open(mapInstance, lngLat)
    })

    mapInstance.add(marker)
    markers.push(marker)
  })

  // 绘制连线
  if (displayPoints.length >= 2) {
    polyline = new AMapLib.Polyline({
      path: displayPoints.map((p) => new AMapLib.LngLat(p.displayLng, p.displayLat)),
      strokeColor: '#4f46e5',
      strokeWeight: 3,
      strokeOpacity: 0.6,
      strokeStyle: 'dashed',
      lineJoin: 'round',
    })
    mapInstance.add(polyline)
  }

  // 自适应视野
  if (markers.length > 0) {
    mapInstance.setFitView(markers, false, [80, 80, 80, 80])
  }
}

// ============================================================================
// 监听数据变化
// ============================================================================

watch(
  () => props.points,
  (newPoints) => {
    if (mapInstance && newPoints.length > 0) {
      renderPoints(newPoints)
    }
  },
  { deep: true }
)

// ============================================================================
// 生命周期
// ============================================================================

onMounted(() => {
  initMap()
})

onUnmounted(() => {
  if (mapInstance) {
    mapInstance.destroy()
    mapInstance = null
  }
})
</script>

<style scoped>
.plan-map-wrapper {
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.map-container {
  width: 100%;
  height: 360px;
}

.map-tip {
  padding: 8px 14px;
  background: #fffbeb;
  color: #92400e;
  font-size: 12px;
  text-align: center;
  border-top: 1px solid #fde68a;
}

@media (max-width: 640px) {
  .map-container {
    height: 260px;
  }
}
</style>
