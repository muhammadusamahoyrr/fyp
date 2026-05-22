'use client';
import { Suspense, useRef } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import {
    useGLTF,
    OrbitControls,
    ContactShadows,
    Environment,
    Center,
} from '@react-three/drei';

function CourthouseModel() {
    const { scene } = useGLTF('/courthouse.glb');
    const ref = useRef();
    useFrame(({ clock }) => {
        if (ref.current) ref.current.rotation.y = clock.elapsedTime * 0.10;
    });
    return <primitive ref={ref} object={scene} dispose={null} />;
}

function FallbackBox() {
    return (
        <mesh>
            <boxGeometry args={[1, 1, 1]} />
            <meshStandardMaterial color="#334155" />
        </mesh>
    );
}

useGLTF.preload('/courthouse.glb');

export default function CourthouseViewer({ height = 300 }) {
    return (
        <Canvas
            shadows
            camera={{ position: [18, 8, 22], fov: 38 }}
            style={{ width: '100%', height, display: 'block' }}
            gl={{ antialias: true, alpha: true }}
        >
            {/* Warm key light from upper-left (golden hour) */}
            <directionalLight
                position={[12, 18, 10]}
                intensity={3.2}
                color="#ffe8b0"
                castShadow
                shadow-mapSize={[1024, 1024]}
                shadow-camera-near={0.5}
                shadow-camera-far={80}
                shadow-camera-left={-20}
                shadow-camera-right={20}
                shadow-camera-top={20}
                shadow-camera-bottom={-20}
            />
            {/* Cool sky fill from right */}
            <directionalLight position={[-10, 10, -8]} intensity={1.0} color="#9bbfff" />
            {/* Soft ambient */}
            <ambientLight intensity={0.55} color="#d0deff" />

            <Suspense fallback={<FallbackBox />}>
                <Center>
                    <CourthouseModel />
                </Center>

                <ContactShadows
                    position={[0, -0.01, 0]}
                    opacity={0.45}
                    scale={40}
                    blur={2.8}
                    far={12}
                    color="#000020"
                />
            </Suspense>

            <OrbitControls
                autoRotate
                autoRotateSpeed={0.35}
                enableZoom={false}
                enablePan={false}
                maxPolarAngle={Math.PI / 2.1}
                minPolarAngle={Math.PI / 8}
                makeDefault
            />
        </Canvas>
    );
}
