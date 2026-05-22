'use client';

import { useState, useRef, useEffect } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { useEnvironment, CameraShake } from '@react-three/drei';
import * as THREE from 'three';
import { Suspense } from 'react';

import { EffectComposer, Bloom, ChromaticAberration, Vignette, DepthOfField, ToneMapping, SMAA } from '@react-three/postprocessing';
import { ToneMappingMode, BlendFunction } from 'postprocessing';
import { useCourtroomStore, BEAT_FOCUS_DISTANCE, BEAT_VIGNETTE_VAL, BEAT_BLOOM_VAL } from '../../store/courtroomStore';

import ExteriorScene from './ExteriorScene';

// ─── CAMERA PRESETS — cinematic compositions ──────────────────────────────────
export const CAMERA_PRESETS = {
  establishing: {
    position: [0, 24, 85],
    target: [0, 10, 0],
    fov: 46,
    label: 'Establishing',
  },
  street: {
    position: [18, 4.8, 62],
    target: [-2, 12, 0],
    fov: 58,
    label: 'Street Level',
  },
  entrance: {
    position: [0, 8.5, 38],
    target: [0, 14, 0],
    fov: 52,
    label: 'Grand Entrance',
  },
  aerial: {
    position: [40, 65, 70],
    target: [0, 6, 8],
    fov: 38,
    label: 'Aerial',
  },
};
import CourtroomScene from './CourtroomScene';
import CourtroomHUD from './CourtroomHUD';

useEnvironment.preload({ preset: 'apartment' });

// ─── Camera path — module-level: allocated once, never recreated ──────────────
const CAMERA_CURVE = new THREE.CatmullRomCurve3([
  new THREE.Vector3(0, 4.5, 75),   // Stage 0: Over Constitution Ave
  new THREE.Vector3(0, 3.5, 45),   // Stage 1: Approach plaza
  new THREE.Vector3(0, 2.2, 26),   // Stage 2: Climb stairs, reach doors
  new THREE.Vector3(0, 2.2, 16),   // Stage 3: Pass through doors
  new THREE.Vector3(0, 2.6, 11.5), // Stage 4: Settle at lawyer view
]);

// Layered-sine pseudo-noise — no external dep needed
function breathe(t, seed) {
  return (
    Math.sin(t * 0.8  + seed) * 0.40 +
    Math.sin(t * 1.7  + seed * 1.5) * 0.25 +
    Math.sin(t * 3.1  + seed * 2.3) * 0.10
  );
}

// UI Overlay for Exterior Exploring
function ExteriorControls({ mode, setMode, activePreset, setActivePreset, onEnter }) {
  return (
    <div style={{ position: 'absolute', top: 32, left: 0, right: 0, display: 'flex', justifyContent: 'center', flexWrap: 'wrap', gap: 12, zIndex: 100, padding: '0 20px' }}>
      {Object.entries(CAMERA_PRESETS).map(([key, preset]) => (
        <button
          key={key}
          onClick={() => { setMode('preset'); setActivePreset(key); }}
          style={{
             padding: '10px 20px', 
             background: mode === 'preset' && activePreset === key ? '#FFF' : 'rgba(20, 20, 25, 0.8)', 
             color: mode === 'preset' && activePreset === key ? '#000' : '#FFF', 
             border: '1px solid rgba(255, 255, 255, 0.2)', 
             borderRadius: 24, 
             cursor: 'pointer', 
             fontFamily: 'sans-serif',
             fontSize: '14px',
             backdropFilter: 'blur(8px)',
             transition: 'all 0.3s ease'
          }}
        >
          {preset.label}
        </button>
      ))}
      <button 
         onClick={onEnter}
         style={{ 
            padding: '10px 24px', 
            background: '#D4AF37', 
            color: '#000', 
            border: 'none', 
            borderRadius: 24, 
            cursor: 'pointer', 
            fontWeight: 'bold',
            fontFamily: 'sans-serif',
            fontSize: '14px',
            marginLeft: 16,
            boxShadow: '0 4px 12px rgba(212, 175, 55, 0.3)',
            transition: 'all 0.3s ease'
         }}
      >
        Enter Courtroom →
      </button>
    </div>
  );
}

