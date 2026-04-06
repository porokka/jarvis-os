"use client";

import { useRef, useMemo } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import {
  FACE_VERTICES,
  FACE_EDGES,
  EMOTION_OFFSETS,
  type EmotionOffsets,
} from "./geometry";

interface LatticeFaceProps {
  emotion: string;
  speaking: boolean;
  thinking: boolean;
}

function lerpVertices(
  current: Float32Array,
  target: Float32Array,
  speed: number
) {
  for (let i = 0; i < current.length; i++) {
    current[i] += (target[i] - current[i]) * speed;
  }
}

export function LatticeFace({ emotion, speaking, thinking }: LatticeFaceProps) {
  const timeRef = useRef(0);
  const speakPhaseRef = useRef(0);

  // Positions
  const basePositions = useMemo(() => {
    const arr = new Float32Array(FACE_VERTICES.length * 3);
    FACE_VERTICES.forEach(([x, y, z], i) => {
      arr[i * 3] = x;
      arr[i * 3 + 1] = y;
      arr[i * 3 + 2] = z;
    });
    return arr;
  }, []);

  const currentPositions = useMemo(() => new Float32Array(basePositions), [basePositions]);
  const targetPositions = useMemo(() => new Float32Array(basePositions.length), [basePositions]);

  // Edge indices
  const edgeIndices = useMemo(() => {
    const indices: number[] = [];
    FACE_EDGES.forEach(([a, b]) => indices.push(a, b));
    return new Uint16Array(indices);
  }, []);

  // Create geometries imperatively
  const nodeGeo = useMemo(() => {
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(currentPositions), 3));
    const colors = new Float32Array(FACE_VERTICES.length * 3);
    for (let i = 0; i < FACE_VERTICES.length; i++) {
      colors[i * 3] = 0.25;
      colors[i * 3 + 1] = 0.63;
      colors[i * 3 + 2] = 0.94;
    }
    geo.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    return geo;
  }, [currentPositions]);

  const lineGeo = useMemo(() => {
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(currentPositions), 3));
    geo.setIndex(new THREE.BufferAttribute(edgeIndices, 1));
    return geo;
  }, [currentPositions, edgeIndices]);

  const glowGeo = useMemo(() => {
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(currentPositions), 3));
    return geo;
  }, [currentPositions]);

  const groupRef = useRef<THREE.Group>(null);

  useFrame((_, delta) => {
    timeRef.current += delta;
    const t = timeRef.current;

    // Compute target positions
    const offsets: EmotionOffsets = EMOTION_OFFSETS[emotion] || {};
    for (let i = 0; i < FACE_VERTICES.length; i++) {
      let tx = basePositions[i * 3];
      let ty = basePositions[i * 3 + 1];
      let tz = basePositions[i * 3 + 2];

      if (offsets[i]) {
        tx += offsets[i][0];
        ty += offsets[i][1];
        tz += offsets[i][2];
      }

      if (speaking) {
        speakPhaseRef.current += delta * 8;
        const speakOffsets = EMOTION_OFFSETS.speaking || {};
        if (speakOffsets[i]) {
          const wave = Math.sin(speakPhaseRef.current) * 0.5 + 0.5;
          tx += speakOffsets[i][0] * wave;
          ty += speakOffsets[i][1] * wave;
          tz += speakOffsets[i][2] * wave;
        }
      }

      // Idle breathing
      ty += Math.sin(t * 0.8 + i * 0.1) * 0.005;
      tz += Math.sin(t * 0.6 + i * 0.2) * 0.003;

      targetPositions[i * 3] = tx;
      targetPositions[i * 3 + 1] = ty;
      targetPositions[i * 3 + 2] = tz;
    }

    lerpVertices(currentPositions, targetPositions, 0.08);

    // Update all geometries
    for (const geo of [nodeGeo, lineGeo, glowGeo]) {
      const pos = geo.getAttribute("position") as THREE.BufferAttribute;
      (pos.array as Float32Array).set(currentPositions);
      pos.needsUpdate = true;
    }

    // Pulse node colors
    const col = nodeGeo.getAttribute("color") as THREE.BufferAttribute;
    const colors = col.array as Float32Array;
    for (let i = 0; i < FACE_VERTICES.length; i++) {
      const pulse = Math.sin(t * 2 + i * 0.5) * 0.1 + 0.9;
      const thinkBoost = thinking ? 0.3 : 0;

      colors[i * 3] = 0.25 * pulse + thinkBoost;
      colors[i * 3 + 1] = 0.63 * pulse + thinkBoost * 0.6;
      colors[i * 3 + 2] = 0.94 * pulse - thinkBoost * 0.3;
    }
    col.needsUpdate = true;

    // Gentle rotation
    if (groupRef.current) {
      groupRef.current.rotation.y = Math.sin(t * 0.3) * 0.05;
    }
  });

  return (
    <group ref={groupRef} position={[0, -0.3, 0]}>
      {/* Glow layer */}
      <points geometry={glowGeo}>
        <pointsMaterial
          size={0.08}
          color="#40a0f0"
          transparent
          opacity={0.15}
          sizeAttenuation
          depthWrite={false}
          blending={THREE.AdditiveBlending}
        />
      </points>

      {/* Edge lines */}
      <lineSegments geometry={lineGeo}>
        <lineBasicMaterial
          color="#40a0f0"
          transparent
          opacity={0.3}
          blending={THREE.AdditiveBlending}
        />
      </lineSegments>

      {/* Node points */}
      <points geometry={nodeGeo}>
        <pointsMaterial
          size={0.04}
          vertexColors
          transparent
          opacity={0.9}
          sizeAttenuation
          depthWrite={false}
          blending={THREE.AdditiveBlending}
        />
      </points>
    </group>
  );
}
