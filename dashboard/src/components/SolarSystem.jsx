import React from 'react'
import { ORBIT_CONFIGS } from '../styles/theme'
import { useTheme } from '../ThemeContext'
import PlanetScene from './PlanetScene'

const RING_LEGEND = [
  { color: '#c45c0a', label: 'CPU usage', key: 'cpu_mean' },
  { color: '#5588cc', label: 'Memory usage', key: 'mem_mean' },
  { color: '#cc2222', label: 'Error rate', key: 'error_rate_mean', scale: 100 },
  { color: '#9944bb', label: 'Anomaly score', key: 'combined_score', scale: 100 },
]

export default function SolarSystem({ topology, selectedService, onSelectService }) {
  const { theme } = useTheme()

  const services = topology?.services || {}
  const selData = services[selectedService]

  // Legend values for selected service
  const legendValues = RING_LEGEND.map(({ color, label, key, scale }) => {
    let val = null
    if (key && selData) {
      val = selData[key] ?? selData?.features?.[key]
      if (val != null && scale) val = val * scale
    }
    return { color, label, val }
  })

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%', overflow: 'hidden' }}>
      {/* Live / offline indicator */}
      <div style={{
        position: 'absolute', top: 8, left: 12, zIndex: 10,
        fontFamily: theme.font, fontSize: '10px', color: theme.textMuted,
        display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap',
      }}>
        <span style={{
          display: 'inline-block', width: 7, height: 7, borderRadius: '50%',
          background: topology ? '#2a8a2a' : '#cc2222',
          boxShadow: topology ? '0 0 6px #2a8a2a' : '0 0 6px #cc2222',
        }} />
        {topology ? 'Live' : 'Backend offline'}
      </div>

      {/* Bottom-left ring legend (always visible) */}
      <div style={{
        position: 'absolute', bottom: 36, left: 12, zIndex: 10,
        background: theme.card, border: `1px solid ${theme.borderLight}`,
        padding: '8px 14px', fontFamily: theme.font,
        minWidth: 176,
        pointerEvents: 'none',
      }}>
        <div style={{ fontSize: 8, color: theme.textMuted, marginBottom: 7, letterSpacing: 1.5, fontWeight: 'bold' }}>
          {selectedService ? `${selectedService.toUpperCase()} SIGNALS` : 'SERVICE SIGNALS'}
        </div>
        {legendValues.map(({ color, label, val }) => (
          <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 5 }}>
            <div style={{ width: 10, height: 10, borderRadius: '50%', background: color, flexShrink: 0 }} />
            <span style={{ fontSize: 10, color: theme.textMuted, width: 74 }}>{label}</span>
            <span style={{ fontSize: 10, color: theme.text, fontWeight: 'bold' }}>
              {val != null ? `${Math.round(val)}%` : '—'}
            </span>
          </div>
        ))}
      </div>

      <PlanetScene
        topology={topology}
        selectedService={selectedService}
        onSelectService={onSelectService}
      />
    </div>
  )
}
