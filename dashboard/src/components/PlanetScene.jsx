import React, { useRef } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { OrbitControls, Stars } from '@react-three/drei'
import PlanetNode3D from './PlanetNode3D'
import DependencyEdges3D from './DependencyEdges3D'
import { ORBIT_CONFIGS, RING_RADII } from '../styles/theme'
import { useTheme } from '../ThemeContext'
import * as THREE from 'three'

const ALL_SERVICES = Object.keys(ORBIT_CONFIGS)

function DynamicBackground() {
  const ref = useRef()
  useFrame((state, delta) => {
    if (ref.current) {
      ref.current.rotation.y += delta * 0.015
      ref.current.rotation.z += delta * 0.005
    }
  })

  return (
    <group ref={ref}>
      <Stars radius={100} depth={50} count={5000} factor={6} saturation={0} fade speed={0.5} />
      <Stars radius={150} depth={30} count={2000} factor={10} saturation={0} fade speed={4} />
      <Stars radius={200} depth={10} count={500} factor={14} saturation={0} fade speed={8} />
    </group>
  )
}


function AnimatedOrbitRing({ ringIdx, theme }) {
  const ref = useRef()
  // Adjust base speed and rotate opposite directions for odd/even rings
  const speed = (ringIdx % 2 === 0 ? 1 : -1) * (0.1 / ringIdx)
  
  useFrame((state, delta) => {
    if (ref.current) ref.current.rotation.z += delta * speed
  })
  
  return (
    <mesh ref={ref} rotation-x={-Math.PI / 2} position-y={-0.1}>
      <ringGeometry args={[RING_RADII[ringIdx] / 100 - 0.004, RING_RADII[ringIdx] / 100 + 0.004, 128]} />
      <meshBasicMaterial color={theme.text} transparent opacity={0.25} side={THREE.DoubleSide} />
    </mesh>
  )
}

function get3DPos(service) {
  const cfg = ORBIT_CONFIGS[service]
  if (!cfg) return [0, 0, 0]
  const r = RING_RADII[cfg.ring] / 100
  const rad = (cfg.angle - 90) * Math.PI / 180
  return [r * Math.cos(rad), 0, r * Math.sin(rad)]
}

export default function PlanetScene({ topology, selectedService, onSelectService }) {
  const { theme } = useTheme()
  const services = topology?.services || {}
  const graph = topology?.dependency_graph || {}
  const rootCause = topology?.root_cause || {}
  const propagationPath = rootCause?.propagation_path || []

  const isLight = theme.bg === '#f4f0e8' || theme.bg === '#ffffff'

  return (
    <div style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', pointerEvents: 'auto' }}>
      <Canvas shadows camera={{ position: [0, 15, 0.1], fov: 45 }}>
        {/* Lighting */}
        <ambientLight intensity={isLight ? 0.35 : 0.25} />
        <directionalLight 
          position={[10, 15, 10]} 
          intensity={isLight ? 1.0 : 1.2} 
          castShadow 
          shadow-mapSize-width={2048} 
          shadow-mapSize-height={2048}
        />
        {/* Rim Light for better shape definition without Sun */}
        <pointLight position={[-10, 8, -10]} intensity={isLight ? 0.6 : 0.8} color="#ffffff" />
        
        {/* Dynamic Background */}
        <DynamicBackground />
        
        {/* Interaction Controls */}
        <OrbitControls 
          makeDefault 
          enableDamping 
          dampingFactor={0.05} 
          minDistance={5} 
          maxDistance={35} 
          maxPolarAngle={Math.PI / 2 + 0.1}
          autoRotate={false}
        />

        {/* Edges */}
        <DependencyEdges3D
          graph={graph}
          services={services}
          selectedService={selectedService}
          propagationPath={propagationPath}
        />

        {/* Orbit Rings (Aesthetic) */}
        {[1, 2, 3, 4, 5].map(ringIdx => (
          <AnimatedOrbitRing key={`orbit-${ringIdx}`} ringIdx={ringIdx} theme={theme} />
        ))}

        {/* Planet Nodes */}
        {ALL_SERVICES.map(svc => (
          <PlanetNode3D
            key={svc}
            service={svc}
            data={services[svc]}
            isSelected={selectedService === svc}
            isRootCause={rootCause?.service === svc}
            onClick={onSelectService}
            orbitRing={ORBIT_CONFIGS[svc].ring}
            position={get3DPos(svc)}
          />
        ))}
      </Canvas>
    </div>
  )
}
