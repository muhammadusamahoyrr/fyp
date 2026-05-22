import { create } from 'zustand'

const BEAT_ORDER = [
  'city_above',
  'descent',
  'plaza_vista',
  'security_gate',
  'staircase',
  'portal',
  'corridor',
  'interior',
]

// DoF focusDistance per beat — pulls focus as camera approaches
const BEAT_FOCUS = {
  city_above:    0.0015,
  descent:       0.002,
  plaza_vista:   0.004,
  security_gate: 0.008,
  staircase:     0.012,
  portal:        0.018,
  corridor:      0.025,
  interior:      0.01,
}

// Vignette darkness per beat
const BEAT_VIGNETTE = {
  city_above:    0.3,
  descent:       0.35,
  plaza_vista:   0.4,
  security_gate: 0.55,
  staircase:     0.45,
  portal:        0.6,
  corridor:      0.75,
  interior:      0.5,
}

// Bloom intensity per beat
const BEAT_BLOOM = {
  city_above:    0.9,
  descent:       0.8,
  plaza_vista:   0.7,
  security_gate: 0.6,
  staircase:     0.6,
  portal:        0.5,
  corridor:      0.3,
  interior:      0.3,
}

export const BEAT_FOCUS_DISTANCE = BEAT_FOCUS
export const BEAT_VIGNETTE_VAL   = BEAT_VIGNETTE
export const BEAT_BLOOM_VAL      = BEAT_BLOOM

export const useCourtroomStore = create((set, get) => ({
  // ── Camera / journey state ──────────────────────────────────────────────────
  beat:         'city_above',    // current cinematic beat name
  beatIndex:    0,               // index into BEAT_ORDER
  cameraZ:      90,              // live camera Z — used to trigger gate, lighting
  isInterior:   false,           // true when camera passes portal corridor
  introPlaying: true,            // true during the GSAP cinematic intro
  introFinished: false,          // true once timeline completes

  // ── Gate state ───────────────────────────────────────────────────────────────
  gateOpen:     false,           // boom gate animation state

  // ── Environment state ────────────────────────────────────────────────────────
  skyTurbidity: 5.0,
  skyRayleigh:  1.2,
  skyMie:       0.01,
  skyInclination: 0.52,
  skyAzimuth:   0.18,

  // ── Actions ──────────────────────────────────────────────────────────────────
  setBeat: (beat) => {
    const idx = BEAT_ORDER.indexOf(beat)
    set({
      beat,
      beatIndex: idx,
      isInterior: beat === 'corridor' || beat === 'interior',
    })
  },

  setCameraZ: (z) => {
    set({ cameraZ: z })
    // Auto-open gate when camera reaches z ≤ 40
    if (z <= 40 && !get().gateOpen) {
      set({ gateOpen: true })
    }
  },

  setIntroFinished: () => set({ introPlaying: false, introFinished: true }),

  setSky: (params) => set(params),
}))
