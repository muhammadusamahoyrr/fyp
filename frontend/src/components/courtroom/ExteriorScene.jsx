'use client';

import { useRef, useMemo, useEffect } from 'react';
import { useFrame } from '@react-three/fiber';
import { Instances, Instance, Sparkles, Sky as DreiSky, Clouds, Cloud } from '@react-three/drei';
import * as THREE from 'three';
import { useCourtroomStore } from '../../store/courtroomStore';

const PI = Math.PI;

/**
 * ── Realistic GPU flag wave math — based on shaders/flagWave_realistic.glsl ──
 * This update creates smoother, more organic billows that are intense at the hoist
 * and complex towards the fly, matching the reference images. It is injected
 * while preserving full PBR lighting.
 */
// ─── Shrub wind vertex injection — GPU-side, same pattern as FLAG_WAVE_VERT ────
const SHRUB_WIND_VERT = `
  float windFact = (position.y + 0.5) * 0.5;
  transformed.x += sin(time * 2.2 + position.z * 3.0) * 0.04 * windFact;
  transformed.z += cos(time * 1.8 + position.x * 2.5) * 0.03 * windFact;
`;

const FLAG_WAVE_VERT = `
  float _xFact = position.x + 0.5;
  // Primary organic, varied billows (reference shaders/flagWave_realistic.glsl line 10)
  transformed.z += sin(position.y * 2.8 + time * 3.1) * 0.11 * _xFact
                 + sin(position.y * 4.9 + time * 4.2) * 0.04 * _xFact;
  // Secondary high-frequency rippling, focused on the trailing edge (reference shaders/flagWave_realistic.glsl line 14)
  transformed.x += sin(position.y * 1.5 - time * 6.0) * 0.006 * _xFact;
`;

// ─── Shared material constants — tuned for cinematic realism — based on image_29.png palette ────
const M = {
  // Clean, high-roughness white marble with subtle veining
  marble: { color: '#F8F6F1', roughness: 0.12, metalness: 0.01, emissive: '#101010' },
  // Deeper, textured shadows (reference image_29.png line 18 shadows)
  shadowBox: { color: '#252320', roughness: 0.98, metalness: 0.00 },
  // Highly intricate brass/gold for the portal frame
  brassPortal: { color: '#E8CA6A', roughness: 0.14, metalness: 0.96, envMapIntensity: 2.0 },
  // Rich, deep vegetation as seen in the foreground lawns and Margalla Hills
  grass: { color: '#224810', roughness: 0.99, metalness: 0.00 },
  shrub: { color: '#102A04', roughness: 0.99, metalness: 0.00 },
  // Clean modern window glass with warm interior glow
  glass: { color: '#5A7A98', roughness: 0.02, metalness: 0.15, transparent: true, opacity: 0.68, emissive: '#FF9040', emissiveIntensity: 0.25 },
  asphalt: { color: '#1A1C22', roughness: 0.99, metalness: 0.00 },
  pavement: { color: '#CDC8BC', roughness: 0.88, metalness: 0.01 },
  steel: { color: '#A2A4A8', roughness: 0.28, metalness: 0.88 },
  khaki: { color: '#8A7E58', roughness: 0.88, metalness: 0.00 },
  black: { color: '#0F0F0F', roughness: 0.88, metalness: 0.00 },
  skin: { color: '#C89A7A', roughness: 0.94, metalness: 0.00 },
};

