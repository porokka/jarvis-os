"use client";

import dynamic from "next/dynamic";
import { Suspense } from "react";
import { Canvas } from "@react-three/fiber";
import { LatticeFace } from "./lattice-face";
import { AmbientParticles, DataGrid } from "./ambient";

interface JarvisSceneProps {
  emotion: string;
  speaking: boolean;
  thinking: boolean;
}

function Scene({ emotion, speaking, thinking }: JarvisSceneProps) {
  return (
    <>
      <color attach="background" args={["#06060b"]} />
      <fog attach="fog" args={["#06060b", 3, 8]} />

      <LatticeFace
        emotion={emotion}
        speaking={speaking}
        thinking={thinking}
      />
      <AmbientParticles />
      <DataGrid />
    </>
  );
}

function JarvisSceneInner(props: JarvisSceneProps) {
  return (
    <Canvas
      camera={{ position: [0, 0, 2.8], fov: 45 }}
      style={{ width: "100%", height: "100%" }}
      gl={{ antialias: true, alpha: false }}
    >
      <Suspense fallback={null}>
        <Scene {...props} />
      </Suspense>
    </Canvas>
  );
}

// Dynamic import to avoid SSR issues with Three.js
export const JarvisScene = dynamic(
  () => Promise.resolve(JarvisSceneInner),
  { ssr: false }
);
