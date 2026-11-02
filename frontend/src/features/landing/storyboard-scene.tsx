"use client";

import { Canvas, useFrame, useLoader, useThree } from "@react-three/fiber";
import { Suspense, useEffect, useRef } from "react";
import { Group, TextureLoader, MathUtils } from "three";

function Frames({ active, onReady }: {active: boolean; onReady: () => void}) {
  const group = useRef<Group>(null);
  const progress = useRef(0);
  const target = useRef({x: 0, y: 0});
  const textures = useLoader(TextureLoader, ["/landing/frame-1.svg", "/landing/frame-2.svg", "/landing/frame-3.svg"]);
  const { gl, invalidate, viewport } = useThree();
  useEffect(() => { onReady(); }, [onReady]);
  useEffect(() => {
    if (!active) return;
    const element = gl.domElement;
    const move = (event: PointerEvent) => {
      const rect = element.getBoundingClientRect();
      target.current = {x: (event.clientX - rect.left) / rect.width - .5, y: (event.clientY - rect.top) / rect.height - .5};
      invalidate();
    };
    const leave = () => { target.current = {x: 0, y: 0}; invalidate(); };
    element.addEventListener("pointermove", move); element.addEventListener("pointerleave", leave);
    invalidate();
    return () => { element.removeEventListener("pointermove", move); element.removeEventListener("pointerleave", leave); };
  }, [active, gl, invalidate]);
  useFrame((_, delta) => {
    if (!group.current || !active) return;
    progress.current = Math.min(1, progress.current + Math.min(delta, .05) / 1.7);
    const ease = 1 - Math.pow(1 - progress.current, 3);
    const x = target.current.y * .12;
    const y = target.current.x * .18;
    group.current.rotation.x = MathUtils.damp(group.current.rotation.x, x, 5, delta);
    group.current.rotation.y = MathUtils.damp(group.current.rotation.y, y, 5, delta);
    group.current.position.y = (1 - ease) * -.5;
    group.current.scale.setScalar(Math.min(viewport.width / 10.8, 1.5) * (.92 + ease * .08));
    if (progress.current < 1 || Math.abs(group.current.rotation.x - x) + Math.abs(group.current.rotation.y - y) > .0002) invalidate();
  });
  return <group ref={group}>
    {textures.map((texture, index) => <group key={index} position={[(index - 1) * 3.05, index === 1 ? .35 : -.12, index === 1 ? .5 : -.4]} rotation={[0, (1 - index) * .15, (index - 1) * -.08]}>
      <mesh><boxGeometry args={[3.7, 2.65, .06]} /><meshBasicMaterial color="#344a4d" /></mesh>
      <mesh position={[0, 0, .04]}><planeGeometry args={[3.6, 2.55]} /><meshBasicMaterial color="#171c21" /></mesh>
      <mesh position={[0, .03, .06]}><planeGeometry args={[3.4, 2.125]} /><meshBasicMaterial map={texture} toneMapped={false} /></mesh>
      <mesh position={[-1.52, -1.17, .07]}><planeGeometry args={[.25, .025]} /><meshBasicMaterial color="#89dcc2" /></mesh>
      {[0, 1, 2].map(tick => <mesh key={tick} position={[1.15 + tick * .13, -1.17, .07]}><planeGeometry args={[.06, .025]} /><meshBasicMaterial color="#98a8ae" /></mesh>)}
    </group>)}
  </group>;
}

function ContextGuard({ onFailure }: {onFailure: () => void}) {
  const { gl } = useThree();
  useEffect(() => {
    const lost = (event: Event) => { event.preventDefault(); onFailure(); };
    const element = gl.domElement;
    element.addEventListener("webglcontextlost", lost);
    return () => element.removeEventListener("webglcontextlost", lost);
  }, [gl, onFailure]);
  return null;
}

export default function StoryboardScene({active, onReady, onFailure}: {active: boolean; onReady: () => void; onFailure: () => void}) {
  return <Canvas frameloop="demand" dpr={[1, 1.5]} camera={{position: [0, 0, 9], fov: 38}} gl={{alpha: false, antialias: true, powerPreference: "low-power"}} fallback={<span />}>
    <color attach="background" args={["#0d1014"]} />
    <ContextGuard onFailure={onFailure} />
    <Suspense fallback={null}><Frames active={active} onReady={onReady} /></Suspense>
  </Canvas>;
}