// ─── Ground + Constitution Avenue ────────────────────────────────────────────
function Ground() {
  const tiles = useMemo(() => {
    const v = [];
    for (let i = 0; i < 10; i++) v.push({ h: true, x: 0, z: 8 + i * 3.2 });
    for (let i = 0; i < 19; i++) v.push({ h: false, x: -27 + i * 3, z: 24 });
    return v;
  }, []);

  return (
    <group>
      {/* Plaza paving */}
      <mesh rotation={[-PI / 2, 0, 0]} position={[0, 0, 20]} receiveShadow>
        <planeGeometry args={[84, 32]} />
        <meshStandardMaterial {...M.pavement} />
      </mesh>
      {tiles.map(({ h, x, z }, i) => (
        <mesh key={i} rotation={[-PI / 2, 0, 0]} position={[x, 0.002, z]}>
          <planeGeometry args={h ? [84, 0.04] : [0.04, 32]} />
          <meshStandardMaterial color="#B0ABA4" roughness={0.90} />
        </mesh>
      ))}

      {/* Constitution Avenue */}
      <mesh rotation={[-PI / 2, 0, 0]} position={[0, 0, 54]} receiveShadow>
        <planeGeometry args={[130, 24]} />
        <meshStandardMaterial {...M.asphalt} />
      </mesh>
      {Array.from({ length: 10 }, (_, i) => (
        <mesh key={i} rotation={[-PI / 2, 0, 0]} position={[-22.5 + i * 5, 0.003, 54]}>
          <planeGeometry args={[0.2, 24]} />
          <meshStandardMaterial color="#2E2E36" roughness={0.98} />
        </mesh>
      ))}
      {/* Central reservation */}
      <mesh rotation={[-PI / 2, 0, 0]} position={[0, 0.008, 54]} receiveShadow>
        <planeGeometry args={[5.2, 24]} />
        <meshStandardMaterial color="#264C10" roughness={0.99} />
      </mesh>
      {[-2.6, 2.6].map((x, i) => (
        <mesh key={i} rotation={[-PI / 2, 0, 0]} position={[x, 0.016, 54]}>
          <planeGeometry args={[0.16, 24]} />
          <meshStandardMaterial color="#A0A098" roughness={0.84} />
        </mesh>
      ))}

      {/* Lawns */}
      <mesh rotation={[-PI / 2, 0, 0]} position={[-46, 0.006, 16]} receiveShadow>
        <planeGeometry args={[46, 52]} />
        <meshStandardMaterial {...M.grass} />
      </mesh>
      <mesh rotation={[-PI / 2, 0, 0]} position={[46, 0.006, 16]} receiveShadow>
        <planeGeometry args={[46, 52]} />
        <meshStandardMaterial {...M.grass} />
      </mesh>

      {/* Far background */}
      <mesh rotation={[-PI / 2, 0, 0]} position={[0, -0.04, -50]} receiveShadow>
        <planeGeometry args={[400, 120]} />
        <meshStandardMaterial color="#203E0C" roughness={0.99} />
      </mesh>
    </group>
  );
}

// ─── Window recess grid — single draw call per geometry type ─────────────────
function WindowGrid({ cols, rows, W, H, faceZ, x0, y0, dx, dy }) {
  const positions = useMemo(() => {
    const pts = [];
    for (let r = 0; r < rows; r++)
      for (let c = 0; c < cols; c++)
        pts.push([x0 + c * dx, y0 + r * dy, faceZ]);
    return pts;
  }, [cols, rows, faceZ, x0, y0, dx, dy]);

  return (
    <>
      {/* All recess boxes — 1 draw call */}
      <Instances limit={positions.length} castShadow>
        <boxGeometry args={[W, H, 0.48]} />
        <meshStandardMaterial {...M.shadowBox} />
        {positions.map(([x, y, z], i) => (
          <Instance key={i} position={[x, y, z - 0.24]} />
        ))}
      </Instances>
      {/* All glass panes — 1 draw call */}
      <Instances limit={positions.length}>
        <boxGeometry args={[W * 0.82, H * 0.82, 0.04]} />
        <meshStandardMaterial {...M.glass} />
        {positions.map(([x, y, z], i) => (
          <Instance key={i} position={[x, y, z + 0.02]} />
        ))}
      </Instances>
    </>
  );
}

