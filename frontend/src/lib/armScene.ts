import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { ARM_KINEMATICS, degToRad, jetarmToViewportDeg } from '@/lib/kinematics'

type JointHandles = {
  j1: THREE.Object3D
  j2: THREE.Object3D
  j3: THREE.Object3D
  j4: THREE.Object3D
  j5: THREE.Object3D
  gripperL: THREE.Object3D
  gripperR: THREE.Object3D
}

const { green, black, white, screen, metal } = ARM_KINEMATICS.colors

function mat(color: number, metalness = 0.35, roughness = 0.42) {
  return new THREE.MeshStandardMaterial({
    color,
    metalness,
    roughness,
    flatShading: false,
  })
}

function addMesh(
  parent: THREE.Object3D,
  geo: THREE.BufferGeometry,
  color: number,
  opts?: {
    pos?: [number, number, number]
    rot?: [number, number, number]
    metalness?: number
    roughness?: number
  },
) {
  const mesh = new THREE.Mesh(
    geo,
    mat(color, opts?.metalness ?? 0.35, opts?.roughness ?? 0.42),
  )
  if (opts?.pos) mesh.position.set(...opts.pos)
  if (opts?.rot) mesh.rotation.set(...opts.rot)
  mesh.castShadow = true
  mesh.receiveShadow = true
  parent.add(mesh)
  return mesh
}

