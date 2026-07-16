export type SystemMode = 'idle' | 'running' | 'paused' | 'estop' | 'hold'
export type ControlAction = 'start' | 'pause' | 'estop' | 'reset'

export interface SystemStatus {
  module_id: string
  module_name: string
  carrier: string
  link: 'up' | 'down' | string
  hb_age_ms: number
  mode: SystemMode
  device_online: boolean
  stm32_online: boolean
  pc_online: boolean
  last_gesture: string
  target: number[]
  actual: number[]
  fault: string
  estop: boolean
  latency_ms: number
  control_hz: number
  seq: number
  source?: string
}

export const JOINT_LABELS = [
  'J1_BASE',
  'J2_SHOULDER',
  'J3_ELBOW',
  'J4_WRIST_P',
  'J5_WRIST_R',
  'J6_GRIPPER',
] as const

export const defaultStatus = (): SystemStatus => ({
  module_id: 'SC171V2',
  module_name: 'Fibocom SC171V2',
  carrier: '5G/Wi-Fi',
  link: 'down',
  hb_age_ms: 0,
  mode: 'idle',
  device_online: false,
  stm32_online: false,
  pc_online: false,
  last_gesture: '',
  target: [0, 0, 0, 0, 0, 0],
  actual: [0, 0, 0, 0, 0, 0],
  fault: '',
  estop: false,
  latency_ms: 0,
  control_hz: 0,
  seq: 0,
  source: 'sim',
})