// ─── Central Block ────────────────────────────────────────────────────────────
function CentralBlock() {
  const W = 24, H = 20, D = 12, fZ = D / 2;
  return (
    <group>
      <mesh position={[0, H / 2, 0]} receiveShadow castShadow>
        <boxGeometry args={[W, H, D]} />
        <meshStandardMaterial {...M.marble} />
      </mesh>

      {/* Attic section */}
      <mesh position={[0, H + 0.70, 0]} castShadow>
        <boxGeometry args={[W + 0.6, 1.40, D + 0.6]} />
        <meshStandardMaterial color="#EAE7DE" roughness={0.88} />
      </mesh>
      <mesh position={[0, H + 1.44, 0]}>
        <boxGeometry args={[W + 0.4, 0.18, D + 0.4]} />
        <meshStandardMaterial color="#D4D0C8" roughness={0.90} />
      </mesh>

      {/* Decorative horizontal bands */}
      {[3.0, 6.5, 10.0, 13.5, 17.0].map((y, i) => (
        <mesh key={i} position={[0, y, fZ + 0.18]}>
          <boxGeometry args={[W + 0.2, 0.48, 0.40]} />
          <meshStandardMaterial color="#DAD6CF" roughness={0.88} />
        </mesh>
      ))}

      {/* Windows */}
      <WindowGrid cols={3} rows={4} W={1.7} H={1.5}
        faceZ={fZ + 0.04} x0={-9.8} y0={4.0} dx={3.4} dy={3.5} />
      <WindowGrid cols={3} rows={4} W={1.7} H={1.5}
        faceZ={fZ + 0.04} x0={3.6} y0={4.0} dx={3.4} dy={3.5} />

      {/* Jali screens */}
      {[-3.2, 3.2].map((x, i) => (
        <mesh key={i} position={[x, 4.0, fZ + 0.04]}>
          <boxGeometry args={[2.2, 7.6, 0.28]} />
          <meshStandardMaterial {...M.shadowBox} />
        </mesh>
      ))}
      {/* Central panel behind portal */}
      <mesh position={[0, 3.4, fZ + 0.04]}>
        <boxGeometry args={[5.0, 6.4, 0.28]} />
        <meshStandardMaterial color="#403C38" roughness={0.98} />
      </mesh>

      {/* Overhanging central portico roof */}
      <mesh position={[0, 8.2, fZ + 3.0]} castShadow>
        <boxGeometry args={[15, 1.0, 6.2]} />
        <meshStandardMaterial color="#DCD8D4" roughness={0.90} />
      </mesh>
      {/* Intricate brass/gold portal frame (image_29.png Line 19 focus) */}
      <mesh position={[0, 7.72, fZ + 3.5]}>
        <boxGeometry args={[14.6, 0.06, 5.4]} />
        <meshStandardMaterial {...M.brassPortal} />
      </mesh>
      <mesh position={[0, 8.24, fZ + 6.0]}>
        <boxGeometry args={[15, 1.12, 0.30]} />
        <meshStandardMaterial color="#CDC9C0" roughness={0.90} />
      </mesh>

      {/* Decorative vertical columns flanking portal */}
      {[-6.0, 6.0].map((x, i) => (
        <group key={i} position={[x, 0, fZ + 1.2]}>
          <mesh position={[0, 4.1, 0]} castShadow receiveShadow>
            <boxGeometry args={[2.4, 8.2, 2.6]} />
            <meshStandardMaterial color="#EAE7E0" roughness={0.86} />
          </mesh>
          <mesh position={[0, 8.3, 0]}>
            <boxGeometry args={[2.5, 0.24, 2.7]} />
            <meshStandardMaterial color="#D8D6CE" roughness={0.90} />
          </mesh>
        </group>
      ))}
      {[-10.0, 10.0].map((x, i) => (
        <mesh key={i} position={[x, 4.1, fZ + 0.8]} castShadow>
          <boxGeometry args={[2.0, 8.2, 1.8]} />
          <meshStandardMaterial color="#EAE7E0" roughness={0.86} />
        </mesh>
      ))}
    </group>
  );
}

// ─── Connector blocks ─────────────────────────────────────────────────────────
function Connector({ sign }) {
  return (
    <mesh position={[sign * (12 + 1.6), 7.0, 0.5]} receiveShadow castShadow>
      <boxGeometry args={[3.2, 14, 11]} />
      <meshStandardMaterial color="#F0EEE8" roughness={0.84} />
    </mesh>
  );
}

// ─── Side wings ───────────────────────────────────────────────────────────────
function Wing({ sign }) {
  const ox = sign * (12 + 3.2 + 7);
  const W = 14, H = 10, D = 10, fZ = D / 2;
  return (
    <group position={[ox, 0, 1.2]}>
      <mesh position={[0, H / 2, 0]} receiveShadow castShadow>
        <boxGeometry args={[W, H, D]} />
        <meshStandardMaterial {...M.marble} />
      </mesh>
      <mesh position={[0, H + 0.52, 0]}>
        <boxGeometry args={[W + 0.4, 1.04, D + 0.4]} />
        <meshStandardMaterial color="#EEEAE2" roughness={0.88} />
      </mesh>
      {/* bands */}
      {[2.4, 4.9, 7.4].map((y, i) => (
        <mesh key={i} position={[0, y, fZ + 0.14]}>
          <boxGeometry args={[W + 0.1, 0.40, 0.32]} />
          <meshStandardMaterial color="#DAD6CF" roughness={0.88} />
        </mesh>
      ))}
      <WindowGrid cols={3} rows={3} W={1.6} H={1.3}
        faceZ={fZ + 0.04} x0={-3.2} y0={1.6} dx={3.2} dy={2.7} />
    </group>
  );
}

