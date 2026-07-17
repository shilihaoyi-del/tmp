<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import BootSequence from '@/components/BootSequence.vue'
import SensorTag from '@/components/SensorTag.vue'
import ArmViewport from '@/components/ArmViewport.vue'
import JointPanel from '@/components/JointPanel.vue'
import JointChart from '@/components/JointChart.vue'
import ControlDeck from '@/components/ControlDeck.vue'
import ScenarioMetrics from '@/components/ScenarioMetrics.vue'
import { useArmConsole } from '@/composables/useArmConsole'
import type { ControlAction } from '@/types/arm'

gsap.registerPlugin(ScrollTrigger)

const {
  status,
  history,
  connectedHttp,
  connectedMqtt,
  linkOk,
  moduleOnline,
  isDemo,
  bootDone,
  lastError,
  sendControl,
} = useArmConsole()

const showBoot = ref(true)
const actionError = ref('')

// Prefer target for viewport: no real SC171V2 feedback yet; actual stays 0
const displayAngles = computed(() => {
  const t = status.target || []
  const a = status.actual || []
  const targetLive = t.some((v) => Math.abs(v) > 0.01)
  const actualLive = a.some((v) => Math.abs(v) > 0.01)
  if (targetLive) return [...t]
  if (actualLive) return [...a]
  return t.length === 6 ? [...t] : [0, 0, 0, 0, 0, 0]
})


const modeTone = computed(() => {
  if (status.estop || status.mode === 'estop') return 'danger'
  if (status.mode === 'running') return 'active'
  if (status.mode === 'hold' || status.mode === 'paused') return 'warn'
  return ''
})

function onBootDone() {
  showBoot.value = false
  bootDone.value = true
  void nextTick(() => initReveal())
}

function initReveal() {
  gsap.utils.toArray<HTMLElement>('.reveal').forEach((el, i) => {
    gsap.fromTo(
      el,
      { opacity: 0, y: 28 },
      {
        opacity: 1,
        y: 0,
        duration: 0.55,
        ease: 'power1.out',
        delay: i * 0.04,
        scrollTrigger: {
          trigger: el,
          start: 'top 88%',
          toggleActions: 'play none none none',
        },
      },
    )
  })
}

async function onAction(action: ControlAction) {
  actionError.value = ''
  try {
    await sendControl(action)
  } catch (err) {
    actionError.value = err instanceof Error ? err.message : 'control_failed'
  }
}

onMounted(() => {
  gsap.to('.scan', {
    backgroundPositionY: '200px',
    duration: 8,
    repeat: -1,
    ease: 'none',
  })
})
</script>

<template>
  <BootSequence v-if="showBoot" :active="true" @done="onBootDone" />

  <div class="shell scan">
    <header class="top reveal">
      <div class="identity">
        <div class="logo">FIBOCOM <span>SC171V2</span></div>
        <p class="comment">5G smart module edge plane · teleop / showfloor / cloud-robot scenarios</p>
      </div>
      <div class="tags">
        <SensorTag
          v-if="isDemo"
          label="SOURCE"
          value="DEMO"
          tone="warn"
        />
        <SensorTag
          v-else-if="status.source"
          label="SOURCE"
          :value="String(status.source).toUpperCase()"
          :tone="status.source === 'sim' || status.source === 'SIM' ? 'warn' : 'active'"
        />
        <SensorTag
          label="SC171V2"
          :value="moduleOnline ? 'ONLINE' : 'OFFLINE'"
          :tone="moduleOnline ? 'active' : 'danger'"
        />
        <SensorTag
          label="LINK"
          :value="(status.link || 'DOWN').toUpperCase()"
          :tone="status.link === 'up' ? 'active' : 'danger'"
        />
        <SensorTag
          label="CARRIER"
          :value="(status.carrier || '5G/Wi-Fi').toUpperCase()"
          :tone="moduleOnline ? 'active' : ''"
        />
        <SensorTag
          label="MODE"
          :value="status.mode.toUpperCase()"
          :tone="modeTone"
        />
      </div>
    </header>

    <section class="hero reveal">
      <div>
        <h1>SC171V2<br />REMOTE ROBOT LINK</h1>
        <p class="lede">体感机械臂远程跟随 · 场景包装</p>
        <p class="comment">
          fibocom module owns public-network session, edge safety, and telemetry — web is observation only
        </p>
      </div>
      <div class="hero-metrics">
        <div class="metric primary">
          <span class="k">LATENCY</span>
          <span class="v">{{ status.latency_ms.toFixed(1) }}<small>ms</small></span>
        </div>
        <div class="metric primary">
          <span class="k">HB_AGE</span>
          <span class="v">{{ status.hb_age_ms.toFixed(0) }}<small>ms</small></span>
        </div>
        <div class="metric">
          <span class="k">CTRL_HZ</span>
          <span class="v">{{ status.control_hz.toFixed(1) }}<small>Hz</small></span>
        </div>
        <div class="metric">
          <span class="k">SEQ</span>
          <span class="v">{{ status.seq }}</span>
        </div>
      </div>
    </section>

    <!-- Primary KPIs: module / safety -->
    <section class="status-row hero-row reveal">
      <SensorTag
        label="ESTOP"
        :value="status.estop ? 'TRIPPED' : 'CLEAR'"
        :tone="status.estop ? 'danger' : 'active'"
      />
      <SensorTag
        v-if="status.fault"
        label="FAULT"
        :value="status.fault.toUpperCase()"
        tone="danger"
      />
      <SensorTag
        label="MQTT_WS"
        :value="connectedMqtt ? 'LIVE' : 'WAIT'"
        :tone="connectedMqtt ? 'active' : 'warn'"
      />
      <SensorTag
        label="HTTP"
        :value="connectedHttp ? 'OK' : 'STANDBY'"
        :tone="connectedHttp ? 'active' : ''"
      />
      <SensorTag
        label="BRIDGE"
        :value="linkOk ? 'UP' : 'DOWN'"
        :tone="linkOk ? 'active' : 'warn'"
      />
    </section>

    <section class="main-grid">
      <div class="reveal col-span-2">
        <ArmViewport :angles="displayAngles" />
      </div>
      <div class="stack">
        <div class="reveal">
          <JointPanel :target="status.target" :actual="status.actual" />
        </div>
        <div class="reveal">
          <ControlDeck :mode="status.mode" :estop="status.estop" @action="onAction" />
        </div>
      </div>
    </section>

    <section class="reveal chart-wrap">
      <JointChart :series="history" />
    </section>

    <section class="reveal chart-wrap">
      <ScenarioMetrics />
    </section>

    <!-- Downstream / packaging (secondary) -->
    <section class="aux reveal">
      <div class="panel">
        <div class="panel-header">
          <span>DOWNSTREAM / PACKAGING</span>
          <span>NOT THE HERO</span>
        </div>
        <div class="panel-body aux-body">
          <p class="comment">executor and vision input sit under the module link</p>
          <div class="aux-tags">
            <SensorTag
              label="STM32"
              :value="status.stm32_online ? 'ONLINE' : 'OFFLINE'"
              :tone="status.stm32_online ? 'active' : 'warn'"
            />
            <SensorTag
              label="PC_VISION"
              :value="status.pc_online ? 'ONLINE' : 'OFFLINE'"
              :tone="status.pc_online ? 'active' : ''"
            />
            <SensorTag
              label="GESTURE"
              :value="(status.last_gesture || 'NONE').toUpperCase()"
              :tone="status.last_gesture ? 'active' : ''"
            />
          </div>
        </div>
      </div>
    </section>

    <footer class="foot reveal">
      <p class="comment">
        hero={{ status.module_name || 'Fibocom SC171V2' }} · mqtt arm/web/status · api /api/status fallback
      </p>
      <p v-if="lastError || actionError" class="err">
        [ERR] {{ actionError || lastError }}
      </p>
    </footer>
  </div>
