import React, { useMemo, useRef, useState, useEffect } from 'react'
import { useFrame } from '@react-three/fiber'
import { Billboard, Text, Html, Line } from '@react-three/drei'
import * as THREE from 'three'
import { damp, dampC } from 'maath/easing'
import { anomalyScoreColor, anomalyGlowColor, SERVICE_SHORT } from '../styles/theme'
import { useTheme } from '../ThemeContext'

// Scale stress to match 2D layout semantics inside 3D environment
function getScale(service, data) {
  const base = 0.16
  const score = data?.combined_score || 0
  const cpu   = (data?.cpu_mean || 0) / 100
  const mem   = (data?.mem_mean || 0) / 100
  const stress = Math.max(score, cpu * 0.4, mem * 0.3)
  const radius = base + stress * 0.10
  return service === 'redis-cart' ? Math.max(0.12, radius - 0.03) : radius
}

const SERVICE_PLANET = {
  'redis-cart':            'mercury',
  'productcatalogservice': 'venus',
  'paymentservice':        'earth',
  'shippingservice':       'mars',
  'emailservice':          'jupiter',
  'currencyservice':       'saturn',
  'adservice':             'uranus',
  'cartservice':           'neptune',
  'recommendationservice': 'pluto',
  'checkoutservice':       'moon',
  'frontend':              'exoblue',
}

const PLANET_COLORS = {
  mercury: '#97979F',
  venus:   '#E3BB76',
  earth:   '#2271B3',
  mars:    '#B24D35',
  jupiter: '#D39C7E',
  saturn:  '#C5AB6E',
  uranus:  '#BBE1E4',
  neptune: '#6081FF',
  pluto:   '#DED08B',
  moon:    '#B0B0B8',
  exoblue: '#4A90E2',
}

// Generate a deterministic and distinct procedural color string based on the service name
function getPlanetBaseColor(service, themeBg) {
  const type = SERVICE_PLANET[service] || 'exoblue'
  return PLANET_COLORS[type]
}

// Advanced Procedural Planet Texture Engine
const planetCache = {}

function getPlanetTextures(type) {
  if (planetCache[type]) return planetCache[type]

  const size = 512
  const cnvs = document.createElement('canvas')
  cnvs.width = size
  cnvs.height = size / 2
  const ctx = cnvs.getContext('2d')
  
  const cloudCnvs = document.createElement('canvas')
  cloudCnvs.width = size
  cloudCnvs.height = size / 2
  const cloudCtx = cloudCnvs.getContext('2d')

  // Base Fill
  ctx.fillStyle = PLANET_COLORS[type] || '#888888'
  ctx.fillRect(0, 0, size, size / 2)

  // Surface Generation Per Type
  if (type === 'mercury' || type === 'moon') {
    for (let i = 0; i < 2000; i++) {
       const x = Math.random() * size;
       const y = Math.random() * (size / 2);
       const r = Math.random() * 4 + 1;
       ctx.fillStyle = `rgba(50, 50, 50, ${Math.random() * 0.3})`;
       ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill();
    }
  } else if (type === 'earth') {
    // Basic Procedural Continents
    for (let i = 0; i < 15; i++) {
       ctx.fillStyle = i % 2 === 0 ? '#3d6e3d' : '#8b4513';
       ctx.beginPath();
       ctx.moveTo(Math.random() * size, Math.random() * (size / 2));
       for (let j = 0; j < 8; j++) ctx.lineTo(Math.random() * size, Math.random() * (size / 2));
       ctx.closePath(); ctx.fill();
    }
  } else if (type === 'jupiter' || type === 'saturn') {
    for (let i = 0; i < 40; i++) {
       const y = Math.random() * (size / 2);
       const h = Math.random() * 8 + 2;
       ctx.fillStyle = `rgba(255, 255, 255, ${Math.random() * 0.15})`;
       ctx.fillRect(0, y, size, h);
    }
    if (type === 'jupiter') {
       ctx.fillStyle = 'rgba(180, 50, 50, 0.4)';
       ctx.beginPath(); ctx.arc(size * 0.7, size / 3, 15, 0, Math.PI * 2); ctx.fill();
    }
  } else if (type === 'mars') {
    for (let i = 0; i < 1000; i++) {
       ctx.fillStyle = `rgba(80, 30, 10, ${Math.random() * 0.2})`;
       ctx.fillRect(Math.random() * size, Math.random() * (size / 2), 4, 4);
    }
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, size, 8); // Polar Cap
    ctx.fillRect(0, (size / 2) - 8, size, 8);
  }

  // Cloud Generation
  if (['earth', 'venus', 'mars', 'jupiter', 'exoblue'].includes(type)) {
     const density = type === 'venus' ? 4000 : 1200;
     const opacity = type === 'venus' ? 0.6 : 0.35;
     for (let i = 0; i < density; i++) {
        const x = Math.random() * size;
        const y = Math.random() * (size / 2);
        const w = Math.random() * 30 + 5;
        const grd = cloudCtx.createRadialGradient(x, y, 0, x, y, w);
        grd.addColorStop(0, `rgba(255, 255, 255, ${opacity})`);
        grd.addColorStop(1, 'rgba(255, 255, 255, 0)');
        cloudCtx.fillStyle = grd;
        cloudCtx.fillRect(x - w, y - w, w * 2, w * 2);
     }
  }

  const map = new THREE.CanvasTexture(cnvs)
  const cloudMap = new THREE.CanvasTexture(cloudCnvs)
  map.wrapS = cloudMap.wrapS = THREE.RepeatWrapping
  planetCache[type] = { map, cloudMap }
  return planetCache[type]
}