// ─── Grand staircase ──────────────────────────────────────────────────────────
function GrandStaircase() {
  const N = 9, sH = 0.28, sD = 1.1, W = 18;
  return (
    <group position={[0, 0, 6]}>
      {Array.from({ length: N }, (_, i) => (
        <group key={i}>
          <mesh position={[0, i * sH + sH / 2, (N - 1 - i) * sD + sD / 2]} receiveShadow castShadow>
            <boxGeometry args={[W - i * 0.28, sH, sD + 0.02]} />
            <meshStandardMaterial color="#EAE7D8" roughness={0.84} metalness={0.03} />
          </mesh>
          <mesh position={[0, i * sH + sH, (N - 1 - i) * sD + sD]}>
            <boxGeometry args={[W - i * 0.28, 0.05, 0.05]} />
            <meshStandardMaterial color="#D8D4CC" roughness={0.76} />
          </mesh>
        </group>
      ))}
    </group>
  );
}

// ─── Portal Corridor ──────────────────────────────────────────────────────────
function PortalCorridor() {
  const cZ = 2.0, cW = 7.0, cH = 5.6, cD = 8.0;
  const flY = 2.52;
  const cY = flY + cH / 2;
  const dark = { color: '#100E0C', roughness: 0.98, metalness: 0.00 };
  const darker = { color: '#0C0A08', roughness: 1.00, metalness: 0.00 };
  return (
    <group>
      <mesh position={[0, flY, cZ]} receiveShadow>
        <boxGeometry args={[cW, 0.06, cD]} />
        <meshStandardMaterial color="#201C14" roughness={0.92} />
      </mesh>
      <mesh position={[0, flY + cH, cZ]}>
        <boxGeometry args={[cW, 0.08, cD]} />
        <meshStandardMaterial {...darker} />
      </mesh>
      <mesh position={[-cW / 2, cY, cZ]}>
        <boxGeometry args={[0.12, cH, cD]} />
        <meshStandardMaterial {...dark} />
      </mesh>
      <mesh position={[cW / 2, cY, cZ]}>
        <boxGeometry args={[0.12, cH, cD]} />
        <meshStandardMaterial {...dark} />
      </mesh>
      <mesh position={[0, cY, -2]}>
        <boxGeometry args={[cW, cH, 0.12]} />
        <meshStandardMaterial {...darker} />
      </mesh>
    </group>
  );
}

function Building() {
  return (
    <group>
      <Connector sign={-1} />
      <Connector sign={1} />
      <Wing sign={-1} />
      <Wing sign={1} />
      <CentralBlock />
      <GrandStaircase />
      <PortalCorridor />
    </group>
  );
}

// ─── Pakistan flag — GPU wave via onBeforeCompile ────────────────────────────
// The new FLAG_WAVE_VERT (line 12) is used, referencing shaders/flagWave_realistic.glsl
function Flag({ position }) {
  // Use higher subdivision (24, 16) for smoother realistic billows
  const geo = useMemo(() => new THREE.PlaneGeometry(2.4, 1.5, 24, 16), []);

  const mat = useMemo(() => {
    const m = new THREE.MeshStandardMaterial({
      // Deep Pakistan Green
      color: '#013D18',
      roughness: 0.88,
      side: THREE.DoubleSide,
    });
    m.onBeforeCompile = (shader) => {
      shader.uniforms.time = { value: 0 };
      // Prepend uniform declaration before Three.js vertex preamble
      shader.vertexShader = 'uniform float time;\n' + shader.vertexShader;
      // Inject wave after position is copied into `transformed`
      shader.vertexShader = shader.vertexShader.replace(
        '#include <begin_vertex>',
        `#include <begin_vertex>
        ${FLAG_WAVE_VERT}`
      );
      m.userData.shader = shader;
    };
    return m;
  }, []);

  useFrame(({ clock }) => {
    if (mat.userData.shader) {
      mat.userData.shader.uniforms.time.value = clock.elapsedTime;
    }
  });

  useEffect(() => () => { geo.dispose(); mat.dispose(); }, [geo, mat]);

  return (
    <group position={position}>
      {/* Pole */}
      <mesh position={[0, 6.5, 0]} castShadow>
        <cylinderGeometry args={[0.06, 0.075, 13, 8]} />
        <meshStandardMaterial {...M.steel} />
      </mesh>
      {/* Finial */}
      <mesh position={[0, 13.15, 0]}>
        <sphereGeometry args={[0.13, 8, 8]} />
        <meshStandardMaterial {...M.brassPortal} />
      </mesh>
      {/* Green field — wave shader active */}
      <mesh position={[1.2, 11.8, 0]} geometry={geo} material={mat} castShadow />
      {/* White hoist stripe */}
      <mesh position={[0.08, 11.8, 0.015]}>
        <planeGeometry args={[0.42, 1.5]} />
        <meshStandardMaterial color="#F8F6F0" roughness={0.92} side={THREE.DoubleSide} />
      </mesh>
    </group>
  );
}