</template>

<style scoped>
.shell {
  width: min(1280px, calc(100% - 32px));
  margin: 0 auto;
  padding: 28px 0 64px;
}

.scan {
  background-image: linear-gradient(
    to bottom,
    transparent 50%,
    rgba(61, 255, 106, 0.015) 50%
  );
  background-size: 100% 4px;
}

.top {
  display: flex;
  justify-content: space-between;
  gap: 24px;
  align-items: flex-start;
  padding-bottom: 22px;
  border-bottom: 1px solid var(--line);
}

.logo {
  font-family: var(--display);
  font-size: 28px;
  font-weight: 600;
  letter-spacing: 0.1em;
}

.logo span {
  color: var(--accent);
}

.tags,
.status-row,
.aux-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
}

.hero {
  display: flex;
  justify-content: space-between;
  gap: 24px;
  align-items: flex-end;
  padding: 36px 0 18px;
}

.hero h1 {
  margin: 0;
  font-family: var(--display);
  font-size: clamp(28px, 5vw, 48px);
  font-weight: 500;
  letter-spacing: 0.04em;
  line-height: 1.05;
}

.lede {
  margin: 10px 0 6px;
  color: var(--text-dim);
  letter-spacing: 0.06em;
  font-size: 12px;
}

.hero-metrics {
  display: grid;
  grid-template-columns: repeat(2, auto);
  gap: 14px 18px;
}

.metric {
  min-width: 88px;
  border-left: 1px solid var(--line);
  padding-left: 12px;
}

.metric.primary .v {
  color: var(--accent);
}

.metric .k {
  display: block;
  font-size: 10px;
  color: var(--text-faint);
  letter-spacing: 0.08em;
}

.metric .v {
  font-size: 22px;
  font-family: var(--display);
  font-variant-numeric: tabular-nums;
}

.metric small {
  font-size: 12px;
  color: var(--text-dim);
  margin-left: 4px;
}

.hero-row {
  justify-content: flex-start;
  margin-bottom: 18px;
}

.main-grid {
  display: grid;
  grid-template-columns: 1.4fr 1fr;
  gap: 14px;
  align-items: stretch;
}

.col-span-2 {
  min-height: 460px;
}

.stack {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.chart-wrap,
.aux {
  margin-top: 14px;
}

.aux-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.aux-tags {
  justify-content: flex-start;
}

.foot {
  margin-top: 28px;
  padding-top: 16px;
  border-top: 1px solid var(--line);
  display: flex;
  justify-content: space-between;
  gap: 16px;
}

.err {
  color: var(--danger);
  margin: 0;
  font-size: 11px;
}

@media (max-width: 980px) {
  .top,
  .hero {
    flex-direction: column;
  }

  .tags {
    justify-content: flex-start;
  }

  .main-grid {
    grid-template-columns: 1fr;
  }

  .hero-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    width: 100%;
  }
}
</style>
