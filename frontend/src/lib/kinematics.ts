/**
 * JetArm 6DOF kinematics distilled from jetarm_6dof_description.urdf.xacro.
 * Mesh STLs are absent locally — geometry is procedural; joints match URDF.
 */
export const ARM_KINEMATICS = {
  baseHeight: 0.10314916202,
  link2Len: 0.12941763737,
  link3Len: 0.12941763737,
  link4Len: 0.05945312631,
  wristOffset: 0.11054687369,
  colors: {
    green: 0x66e666,
    black: 0x262626,
    white: 0xcccccc,
    metal: 0x9a9a9a,
  },
} as const

export function degToRad(d: number) {
  return (d * Math.PI) / 180
}
