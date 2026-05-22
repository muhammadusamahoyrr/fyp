import React, { useRef, useEffect, useState, useMemo } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import { OrbitControls, Environment, PerspectiveCamera, ContactShadows, Instances, Instance } from '@react-three/drei';
import * as THREE from 'three';

const PI = Math.PI;

// ─── Module-level camera constants — single allocation, never recreated ───────
const CAM_REST   = new THREE.Vector3(0, 2.6, 11.5);
const CAM_TARGET = new THREE.Vector3(0, 1.8, -1.0);
const CAM_LOOKAT = new THREE.Vector3(0, 2.0, -2.0);
const CAM_INIT   = new THREE.Vector3(0, 2.8, 22.0);

// ─── Chandelier arm radius ────────────────────────────────────────────────────
const CHANDELIER_R = 0.70;

// ─── Cinematic palette ────────────────────────────────────────────────────────
const C = {
  WD:  '#0A0806', WM:  '#121418', WL:  '#2C1A10', WS:  '#1A1008', WT:  '#4A2810',
  MAR: '#D0D6D6', VEI: '#A0A8A8',
  WAL: '#242832', WAU: '#1A1E26', CEI: '#D6DDE4',
  CAR: '#4A0808',
  BRS: '#C8A238', BRD: '#7E5E22',
  LEA: '#1A0A06',
  STN: '#B8B0A4', STS: '#CAC4B8',
  GLS: '#C8E2F4',
  PAP: '#F6EED8',
  MET: '#7A7868',
};

// ─── Shared material props ────────────────────────────────────────────────────
const MAT = {
  wood:      { roughness: 0.30, metalness: 0.04 },
  woodDark:  { roughness: 0.38, metalness: 0.02 },
  woodGloss: { roughness: 0.18, metalness: 0.08 },
  marble:    { roughness: 0.04, metalness: 0.10 },
  brass:     { roughness: 0.15, metalness: 0.88 },
  brassDim:  { roughness: 0.30, metalness: 0.72 },
  stone:     { roughness: 0.72, metalness: 0.02 },
  leather:   { roughness: 0.76, metalness: 0.00 },
  carpet:    { roughness: 0.96, metalness: 0.00 },
  plaster:   { roughness: 0.90, metalness: 0.00 },
  glass:     { roughness: 0.02, metalness: 0.04, transparent: true, opacity: 0.28 },
  paper:     { roughness: 0.96, metalness: 0.00 },
};

// ─── HDRI error boundary — falls back to dark background if CDN is unreachable ─
class EnvBoundary extends React.Component {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    if (this.state.failed) return <color attach="background" args={['#1A1510']} />;
    return this.props.children;
  }
}

// ─── Floor ────────────────────────────────────────────────────────────────────
function Floor() {
  const hLines = Array.from({ length: 11 }, (_, i) => -13 + i * 2.6);
  const vLines = Array.from({ length: 9  }, (_, i) => -10 + i * 2.5);
  return (
    <group>
      <mesh rotation={[-PI / 2, 0, 0]} receiveShadow>
        <planeGeometry args={[22, 40]} />
        <meshStandardMaterial color={C.MAR} {...MAT.marble} />
      </mesh>
      {hLines.map((z, i) => (
        <mesh key={`h${i}`} rotation={[-PI / 2, 0, 0]} position={[0, 0.003, z]}>
          <planeGeometry args={[22, 0.025]} />
          <meshStandardMaterial color={C.VEI} roughness={0.06} />
        </mesh>
      ))}
      {vLines.map((x, i) => (
        <mesh key={`v${i}`} rotation={[-PI / 2, 0, 0]} position={[x, 0.003, 0]}>
          <planeGeometry args={[0.025, 28]} />
          <meshStandardMaterial color={C.VEI} roughness={0.06} />
        </mesh>
      ))}
      <mesh rotation={[-PI / 2, 0, 0]} position={[0, 0.007, 2]}>
        <planeGeometry args={[2.2, 20]} />
        <meshStandardMaterial color={C.CAR} {...MAT.carpet} />
      </mesh>
      {[-1.14, 1.14].map((x, i) => (
        <mesh key={i} rotation={[-PI / 2, 0, 0]} position={[x, 0.008, 2]}>
          <planeGeometry args={[0.08, 20]} />
          <meshStandardMaterial color="#500808" roughness={0.94} />
        </mesh>
      ))}
    </group>
  );
}

