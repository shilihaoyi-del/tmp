/**
 * JetArm 6DOF kinematics from jetarm_6dof_description.urdf.xacro.
 * Meshes are procedural (STL package not bundled); joint origins match URDF.
 */
export const ARM_KINEMATICS = {
  baseHeight: 0.10314916202,
  link2Len: 0.12941763737,
  link3Len: 0.12941763737,
  link4Len: 0.05945312631,
  wristOffset: 0.11054687369,
  // From jetarm_6dof_description.urdf.xacro + materials.xacro
  colors: {
    green: 0x66e666, // rgba 0.4 0.9 0.4
    black: 0x262626, // rgba 0.15 0.15 0.15
    white: 0xcccccc, // rgba 0.8 0.8 0.8
    screen: 0x111111,
    metal: 0x8a8a8a,
  },
  gripper: {
    // Approximate URDF finger mounts (gripper.urdf.xacro)
    baseZ: 0.012,
    fingerZ: 0.027,
    halfSpan: 0.014,
    fingerLen: 0.042,
    openRad: 0.85,
  },
} as const

/**
 * JetArm joint deg → viewport mesh deg (Z-up URDF).
 * Offsets are taught so the recorded home pose maps to ~0 on j1..j5:
 * mesh then draws as a straight chain along robot Z (links stacked).
 * home ≈ [1.68, -89.28, 4.56, -156.72, -3.84, 45]  → viewport ≈ [0,0,0,0,0,45]
 * initial (working start) is separate: see sc171v2_agent/initial_pose.json
 */
export const VIEW_JOINT_SIGN = [1, 1, 1, 1, 1, 1] as const
/** Z-line home (matches sc171v2_agent/home_pose.json). */
export const VIEW_HOME_JOINTS_DEG = [1.68, -89.28, 4.56, -156.72, -3.84, 45.0] as const
/** Working initial pose (matches sc171v2_agent/initial_pose.json). */
export const VIEW_INITIAL_JOINTS_DEG = [1.92, -89.76, -31.92, -210.0, -3.84, 45.0] as const
/** offset = -sign * home  → home displays as Z-line (j1..j5 ≈ 0). */
export const VIEW_JOINT_OFFSET_DEG = [-1.68, 89.28, -4.56, 156.72, 3.84, 0.0] as const

export function jetarmToViewportDeg(joints: number[]): number[] {
  const out = [0, 0, 0, 0, 0, 0]
  for (let i = 0; i < 6; i++) {
    const raw = joints[i] ?? 0
    out[i] = raw * VIEW_JOINT_SIGN[i] + VIEW_JOINT_OFFSET_DEG[i]
  }
  return out
}

export function degToRad(d: number) {
  return (d * Math.PI) / 180
}