function Flagpoles() {
  return <>{[-20, -10, 10, 20].map((x, i) => <Flag key={i} position={[x, 0, 22]} />)}</>;
}

// ─── Security gate — animated boom arm reacts to camera approach ──────────────
function SecurityGate() {
  const boomRef = useRef();
  const gateOpen = useCourtroomStore(s => s.gateOpen);

  useFrame(() => {
    if (!boomRef.current) return;
    // Pivot group rotates from 0 (horizontal/closed) to PI/2 (vertical/open)
    const target = gateOpen ? PI / 2 : 0;
    boomRef.current.rotation.z = THREE.MathUtils.lerp(
      boomRef.current.rotation.z,
      target,
      0.06
    );
  });

  return (
    <group position={[0, 0, 34]}>
      {[-9, 9].map((x, i) => (
        <group key={i} position={[x, 0, 0]}>
          <mesh position={[0, 1.28, 0]} castShadow>
            <boxGeometry args={[2.2, 2.56, 2.2]} />
            <meshStandardMaterial color="#EEEAE0" roughness={0.90} emissive="#050505" />
          </mesh>
          <mesh position={[0, 2.66, 0]}>
            <boxGeometry args={[2.4, 0.22, 2.4]} />
            <meshStandardMaterial color="#305018" roughness={0.92} />
          </mesh>
          <mesh position={[0, 1.28, 1.12]}>
            <boxGeometry args={[1.6, 0.96, 0.05]} />
            <meshStandardMaterial color="#7A9ABA" roughness={0.03} transparent opacity={0.72} />
          </mesh>
        </group>
      ))}
      {Array.from({ length: 14 }, (_, i) => (
        <mesh key={i} position={[-15.6 + i * 2.4, 0.52, 0]} castShadow>
          <boxGeometry args={[0.16, 1.04, 0.16]} />
          <meshStandardMaterial {...M.steel} />
        </mesh>
      ))}
      <mesh position={[0, 1.06, 0]}>
        <boxGeometry args={[33, 0.10, 0.10]} />
        <meshStandardMaterial color="#686C70" roughness={0.38} metalness={0.80} />
      </mesh>
      {/* Hinge post */}
      <mesh position={[-3.6, 0.72, 0.2]} castShadow>
        <boxGeometry args={[0.24, 1.44, 0.24]} />
        <meshStandardMaterial color="#404246" roughness={0.60} metalness={0.65} />
      </mesh>
      {/* Boom arm — pivot at post top, extends +X when closed, rotates up when open */}
      <group ref={boomRef} position={[-3.6, 1.32, 0.2]}>
        <mesh position={[3.5, 0, 0]} rotation={[0, 0, PI / 2]}>
          <cylinderGeometry args={[0.045, 0.045, 7, 6]} />
          <meshStandardMaterial color="#D83030" roughness={0.60} />
        </mesh>
      </group>
      {/* Indicator light — green open, red closed */}
      <pointLight
        position={[-3.6, 2.8, 0.2]}
        color={gateOpen ? '#4DD4A3' : '#FF6B7A'}
        intensity={0.8}
        distance={4}
      />
    </group>
  );
}