// ─── Architecture ─────────────────────────────────────────────────────────────
function Architecture() {
  const H = 7.0, halfH = H / 2;
  return (
    <group>
      {/* Back wall */}
      <mesh position={[0, halfH, -12]} receiveShadow>
        <boxGeometry args={[22, H, 0.3]} />
        <meshStandardMaterial color={C.WAL} {...MAT.plaster} />
      </mesh>
      <mesh position={[0, 0.88, -11.84]}>
        <boxGeometry args={[21.4, 1.76, 0.22]} />
        <meshStandardMaterial color={C.WM} {...MAT.woodDark} />
      </mesh>
      <mesh position={[0, 1.8, -11.78]}>
        <boxGeometry args={[21.4, 0.12, 0.3]} />
        <meshStandardMaterial color={C.WT} {...MAT.woodGloss} />
      </mesh>
      <mesh position={[0, 5.6, -11.82]}>
        <boxGeometry args={[21.4, 0.09, 0.18]} />
        <meshStandardMaterial color={C.WT} {...MAT.woodGloss} />
      </mesh>

      {/* Left wall */}
      <mesh position={[-11, halfH, 0]} receiveShadow>
        <boxGeometry args={[0.3, H, 26]} />
        <meshStandardMaterial color={C.WAL} {...MAT.plaster} />
      </mesh>
      <mesh position={[-10.84, 0.88, 0]}>
        <boxGeometry args={[0.22, 1.76, 25.4]} />
        <meshStandardMaterial color={C.WM} {...MAT.woodDark} />
      </mesh>
      <mesh position={[-10.78, 1.8, 0]}>
        <boxGeometry args={[0.3, 0.12, 25.4]} />
        <meshStandardMaterial color={C.WT} {...MAT.woodGloss} />
      </mesh>

      {/* Right wall */}
      <mesh position={[11, halfH, 0]} receiveShadow>
        <boxGeometry args={[0.3, H, 26]} />
        <meshStandardMaterial color={C.WAL} {...MAT.plaster} />
      </mesh>
      <mesh position={[10.84, 0.88, 0]}>
        <boxGeometry args={[0.22, 1.76, 25.4]} />
        <meshStandardMaterial color={C.WM} {...MAT.woodDark} />
      </mesh>
      <mesh position={[10.78, 1.8, 0]}>
        <boxGeometry args={[0.3, 0.12, 25.4]} />
        <meshStandardMaterial color={C.WT} {...MAT.woodGloss} />
      </mesh>

      {/* Front wall with doorway */}
      <mesh position={[-7.5, halfH, 20]}>
        <boxGeometry args={[7, H, 0.3]} />
        <meshStandardMaterial color={C.WAL} {...MAT.plaster} />
      </mesh>
      <mesh position={[7.5, halfH, 20]}>
        <boxGeometry args={[7, H, 0.3]} />
        <meshStandardMaterial color={C.WAL} {...MAT.plaster} />
      </mesh>
      <mesh position={[0, 6, 20]}>
        <boxGeometry args={[8, 2, 0.3]} />
        <meshStandardMaterial color={C.WAL} {...MAT.plaster} />
      </mesh>

      {/* Ceiling */}
      <mesh position={[0, H, 0]}>
        <boxGeometry args={[22, 0.24, 26]} />
        <meshStandardMaterial color={C.CEI} roughness={0.96} />
      </mesh>
      {[
        { p: [0, H - 0.28, -12],  a: [22, 0.56, 0.36] },
        { p: [0, H - 0.28,  20],  a: [22, 0.56, 0.36] },
        { p: [-11, H - 0.28, 4],  a: [0.36, 0.56, 32] },
        { p: [ 11, H - 0.28, 4],  a: [0.36, 0.56, 32] },
      ].map(({ p, a }, i) => (
        <mesh key={i} position={p}>
          <boxGeometry args={a} />
          <meshStandardMaterial color={C.CEI} roughness={0.88} />
        </mesh>
      ))}
      {[-7, 0, 7].map((x, i) => (
        <mesh key={`cx${i}`} position={[x, H - 0.13, 1]}>
          <boxGeometry args={[0.38, 0.26, 26]} />
          <meshStandardMaterial color={C.CEI} roughness={0.92} />
        </mesh>
      ))}
      {[-8, -4, 0, 4, 8].map((z, i) => (
        <mesh key={`cz${i}`} position={[0, H - 0.13, z]}>
          <boxGeometry args={[22, 0.26, 0.38]} />
          <meshStandardMaterial color={C.CEI} roughness={0.92} />
        </mesh>
      ))}
      <mesh position={[0, H - 0.01, -1.5]} rotation={[PI / 2, 0, 0]}>
        <torusGeometry args={[1.0, 0.1, 8, 36]} />
        <meshStandardMaterial color="#E8E2D0" roughness={0.88} />
      </mesh>
      <mesh position={[0, H - 0.01, -1.5]} rotation={[PI / 2, 0, 0]}>
        <torusGeometry args={[0.6, 0.07, 8, 28]} />
        <meshStandardMaterial color="#E8E2D0" roughness={0.88} />
      </mesh>
    </group>
  );
}

// ─── Column ───────────────────────────────────────────────────────────────────
function Column({ position }) {
  return (
    <group position={position}>
      <mesh position={[0, 0.22, 0]} receiveShadow>
        <boxGeometry args={[0.58, 0.44, 0.58]} />
        <meshStandardMaterial color={C.STN} {...MAT.stone} />
      </mesh>
      <mesh position={[0, 0.46, 0]} rotation={[PI / 2, 0, 0]}>
        <torusGeometry args={[0.24, 0.032, 6, 20]} />
        <meshStandardMaterial color={C.STS} roughness={0.60} />
      </mesh>
      <mesh position={[0, 3.2, 0]} castShadow receiveShadow>
        <cylinderGeometry args={[0.20, 0.26, 5.48, 16]} />
        <meshStandardMaterial color={C.STS} roughness={0.58} metalness={0.02} />
      </mesh>
      <mesh position={[0, 5.98, 0]}>
        <cylinderGeometry args={[0.30, 0.22, 0.28, 16]} />
        <meshStandardMaterial color={C.STN} roughness={0.62} />
      </mesh>
      <mesh position={[0, 6.16, 0]}>
        <boxGeometry args={[0.66, 0.20, 0.66]} />
        <meshStandardMaterial color={C.STN} roughness={0.65} />
      </mesh>
    </group>
  );
}

function Columns() {
  const xPos = 10.45;
  const positions = [
    [-xPos, 0, -6], [-xPos, 0,  1], [-xPos, 0,  7],
    [ xPos, 0, -6], [ xPos, 0,  1], [ xPos, 0,  7],
  ];
  return <>{positions.map((p, i) => <Column key={i} position={p} />)}</>;
}

// ─── Windows ──────────────────────────────────────────────────────────────────
function Window({ position, side }) {
  const inX = side === 'left' ? 0.52 : -0.52;
  return (
    <group position={position}>
      <mesh>
        <boxGeometry args={[0.22, 3.8, 1.45]} />
        <meshStandardMaterial color={C.WAL} roughness={0.88} />
      </mesh>
      <mesh position={[inX * 0.05, 0, 0]}>
        <boxGeometry args={[0.12, 3.6, 1.22]} />
        <meshStandardMaterial color="#E8E0C8" roughness={0.90} />
      </mesh>
      <mesh position={[inX * 0.03, 0, 0]}>
        <boxGeometry args={[0.09, 3.6, 1.22]} />
        <meshStandardMaterial color={C.CEI} roughness={0.84} />
      </mesh>
      <mesh position={[inX * 0.06, 0.1, 0]}>
        <boxGeometry args={[0.04, 3.3, 1.05]} />
        <meshStandardMaterial color={C.GLS} {...MAT.glass} />
      </mesh>
      <mesh position={[inX * 0.065, 0.4, 0]}>
        <boxGeometry args={[0.048, 0.045, 1.05]} />
        <meshStandardMaterial color={C.CEI} roughness={0.80} />
      </mesh>
      <mesh position={[inX * 0.065, 0.1, 0]}>
        <boxGeometry args={[0.048, 3.3, 0.045]} />
        <meshStandardMaterial color={C.CEI} roughness={0.80} />
      </mesh>
      <mesh position={[inX * 0.14, -1.96, 0]}>
        <boxGeometry args={[0.32, 0.12, 1.60]} />
        <meshStandardMaterial color={C.CEI} roughness={0.78} />
      </mesh>
    </group>
  );
}

