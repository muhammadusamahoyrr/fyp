// Flag wave vertex shader — reference implementation
// Active usage: injected via MeshStandardMaterial.onBeforeCompile in ExteriorScene.jsx
// This preserves full PBR lighting while running wave math entirely on the GPU.
//
// Injection point: after `#include <begin_vertex>` so `transformed` (= position copy)
// is already declared and ready to mutate.

uniform float time;

// Amplitude grows from the pole edge (x ≈ -0.5) toward the free edge (x ≈ +1.2).
// Two sine waves at different frequencies create a naturalistic flutter.
float _xFact = position.x + 0.5;
transformed.z += sin(position.y * 3.0 + time * 2.5) * 0.08 * _xFact
               + sin(position.y * 5.2 + time * 3.8) * 0.03 * _xFact;