// Extracted Master Camera Controller
function CameraController({ mode, activePreset, setStage, onSessionReady }) {
  const { camera } = useThree();
  const elapsed   = useRef(0);
  const firedRef  = useRef(false);

  // Pre-allocated vectors — reused every frame, no heap pressure
  const lookTargetRef  = useRef(new THREE.Vector3(0, 2.5, 0));
  const currentLookRef = useRef(new THREE.Vector3());
  
  const presetPosRef = useRef(new THREE.Vector3());
  const presetTargetRef = useRef(new THREE.Vector3());

  useEffect(() => {
    camera.position.set(0, 4.5, 75);
    camera.lookAt(0, 4.5, 0);
  }, [camera]);

  useFrame((_, delta) => {
    const dt = Math.min(delta, 0.1);

    if (mode === 'cinematic') {
      elapsed.current += dt;
      // Slowed down from 6s to 25s for relaxed exterior viewing
      const duration    = 25.0; 
      const progress    = Math.min(elapsed.current / duration, 1.0);
      const easeProgress = 1 - Math.pow(1 - progress, 3);

      let currentStage = 0;
      if      (progress > 0.85) currentStage = 4;
      else if (progress > 0.65) currentStage = 3;
      else if (progress > 0.45) currentStage = 2;
      else if (progress > 0.20) currentStage = 1;

      setStage(prev => (prev !== currentStage ? currentStage : prev));

      if (progress < 1.0) {
        camera.position.copy(CAMERA_CURVE.getPoint(easeProgress));

        const jitter = 0.018 * Math.pow(1 - easeProgress, 2);
        const t = elapsed.current;
        camera.position.x += breathe(t,  0) * jitter;
        camera.position.y += breathe(t, 50) * jitter * 0.4;

        if      (currentStage <= 1)  camera.fov = THREE.MathUtils.lerp(camera.fov, 70, 0.05);
        else if (currentStage === 2) camera.fov = THREE.MathUtils.lerp(camera.fov, 60, 0.05);
        else                         camera.fov = THREE.MathUtils.lerp(camera.fov, 55, 0.05);
        camera.updateProjectionMatrix();

        if (currentStage >= 3) lookTargetRef.current.set(0, 2, -2);
        else                   lookTargetRef.current.set(0, 2.5, 0);

        camera.getWorldDirection(currentLookRef.current);
        currentLookRef.current.add(camera.position);
        currentLookRef.current.lerp(lookTargetRef.current, 0.05);
        camera.lookAt(currentLookRef.current);
      } else {
        if (!firedRef.current) {
          firedRef.current = true;
          onSessionReady();
        }
      }
    } else if (mode === 'preset') {
      // Interpolate smoothly to the selected preset view
      const p = CAMERA_PRESETS[activePreset];
      if (p) {
        presetPosRef.current.set(...p.position);
        presetTargetRef.current.set(...p.target);
        
        camera.position.lerp(presetPosRef.current, 0.03);
        
        camera.getWorldDirection(currentLookRef.current);
        currentLookRef.current.add(camera.position);
        currentLookRef.current.lerp(presetTargetRef.current, 0.04);
        camera.lookAt(currentLookRef.current);

        camera.fov = THREE.MathUtils.lerp(camera.fov, p.fov, 0.04);
        camera.updateProjectionMatrix();
      }
    } else if (mode === 'entering') {
      // Force camera smoothly inside and trigger session
      setStage(4);
      presetPosRef.current.set(0, 2.6, 11.5);
      presetTargetRef.current.set(0, 2.0, -2.0);
      
      camera.position.lerp(presetPosRef.current, 0.04);
      
      camera.getWorldDirection(currentLookRef.current);
      currentLookRef.current.add(camera.position);
      currentLookRef.current.lerp(presetTargetRef.current, 0.05);
      camera.lookAt(currentLookRef.current);

      camera.fov = THREE.MathUtils.lerp(camera.fov, 55, 0.05);
      camera.updateProjectionMatrix();

      if (camera.position.distanceTo(presetPosRef.current) < 0.5 && !firedRef.current) {
        firedRef.current = true;
        onSessionReady();
      }
    }
  });

  return null;
}

// Maps camera Z position to one of 8 cinematic beats
function zToBeat(z) {
  if (z > 65) return 'city_above';
  if (z > 48) return 'descent';
  if (z > 38) return 'plaza_vista';
  if (z > 30) return 'security_gate';
  if (z > 22) return 'staircase';
  if (z > 14) return 'portal';
  if (z > 8)  return 'corridor';
  return 'interior';
}