function Windows() {
  const Lx = -10.88, Rx = 10.88;
  return (
    <>
      {[-6.2, 1.0, 6.0].map((z, i) => <Window key={`L${i}`} position={[Lx, 3.6, z]} side="left"  />)}
      {[-6.2, 1.0, 6.0].map((z, i) => <Window key={`R${i}`} position={[Rx, 3.6, z]} side="right" />)}
    </>
  );
}

// ─── Judge's Bench — decomposed sub-components ────────────────────────────────

function BenchDais() {
  return (
    <>
      {[
        { y: 0.12, z: 2.0,  w: 12,  d: 5.0, c: '#9A9080' },
        { y: 0.32, z: 1.1,  w: 10,  d: 4.0, c: '#908878' },
        { y: 0.52, z: 0.15, w: 8.2, d: 2.8, c: C.STN    },
      ].map(({ y, z, w, d, c }, i) => (
        <mesh key={i} position={[0, y, z]} receiveShadow castShadow>
          <boxGeometry args={[w, 0.24, d]} />
          <meshStandardMaterial color={c} roughness={0.70} metalness={0.02} />
        </mesh>
      ))}
      <mesh position={[0, 0.645, 0.15]} rotation={[-PI / 2, 0, 0]}>
        <planeGeometry args={[7.8, 2.55]} />
        <meshStandardMaterial color="#5A0808" {...MAT.carpet} />
      </mesh>
    </>
  );
}

function BenchBody() {
  return (
    <>
      <mesh position={[0, 1.38, 0.42]} receiveShadow castShadow>
        <boxGeometry args={[6.0, 1.52, 0.96]} />
        <meshStandardMaterial color={C.WD} {...MAT.woodDark} />
      </mesh>
      {[-2.1, -1.05, 0, 1.05, 2.1].map((x, i) => (
        <mesh key={i} position={[x, 1.38, 0.91]}>
          <boxGeometry args={[0.76, 1.12, 0.07]} />
          <meshStandardMaterial color={C.WM} roughness={0.36} metalness={0.03} />
        </mesh>
      ))}
      {[-2.55, -1.58, -0.53, 0.53, 1.58, 2.55].map((x, i) => (
        <mesh key={i} position={[x, 1.38, 0.89]}>
          <boxGeometry args={[0.11, 1.52, 0.10]} />
          <meshStandardMaterial color={C.WT} {...MAT.woodGloss} />
        </mesh>
      ))}
      <mesh position={[0, 2.16, 0.86]}>
        <boxGeometry args={[6.02, 0.115, 0.13]} />
        <meshStandardMaterial color={C.WT} {...MAT.woodGloss} />
      </mesh>
      <mesh position={[0, 0.71, 0.88]}>
        <boxGeometry args={[6.02, 0.12, 0.16]} />
        <meshStandardMaterial color={C.WT} {...MAT.woodGloss} />
      </mesh>
      <mesh position={[0, 2.22, -0.12]} receiveShadow castShadow>
        <boxGeometry args={[6.1, 0.095, 1.8]} />
        <meshStandardMaterial color={C.WL} roughness={0.22} metalness={0.08} />
      </mesh>
      <mesh position={[0, 2.27, -0.08]}>
        <boxGeometry args={[4.8, 0.01, 1.3]} />
        <meshStandardMaterial color="#1E3A22" roughness={0.84} />
      </mesh>
      <mesh position={[0, 2.18, 0.88]}>
        <boxGeometry args={[6.1, 0.07, 0.09]} />
        <meshStandardMaterial color={C.WT} {...MAT.woodGloss} />
      </mesh>
    </>
  );
}

function BenchBackboard() {
  return (
    <>
      <mesh position={[0, 4.4, -1.45]} receiveShadow castShadow>
        <boxGeometry args={[6.2, 4.6, 0.26]} />
        <meshStandardMaterial color={C.WD} roughness={0.40} metalness={0.03} />
      </mesh>
      {[-2.95, 2.95].map((x, i) => (
        <mesh key={i} position={[x, 4.4, -1.36]}>
          <boxGeometry args={[0.18, 4.6, 0.14]} />
          <meshStandardMaterial color={C.WT} {...MAT.woodGloss} />
        </mesh>
      ))}
      <mesh position={[0, 6.75, -1.42]}>
        <boxGeometry args={[6.56, 0.22, 0.44]} />
        <meshStandardMaterial color={C.WT} {...MAT.woodGloss} />
      </mesh>
      {[-1.5, 0, 1.5].map((x, i) => (
        <mesh key={i} position={[x, 5.2, -1.34]}>
          <boxGeometry args={[1.22, 2.2, 0.07]} />
          <meshStandardMaterial color={C.WM} roughness={0.44} />
        </mesh>
      ))}
      {[-1.5, 0, 1.5].map((x, i) => (
        <mesh key={i} position={[x, 3.1, -1.34]}>
          <boxGeometry args={[1.22, 1.1, 0.07]} />
          <meshStandardMaterial color={C.WM} roughness={0.44} />
        </mesh>
      ))}
      <mesh position={[0, 3.75, -1.34]}>
        <boxGeometry args={[5.8, 0.10, 0.09]} />
        <meshStandardMaterial color={C.WT} {...MAT.woodGloss} />
      </mesh>
      <mesh position={[0, 2.2, -1.38]}>
        <boxGeometry args={[6.2, 0.115, 0.36]} />
        <meshStandardMaterial color={C.WT} {...MAT.woodGloss} />
      </mesh>
    </>
  );
}

function JudicialSeal() {
  return (
    <>
      <mesh position={[0, 5.0, -1.24]} rotation={[PI / 2, 0, 0]}>
        <cylinderGeometry args={[0.68, 0.68, 0.07, 48]} />
        <meshStandardMaterial color={C.BRS} {...MAT.brass} />
      </mesh>
      <mesh position={[0, 5.0, -1.19]} rotation={[PI / 2, 0, 0]}>
        <cylinderGeometry args={[0.52, 0.52, 0.05, 48]} />
        <meshStandardMaterial color={C.BRD} {...MAT.brassDim} />
      </mesh>
      <mesh position={[-0.07, 5.02, -1.15]} rotation={[PI / 2, 0, 0]}>
        <cylinderGeometry args={[0.19, 0.19, 0.04, 24]} />
        <meshStandardMaterial color={C.BRS} {...MAT.brass} />
      </mesh>
      <mesh position={[0.08, 5.02, -1.14]} rotation={[PI / 2, 0, 0]}>
        <cylinderGeometry args={[0.155, 0.155, 0.05, 24]} />
        <meshStandardMaterial color={C.WD} roughness={0.42} />
      </mesh>
      <mesh position={[0.32, 5.04, -1.15]} rotation={[PI / 2, 0, 0]}>
        <cylinderGeometry args={[0.072, 0.072, 0.03, 5]} />
        <meshStandardMaterial color={C.BRS} {...MAT.brass} />
      </mesh>
    </>
  );
}

