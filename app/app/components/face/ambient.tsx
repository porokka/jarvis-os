"use client";

import { useRef, useMemo, useEffect } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";

/** Floating particles that drift around the face */
export function AmbientParticles({ count = 80 }: { count?: number }) {
  const ref = useRef<THREE.Points>(null);

  const positions = useMemo(() => {
    const arr = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      arr[i * 3] = (Math.random() - 0.5) * 4;
      arr[i * 3 + 1] = (Math.random() - 0.5) * 4;
      arr[i * 3 + 2] = (Math.random() - 0.5) * 3 - 1;
    }
    return arr;
  }, [count]);

  const velocities = useMemo(() => {
    const arr = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      arr[i * 3] = (Math.random() - 0.5) * 0.002;
      arr[i * 3 + 1] = (Math.random() - 0.5) * 0.002;
      arr[i * 3 + 2] = (Math.random() - 0.5) * 0.001;
    }
    return arr;
  }, [count]);

  const geometry = useMemo(() => {
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    return geo;
  }, [positions]);

  useFrame(() => {
    const pos = geometry.getAttribute("position") as THREE.BufferAttribute;
    const arr = pos.array as Float32Array;

    for (let i = 0; i < count; i++) {
      arr[i * 3] += velocities[i * 3];
      arr[i * 3 + 1] += velocities[i * 3 + 1];
      arr[i * 3 + 2] += velocities[i * 3 + 2];

      for (let j = 0; j < 3; j++) {
        const idx = i * 3 + j;
        const limit = j === 2 ? 2 : 2.5;
        if (Math.abs(arr[idx]) > limit) {
          arr[idx] = -arr[idx] * 0.5;
        }
      }
    }
    pos.needsUpdate = true;
  });

  return (
    <points geometry={geometry}>
      <pointsMaterial
        size={0.015}
        color="#40a0f0"
        transparent
        opacity={0.2}
        sizeAttenuation
        depthWrite={false}
        blending={THREE.AdditiveBlending}
      />
    </points>
  );
}

/** Radial grid on the floor — data-space feel */
export function DataGrid() {
  const ref = useRef<THREE.Group>(null);

  useFrame((_, delta) => {
    if (ref.current) {
      ref.current.rotation.y += delta * 0.02;
    }
  });

  const radialGeos = useMemo(() => {
    return Array.from({ length: 12 }).map((_, i) => {
      const angle = (i / 12) * Math.PI * 2;
      const x2 = Math.cos(angle) * 3;
      const y2 = Math.sin(angle) * 3;
      const points = [
        new THREE.Vector3(0, 0, 0),
        new THREE.Vector3(x2, y2, 0),
      ];
      return new THREE.BufferGeometry().setFromPoints(points);
    });
  }, []);

  return (
    <group ref={ref} position={[0, -1.8, 0]} rotation={[-Math.PI / 2, 0, 0]}>
      {[0.8, 1.4, 2.0, 2.8].map((radius, i) => (
        <mesh key={`ring-${i}`}>
          <ringGeometry args={[radius - 0.005, radius + 0.005, 64]} />
          <meshBasicMaterial
            color="#40a0f0"
            transparent
            opacity={0.06 - i * 0.01}
            side={THREE.DoubleSide}
            blending={THREE.AdditiveBlending}
          />
        </mesh>
      ))}
      {radialGeos.map((geo, i) => (
        <lineSegments key={`line-${i}`} geometry={geo}>
          <lineBasicMaterial
            color="#40a0f0"
            transparent
            opacity={0.04}
            blending={THREE.AdditiveBlending}
          />
        </lineSegments>
      ))}
    </group>
  );
}