/** Dual-plate arm segment (green sides + white core + black joint hubs) — URDF multi-visual style. */
function buildArmBeam(
  parent: THREE.Object3D,
  len: number,
  opts?: { width?: number; depth?: number; withCamera?: boolean },
) {
  const w = opts?.width ?? 0.036
  const d = opts?.depth ?? 0.028
  const plate = 0.006

  // Side plates (green)
  addMesh(parent, new THREE.BoxGeometry(plate, len * 0.92, d), green, {
    pos: [-w / 2 + plate / 2, len / 2, 0],
    metalness: 0.25,
    roughness: 0.5,
  })
  addMesh(parent, new THREE.BoxGeometry(plate, len * 0.92, d), green, {
    pos: [w / 2 - plate / 2, len / 2, 0],
    metalness: 0.25,
    roughness: 0.5,
  })
  // White structural core
  addMesh(parent, new THREE.BoxGeometry(w * 0.42, len * 0.86, d * 0.55), white, {
    pos: [0, len / 2, 0],
    metalness: 0.15,
    roughness: 0.55,
  })
  // Proximal / distal hubs (black)
  addMesh(parent, new THREE.CylinderGeometry(0.016, 0.016, w * 0.95, 20), black, {
    pos: [0, 0.004, 0],
    rot: [0, 0, Math.PI / 2],
    metalness: 0.55,
    roughness: 0.35,
  })
  addMesh(parent, new THREE.CylinderGeometry(0.015, 0.015, w * 0.9, 20), black, {
    pos: [0, len - 0.004, 0],
    rot: [0, 0, Math.PI / 2],
    metalness: 0.55,
    roughness: 0.35,
  })

  if (opts?.withCamera) {
    // GEMINI-style depth camera on link4
    addMesh(parent, new THREE.BoxGeometry(0.028, 0.022, 0.018), black, {
      pos: [0, len * 0.55, d * 0.55],
      metalness: 0.4,
      roughness: 0.4,
    })
    addMesh(parent, new THREE.CylinderGeometry(0.006, 0.006, 0.008, 16), metal, {
      pos: [-0.006, len * 0.55, d * 0.55 + 0.01],
      rot: [Math.PI / 2, 0, 0],
      metalness: 0.8,
      roughness: 0.2,
    })
    addMesh(parent, new THREE.CylinderGeometry(0.006, 0.006, 0.008, 16), metal, {
      pos: [0.006, len * 0.55, d * 0.55 + 0.01],
      rot: [Math.PI / 2, 0, 0],
      metalness: 0.8,
      roughness: 0.2,
    })
  }
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
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap
    host.appendChild(this.renderer.domElement)

    this.scene = new THREE.Scene()
    this.scene.fog = new THREE.Fog(0x050505, 2.0, 4.8)

    this.camera = new THREE.PerspectiveCamera(40, w / h, 0.01, 20)
    this.camera.position.set(0.58, 0.38, 0.68)

    this.controls = new OrbitControls(this.camera, this.renderer.domElement)
    this.controls.enableDamping = true
    this.controls.dampingFactor = 0.07
    this.controls.target.set(0, 0.2, 0)
    this.controls.maxDistance = 2.4
    this.controls.minDistance = 0.22

    this.buildLights()
    this.buildFloor()
    this.joints = this.buildArm()

    window.addEventListener('resize', this.onResize)
    this.loop()
  }

  private buildLights() {
    this.scene.add(new THREE.AmbientLight(0xffffff, 0.4))
    const key = new THREE.DirectionalLight(0xffffff, 1.1)
    key.position.set(0.9, 1.3, 0.7)
    key.castShadow = true
    key.shadow.mapSize.set(1024, 1024)
    key.shadow.camera.near = 0.1
    key.shadow.camera.far = 4
    this.scene.add(key)
    const fill = new THREE.DirectionalLight(0xaaccff, 0.28)
    fill.position.set(-0.7, 0.5, -0.5)
    this.scene.add(fill)
    const rim = new THREE.DirectionalLight(green, 0.22)
    rim.position.set(-0.4, 0.35, -0.9)
    this.scene.add(rim)
  }

  private buildFloor() {
    const grid = new THREE.GridHelper(1.8, 36, 0x2e2e2e, 0x141414)
    this.scene.add(grid)
    const plate = new THREE.Mesh(
      new THREE.CircleGeometry(0.3, 56),
      mat(0x101010, 0.15, 0.9),
    )
    plate.rotation.x = -Math.PI / 2
    plate.receiveShadow = true
    this.scene.add(plate)
  }

  private buildArm(): JointHandles {
    const root = new THREE.Group()
    this.scene.add(root)

    // JetArm / URDF is Z-up. Three.js is Y-up → rotate whole robot.
    const robot = new THREE.Group()
    robot.rotation.x = -Math.PI / 2
    root.add(robot)

    // —— base_link (multi-part: green / black / screen / white) ——
    const base = new THREE.Group()
    robot.add(base)
    // Main black chassis
    addMesh(base, new THREE.BoxGeometry(0.118, 0.118, 0.038), black, {
      pos: [0, 0, 0.019],
      metalness: 0.3,
      roughness: 0.55,
    })
    // Green accent skirt
    addMesh(base, new THREE.BoxGeometry(0.126, 0.126, 0.01), green, {
      pos: [0, 0, 0.006],
      metalness: 0.2,
      roughness: 0.55,
    })
    // White face / deck
    addMesh(base, new THREE.BoxGeometry(0.1, 0.055, 0.012), white, {
      pos: [0, 0.028, 0.042],
      metalness: 0.12,
      roughness: 0.6,
    })
    // Screen (BASE_SCREEN)
    addMesh(base, new THREE.BoxGeometry(0.052, 0.032, 0.004), screen, {
      pos: [0, 0.052, 0.04],
      metalness: 0.05,
      roughness: 0.25,
    })
    // Corner green caps
    for (const [x, y] of [
      [0.048, 0.048],
      [-0.048, 0.048],
      [0.048, -0.048],
      [-0.048, -0.048],
    ] as const) {
      addMesh(base, new THREE.CylinderGeometry(0.008, 0.008, 0.012, 12), green, {
        pos: [x, y, 0.04],
        rot: [Math.PI / 2, 0, 0],
      })
    }
    const led = new THREE.Mesh(
      new THREE.SphereGeometry(0.0055, 12, 12),
      new THREE.MeshBasicMaterial({ color: 0x3dff6a }),
    )
    led.position.set(0.042, -0.042, 0.042)
    base.add(led)

    // —— joint1 / link1 (yaw turret) ——
    const j1 = new THREE.Group()
    j1.position.z = ARM_KINEMATICS.baseHeight
    robot.add(j1)
    addMesh(j1, new THREE.CylinderGeometry(0.034, 0.038, 0.028, 28), black, {
      pos: [0, 0, 0],
      rot: [Math.PI / 2, 0, 0],
      metalness: 0.5,
      roughness: 0.35,
    })
    addMesh(j1, new THREE.CylinderGeometry(0.028, 0.028, 0.018, 28), green, {
      pos: [0, 0, 0.02],
      rot: [Math.PI / 2, 0, 0],
    })
    addMesh(j1, new THREE.BoxGeometry(0.052, 0.04, 0.03), black, {
      pos: [0, 0, 0.038],
      metalness: 0.45,
      roughness: 0.4,
    })

    // —— joint2 mount rpy(π/2) then link2 ——
    const j2Mount = new THREE.Group()
    j2Mount.rotation.x = Math.PI / 2
    j1.add(j2Mount)
    const j2 = new THREE.Group()
    j2Mount.add(j2)
    const link2 = new THREE.Group()
    j2.add(link2)
    buildArmBeam(link2, ARM_KINEMATICS.link2Len)

    // —— joint3 / link3 ——
    const j3 = new THREE.Group()
    j3.position.y = ARM_KINEMATICS.link2Len
    link2.add(j3)
    const link3 = new THREE.Group()
    j3.add(link3)
    buildArmBeam(link3, ARM_KINEMATICS.link3Len, { width: 0.034, depth: 0.026 })

    // —— joint4 / link4 (+ camera) ——
    const j4 = new THREE.Group()
    j4.position.y = ARM_KINEMATICS.link3Len
    link3.add(j4)
    const link4 = new THREE.Group()
    j4.add(link4)
    buildArmBeam(link4, ARM_KINEMATICS.link4Len, {
      width: 0.032,
      depth: 0.03,
      withCamera: true,
    })

    // —— joint5 mount rpy(-π/2) / link5 + gripper ——
    const j5Mount = new THREE.Group()
    j5Mount.position.y = ARM_KINEMATICS.link4Len
    j5Mount.rotation.x = -Math.PI / 2
    link4.add(j5Mount)
    const j5 = new THREE.Group()
    j5Mount.add(j5)

    // link5 white wrist (URDF LINK5_WHITE)
    const wrist = new THREE.Group()
    wrist.rotation.x = Math.PI / 2
    j5.add(wrist)
    addMesh(wrist, new THREE.CylinderGeometry(0.016, 0.016, 0.036, 20), white, {
      pos: [0, 0.018, 0],
      metalness: 0.2,
      roughness: 0.45,
    })
    addMesh(wrist, new THREE.CylinderGeometry(0.02, 0.02, 0.012, 20), black, {
      pos: [0, 0.004, 0],
      metalness: 0.5,
      roughness: 0.35,
    })

    // gripper_servo_link + fingers (gripper.urdf.xacro style)
    const g = ARM_KINEMATICS.gripper
    const gripRoot = new THREE.Group()
    gripRoot.position.y = 0.04
    wrist.add(gripRoot)
    addMesh(gripRoot, new THREE.BoxGeometry(0.034, 0.022, 0.028), black, {
      pos: [0, g.baseZ, 0],
      metalness: 0.4,
      roughness: 0.4,
    })

    const gripperR = new THREE.Group()
    const gripperL = new THREE.Group()
    gripperR.position.set(0, g.fingerZ, -g.halfSpan)
    gripperL.position.set(0, g.fingerZ, g.halfSpan)
    gripRoot.add(gripperR, gripperL)

    // Outer finger + tip pad
    const fingerGeo = () => {
      const group = new THREE.Group()
      addMesh(group, new THREE.BoxGeometry(0.01, g.fingerLen, 0.012), black, {
        pos: [0, g.fingerLen / 2, 0],
        metalness: 0.35,
        roughness: 0.45,
      })
      addMesh(group, new THREE.BoxGeometry(0.008, 0.014, 0.01), metal, {
        pos: [0, g.fingerLen - 0.006, 0],
        metalness: 0.7,
        roughness: 0.3,
      })
      return group
    }
    gripperR.add(fingerGeo())
    gripperL.add(fingerGeo())

    // Inner linkage stubs (visual only)
    addMesh(gripRoot, new THREE.BoxGeometry(0.006, 0.02, 0.006), black, {
      pos: [0.01, 0.038, -0.008],
    })
    addMesh(gripRoot, new THREE.BoxGeometry(0.006, 0.02, 0.006), black, {
      pos: [0.01, 0.038, 0.008],
    })

    return { j1, j2, j3, j4, j5, gripperL, gripperR }
  }

  setJoints(anglesDeg: number[], opts?: { snap?: boolean }) {
    const mapped = jetarmToViewportDeg(anglesDeg)
    const alpha = opts?.snap ? 1 : 0.88
    for (let i = 0; i < 6; i++) {
      const t = mapped[i] ?? 0
      this.display[i] += (t - this.display[i]) * alpha
    }
    const [a1, a2, a3, a4, a5, a6] = this.display
    // Z-up JetArm: revolute joints about local Z after URDF fixed rpy mounts
    this.joints.j1.rotation.set(0, 0, degToRad(a1))
    this.joints.j2.rotation.set(0, 0, degToRad(a2))
    this.joints.j3.rotation.set(0, 0, degToRad(a3))
    this.joints.j4.rotation.set(0, 0, degToRad(a4))
    this.joints.j5.rotation.set(0, 0, degToRad(a5))

    // Gripper: map servo deg → finger open angle (URDF r_joint 0..~π/2 about ±Y)
    const closed = THREE.MathUtils.clamp(a6 / 90, 0, 1)
    const open = (1 - closed) * ARM_KINEMATICS.gripper.openRad
    this.joints.gripperR.rotation.set(0, open, 0)
    this.joints.gripperL.rotation.set(0, -open, 0)
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