function BenchFlagPoles() {
  return (
    <>
      {[
        { x: -2.9, flag: '#00631C' },
        { x:  2.9, flag: '#00308F' },
      ].map(({ x, flag }, i) => (
        <group key={i} position={[x, 0.64, -0.85]}>
          <mesh position={[0, 2.5, 0]} castShadow>
            <cylinderGeometry args={[0.026, 0.026, 5.0, 8]} />
            <meshStandardMaterial color={C.BRS} {...MAT.brass} />
          </mesh>
          <mesh position={[0, 5.1, 0]}>
            <sphereGeometry args={[0.075, 12, 12]} />
            <meshStandardMaterial color={C.BRS} {...MAT.brass} />
          </mesh>
          <mesh position={[i === 0 ? -0.35 : 0.35, 4.52, 0]}>
            <boxGeometry args={[0.72, 0.50, 0.01]} />
            <meshStandardMaterial color={flag} roughness={0.88} side={2} />
          </mesh>
        </group>
      ))}
    </>
  );
}

function BenchChair() {
  return (
    <>
      <mesh position={[0, 2.37, -0.55]} castShadow>
        <boxGeometry args={[0.82, 0.112, 0.72]} />
        <meshStandardMaterial color={C.LEA} {...MAT.leather} />
      </mesh>
      <mesh position={[0, 2.30, -0.56]}>
        <boxGeometry args={[0.86, 0.048, 0.76]} />
        <meshStandardMaterial color={C.WD} roughness={0.44} />
      </mesh>
      <mesh position={[0, 3.12, -0.88]} castShadow>
        <boxGeometry args={[0.82, 1.52, 0.112]} />
        <meshStandardMaterial color={C.LEA} {...MAT.leather} />
      </mesh>
      {[-0.36, 0.36].map((x, i) => (
        <mesh key={i} position={[x, 2.50, -0.66]}>
          <boxGeometry args={[0.065, 0.075, 0.60]} />
          <meshStandardMaterial color={C.WD} roughness={0.44} />
        </mesh>
      ))}
      {[[-0.3, -0.26], [-0.3, 0.26], [0.3, -0.26], [0.3, 0.26]].map(([cx, cz], i) => (
        <mesh key={i} position={[cx, 2.0, cz - 0.55]}>
          <cylinderGeometry args={[0.024, 0.024, 0.58, 6]} />
          <meshStandardMaterial color={C.WD} roughness={0.46} />
        </mesh>
      ))}
    </>
  );
}

function DeskAccessories() {
  return (
    <>
      <group position={[1.8, 2.32, 0.15]}>
        <mesh><cylinderGeometry args={[0.09, 0.11, 0.09, 10]} /><meshStandardMaterial color={C.BRS} {...MAT.brass} /></mesh>
        <mesh position={[0, 0.38, 0]}><cylinderGeometry args={[0.018, 0.018, 0.6, 6]} /><meshStandardMaterial color={C.BRS} {...MAT.brass} /></mesh>
        <mesh position={[0, 0.72, 0]} rotation={[PI, 0, 0]}><coneGeometry args={[0.15, 0.26, 12]} /><meshStandardMaterial color="#F0E8D0" roughness={0.72} metalness={0.08} /></mesh>
        <pointLight position={[0, 0.58, 0]} intensity={0.6} color="#FFE0A0" distance={2.5} decay={2} />
      </group>
      <mesh position={[-1.3, 2.36, 0.2]}>
        <cylinderGeometry args={[0.013, 0.013, 0.46, 6]} />
        <meshStandardMaterial color={C.MET} roughness={0.30} metalness={0.78} />
      </mesh>
      <mesh position={[-1.3, 2.60, 0.2]}>
        <sphereGeometry args={[0.040, 10, 10]} />
        <meshStandardMaterial color="#606050" roughness={0.48} metalness={0.68} />
      </mesh>
      <mesh position={[0.3, 2.28, 0.1]}>
        <boxGeometry args={[0.42, 0.013, 0.32]} />
        <meshStandardMaterial color={C.PAP} {...MAT.paper} />
      </mesh>
      <mesh position={[0.14, 2.295, 0.18]}>
        <boxGeometry args={[0.32, 0.01, 0.24]} />
        <meshStandardMaterial color={C.PAP} {...MAT.paper} />
      </mesh>
      <mesh position={[-0.7, 2.37, -0.3]}>
        <boxGeometry args={[0.20, 0.26, 0.30]} />
        <meshStandardMaterial color="#1A3A1A" roughness={0.82} />
      </mesh>
      <mesh position={[0, 2.28, 0.78]}>
        <boxGeometry args={[1.25, 0.07, 0.10]} />
        <meshStandardMaterial color={C.BRS} {...MAT.brass} />
      </mesh>
      <mesh position={[0.85, 2.30, 0.35]} rotation={[0, 0.6, 0]}>
        <boxGeometry args={[0.07, 0.07, 0.24]} />
        <meshStandardMaterial color={C.WM} roughness={0.36} metalness={0.04} />
      </mesh>
      <mesh position={[0.85, 2.30, 0.26]} rotation={[0, 0.6, PI / 2]}>
        <cylinderGeometry args={[0.055, 0.055, 0.18, 10]} />
        <meshStandardMaterial color={C.WD} roughness={0.38} metalness={0.02} />
      </mesh>
      <mesh position={[0.85, 2.235, 0.5]} rotation={[0, 0.4, 0]}>
        <boxGeometry args={[0.22, 0.036, 0.22]} />
        <meshStandardMaterial color={C.WM} roughness={0.38} />
      </mesh>
    </>
  );
}