// ─── Ornamental shrubs — instanced, GPU wind shader ───────────────────────────
function Shrubs() {
  const pts = [
    [-26, 0, 16], [-21, 0, 18], [-16, 0, 16],
    [16, 0, 16], [21, 0, 18], [26, 0, 16],
    [-12, 0, 26], [12, 0, 26], [-28, 0, 26], [28, 0, 26],
  ];

  const shaderRef = useRef(null);

  useFrame(({ clock }) => {
    if (shaderRef.current) {
      shaderRef.current.uniforms.time.value = clock.elapsedTime;
    }
  });

  return (
    <>
      {/* Foliage spheres with wind animation — 1 draw call */}
      <Instances limit={pts.length} castShadow>
        <sphereGeometry args={[0.72, 8, 6]} />
        <meshStandardMaterial
          color="#102A04"
          roughness={0.99}
          metalness={0}
          onBeforeCompile={(shader) => {
            shader.uniforms.time = { value: 0 };
            shader.vertexShader = 'uniform float time;\n' + shader.vertexShader;
            shader.vertexShader = shader.vertexShader.replace(
              '#include <begin_vertex>',
              `#include <begin_vertex>\n${SHRUB_WIND_VERT}`
            );
            shaderRef.current = shader;
          }}
        />
        {pts.map(([x, y, z], i) => (
          <Instance key={i} position={[x, y + 0.68, z]} />
        ))}
      </Instances>
      {/* Trunks — 1 draw call */}
      <Instances limit={pts.length}>
        <cylinderGeometry args={[0.18, 0.22, 0.38, 6]} />
        <meshStandardMaterial color="#4A3A24" roughness={0.98} />
        {pts.map(([x, y, z], i) => (
          <Instance key={i} position={[x, y + 0.20, z]} />
        ))}
      </Instances>
    </>
  );
}

// ─── Margalla Hills (Deep Forest Green, image_29.png line 21) ─────────────────
function MargallaHills() {
  const ridges = [
    [-55, -68, 78, 24, 26], [8, -72, 96, 30, 22], [68, -62, 68, 20, 28],
    [-18, -82, 108, 34, 18], [48, -76, 82, 26, 20], [-82, -70, 58, 18, 24],
    [30, -88, 90, 28, 16], [-35, -60, 60, 14, 20],
  ];
  const feet = [
    [-42, -52, 52, 10, 18], [42, -52, 52, 10, 18],
    [0, -54, 64, 12, 14], [-22, -46, 44, 8, 16], [22, -46, 44, 8, 16],
  ];
  return (
    <>
      {ridges.map(([x, z, w, h, d], i) => (
        <mesh key={i} position={[x, h / 2 - 2, z]} receiveShadow>
          <boxGeometry args={[w, h, d]} />
          <meshStandardMaterial color={i % 2 === 0 ? '#103A04' : '#144006'} roughness={0.99} />
        </mesh>
      ))}
      {feet.map(([x, z, w, h, d], i) => (
        <mesh key={`f${i}`} position={[x, h / 2 - 1, z]} receiveShadow>
          <boxGeometry args={[w, h, d]} />
          <meshStandardMaterial color="#163C08" roughness={0.99} />
        </mesh>
      ))}
    </>
  );
}

// ─── Background buildings ─────────────────────────────────────────────────────
function BackgroundBuildings() {
  return (
    <>
      <group position={[-58, 0, -38]}>
        <mesh position={[0, 5.5, 0]}>
          <boxGeometry args={[32, 11, 20]} />
          <meshStandardMaterial color="#EEEAE2" roughness={0.92} transparent opacity={0.82} />
        </mesh>
        <mesh position={[0, 11.6, 0]}>
          <cylinderGeometry args={[5.2, 5.2, 2.4, 16]} />
          <meshStandardMaterial color="#F2F0E8" roughness={0.88} transparent opacity={0.80} />
        </mesh>
        <mesh position={[0, 14.2, 0]}>
          <sphereGeometry args={[5.6, 16, 10, 0, PI * 2, 0, PI / 2]} />
          <meshStandardMaterial color="#F8F6F0" roughness={0.84} transparent opacity={0.78} />
        </mesh>
      </group>
      <group position={[58, 0, -36]}>
        <mesh position={[0, 6.5, 0]}>
          <boxGeometry args={[26, 13, 16]} />
          <meshStandardMaterial color="#EEEAE0" roughness={0.94} transparent opacity={0.78} />
        </mesh>
        <mesh position={[0, 13.2, 0]}>
          <boxGeometry args={[26.4, 1.0, 16.4]} />
          <meshStandardMaterial color="#F2EEE4" roughness={0.92} transparent opacity={0.78} />
        </mesh>
      </group>
    </>
  );
}