function Ripple({ radius, color }) {
  const ref = useRef()
  useFrame((state, delta) => {
    if (ref.current) {
      ref.current.scale.addScalar(delta * 1.5)
      ref.current.material.opacity = Math.max(0, ref.current.material.opacity - delta * 0.5)
      if (ref.current.material.opacity <= 0) {
        ref.current.scale.setScalar(1)
        ref.current.material.opacity = 0.6
      }
    }
  })
  return (
    <mesh rotation-x={-Math.PI / 2} ref={ref}>
      <ringGeometry args={[radius, radius + 0.05, 64]} />
      <meshBasicMaterial color={color} transparent opacity={0.6} blending={THREE.AdditiveBlending} depthWrite={false} />
    </mesh>
  )
}

function MetricRing({ radius, percent, color, tube = 0.008, speed = 0.1, isAnomaly }) {
  const ref = useRef()
  const fgRef = useRef()
  
  const bgGeom = useMemo(() => new THREE.TorusGeometry(radius, tube, 8, 64, Math.PI * 2), [radius, tube])
  const bgMat = useMemo(() => new THREE.MeshBasicMaterial({ color, opacity: isAnomaly ? 0.35 : 0.25, transparent: true }), [color, isAnomaly])
  
  const arc = (Math.max(0.001, percent) / 100) * Math.PI * 2
  const fgGeom = useMemo(() => new THREE.TorusGeometry(radius, Math.max(0.001, tube * 1.2), 8, 64, arc), [radius, tube, arc])
  const fgMat = useMemo(() => new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0.5, transparent: true, opacity: isAnomaly ? 0.9 : 0.75 }), [color, isAnomaly])
  
  const emitMat = useMemo(() => new THREE.MeshBasicMaterial({ color, opacity: isAnomaly ? 0.4 : 0.25, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false }), [color, isAnomaly])

  useFrame((state, delta) => {
    if (ref.current) {
      ref.current.rotation.z -= delta * speed
    }
    if (fgRef.current) {
       fgRef.current.material.emissiveIntensity = 0.5 + Math.sin(state.clock.elapsedTime * 3) * 0.2
    }
  })

  return (
    <group ref={ref}>
      <mesh geometry={bgGeom} material={bgMat} />
      {percent > 0.5 && (
        <group>
           <mesh ref={fgRef} geometry={fgGeom} material={fgMat} />
           <mesh geometry={fgGeom} material={emitMat} scale={1.2} />
        </group>
      )}
    </group>
  )
}