function JudgeBench({ sessionStarted }) {
  const spotRef = useRef();

  useEffect(() => {
    if (!spotRef.current) return;
    spotRef.current.target.position.set(0, 1.0, -8.5);
    spotRef.current.parent?.add(spotRef.current.target);
    spotRef.current.target.updateMatrixWorld();
  }, []);

  useFrame((_, delta) => {
    if (spotRef.current) {
      const targetIntensity = sessionStarted ? 8.5 : 4.5;
      spotRef.current.intensity = THREE.MathUtils.lerp(
        spotRef.current.intensity, targetIntensity, delta * 2
      );
    }
  });

  return (
    <group position={[0, 0, -8.5]}>
      <BenchDais />
      <BenchBody />
      <BenchBackboard />
      <JudicialSeal />
      <BenchFlagPoles />
      <BenchChair />
      <DeskAccessories />
      <spotLight
        ref={spotRef}
        position={[0, 6.8, -4.0]}
        angle={0.38}
        penumbra={0.62}
        intensity={4.5}
        color="#FFF6E0"
        castShadow
        shadow-mapSize={[1024, 1024]}
        shadow-bias={-0.001}
        decay={1.8}
      />
    </group>
  );
}

// ─── Lawyer Table ─────────────────────────────────────────────────────────────
function LawyerTable({ position, rotation = [0, 0, 0] }) {
  return (
    <group position={position} rotation={rotation}>
      <mesh position={[0, 0.82, 0]} castShadow receiveShadow>
        <boxGeometry args={[3.1, 0.09, 1.2]} />
        <meshStandardMaterial color={C.WL} roughness={0.28} metalness={0.07} />
      </mesh>
      {[0.62, -0.62].map((z, i) => (
        <mesh key={i} position={[0, 0.78, z]}>
          <boxGeometry args={[3.1, 0.065, 0.045]} />
          <meshStandardMaterial color={C.WT} {...MAT.woodGloss} />
        </mesh>
      ))}
      {[[-1.4, -0.48], [-1.4, 0.48], [1.4, -0.48], [1.4, 0.48]].map(([x, z], i) => (
        <mesh key={i} position={[x, 0.39, z]} castShadow>
          <boxGeometry args={[0.09, 0.78, 0.09]} />
          <meshStandardMaterial color={C.WD} roughness={0.44} />
        </mesh>
      ))}
      <mesh position={[0, 0.18, 0]}>
        <boxGeometry args={[2.7, 0.065, 0.075]} />
        <meshStandardMaterial color={C.WD} roughness={0.44} />
      </mesh>
      <mesh position={[-0.6, 0.875, 0.08]}>
        <boxGeometry args={[0.38, 0.013, 0.30]} />
        <meshStandardMaterial color={C.PAP} {...MAT.paper} />
      </mesh>
      <mesh position={[0.6, 0.875, -0.08]}>
        <boxGeometry args={[0.30, 0.013, 0.22]} />
        <meshStandardMaterial color={C.PAP} {...MAT.paper} />
      </mesh>
      <mesh position={[0.08, 0.925, 0.22]}>
        <boxGeometry args={[0.22, 0.19, 0.30]} />
        <meshStandardMaterial color="#1C2C3A" roughness={0.82} />
      </mesh>
      <mesh position={[0, 0.875, 0.57]}>
        <boxGeometry args={[1.0, 0.058, 0.075]} />
        <meshStandardMaterial color={C.BRS} {...MAT.brass} />
      </mesh>
      <mesh position={[-1.15, 0.91, 0.05]}>
        <cylinderGeometry args={[0.058, 0.072, 0.22, 10]} />
        <meshStandardMaterial color="#CCE8F4" roughness={0.02} metalness={0.04} transparent opacity={0.6} />
      </mesh>
      {[-0.85, 0.85].map((x, ci) => (
        <group key={ci} position={[x, 0, 0.98]}>
          <mesh position={[0, 0.48, 0]} castShadow>
            <boxGeometry args={[0.54, 0.075, 0.52]} />
            <meshStandardMaterial color={C.LEA} {...MAT.leather} />
          </mesh>
          <mesh position={[0, 0.82, 0.24]} castShadow>
            <boxGeometry args={[0.54, 0.62, 0.075]} />
            <meshStandardMaterial color={C.LEA} {...MAT.leather} />
          </mesh>
          {[-0.23, 0.23].map((ax, ai) => (
            <mesh key={ai} position={[ax, 0.58, 0.12]}>
              <boxGeometry args={[0.055, 0.055, 0.40]} />
              <meshStandardMaterial color={C.WD} roughness={0.46} />
            </mesh>
          ))}
          {[[-0.21, -0.21], [-0.21, 0.21], [0.21, -0.21], [0.21, 0.21]].map(([cx, cz], i) => (
            <mesh key={i} position={[cx, 0.23, cz]}>
              <cylinderGeometry args={[0.022, 0.022, 0.46, 6]} />
              <meshStandardMaterial color={C.WD} roughness={0.48} />
            </mesh>
          ))}
        </group>
      ))}
    </group>
  );
}

// ─── Witness Stand ────────────────────────────────────────────────────────────
function WitnessStand() {
  return (
    <group position={[-5.8, 0, -7.0]}>
      <mesh position={[0, 0.14, 0]} castShadow receiveShadow>
        <boxGeometry args={[1.82, 0.28, 1.82]} />
        <meshStandardMaterial color={C.STN} roughness={0.66} />
      </mesh>
      <mesh position={[0, 0.88, 0]} castShadow receiveShadow>
        <boxGeometry args={[1.55, 1.24, 1.55]} />
        <meshStandardMaterial color={C.WD} roughness={0.38} metalness={0.04} />
      </mesh>
      <mesh position={[0, 0.88, 0.79]}>
        <boxGeometry args={[1.22, 0.92, 0.075]} />
        <meshStandardMaterial color={C.WM} roughness={0.42} />
      </mesh>
      <mesh position={[0, 1.54, 0]} castShadow receiveShadow>
        <boxGeometry args={[1.62, 0.095, 1.62]} />
        <meshStandardMaterial color={C.WL} roughness={0.26} metalness={0.07} />
      </mesh>
      <mesh position={[0, 1.68, -0.38]} castShadow>
        <boxGeometry args={[0.52, 0.075, 0.50]} />
        <meshStandardMaterial color={C.LEA} {...MAT.leather} />
      </mesh>
      <mesh position={[0, 1.98, -0.58]}>
        <boxGeometry args={[0.52, 0.58, 0.085]} />
        <meshStandardMaterial color={C.LEA} {...MAT.leather} />
      </mesh>
      <mesh position={[0, 1.68, 0.44]}>
        <cylinderGeometry args={[0.011, 0.011, 0.30, 6]} />
        <meshStandardMaterial color={C.MET} roughness={0.28} metalness={0.80} />
      </mesh>
      <mesh position={[0, 1.84, 0.44]}>
        <sphereGeometry args={[0.033, 8, 8]} />
        <meshStandardMaterial color="#606050" roughness={0.48} metalness={0.68} />
      </mesh>
    </group>
  );
}