// Reads camera.z each frame: syncs light progress ref + courtroom store beat/cameraZ.
function TransitionSync({ lightProgressRef }) {
  const { camera } = useThree();
  const setCameraZ = useCourtroomStore(s => s.setCameraZ);
  const setBeat = useCourtroomStore(s => s.setBeat);
  useFrame(() => {
    const z = camera.position.z;
    lightProgressRef.current = 1 - THREE.MathUtils.smoothstep(z, 16, 28);
    setCameraZ(z);
    setBeat(zToBeat(z));
  });
  return null;
}

// Beat-driven cinematic post-processing stack
function CinematicFX() {
  const beat = useCourtroomStore(s => s.beat);
  const isInterior = useCourtroomStore(s => s.isInterior);

  return (
    <EffectComposer multisampling={0}>
      <SMAA />
      <ToneMapping mode={ToneMappingMode.ACES_FILMIC} />
      <DepthOfField
        focusDistance={BEAT_FOCUS_DISTANCE[beat] ?? 0.004}
        focalLength={0.025}
        bokehScale={isInterior ? 2 : 4}
      />
      <Bloom
        luminanceThreshold={0.80}
        luminanceSmoothing={0.9}
        intensity={BEAT_BLOOM_VAL[beat] ?? 0.6}
        mipmapBlur
      />
      <Vignette
        offset={0.35}
        darkness={BEAT_VIGNETTE_VAL[beat] ?? 0.4}
        blendFunction={BlendFunction.NORMAL}
      />
      {beat === 'portal' ? (
        <ChromaticAberration
          offset={[0.002, 0.002]}
          blendFunction={BlendFunction.NORMAL}
        />
      ) : (
        <ChromaticAberration
          offset={[0.00045, 0.00045]}
          radialModulation
          modulationOffset={0.60}
        />
      )}
    </EffectComposer>
  );
}

// Camera shake on held beats — plaza vista and portal threshold
function BeatEffects() {
  const beat = useCourtroomStore(s => s.beat);
  if (beat !== 'plaza_vista' && beat !== 'portal') return null;
  return (
    <CameraShake
      maxYaw={0.005}
      maxPitch={0.003}
      maxRoll={0.002}
      yawFrequency={0.3}
      pitchFrequency={0.2}
      rollFrequency={0.15}
    />
  );
}

export default function CourtroomIntro() {
  const [stage, setStage] = useState(0);
  const [sessionReady, setSessionReady] = useState(false);
  const lightProgressRef = useRef(0);

  const [mode, setMode] = useState('cinematic'); 
  const [activePreset, setActivePreset] = useState('establishing');

  const doorProgress = stage === 2 ? 0.5 : stage >= 3 ? 1.0 : 0;
  const doorsJustOpened = stage === 3;

  return (
    <div style={{ width: '100vw', height: '100vh', position: 'relative', overflow: 'hidden', background: '#0A0C10' }}>
      
      {/* UI Overlay for Exploring Exterior */}
      {!sessionReady && mode !== 'entering' && (
        <ExteriorControls 
           mode={mode}
           setMode={setMode} 
           activePreset={activePreset} 
           setActivePreset={setActivePreset} 
           onEnter={() => setMode('entering')} 
        />
      )}

      {/* 3D World */}
      <Canvas
        shadows="soft"
        gl={{ antialias: true, powerPreference: 'high-performance' }}
        dpr={[1, 1.5]}
      >
        <Suspense fallback={null}>
          <CameraController 
            mode={mode} 
            activePreset={activePreset} 
            setStage={setStage} 
            onSessionReady={() => setSessionReady(true)} 
          />
          <TransitionSync lightProgressRef={lightProgressRef} />

          {stage <= 3 && (
            <group position={[0, -1.5, 14]}>
              <ExteriorScene lightProgressRef={lightProgressRef} />
            </group>
          )}

          {stage >= 2 && (
            <CourtroomScene
              externalCamera={true}
              sessionStarted={sessionReady}
              doorProgress={doorProgress}
              doorsJustOpened={doorsJustOpened}
              lightProgressRef={lightProgressRef}
            />
          )}

          {/* Cinematic post-processing — active throughout, beat-driven parameters */}
          <CinematicFX />
          <BeatEffects />
        </Suspense>
      </Canvas>

      {/* UI Overlay */}
      {sessionReady && <CourtroomHUD visible={true} />}
      
    </div>
  );
}
