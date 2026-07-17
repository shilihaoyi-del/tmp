import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { ARM_KINEMATICS, degToRad } from '@/lib/kinematics'

type JointHandles = {
  j1: THREE.Object3D
  j2: THREE.Object3D
  j3: THREE.Object3D
  j4: THREE.Object3D
  j5: THREE.Object3D
  gripperL: THREE.Object3D
  gripperR: THREE.Object3D
}

function mat(color: number, metalness = 0.55, roughness = 0.35) {
  return new THREE.MeshStandardMaterial({
    color,
    metalness,
    roughness,
    flatShading: false,
  })
}

function box(
  w: number,
  h: number,
  d: number,
  color: number,
  y = 0,
): THREE.Mesh {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat(color))
  mesh.position.y = y
  mesh.castShadow = true
  mesh.receiveShadow = true
  return mesh
}

function cyl(
  rTop: number,
  rBot: number,
  h: number,
  color: number,
  y = 0,
): THREE.Mesh {
  const mesh = new THREE.Mesh(
    new THREE.CylinderGeometry(rTop, rBot, h, 24),
    mat(color, 0.7, 0.28),
  )
  mesh.position.y = y
  mesh.castShadow = true
  return mesh
}

export class ArmScene {
  private renderer: THREE.WebGLRenderer
  private scene: THREE.Scene
  private camera: THREE.PerspectiveCamera
  private controls: OrbitControls
  private joints!: JointHandles
  private raf = 0
  private disposed = false
  private display = [0, 0, 0, 0, 0, 0]
  private host: HTMLElement

  constructor(host: HTMLElement) {
    this.host = host
    const w = host.clientWidth || 640
    const h = host.clientHeight || 420

    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    this.renderer.setSize(w, h)
    this.renderer.shadowMap.enabled = true
    host.appendChild(this.renderer.domElement)

    this.scene = new THREE.Scene()
    this.scene.fog = new THREE.Fog(0x050505, 1.8, 4.2)

    this.camera = new THREE.PerspectiveCamera(42, w / h, 0.01, 20)
    this.camera.position.set(0.55, 0.42, 0.62)

    this.controls = new OrbitControls(this.camera, this.renderer.domElement)
    this.controls.enableDamping = true
    this.controls.dampingFactor = 0.06
    this.controls.target.set(0, 0.22, 0)
    this.controls.maxDistance = 2.2
    this.controls.minDistance = 0.25

    this.buildLights()
    this.buildFloor()
    this.joints = this.buildArm()

    window.addEventListener('resize', this.onResize)
    this.loop()
  }

  private buildLights() {
    const amb = new THREE.AmbientLight(0xffffff, 0.35)
    this.scene.add(amb)
    const key = new THREE.DirectionalLight(0xffffff, 1.05)
    key.position.set(0.8, 1.2, 0.6)
    key.castShadow = true
    key.shadow.mapSize.set(1024, 1024)
    this.scene.add(key)
    const rim = new THREE.DirectionalLight(0x66e666, 0.25)
    rim.position.set(-0.6, 0.4, -0.8)
    this.scene.add(rim)
  }

  private buildFloor() {
    const grid = new THREE.GridHelper(1.6, 32, 0x2a2a2a, 0x151515)
    grid.position.y = 0
    this.scene.add(grid)
    const plate = new THREE.Mesh(
      new THREE.CircleGeometry(0.28, 48),
      mat(0x111111, 0.2, 0.85),
    )
    plate.rotation.x = -Math.PI / 2
    plate.receiveShadow = true
    this.scene.add(plate)
  }