// ─── Clerk Desk ───────────────────────────────────────────────────────────────
function ClerkDesk() {
  return (
    <group position={[5.8, 0, -7.0]}>
      <mesh position={[0, 0.82, 0]} castShadow receiveShadow>
        <boxGeometry args={[2.1, 0.09, 1.1]} />
        <meshStandardMaterial color={C.WL} roughness={0.30} metalness={0.06} />
      </mesh>
      {[[-0.9, -0.42], [-0.9, 0.42], [0.9, -0.42], [0.9, 0.42]].map(([x, z], i) => (
        <mesh key={i} position={[x, 0.39, z]} castShadow>
          <boxGeometry args={[0.08, 0.78, 0.08]} />
          <meshStandardMaterial color={C.WD} roughness={0.44} />
        </mesh>
      ))}
      <mesh position={[0, 0.875, 0.52]}>
        <boxGeometry args={[0.9, 0.058, 0.075]} />
        <meshStandardMaterial color={C.BRS} {...MAT.brass} />
      </mesh>
      <mesh position={[-0.42, 0.875, -0.1]}>
        <boxGeometry args={[0.34, 0.013, 0.26]} />
        <meshStandardMaterial color={C.PAP} {...MAT.paper} />
      </mesh>
      <group position={[0, 0, 0.78]}>
        <mesh position={[0, 0.48, 0]}>
          <boxGeometry args={[0.52, 0.075, 0.50]} />
          <meshStandardMaterial color={C.LEA} {...MAT.leather} />
        </mesh>
        <mesh position={[0, 0.82, 0.24]}>
          <boxGeometry args={[0.52, 0.62, 0.075]} />
          <meshStandardMaterial color={C.LEA} {...MAT.leather} />
        </mesh>
        {[[-0.21, -0.21], [-0.21, 0.21], [0.21, -0.21], [0.21, 0.21]].map(([cx, cz], i) => (
          <mesh key={i} position={[cx, 0.23, cz]}>
            <cylinderGeometry args={[0.022, 0.022, 0.46, 6]} />
            <meshStandardMaterial color={C.WD} roughness={0.48} />
          </mesh>
        ))}
      </group>
    </group>
  );
}

// ─── Bar Railing — balusters instanced ───────────────────────────────────────
function BarRailing() {
  const balusters = useMemo(() => {
    const xs = [];
    for (let i = 0; i < 34; i++) {
      const x = -7.5 + i * 0.455;
      if (x > -0.7 && x < 0.7) continue;
      xs.push(x);
    }
    return xs;
  }, []);

  return (
    <group position={[0, 0, 2.2]}>
      <mesh position={[0, 1.06, 0]} castShadow>
        <boxGeometry args={[15.5, 0.10, 0.10]} />
        <meshStandardMaterial color={C.WL} roughness={0.28} metalness={0.06} />
      </mesh>
      <mesh position={[0, 0.18, 0]}>
        <boxGeometry args={[15.5, 0.065, 0.065]} />
        <meshStandardMaterial color={C.WL} roughness={0.32} />
      </mesh>
      {/* 34 balusters → 1 draw call */}
      <Instances limit={balusters.length} castShadow>
        <boxGeometry args={[0.045, 0.92, 0.045]} />
        <meshStandardMaterial color={C.WD} roughness={0.46} />
        {balusters.map((x, i) => (
          <Instance key={i} position={[x, 0.52, 0]} />
        ))}
      </Instances>
      {[-0.72, 0.72].map((x, i) => (
        <mesh key={i} position={[x, 0.62, 0]} castShadow>
          <boxGeometry args={[0.115, 1.22, 0.115]} />
          <meshStandardMaterial color={C.WT} {...MAT.woodGloss} />
        </mesh>
      ))}
    </group>
  );
}

// ─── Gallery Bench ────────────────────────────────────────────────────────────
function GalleryBench({ position }) {
  return (
    <group position={position}>
      <mesh position={[0, 0.48, 0]} receiveShadow castShadow>
        <boxGeometry args={[8.5, 0.09, 0.62]} />
        <meshStandardMaterial color={C.WM} roughness={0.52} metalness={0.02} />
      </mesh>
      <mesh position={[0, 0.94, -0.25]} castShadow>
        <boxGeometry args={[8.5, 0.88, 0.09]} />
        <meshStandardMaterial color={C.WM} roughness={0.52} />
      </mesh>
      {[-4.32, 4.32].map((x, i) => (
        <mesh key={i} position={[x, 0.48, 0]} castShadow>
          <boxGeometry args={[0.09, 0.96, 0.62]} />
          <meshStandardMaterial color={C.WL} roughness={0.50} />
        </mesh>
      ))}
      {[-3.2, 0, 3.2].map((x, i) => (
        <mesh key={i} position={[x, 0.24, 0]}>
          <boxGeometry args={[0.095, 0.48, 0.62]} />
          <meshStandardMaterial color={C.WD} roughness={0.52} />
        </mesh>
      ))}
    </group>
  );
}