// ─── Atmospheric sky — Preetham model matched to golden-hour sun direction ────
function AtmosphericSky() {
  return (
    <>
      <DreiSky
        distance={450}
        sunPosition={[70, 30, 20]}
        inclination={0.52}
        azimuth={0.18}
        mieCoefficient={0.01}
        mieDirectionalG={0.87}
        rayleigh={1.2}
        turbidity={5.0}
      />
      <Clouds>
        <Cloud
          position={[0, 80, -60]}
          speed={0.1}
          opacity={0.35}
          color="#F8F4EE"
          scale={12}
        />
      </Clouds>
    </>
  );
}

// ─── Human figures ────────────────────────────────────────────────────────────
function Lawyer({ position, ry = 0 }) {
  return (
    <group position={position} rotation={[0, ry, 0]}>
      <mesh position={[0, 1.02, 0]} castShadow>
        <boxGeometry args={[0.36, 1.04, 0.24]} />
        <meshStandardMaterial {...M.black} />
      </mesh>
      {/* Court collar */}
      <mesh position={[0, 1.56, 0.13]}>
        <boxGeometry args={[0.18, 0.12, 0.04]} />
        <meshStandardMaterial color="#FAF6F0" roughness={0.90} />
      </mesh>
      <mesh position={[0, 1.78, 0]} castShadow>
        <sphereGeometry args={[0.16, 8, 7]} />
        <meshStandardMaterial {...M.skin} />
      </mesh>
      {[-0.10, 0.10].map((x, i) => (
        <mesh key={i} position={[x, 0.30, 0]} castShadow>
          <boxGeometry args={[0.16, 0.60, 0.20]} />
          <meshStandardMaterial {...M.black} />
        </mesh>
      ))}
      {/* Briefcase */}
      <mesh position={[0.26, 0.90, 0.02]} castShadow>
        <boxGeometry args={[0.30, 0.22, 0.10]} />
        <meshStandardMaterial color="#4A3A18" roughness={0.76} />
      </mesh>
    </group>
  );
}

function Police({ position, ry = 0 }) {
  return (
    <group position={position} rotation={[0, ry, 0]}>
      <mesh position={[0, 1.02, 0]} castShadow>
        <boxGeometry args={[0.36, 1.04, 0.24]} />
        <meshStandardMaterial {...M.khaki} />
      </mesh>
      <mesh position={[0, 1.78, 0]} castShadow>
        <sphereGeometry args={[0.16, 8, 7]} />
        <meshStandardMaterial {...M.skin} />
      </mesh>
      {/* Beret */}
      <mesh position={[0, 1.96, 0]}>
        <cylinderGeometry args={[0.18, 0.16, 0.14, 8]} />
        <meshStandardMaterial color="#706A48" roughness={0.92} />
      </mesh>
      {[-0.10, 0.10].map((x, i) => (
        <mesh key={i} position={[x, 0.30, 0]} castShadow>
          <boxGeometry args={[0.16, 0.60, 0.20]} />
          <meshStandardMaterial {...M.khaki} />
        </mesh>
      ))}
    </group>
  );
}

function People() {
  return (
    <>
      <Lawyer position={[-2.2, 0.42, 13.8]} ry={PI} />
      <Lawyer position={[1.4, 1.12, 11.4]} ry={PI} />
      <Lawyer position={[-0.6, 1.82, 9.0]} ry={PI} />
      <Lawyer position={[2.8, 0.14, 15.0]} ry={PI + 0.25} />
      <Lawyer position={[-14, 0, 21]} ry={PI * 0.7} />
      <Lawyer position={[15, 0, 23]} ry={PI * 1.3} />
      <Police position={[-6.8, 2.52, 6.5]} ry={PI * 0.5} />
      <Police position={[6.8, 2.52, 6.5]} ry={-PI * 0.5} />
    </>
  );
}

