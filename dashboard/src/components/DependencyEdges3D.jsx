import React, { useRef, useMemo } from 'react'
import { Line, Billboard, Text } from '@react-three/drei'
import { useFrame } from '@react-three/fiber'
import { ORBIT_CONFIGS, RING_RADII } from '../styles/theme'
import { useTheme } from '../ThemeContext'
import * as THREE from 'three'

// Moves point p1 along the direction toward p2 by defined fixed offset distance
function offsetPoint(p1, p2, offsetDist) {
  const dir = new THREE.Vector3().subVectors(p2, p1).normalize()
  return new THREE.Vector3().copy(p1).add(dir.multiplyScalar(offsetDist))
}

function AnimatedEdge({ p1, p2, color, lineWidth, dashSize, gapSize, opacity, isPropagate, isBroken }) {
  const lineRef = useRef()
  const arrowRef = useRef()

  // Generate an arching 3D curve between the two planets
  const curvePoints = useMemo(() => {
    const mx = (p1.x + p2.x) / 2
    const mz = (p1.z + p2.z) / 2
    const dist = p1.distanceTo(p2)
    // Arch upward based on distance
    const cp = new THREE.Vector3(mx, dist * 0.3, mz)
    const curve = new THREE.QuadraticBezierCurve3(p1, cp, p2)
    return {
      points: curve.getPoints(32),
      tangent: curve.getTangent(1).normalize(),
      midpoint: curve.getPoint(0.5)
    }
  }, [p1, p2])

  // Material animation for data flow
  useFrame((state, delta) => {
    if (isPropagate && lineRef.current?.material) {
        lineRef.current.material.dashOffset -= delta * 1.5 // Speed up flow
    }
  })

  // Arrow rotation logic
  const arrowQuat = useMemo(() => {
    const axis = new THREE.Vector3(0, 1, 0)
    const quaternion = new THREE.Quaternion().setFromUnitVectors(axis, curvePoints.tangent)
    return quaternion
  }, [curvePoints.tangent])

  return (
    <group>
      <Line
        ref={lineRef}
        points={curvePoints.points}
        color={color}
        lineWidth={lineWidth}
        dashed={dashSize > 0}
        dashSize={dashSize}
        dashScale={1}
        dashOffset={0}
        gapSize={gapSize}
        transparent
        opacity={opacity}
      />
      {/* Directional Arrow at end of path */}
      <mesh position={p2} quaternion={arrowQuat}>
        <coneGeometry args={[0.06, 0.2, 8]} />
        <meshBasicMaterial color={color} transparent opacity={opacity} />
      </mesh>
      
      {/* Broken path X indicator */}
      {isBroken && (
        <Billboard position={[curvePoints.midpoint.x, curvePoints.midpoint.y + 0.1, curvePoints.midpoint.z]}>
           <Text fontSize={0.25} color="#ff4444" outlineWidth={0.02} outlineColor="#000000">✕</Text>
        </Billboard>
      )}
    </group>
  )
}

function get3DPos(service) {
  const cfg = ORBIT_CONFIGS[service]
  if (!cfg) return new THREE.Vector3(0, 0, 0)
  const r = RING_RADII[cfg.ring] / 100
  const rad = (cfg.angle - 90) * Math.PI / 180
  return new THREE.Vector3(r * Math.cos(rad), 0, r * Math.sin(rad))
}

export default function DependencyEdges3D({ graph, services, selectedService, propagationPath }) {
  const { theme } = useTheme()
  if (!graph) return null

  const edges = []
  Object.entries(graph).forEach(([from, deps]) => {
    (Array.isArray(deps) ? deps : []).forEach(to => {
      if (!ORBIT_CONFIGS[from] || !ORBIT_CONFIGS[to]) return
      edges.push({ from, to })
    })
  })

  return (
    <group>
      {edges.map(({ from, to }) => {
        const fromSvc = services?.[from]
        const toSvc = services?.[to]
        
        const isPropagate = propagationPath && (propagationPath.includes(from) || propagationPath.includes(to))
        const isBroken = (fromSvc?.status === 'critical' && (fromSvc?.combined_score || 0) > 0.65) ||
                         (toSvc?.status === 'critical' && (toSvc?.combined_score || 0) > 0.65)
        const isAlert = fromSvc?.status === 'warning' || fromSvc?.status === 'critical'
        const isSelected = from === selectedService || to === selectedService

        let color, lineWidth, dashSize, gapSize;
        if (isBroken) {
          color = '#ff4444'; lineWidth = 4; dashSize = 0.1; gapSize = 0.1;
        } else if (isPropagate) {
          color = '#cc2222'; lineWidth = 4; dashSize = 0.15; gapSize = 0.1;
        } else if (isSelected) {
          color = theme.text; lineWidth = 4; dashSize = 0; gapSize = 0;
        } else if (isAlert) {
          color = '#c45c0a'; lineWidth = 3; dashSize = 0.1; gapSize = 0.1;
        } else {
          color = theme.textMuted; lineWidth = 2.5; dashSize = 0; gapSize = 0;
        }

        const rawP1 = get3DPos(from)
        const rawP2 = get3DPos(to)
        
        // Offset by ~1.3 units to clear the sphere and metrics rings so arrows are visible
        const p1 = offsetPoint(rawP1, rawP2, 1.35)
        const p2 = offsetPoint(rawP2, rawP1, 1.35)

        // Elevate lines slightly to avoid z-fighting with orbits
        p1.y = 0.1
        p2.y = 0.1

        return (
          <AnimatedEdge 
            key={`${from}-${to}`} 
            p1={p1} 
            p2={p2} 
            color={color} 
            lineWidth={lineWidth} 
            dashSize={dashSize} 
            gapSize={gapSize} 
            opacity={opacity} 
            isPropagate={isPropagate}
            isBroken={isBroken}
          />
        )
      })}
    </group>
  )
}
