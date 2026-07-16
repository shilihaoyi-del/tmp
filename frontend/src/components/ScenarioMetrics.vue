<script setup lang="ts">
import { onMounted, ref } from 'vue'

export interface Scenario {
  id: string
  name: string
  summary: string
  module_value: string[]
  metrics_focus: string[]
  bench_ready?: boolean
}

export interface MetricsSnap {
  uptime_sec: number
  ready_for: string[]
  traffic: {
    pc_cmd_total: number
    pc_cmd_forwarded: number
    pc_cmd_dropped: number
    forward_hz: number
    device_status_total: number
  }
  latency: {
    avg_ms: number
    p50_ms: number
    p95_ms: number
    max_ms: number
  }
  bench: {
    active: boolean
    bench_id: string | null
    reserved: boolean
  }
}

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

const scenarios = ref<Scenario[]>([])
const metrics = ref<MetricsSnap | null>(null)
const offline = ref(false)

async function refresh() {
  try {
    const [sRes, mRes] = await Promise.all([
      fetch(`${API_BASE}/api/metrics/scenarios`),
      fetch(`${API_BASE}/api/metrics`),
    ])
    if (!sRes.ok || !mRes.ok) throw new Error('metrics_unreachable')
    const sJson = await sRes.json()
    const mJson = (await mRes.json()) as MetricsSnap
    scenarios.value = sJson.scenarios ?? []
    metrics.value = mJson
    offline.value = false
  } catch {
    offline.value = true
    // static fallback so UI still narrates scenarios without backend
    scenarios.value = [
      {
        id: 'remote_embodied_demo',
        name: '远程体感跟随演示',
        summary: '展会/比赛：手势意图经公网到达 SC171V2，驱动机械臂同步跟随。',
        module_value: ['5G/Wi-Fi 公网接入', '低时延指令通道', '边缘安全保持'],
        metrics_focus: ['latency_ms', 'forward_hz', 'hb_age_ms'],
      },
      {
        id: 'industrial_teleop',
        name: '工业远程遥操作',
        summary: '产线/危化：异地遥操作，模组保障链路可靠与断线保持。',
        module_value: ['多模网络冗余', 'TTL/心跳失效保护', '状态遥测回传'],
        metrics_focus: ['pc_cmd_dropped', 'p95_ms'],
      },
      {
        id: 'cloud_robot_link',
        name: '云边机器人接入',
        summary: 'SC171V2 作为边缘控制面，快速把执行体挂上云控。',
        module_value: ['边缘智能模组', 'MQTT 会话', '执行器下游桥接'],
        metrics_focus: ['device_status_total', 'mqtt_error_total'],
      },
      {
        id: 'soak_and_stress',
        name: '长稳 / 压力验证（预留）',
        summary: '后续对 20–30Hz 指令流、并发观摩、弱网做压测基线。',
        module_value: ['链路容量验证', '抖动与丢包可视', '模组在线率'],
        metrics_focus: ['forward_hz', 'p95_ms'],
        bench_ready: true,
      },
    ]
  }
}

onMounted(() => {
  void refresh()
  window.setInterval(() => void refresh(), 3000)
})
</script>

<template>
  <div class="panel">
    <div class="panel-header">
      <span>APPLICATION SCENARIOS // METRICS HOOK</span>
      <span>{{ offline ? 'LOCAL_FALLBACK' : 'LIVE' }}</span>
    </div>
    <div class="panel-body">
      <p class="comment">
        fibocom sc171v2 fits remote teleop / cloud-robot link / showfloor demo — metrics APIs reserved for stress &amp; perf
      </p>

      <div class="scenario-grid">
        <article v-for="s in scenarios" :key="s.id" class="scenario">
          <div class="sid">[{{ s.id.toUpperCase() }}]</div>
          <h3>{{ s.name }}</h3>
          <p>{{ s.summary }}</p>
          <div class="vals">
            <span v-for="v in s.module_value" :key="v">{{ v }}</span>
          </div>
          <div v-if="s.bench_ready" class="bench-flag">[BENCH_READY]</div>
        </article>
      </div>

      <div class="metrics-box">
        <div class="m-head">
          <span>// reserved monitor · GET /api/metrics</span>
          <span v-if="metrics?.bench?.active" class="on">[BENCH: {{ metrics.bench.bench_id }}]</span>
          <span v-else>[BENCH: IDLE]</span>
        </div>
        <div v-if="metrics" class="m-grid">
          <div>
            <span class="k">FWD_HZ</span>
            <span class="v">{{ metrics.traffic.forward_hz.toFixed(1) }}</span>
          </div>
          <div>
            <span class="k">P95_MS</span>
            <span class="v">{{ metrics.latency.p95_ms.toFixed(1) }}</span>
          </div>
          <div>
            <span class="k">CMD_OK</span>
            <span class="v">{{ metrics.traffic.pc_cmd_forwarded }}</span>
          </div>
          <div>
            <span class="k">CMD_DROP</span>
            <span class="v">{{ metrics.traffic.pc_cmd_dropped }}</span>
          </div>
          <div>
            <span class="k">UPTIME</span>
            <span class="v">{{ metrics.uptime_sec }}s</span>
          </div>
          <div>
            <span class="k">READY</span>
            <span class="v tiny">{{ (metrics.ready_for || []).join(' / ') }}</span>
          </div>
        </div>
        <p v-else class="comment">awaiting /api/metrics · endpoints reserved for stress_test / perf_test / soak_test</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.scenario-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-top: 14px;
}

.scenario {
  border: 1px solid var(--line);
  padding: 12px;
  background: #080808;
}

.sid {
  font-size: 10px;
  letter-spacing: 0.08em;
  color: var(--text-faint);
}

.scenario h3 {
  margin: 6px 0 8px;
  font-family: var(--display);
  font-size: 15px;
  font-weight: 500;
  letter-spacing: 0.04em;
}

.scenario p {
  margin: 0;
  color: var(--text-dim);
  font-size: 12px;
  line-height: 1.5;
}

.vals {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}

.vals span {
  border: 1px solid var(--line);
  padding: 2px 6px;
  font-size: 10px;
  color: var(--text-dim);
  letter-spacing: 0.04em;
}

.bench-flag {
  margin-top: 10px;
  color: var(--accent);
  font-size: 11px;
  letter-spacing: 0.08em;
}

.metrics-box {
  margin-top: 14px;
  border: 1px solid var(--line);
  padding: 12px;
}

.m-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  color: var(--text-faint);
  font-size: 11px;
  letter-spacing: 0.06em;
  margin-bottom: 12px;
}

.m-head .on {
  color: var(--accent);
}

.m-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.m-grid .k {
  display: block;
  font-size: 10px;
  color: var(--text-faint);
  letter-spacing: 0.08em;
}

.m-grid .v {
  font-family: var(--display);
  font-size: 18px;
  font-variant-numeric: tabular-nums;
}

.m-grid .tiny {
  font-size: 11px;
  color: var(--text-dim);
  word-break: break-all;
}

@media (max-width: 900px) {
  .scenario-grid,
  .m-grid {
    grid-template-columns: 1fr;
  }
}
</style>
