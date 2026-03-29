const STAGES = [
  { key: 'priming', label: 'Priming' },
  { key: 'attacking', label: 'Attacking' },
  { key: 'observing_failure', label: 'Observing' },
  { key: 'remediating', label: 'Remediating' },
  { key: 'evaluating', label: 'Evaluating' },
  { key: 'completed', label: 'Done' },
]

function stageIndex(stage) {
  const idx = STAGES.findIndex(s => s.key === stage)
  return idx === -1 ? 0 : idx
}

export default function DemoBanner({ demoRun, theme }) {
  if (!demoRun) return null
  const { status, stage, service, elapsed_s } = demoRun
  const done = status === 'resolved' || status === 'failed' || stage === 'completed'
  const current = stageIndex(stage)

  return (
    <div style={{
      position: 'absolute',
      top: 0,
      left: 0,
      right: 0,
      zIndex: 20,
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      padding: '6px 14px',
      background: theme.card,
      borderBottom: `1px solid ${theme.border}`,
      fontFamily: theme.font,
      fontSize: 9,
      letterSpacing: 1.2,
      flexWrap: 'wrap',
    }}>
      <span style={{ color: theme.textMuted, textTransform: 'uppercase', fontWeight: 700, marginRight: 4 }}>
        {done ? (status === 'failed' ? '✗ DEMO FAILED' : '✓ RESOLVED') : `● DEMO · ${(service || 'recommendationservice').toUpperCase()}`}
      </span>
      {STAGES.map((s, i) => {
        const isPast = i < current
        const isCurrent = i === current
        const color = isCurrent
          ? theme.accent
          : isPast
            ? (done && status !== 'failed' ? '#2a8a2a' : theme.textMuted)
            : theme.textDim || theme.borderLight
        return (
          <span key={s.key} style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 4,
            padding: '2px 8px',
            border: `1px solid ${isCurrent ? theme.accent : theme.borderLight}`,
            borderRadius: 999,
            color,
            fontWeight: isCurrent ? 700 : 400,
            background: isCurrent ? `${theme.accent}18` : 'transparent',
            transition: 'all 0.3s',
          }}>
            {s.label}
          </span>
        )
      })}
      {done && elapsed_s != null && (
        <span style={{ marginLeft: 'auto', color: theme.textMuted }}>
          {status === 'failed' ? 'Failed' : `Fixed in ${elapsed_s.toFixed(1)}s`}
        </span>
      )}
    </div>
  )
}
