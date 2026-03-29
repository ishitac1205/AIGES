import React from 'react'
import { RING_RADII, ORBIT_CONFIGS } from '../styles/theme'
import PlanetNode from './PlanetNode'
import DependencyEdges from './DependencyEdges'
import { useTheme } from '../ThemeContext'

export default function SolarSystem2D({ topology, selectedService, onSelectService }) {
  const { theme } = useTheme()
  const services = topology?.services || {}
  const graph = topology?.dependency_graph || {}
  const propagationPath = topology?.anomaly_propagation || null

  return (
    <svg 
      viewBox="0 0 1000 750" 
      preserveAspectRatio="xMidYMid meet" 
      style={{ width: '100%', height: '100%', background: theme.bg }}
    >
      <defs>
        <radialGradient id="ringGlow" cx="50%" cy="50%" r="50%" fx="50%" fy="50%">
          <stop offset="0%" stopColor="rgba(255, 255, 255, 0.05)" />
          <stop offset="100%" stopColor="rgba(255, 255, 255, 0)" />
        </radialGradient>
      </defs>

      {/* Orbits */}
      <g className="orbits">
        {RING_RADII.slice(1).map((r) => (
          <circle 
            key={r} 
            cx={490} 
            cy={340} 
            r={r} 
            fill="none" 
            stroke={theme.borderLight} 
            strokeWidth="1" 
            opacity="0.15" 
          />
        ))}
      </g>

      {/* Dependency Edges (Only if data exists) */}
      {topology && (
        <DependencyEdges 
          graph={graph} 
          services={services} 
          selectedService={selectedService} 
          propagationPath={propagationPath} 
        />
      )}

      {/* Planet Nodes — Use ORBIT_CONFIGS as the source of truth for node presence */}
      <g className="planet-nodes">
        {Object.keys(ORBIT_CONFIGS).map((name) => (
          <PlanetNode
            key={name}
            service={name}
            data={services[name]} // May be undefined if backend is off
            isSelected={selectedService === name}
            isRootCause={topology?.root_cause === name}
            onClick={onSelectService}
            orbitRing={ORBIT_CONFIGS[name].ring}
          />
        ))}
      </g>
    </svg>
  )
}