  private buildArm(): JointHandles {
    const { green, black, white } = ARM_KINEMATICS.colors
    const root = new THREE.Group()
    this.scene.add(root)

    // base
    const base = new THREE.Group()
    base.add(cyl(0.055, 0.06, 0.03, black, 0.015))
    base.add(cyl(0.048, 0.048, 0.02, green, 0.04))
    base.add(box(0.07, 0.018, 0.04, white, 0.055))
    root.add(base)

    // J1 yaw
    const j1 = new THREE.Group()
    j1.position.y = ARM_KINEMATICS.baseHeight
    root.add(j1)
    j1.add(cyl(0.028, 0.028, 0.04, black, 0))
    j1.add(box(0.05, 0.03, 0.05, green, 0.03))

    // J2 pitch (URDF rpy pi/2 then rotate about Z)
    const j2 = new THREE.Group()
    j2.rotation.x = Math.PI / 2
    j1.add(j2)
    const shoulder = new THREE.Group()
    shoulder.rotation.x = -Math.PI / 2
    j2.add(shoulder)
    shoulder.add(box(0.04, ARM_KINEMATICS.link2Len, 0.035, green, ARM_KINEMATICS.link2Len / 2))
    shoulder.add(box(0.02, ARM_KINEMATICS.link2Len * 0.9, 0.01, white, ARM_KINEMATICS.link2Len / 2))

    // J3
    const j3 = new THREE.Group()
    j3.position.y = ARM_KINEMATICS.link2Len
    shoulder.add(j3)
    j3.add(cyl(0.018, 0.018, 0.03, black, 0))
    const upper = new THREE.Group()
    j3.add(upper)
    upper.add(box(0.034, ARM_KINEMATICS.link3Len, 0.03, green, ARM_KINEMATICS.link3Len / 2))
    upper.add(box(0.016, ARM_KINEMATICS.link3Len * 0.85, 0.008, white, ARM_KINEMATICS.link3Len / 2))

    // J4
    const j4 = new THREE.Group()
    j4.position.y = ARM_KINEMATICS.link3Len
    upper.add(j4)
    j4.add(box(0.03, ARM_KINEMATICS.link4Len, 0.026, green, ARM_KINEMATICS.link4Len / 2))

    // J5 roll (URDF -pi/2)
    const j5 = new THREE.Group()
    j5.position.y = ARM_KINEMATICS.link4Len
    j5.rotation.x = -Math.PI / 2
    j4.add(j5)
    const wrist = new THREE.Group()
    wrist.rotation.x = Math.PI / 2
    j5.add(wrist)
    wrist.add(cyl(0.014, 0.014, 0.04, white, 0.02))

    // gripper
    const gripRoot = new THREE.Group()
    gripRoot.position.y = 0.05
    wrist.add(gripRoot)
    gripRoot.add(box(0.03, 0.02, 0.03, black, 0))
    const gripperL = new THREE.Group()
    const gripperR = new THREE.Group()
    gripperL.position.set(-0.012, 0.01, 0)
    gripperR.position.set(0.012, 0.01, 0)
    gripperL.add(box(0.006, 0.045, 0.012, black, 0.022))
    gripperR.add(box(0.006, 0.045, 0.012, black, 0.022))
    gripRoot.add(gripperL, gripperR)

    // accent LED
    const led = new THREE.Mesh(
      new THREE.SphereGeometry(0.006, 12, 12),
      new THREE.MeshBasicMaterial({ color: 0x3dff6a }),
    )
    led.position.set(0.03, 0.02, 0.03)
    base.add(led)

    return { j1, j2, j3, j4, j5, gripperL, gripperR }
  }

  setJoints(anglesDeg: number[]) {
    // Faster follow so Pinch / Swipe are obvious on the viewport
    for (let i = 0; i < 6; i++) {
      const t = anglesDeg[i] ?? 0
      this.display[i] += (t - this.display[i]) * 0.45
    }
    const [a1, a2, a3, a4, a5, a6] = this.display
    this.joints.j1.rotation.y = degToRad(a1)
    this.joints.j2.rotation.z = degToRad(a2)
    this.joints.j3.rotation.z = degToRad(a3)
    this.joints.j4.rotation.z = degToRad(a4)
    this.joints.j5.rotation.z = degToRad(a5)
    // Gripper: closed(90) -> fingers together; open(0) -> wide
    const closed = THREE.MathUtils.clamp(a6 / 90, 0, 1)
    const spread = 0.028 * (1 - closed) + 0.003
    this.joints.gripperL.position.x = -spread
    this.joints.gripperR.position.x = spread
  }

  private onResize = () => {
    if (this.disposed) return
    const w = this.host.clientWidth || 640
    const h = this.host.clientHeight || 420
    this.camera.aspect = w / h
    this.camera.updateProjectionMatrix()
    this.renderer.setSize(w, h)
  }

  private loop = () => {
    if (this.disposed) return
    this.raf = requestAnimationFrame(this.loop)
    this.controls.update()
    this.renderer.render(this.scene, this.camera)
  }

  dispose() {
    this.disposed = true
    cancelAnimationFrame(this.raf)
    window.removeEventListener('resize', this.onResize)
    this.controls.dispose()
    this.renderer.dispose()
    this.renderer.domElement.remove()
  }
}