// ─── Chandelier — arms and candles instanced ──────────────────────────────────
function Chandelier({ position }) {
  const N = 10;

  const armData = useMemo(() =>
    Array.from({ length: N }, (_, i) => {
      const a = (i / N) * PI * 2;
      return {
        a,
        armPos:    [Math.cos(a) * CHANDELIER_R * 0.5, -0.22, Math.sin(a) * CHANDELIER_R * 0.5],
        candlePos: [Math.cos(a) * CHANDELIER_R,       -0.18, Math.sin(a) * CHANDELIER_R],
      };
    }), []);

  return (
    <group position={position}>
      <mesh position={[0, 0.55, 0]}>
        <cylinderGeometry args={[0.025, 0.025, 1.1, 8]} />
        <meshStandardMaterial color={C.BRS} {...MAT.brass} />
      </mesh>
      <mesh position={[0, -0.04, 0]}>
        <cylinderGeometry args={[0.14, 0.18, 0.26, 12]} />
        <meshStandardMaterial color={C.BRS} {...MAT.brass} />
      </mesh>
      <mesh position={[0, -0.22, 0]} rotation={[PI / 2, 0, 0]}>
        <torusGeometry args={[CHANDELIER_R, 0.060, 8, 36]} />
        <meshStandardMaterial color={C.BRS} {...MAT.brass} />
      </mesh>
      <mesh position={[0, -0.22, 0]} rotation={[PI / 2, 0, 0]}>
        <torusGeometry args={[0.36, 0.040, 8, 28]} />
        <meshStandardMaterial color={C.BRS} {...MAT.brass} />
      </mesh>
      <mesh position={[0, -0.72, 0]} rotation={[PI, 0, 0]}>
        <coneGeometry args={[0.115, 0.42, 12]} />
        <meshStandardMaterial color={C.BRS} {...MAT.brass} />
      </mesh>
      {/* Arms — 10 × 1 draw call */}
      <Instances limit={N}>
        <cylinderGeometry args={[0.016, 0.016, CHANDELIER_R, 6]} />
        <meshStandardMaterial color={C.BRS} {...MAT.brass} />
        {armData.map(({ a, armPos }, i) => (
          <Instance key={i} position={armPos} rotation={[0, a, PI / 2]} />
        ))}
      </Instances>
      {/* Candles — 10 × 1 draw call */}
      <Instances limit={N}>
        <cylinderGeometry args={[0.026, 0.026, 0.20, 6]} />
        <meshStandardMaterial color="#FFFEF4" emissive="#FFF8C0" emissiveIntensity={0.4} roughness={0.92} />
        {armData.map(({ candlePos }, i) => (
          <Instance key={i} position={candlePos} />
        ))}
      </Instances>
      <FlickerLight position={[0.36, -0.1, 0]} phaseOffset={0} />
      <FlickerLight position={[0.70, -0.1, 0]} phaseOffset={1.8} />
      <pointLight position={[0, -0.35, 0]} intensity={1.5} color="#FFE090" distance={16} castShadow shadow-mapSize={[512, 512]} decay={1.6} />
    </group>
  );
}

// ─── Flicker Light ────────────────────────────────────────────────────────────
function FlickerLight({ position, phaseOffset }) {
  const lightRef = useRef();
  useFrame(({ clock }) => {
    if (lightRef.current) {
      lightRef.current.intensity = 0.18 + 0.12 * Math.sin(clock.elapsedTime * 4.2 + phaseOffset);
    }
  });
  return <pointLight ref={lightRef} position={position} distance={3} color="#FFD080" decay={2} />;
}

// ─── Double Doors ─────────────────────────────────────────────────────────────
function DoubleDoors({ doorProgress }) {
  const leftDoorRef  = useRef();
  const rightDoorRef = useRef();

  useFrame((_, delta) => {
    if (!leftDoorRef.current || !rightDoorRef.current) return;
    const targetAngle = (PI / 2.2) * doorProgress;
    leftDoorRef.current.rotation.y  = THREE.MathUtils.lerp(leftDoorRef.current.rotation.y,   targetAngle, delta * 3);
    rightDoorRef.current.rotation.y = THREE.MathUtils.lerp(rightDoorRef.current.rotation.y, -targetAngle, delta * 3);
  });

  return (
    <group position={[0, 0, 19.9]}>
      <group ref={leftDoorRef} position={[-4, 0, 0]}>
        <mesh position={[2, 2.5, 0]} castShadow>
          <boxGeometry args={[4, 5, 0.2]} />
          <meshStandardMaterial color={C.WD} {...MAT.woodDark} />
        </mesh>
        <mesh position={[3.6, 2.5, 0.15]}>
          <boxGeometry args={[0.08, 0.6, 0.08]} />
          <meshStandardMaterial color={C.BRS} {...MAT.brass} />
        </mesh>
      </group>
      <group ref={rightDoorRef} position={[4, 0, 0]}>
        <mesh position={[-2, 2.5, 0]} castShadow>
          <boxGeometry args={[4, 5, 0.2]} />
          <meshStandardMaterial color={C.WD} {...MAT.woodDark} />
        </mesh>
        <mesh position={[-3.6, 2.5, 0.15]}>
          <boxGeometry args={[0.08, 0.6, 0.08]} />
          <meshStandardMaterial color={C.BRS} {...MAT.brass} />
        </mesh>
      </group>
    </group>
  );
}

// ─── Dust Particle Burst ──────────────────────────────────────────────────────
function DustBurst({ active }) {
  const pointsRef = useRef();
  const geo = useMemo(() => {
    const geometry = new THREE.BufferGeometry();
    const p = new Float32Array(30 * 3);
    const v = [];
    for (let i = 0; i < 30; i++) {
      p[i * 3]     = (Math.random() - 0.5) * 4;
      p[i * 3 + 1] = Math.random() * 4;
      p[i * 3 + 2] = (Math.random() - 0.5) * 2;
      v.push({
        x: (Math.random() - 0.5) * 0.05,
        y: (Math.random() - 0.2) * 0.02,
        z: (Math.random() - 0.5) * 0.05,
      });
    }
    geometry.setAttribute('position', new THREE.BufferAttribute(p, 3));
    geometry.userData = { velocities: v };
    return geometry;
  }, []);

  // Dispose manually-created geometry on unmount
  useEffect(() => () => geo.dispose(), [geo]);

  useFrame(() => {
    if (!active || !pointsRef.current) return;
    const p = geo.attributes.position;
    const v = geo.userData.velocities;
    for (let i = 0; i < 30; i++) {
      p.setX(i, p.getX(i) + v[i].x);
      p.setY(i, p.getY(i) + v[i].y - 0.005);
      p.setZ(i, p.getZ(i) + v[i].z);
    }
    p.needsUpdate = true;
  });

  if (!active) return null;
  return (
    <points ref={pointsRef} geometry={geo} position={[0, 0, 18]}>
      <pointsMaterial size={0.08} color="#D0D0C0" transparent opacity={0.6} sizeAttenuation />
    </points>
  );
}