// ─── Pigeons — individual with wing-flap animation ───────────────────────────
function Pigeon({ position, phase }) {
  const leftWingRef = useRef();
  const rightWingRef = useRef();

  useFrame(({ clock }) => {
    const flap = Math.sin(clock.elapsedTime * 6 + phase) * 0.4;
    if (leftWingRef.current) leftWingRef.current.rotation.z = flap;
    if (rightWingRef.current) rightWingRef.current.rotation.z = -flap;
  });

  const [x, y, z] = position;
  return (
    <group position={[x, y, z]}>
      <mesh position={[0, 0.07, 0]}>
        <boxGeometry args={[0.20, 0.14, 0.28]} />
        <meshStandardMaterial color="#AAA8A6" roughness={0.96} />
      </mesh>
      <mesh position={[0, 0.18, 0.11]}>
        <sphereGeometry args={[0.08, 6, 5]} />
        <meshStandardMaterial color="#9C9A98" roughness={0.94} />
      </mesh>
      <group ref={leftWingRef} position={[-0.10, 0.07, 0]}>
        <mesh position={[-0.12, 0, 0]}>
          <boxGeometry args={[0.24, 0.04, 0.20]} />
          <meshStandardMaterial color="#9A9896" roughness={0.96} />
        </mesh>
      </group>
      <group ref={rightWingRef} position={[0.10, 0.07, 0]}>
        <mesh position={[0.12, 0, 0]}>
          <boxGeometry args={[0.24, 0.04, 0.20]} />
          <meshStandardMaterial color="#9A9896" roughness={0.96} />
        </mesh>
      </group>
    </group>
  );
}

function Pigeons() {
  const spots = [
    [3.2, 8.8, 6.2], [-1.8, 8.8, 6.2], [7.5, 8.8, 6.2],
    [-7.0, 8.8, 6.2], [1.0, 8.8, 6.2], [-9.2, 10.6, 6.2],
    [5.8, 10.6, 6.2], [-3.0, 10.5, 6.2],
  ];
  return (
    <>
      {spots.map((pos, i) => (
        <Pigeon key={i} position={pos} phase={i * 1.2} />
      ))}
    </>
  );
}

// ─── Atmospheric dust motes — GPU shader via Sparkles — Based on image_29.png golden hour ────────────────────────
function DustMotes() {
  return (
    <Sparkles
      count={65}
      position={[0, 12, 8]}
      scale={[65, 24, 38]}
      size={2.2}
      color="#FBF2D8" // Warm golden dust
      opacity={0.48}
      speed={0.20}
    />
  );
}

// ─── Lighting — Deeper, warmer golden hour as seen in image_29.png ─────────────────────────────────────────────────────────────────
function Lighting({ lightProgressRef }) {
  const sunRef = useRef();
  const fillRef = useRef();
  const bounceRef = useRef();
  const ambRef = useRef();
  const hemiRef = useRef();

  useFrame(() => {
    const dim = 1 - (lightProgressRef?.current ?? 0);
    // Reference image_29.png line 21 focus on intense late light
    if (sunRef.current) sunRef.current.intensity = 3.8 * dim;
    if (fillRef.current) fillRef.current.intensity = 0.72 * dim;
    if (bounceRef.current) bounceRef.current.intensity = 0.28 * dim;
    if (ambRef.current) ambRef.current.intensity = 0.60 * dim;
    if (hemiRef.current) hemiRef.current.intensity = 0.62 * dim;
  });

  return (
    <>
      <ambientLight ref={ambRef} color="#CADBEC" intensity={0.60} />
      <hemisphereLight ref={hemiRef} skyColor="#BBDDFC" groundColor="#305A12" intensity={0.62} />
      <directionalLight
        ref={sunRef}
        position={[70, 30, 20]}
        intensity={3.8}
        color="#FFF0DA" // Deep warm golden
        castShadow
        shadow-mapSize={[2048, 2048]}
        shadow-camera-left={-90}
        shadow-camera-right={90}
        shadow-camera-top={65}
        shadow-camera-bottom={-25}
        shadow-camera-far={220}
        shadow-bias={-0.00015}
      />
      <directionalLight ref={fillRef} position={[-42, 24, 10]} intensity={0.72} color="#C4DEFC" />
      <directionalLight ref={bounceRef} position={[0, -8, 30]} intensity={0.28} color="#F8F6F1" />
    </>
  );
}

// ─── Root export ──────────────────────────────────────────────────────────────
export default function ExteriorScene({ lightProgressRef }) {
  return (
    <group>
      <Lighting lightProgressRef={lightProgressRef} />
      <AtmosphericSky />
      <Ground />
      <Building />
      <Flagpoles />
      <SecurityGate />
      <Shrubs />
      <MargallaHills />
      <BackgroundBuildings />
      <People />
      <Pigeons />
      <DustMotes />
    </group>
  );
}