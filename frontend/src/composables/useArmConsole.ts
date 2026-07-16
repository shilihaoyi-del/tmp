import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import mqtt, { type MqttClient } from 'mqtt'
import { defaultStatus, type ControlAction, type SystemStatus } from '@/types/arm'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''
const MQTT_URL =
  import.meta.env.VITE_MQTT_WS_URL ??
  `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.hostname}:9001`

export function useArmConsole() {
  const status = reactive<SystemStatus>(defaultStatus())
  const history = reactive<number[][]>([[], [], [], [], [], []])
  const connectedHttp = ref(false)
  const connectedMqtt = ref(false)
  const bootDone = ref(false)
  const lastError = ref('')
  const isDemo = ref(false)

  let pollTimer: number | undefined
  let demoTimer: number | undefined
  let client: MqttClient | null = null
  const MAX_HISTORY = 120
  let demoT = 0

  function applyStatus(payload: Partial<SystemStatus>, fromDemo = false) {
    if (!fromDemo) {
      isDemo.value = false
    }
    Object.assign(status, payload)
    const angles = (payload.actual?.length === 6 ? payload.actual : payload.target) ?? status.actual
    if (angles?.length === 6) {
      for (let i = 0; i < 6; i++) {
        history[i].push(angles[i])
        if (history[i].length > MAX_HISTORY) history[i].shift()
      }
    }
  }

  function tickDemo() {
    if (connectedHttp.value || connectedMqtt.value) {
      isDemo.value = false
      return
    }
    isDemo.value = true
    demoT += 0.05
    const target = [
      Math.sin(demoT) * 35,
      Math.sin(demoT * 0.7) * 25,
      Math.cos(demoT * 0.9) * 30,
      Math.sin(demoT * 1.2) * 20,
      Math.cos(demoT * 0.5) * 40,
      (Math.sin(demoT * 0.4) * 0.5 + 0.5) * 80,
    ]
    applyStatus(
      {
        module_id: 'SC171V2',
        module_name: 'Fibocom SC171V2',
        carrier: '5G/Wi-Fi',
        link: 'up',
        hb_age_ms: 80 + Math.sin(demoT) * 20,
        mode: 'running',
        device_online: true,
        stm32_online: true,
        pc_online: true,
        last_gesture: 'Swipe Right',
        target,
        actual: target.map((v, i) => v + Math.sin(demoT + i) * 1.5),
        fault: '',
        estop: false,
        latency_ms: 12 + Math.sin(demoT) * 4,
        control_hz: 24 + Math.sin(demoT * 2) * 2,
        seq: Math.floor(demoT * 20),
      },
      true,
    )
  }

  async function fetchStatus() {
    try {
      const res = await fetch(`${API_BASE}/api/status`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = (await res.json()) as SystemStatus
      applyStatus(data)
      connectedHttp.value = true
      lastError.value = ''
    } catch (err) {
      connectedHttp.value = false
      lastError.value = err instanceof Error ? err.message : 'status_unreachable'
    }
  }

  async function sendControl(action: ControlAction) {
    const res = await fetch(`${API_BASE}/api/control`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action }),
    })
    if (!res.ok) {
      const text = await res.text()
      throw new Error(text || `control_${res.status}`)
    }
    const data = (await res.json()) as SystemStatus
    applyStatus(data)
    return data
  }

  function connectMqtt() {
    try {
      client = mqtt.connect(MQTT_URL, {
        protocolVersion: 4,
        reconnectPeriod: 3000,
        connectTimeout: 5000,
      })
      client.on('connect', () => {
        connectedMqtt.value = true
        client?.subscribe('arm/web/status')
      })
      client.on('close', () => {
        connectedMqtt.value = false
      })
      client.on('error', () => {
        connectedMqtt.value = false
      })
      client.on('message', (_topic, payload) => {
        try {
          const data = JSON.parse(payload.toString()) as SystemStatus
          applyStatus(data)
        } catch {
          /* ignore */
        }
      })
    } catch {
      connectedMqtt.value = false
    }
  }

  const linkOk = computed(() => connectedHttp.value || connectedMqtt.value)
  const moduleOnline = computed(() => status.device_online && status.link !== 'down')

  onMounted(() => {
    void fetchStatus()
    // MQTT is primary; HTTP is slow fallback only
    pollTimer = window.setInterval(() => {
      if (!connectedMqtt.value) void fetchStatus()
    }, 2500)
    demoTimer = window.setInterval(tickDemo, 50)
    connectMqtt()
  })

  onUnmounted(() => {
    if (pollTimer) window.clearInterval(pollTimer)
    if (demoTimer) window.clearInterval(demoTimer)
    client?.end(true)
  })

  return {
    status,
    history,
    connectedHttp,
    connectedMqtt,
    linkOk,
    moduleOnline,
    isDemo,
    bootDone,
    lastError,
    fetchStatus,
    sendControl,
  }
}