// ─── Podium ───────────────────────────────────────────────────────────────────
function Podium({ position }) {
  return (
    <group position={position}>
      <mesh position={[0, 0.62, 0]} castShadow>
        <boxGeometry args={[0.55, 1.24, 0.48]} />
        <meshStandardMaterial color={C.WD} roughness={0.40} metalness={0.03} />
      </mesh>
      <mesh position={[0, 1.25, 0.25]}>
        <boxGeometry args={[0.55, 0.09, 0.08]} />
        <meshStandardMaterial color={C.WT} {...MAT.woodGloss} />
      </mesh>
      <mesh position={[0, 1.25, -0.06]}>
        <boxGeometry args={[0.55, 0.008, 0.58]} />
        <meshStandardMaterial color={C.WL} roughness={0.26} metalness={0.08} />
      </mesh>
      <mesh position={[0, 1.28, 0.2]}>
        <boxGeometry args={[0.32, 0.012, 0.24]} />
        <meshStandardMaterial color={C.PAP} {...MAT.paper} />
      </mesh>
      <mesh position={[0, 0.08, 0]} receiveShadow>
        <cylinderGeometry args={[0.45, 0.50, 0.16, 8]} />
        <meshStandardMaterial color={C.STN} roughness={0.68} />
      </mesh>
    </group>
  );
}

// ─── Interior Light Fader ─────────────────────────────────────────────────────
function LightFader({ lightProgressRef }) {
  const ambRef  = useRef();
  const hemiRef = useRef();
  const keyRef  = useRef();
  const fillRef = useRef();
  const rimRef  = useRef();
  const gallRef = useRef();

  useFrame(() => {
    const p = lightProgressRef?.current ?? 1;
    if (ambRef.current)  ambRef.current.intensity  = 0.25 * p;
    if (hemiRef.current) hemiRef.current.intensity = 0.45 * p;
    if (keyRef.current)  keyRef.current.intensity  = 2.80 * p;
    if (fillRef.current) fillRef.current.intensity = 0.85 * p;
    if (rimRef.current)  rimRef.current.intensity  = 0.65 * p;
    if (gallRef.current) gallRef.current.intensity = 0.60 * p;
  });

  return (
    <>
      <ambientLight ref={ambRef} color="#D6E0F0" intensity={0.25} />
      <hemisphereLight ref={hemiRef} skyColor="#B0C4DE" groundColor="#0F1115" intensity={0.45} />
      <directionalLight
        ref={keyRef}
        position={[-9, 8, 2]}
        intensity={2.8}
        color="#FFF0C8"
        castShadow
        shadow-mapSize={[2048, 2048]}
        shadow-camera-left={-18}
        shadow-camera-right={18}
        shadow-camera-top={14}
        shadow-camera-bottom={-4}
        shadow-camera-far={45}
        shadow-bias={-0.0003}
      />
      <directionalLight ref={fillRef} position={[9, 6, 4]}   intensity={0.85} color="#A0C0FF" />
      <directionalLight ref={rimRef}  position={[0, 4, -14]} intensity={0.65} color="#F0D0A0" />
      <pointLight ref={gallRef} position={[0, 4, 10]} intensity={0.6} color="#FFE8C0" distance={16} decay={2} />
    </>
  );
}

// ─── Main Scene ───────────────────────────────────────────────────────────────
export default function CourtroomScene({
  sessionStarted,
  externalCamera = false,
  doorProgress = 0,
  doorsJustOpened = false,
  lightProgressRef,
}) {
  const { camera } = useThree();
  const [introFinished, setIntroFinished] = useState(false);
  const controlsRef = useRef();

  useFrame((_, delta) => {
    if (externalCamera) return;
    if (!introFinished) {
      if (camera.position.distanceTo(CAM_REST) < 0.1) {
        setIntroFinished(true);
      } else {
        camera.position.lerp(CAM_REST, delta * 0.8);
        camera.lookAt(CAM_LOOKAT);
      }
    } else {
      const distance = camera.position.distanceTo(CAM_TARGET);
      const targetFOV = THREE.MathUtils.mapLinear(distance, 3, 16.5, 48, 82);
      camera.fov = THREE.MathUtils.lerp(camera.fov, targetFOV, delta * 2);
      camera.updateProjectionMatrix(); // single call — duplicate removed
    }
  });

  useEffect(() => {
    if (externalCamera) return;
    camera.position.copy(CAM_INIT);
    camera.lookAt(CAM_LOOKAT);
  }, []);

  return (
    <>
      {!externalCamera && <fog attach="fog" color="#0A0C10" near={10} far={45} />}

      {/* HDRI with offline fallback */}
      <EnvBoundary>
        <Environment preset="apartment" />
      </EnvBoundary>

      <LightFader lightProgressRef={lightProgressRef} />

      <ContactShadows
        position={[0, 0.009, 0]}
        opacity={0.65}
        scale={40}
        blur={2.8}
        far={2.5}
        color="#0A0604"
      />

      <Chandelier position={[0, 6.78, -2.0]} />
      <Chandelier position={[0, 6.78,  5.5]} />

      <Floor />
      <Architecture />
      <Columns />
      <Windows />
      <DoubleDoors doorProgress={doorProgress} />
      <DustBurst active={doorsJustOpened} />

      <JudgeBench sessionStarted={sessionStarted} />
      <WitnessStand />
      <ClerkDesk />
      <LawyerTable position={[-3.5, 0, -3.2]} rotation={[0,  0.06, 0]} />
      <LawyerTable position={[ 3.5, 0, -3.2]} rotation={[0, -0.06, 0]} />
      <Podium position={[0, 0, -5.5]} />

      <BarRailing />
      <GalleryBench position={[0, 0, 3.8]} />
      <GalleryBench position={[0, 0, 5.8]} />
      <GalleryBench position={[0, 0, 7.8]} />

      {!externalCamera && (
        <>
          <PerspectiveCamera makeDefault near={0.1} far={100} />
          <OrbitControls
            ref={controlsRef}
            enabled={introFinished}
            target={[CAM_TARGET.x, CAM_TARGET.y, CAM_TARGET.z]}
            minPolarAngle={0.05}
            maxPolarAngle={PI / 2.02}
            minAzimuthAngle={-PI / 2.5}
            maxAzimuthAngle={ PI / 2.5}
            minDistance={3.8}
            maxDistance={16.5}
            enablePan={false}
            enableDamping
            dampingFactor={0.035}
            rotateSpeed={0.8}
            zoomSpeed={1.2}
          />
        </>
      )}
    </>
  );
}