export default function PlanetNode3D({ position, service, data, isSelected, isRootCause, onClick, orbitRing }) {
  const { theme } = useTheme()
  
  // --- Hooks Top Level ---
  const [hovered, setHover] = useState(false)
  const [displayScore, setDisplayScore] = useState(0)
  const [downPos, setDownPos] = useState({x: 0, y: 0})
  const [tilt] = useState(() => ({
    x: (Math.random() - 0.5) * 0.4,
    z: (Math.random() - 0.5) * 0.4,
    speed: 0.02 + Math.random() * 0.05
  }))

  const ref = useRef()
  const groupRef = useRef()
  const cloudRef = useRef()
  const rootCauseRef = useRef()

  const type = useMemo(() => SERVICE_PLANET[service] || 'exoblue', [service])
  const { map, cloudMap } = useMemo(() => getPlanetTextures(type), [type])
  
  // --- Derived Data ---
  const score = data?.combined_score || 0
  const cpu = Math.min(data?.cpu_mean || 0, 100)
  const mem = Math.min(data?.mem_mean || 0, 100)
  const errRate = Math.min(data?.features?.error_rate_pct ?? data?.error_rate ?? 0, 100)
  const anomScore = Math.min(score * 100, 100)
  const isAnomaly = data?.status !== 'normal'
  
  const targetScale = getScale(service, data) * (hovered || isSelected ? 1.15 : 1)
  const isHealthy = score < 0.1
  const targetColor = useMemo(() => isHealthy ? new THREE.Color(getPlanetBaseColor(service, theme.bg)) : new THREE.Color(anomalyScoreColor(score, 'fill', theme)), [isHealthy, service, theme.bg, score, theme])
  
  const rs = orbitRing === 1 ? 0.6 : 1.0
  const R1 = targetScale + 0.07 * rs
  const R2 = targetScale + 0.13 * rs
  const R3 = targetScale + 0.19 * rs
  const R4 = targetScale + 0.25 * rs
  
  const selectionPoints = useMemo(() => {
    const pts = []
    const radius = R4 + 0.09
    for (let i = 0; i <= 64; i++) {
      const theta = (i / 64) * Math.PI * 2
      pts.push(new THREE.Vector3(Math.cos(theta) * radius, 0, Math.sin(theta) * radius))
    }
    return pts
  }, [R4])
  
  const rootCausePoints = useMemo(() => {
    const pts = []
    const radius = R4 + 0.15
    for (let i = 0; i <= 64; i++) {
      const theta = (i / 64) * Math.PI * 2
      pts.push(new THREE.Vector3(Math.cos(theta) * radius, 0, Math.sin(theta) * radius))
    }
    return pts
  }, [R4])

  const isGaseous = ['jupiter', 'saturn', 'uranus', 'neptune', 'venus'].includes(type)
  const hasClouds = !['mercury', 'moon'].includes(type)

  // --- Animation Loop ---

  useFrame((state, delta) => {
    // Smooth number transition for Billboard
    setDisplayScore(prev => THREE.MathUtils.lerp(prev, score * 100, 0.1))

    if (ref.current) {
      damp(ref.current.scale, 'x', targetScale, 0.2, delta)
      damp(ref.current.scale, 'y', targetScale, 0.2, delta)
      damp(ref.current.scale, 'z', targetScale, 0.2, delta)
      
      // Enforce physical planet tilt and slow rotation with subtle wobble
      ref.current.rotation.x = tilt.x + Math.sin(state.clock.elapsedTime * 0.5) * 0.02
      ref.current.rotation.z = tilt.z + Math.cos(state.clock.elapsedTime * 0.5) * 0.02
      ref.current.rotation.y += delta * tilt.speed
      
      dampC(ref.current.material.color, targetColor, 0.2, delta)
      
      if (isAnomaly) {
        ref.current.material.emissive.copy(targetColor).multiplyScalar(0.4)
        ref.current.material.emissiveIntensity = 0.5 + Math.sin(state.clock.elapsedTime * 2) * 0.3
      } else {
        ref.current.material.emissiveIntensity = 0.05 // Subtle depth glow even when healthy
        ref.current.material.emissive.copy(targetColor).multiplyScalar(0.2)
      }
    }

    if (cloudRef.current) {
      // Atmospheric cloud rotation (drifts independently from surface)
      cloudRef.current.rotation.y += delta * (tilt.speed * 1.5)
      cloudRef.current.rotation.x = tilt.x + Math.sin(state.clock.elapsedTime * 0.3) * 0.03
    }
    

    if (groupRef.current) {
       const targetY = isSelected ? 0.15 : 0
       groupRef.current.position.y = THREE.MathUtils.lerp(groupRef.current.position.y, targetY, 0.1)
    }
    
    if (rootCauseRef.current) {
      rootCauseRef.current.rotation.y -= delta * 1.5
    }
  })


  return (
    <group position={position} 
           ref={groupRef}
           onPointerDown={(e) => setDownPos({x: e.clientX, y: e.clientY})}
           onPointerUp={(e) => {
             const dist = Math.sqrt(Math.pow(e.clientX - downPos.x, 2) + Math.pow(e.clientY - downPos.y, 2));
             if (dist < 5) { // Small threshold to distinguish from drag
               e.stopPropagation(); 
               onClick(service); 
             }
           }}
           onPointerOver={(e) => { e.stopPropagation(); setHover(true); document.body.style.cursor = 'pointer'; }} 
           onPointerOut={(e) => { e.stopPropagation(); setHover(false); document.body.style.cursor = 'auto'; }}>
      
      {/* Core Planet */}
      <mesh ref={ref} castShadow receiveShadow>
        <sphereGeometry args={[1, 64, 64]} />
        <meshPhysicalMaterial 
          roughness={isGaseous ? 0.95 : 0.8} 
          metalness={isGaseous ? 0.05 : 0.15} 
          clearcoat={isGaseous ? 0 : 0.25} 
          clearcoatRoughness={0.4}
          map={map}
          bumpMap={['mercury', 'moon', 'mars', 'earth'].includes(type) ? map : null}
          bumpScale={0.015}
        />
      </mesh>
      
      {/* Atmosphere / Cloud Outer Layer (Drifts independently) */}
      {hasClouds && (
        <mesh ref={cloudRef} scale={targetScale * 1.05}>
           <sphereGeometry args={[1, 64, 64]} />
           <meshStandardMaterial 
             map={cloudMap} 
             transparent 
             opacity={type === 'venus' ? 0.85 : 0.45} 
             side={THREE.DoubleSide} 
             blending={type === 'venus' ? THREE.NormalBlending : THREE.AdditiveBlending} 
             depthWrite={false} 
           />
        </mesh>
      )}
      
      
      {/* Selection State Outline & Ripple */}
      {isSelected && (
        <group>
          <Line points={selectionPoints} color={theme.text} lineWidth={2} dashed dashSize={0.06} gapSize={0.03} />
          <Ripple radius={R4 + 0.09} color={theme.text} />
        </group>
      )}
      
      {/* Root Cause Indicator */}
      {isRootCause && (
        <group ref={rootCauseRef}>
           <Line points={rootCausePoints} color="#c45c0a" lineWidth={3} dashed dashSize={0.1} gapSize={0.06} />
           <Ripple radius={R4 + 0.15} color="#c45c0a" />
        </group>
      )}
      
      {/* Metric Rings */}
      <group rotation-x={-Math.PI / 2}>
        <MetricRing radius={R1} percent={cpu} color="#c45c0a" speed={0.12} isAnomaly={isAnomaly} />
        <MetricRing radius={R2} percent={mem} color="#5588cc" speed={0.08} isAnomaly={isAnomaly} />
        <MetricRing radius={R3} percent={errRate} color="#cc2222" tube={0.004} speed={0.06} isAnomaly={isAnomaly} />
        <MetricRing radius={R4} percent={anomScore} color="#9944bb" tube={0.004} speed={0.04} isAnomaly={isAnomaly} />
      </group>
      
      {/* Labels */}
      <Billboard follow lockX={false} lockY={false} lockZ={false} position={[0, R4 + 0.3, 0]}>
        <Text fontSize={0.12} color={theme.text} anchorY="bottom" characters="0123456789%CPU MEM ERRORS">
           {Math.round(displayScore)}
        </Text>
        <Text position={[0, -0.16, 0]} fontSize={0.07} color={theme.text} anchorY="top">
          {SERVICE_SHORT[service] || service}
        </Text>
        <Text position={[0, -0.26, 0]} fontSize={0.05} color={theme.textMuted} anchorY="top">
          {`CPU ${Math.round(cpu)}% · Mem ${Math.round(mem)}%`}
        </Text>
        {errRate > 0.5 && (
          <Text position={[0, -0.34, 0]} fontSize={0.05} color="#cc2222" anchorY="top">
            {`ERRORS ${Math.round(errRate)}%`}
          </Text>
        )}
      </Billboard>
    </group>
  )
}
