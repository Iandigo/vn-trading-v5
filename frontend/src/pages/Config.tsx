import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { RotateCcw, Save, HardDrive } from 'lucide-react'
import { fetchConfig, saveConfig, clearConfigOverrides, saveConfigToFile } from '../api/client'

interface FieldDef {
  key: string
  label: string
  description: string
  type: 'number' | 'boolean'
  min?: number
  max?: number
  step?: number
  section: string
  strategy: 'carver' | 'martin_luk' | 'shared'
}

const FIELDS: FieldDef[] = [
  // ─── Carver: MA Regime ───
  { key: 'ma_period',           label: 'MA Period',              description: 'Moving average period for regime detection. Keep at 200.', type: 'number', min: 50, max: 500, step: 1, section: 'MA Regime Filter', strategy: 'carver' },
  { key: 'confirm_days',        label: 'Confirm Days',           description: 'Days index must stay above/below MA before regime flips.', type: 'number', min: 1, max: 10, step: 1, section: 'MA Regime Filter', strategy: 'carver' },
  { key: 'bear_tau_multiplier', label: 'Bear τ Multiplier',      description: 'Multiply target vol by this in BEAR regime. 0.5 = half sizing.', type: 'number', min: 0.1, max: 1.0, step: 0.05, section: 'MA Regime Filter', strategy: 'carver' },
  { key: 'bear_new_entries',    label: 'Allow New Entries in Bear', description: 'If false, no new long positions in BEAR.', type: 'boolean', section: 'MA Regime Filter', strategy: 'carver' },
  { key: 'bear_top_n_entries',  label: 'Bear Top-N Exception',   description: 'Allow top-N momentum stocks to enter in BEAR. 0 = disabled.', type: 'number', min: 0, max: 10, step: 1, section: 'MA Regime Filter', strategy: 'carver' },

  // ─── Carver: Cross Momentum ───
  { key: 'lookback_days',        label: 'Lookback Days',         description: '3-month return lookback. Keep at 63.', type: 'number', min: 21, max: 252, step: 1, section: 'Cross-Sectional Momentum', strategy: 'carver' },
  { key: 'skip_recent_days',     label: 'Skip Recent Days',      description: 'Skip most recent N days (short-term reversal bias).', type: 'number', min: 0, max: 21, step: 1, section: 'Cross-Sectional Momentum', strategy: 'carver' },
  { key: 'rebalance_every_days', label: 'Rebalance Every (days)', description: 'Signal update frequency. Lower = more trades.', type: 'number', min: 5, max: 63, step: 1, section: 'Cross-Sectional Momentum', strategy: 'carver' },
  { key: 'top_pct',              label: 'Top % (Buy Zone)',       description: 'Top N% of ranked stocks get BUY signal.', type: 'number', min: 0.1, max: 0.6, step: 0.05, section: 'Cross-Sectional Momentum', strategy: 'carver' },
  { key: 'bottom_pct',           label: 'Bottom % (Reduce Zone)', description: 'Bottom N% get REDUCE signal.', type: 'number', min: 0.1, max: 0.6, step: 0.05, section: 'Cross-Sectional Momentum', strategy: 'carver' },

  // ─── Carver: IBS ───
  { key: 'oversold_threshold',    label: 'IBS Oversold < ',   description: 'IBS below this = oversold signal.', type: 'number', min: 0.05, max: 0.40, step: 0.01, section: 'IBS Mean Reversion', strategy: 'carver' },
  { key: 'overbought_threshold',  label: 'IBS Overbought > ', description: 'IBS above this = overbought signal.', type: 'number', min: 0.60, max: 0.95, step: 0.01, section: 'IBS Mean Reversion', strategy: 'carver' },
  { key: 'only_in_bull_regime',   label: 'BULL Regime Only',  description: 'Only trade IBS in BULL regime.', type: 'boolean', section: 'IBS Mean Reversion', strategy: 'carver' },

  // ─── Carver: Signal weights ───
  { key: 'weight_cross_momentum', label: 'Cross-Momentum Weight', description: 'Primary driver weight. Default 0.55.', type: 'number', min: 0.1, max: 0.9, step: 0.01, section: 'Signal Weights', strategy: 'carver' },
  { key: 'weight_ibs',            label: 'IBS Weight',            description: 'Counter-trend weight. Default 0.15.', type: 'number', min: 0.0, max: 0.40, step: 0.01, section: 'Signal Weights', strategy: 'carver' },

  // ─── Carver: Position sizing ───
  { key: 'target_vol',        label: 'Target Vol (τ)',      description: 'Portfolio target volatility. 0.25 = 25%.', type: 'number', min: 0.10, max: 0.50, step: 0.01, section: 'Position Sizing', strategy: 'carver' },
  { key: 'buffer_fraction',   label: 'Buffer Fraction',     description: 'Trade only when position drifts outside ±N% of optimal.', type: 'number', min: 0.05, max: 0.50, step: 0.01, section: 'Position Sizing', strategy: 'carver' },
  { key: 'max_position_pct',  label: 'Max Position %',      description: 'Max single-stock concentration.', type: 'number', min: 0.05, max: 0.30, step: 0.01, section: 'Position Sizing', strategy: 'carver' },
  { key: 'vol_lookback',      label: 'Vol Lookback (days)',  description: 'Days for volatility estimation. 60 = smoother.', type: 'number', min: 10, max: 120, step: 5, section: 'Position Sizing', strategy: 'carver' },

  // ─── Martin Luk: EMA ───
  { key: 'ml_ema_fast',        label: 'EMA Fast',         description: 'Fast EMA period for alignment.', type: 'number', min: 5, max: 20, step: 1, section: 'EMA Alignment', strategy: 'martin_luk' },
  { key: 'ml_ema_mid',         label: 'EMA Mid',          description: 'Mid EMA period for alignment.', type: 'number', min: 15, max: 50, step: 1, section: 'EMA Alignment', strategy: 'martin_luk' },
  { key: 'ml_ema_slow',        label: 'EMA Slow',         description: 'Slow EMA period for alignment.', type: 'number', min: 30, max: 100, step: 1, section: 'EMA Alignment', strategy: 'martin_luk' },
  { key: 'ml_adr_period',      label: 'ADR Period',       description: 'Average daily range lookback.', type: 'number', min: 10, max: 60, step: 1, section: 'EMA Alignment', strategy: 'martin_luk' },
  { key: 'ml_adr_min_pct',     label: 'ADR Min %',        description: 'Minimum ADR to qualify for entry.', type: 'number', min: 0.01, max: 0.10, step: 0.005, section: 'EMA Alignment', strategy: 'martin_luk' },

  // ─── Martin Luk: Entry ───
  { key: 'ml_breakout_confirm', label: 'Confirm Close',    description: 'Require close above breakout level.', type: 'boolean', section: 'Entry Rules', strategy: 'martin_luk' },
  { key: 'ml_inside_day',       label: 'Inside Day Pattern', description: 'Enable inside-day breakout pattern.', type: 'boolean', section: 'Entry Rules', strategy: 'martin_luk' },
  { key: 'ml_ema_convergence',  label: 'EMA Convergence %', description: 'Max spread between EMAs for convergence signal.', type: 'number', min: 0.005, max: 0.05, step: 0.005, section: 'Entry Rules', strategy: 'martin_luk' },
  { key: 'ml_max_stop_pct',     label: 'Max Stop %',       description: 'Maximum stop-loss distance from entry.', type: 'number', min: 0.02, max: 0.10, step: 0.005, section: 'Entry Rules', strategy: 'martin_luk' },

  // ─── Martin Luk: Risk ───
  { key: 'ml_risk_per_trade',     label: 'Risk/Trade %',       description: 'Risk per trade as % of equity.', type: 'number', min: 0.0025, max: 0.02, step: 0.0025, section: 'Risk & Sizing', strategy: 'martin_luk' },
  { key: 'ml_risk_drawdown',      label: 'Drawdown Risk %',    description: 'Reduced risk during drawdowns.', type: 'number', min: 0.001, max: 0.01, step: 0.00025, section: 'Risk & Sizing', strategy: 'martin_luk' },
  { key: 'ml_drawdown_threshold', label: 'DD Threshold',       description: 'Start reducing risk at this drawdown.', type: 'number', min: 0.05, max: 0.20, step: 0.01, section: 'Risk & Sizing', strategy: 'martin_luk' },
  { key: 'ml_max_position_pct',   label: 'Max Position %',     description: 'Max single stock as % of equity.', type: 'number', min: 0.05, max: 0.20, step: 0.01, section: 'Risk & Sizing', strategy: 'martin_luk' },
  { key: 'ml_max_exposure',       label: 'Max Exposure %',     description: 'Max total portfolio exposure.', type: 'number', min: 0.50, max: 1.00, step: 0.05, section: 'Risk & Sizing', strategy: 'martin_luk' },

  // ─── Martin Luk: Exit ───
  { key: 'ml_partial_1_r',   label: 'Partial 1 at R',     description: 'First partial exit at this R multiple.', type: 'number', min: 1, max: 10, step: 0.5, section: 'Exit & Partials', strategy: 'martin_luk' },
  { key: 'ml_partial_1_pct', label: 'Partial 1 %',        description: 'Sell this % at first partial.', type: 'number', min: 0.10, max: 0.50, step: 0.05, section: 'Exit & Partials', strategy: 'martin_luk' },
  { key: 'ml_partial_2_r',   label: 'Partial 2 at R',     description: 'Second partial exit at this R multiple.', type: 'number', min: 2, max: 15, step: 0.5, section: 'Exit & Partials', strategy: 'martin_luk' },
  { key: 'ml_partial_2_pct', label: 'Partial 2 %',        description: 'Sell this % at second partial.', type: 'number', min: 0.10, max: 0.50, step: 0.05, section: 'Exit & Partials', strategy: 'martin_luk' },
  { key: 'ml_trail_ema',     label: 'Trail EMA',          description: 'Trail stop with this EMA after partial 2.', type: 'number', min: 5, max: 21, step: 1, section: 'Exit & Partials', strategy: 'martin_luk' },
  { key: 'ml_exit_ema',      label: 'Exit EMA',           description: 'Full exit when close < this EMA.', type: 'number', min: 9, max: 50, step: 1, section: 'Exit & Partials', strategy: 'martin_luk' },

  // ─── Martin Luk: Market Health ───
  { key: 'ml_health_strong',   label: 'Strong Health %',   description: '>= this % leaders = STRONG market.', type: 'number', min: 0.30, max: 0.70, step: 0.05, section: 'Market Health', strategy: 'martin_luk' },
  { key: 'ml_health_cautious', label: 'Cautious Health %', description: 'Below strong but above this = CAUTIOUS.', type: 'number', min: 0.10, max: 0.40, step: 0.01, section: 'Market Health', strategy: 'martin_luk' },
  { key: 'ml_cost_per_trade',  label: 'Cost Per Trade %',  description: 'Transaction cost per side.', type: 'number', min: 0.001, max: 0.01, step: 0.0001, section: 'Market Health', strategy: 'martin_luk' },

  // ─── Shared ───
  { key: 'filter_enabled',       label: 'Enable Stock Filter',     description: 'Pre-filter stocks by volume and history.', type: 'boolean', section: 'Stock Quality Filter', strategy: 'shared' },
  { key: 'min_avg_volume',       label: 'Min Avg Volume (shares)', description: 'Minimum average daily volume.', type: 'number', min: 100000, max: 5000000, step: 100000, section: 'Stock Quality Filter', strategy: 'shared' },
  { key: 'volume_lookback_days', label: 'Volume Lookback (days)',  description: 'Period for average volume computation.', type: 'number', min: 20, max: 120, step: 5, section: 'Stock Quality Filter', strategy: 'shared' },
  { key: 'min_history_days',     label: 'Min History (days)',      description: 'Minimum trading days of data required.', type: 'number', min: 100, max: 500, step: 10, section: 'Stock Quality Filter', strategy: 'shared' },
  { key: 'cost_per_trade_pct',   label: 'Cost Per Trade (Carver)', description: 'TCBS: ~0.25% per side.', type: 'number', min: 0.001, max: 0.01, step: 0.0001, section: 'Transaction Costs', strategy: 'shared' },
]

function fmt(v: number | boolean, type: 'number' | 'boolean') {
  if (type === 'boolean') return v ? 'true' : 'false'
  if (typeof v === 'number') {
    return v < 0.01 ? v.toFixed(4) : v < 0.1 ? v.toFixed(3) : v < 1 ? v.toFixed(2) : v.toString()
  }
  return String(v)
}

type StrategyTab = 'carver' | 'martin_luk' | 'shared'

export default function Config() {
  const qc = useQueryClient()
  const { data: cfg, isLoading } = useQuery({ queryKey: ['config'], queryFn: fetchConfig })

  const [draft, setDraft] = useState<Record<string, number | boolean>>({})
  const [tab, setTab] = useState<StrategyTab>('carver')
  const [saved, setSaved] = useState(false)
  const [fileSaved, setFileSaved] = useState<string | null>(null)

  const saveMut = useMutation({
    mutationFn: saveConfig,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['config'] })
      setDraft({})
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    },
  })

  const clearMut = useMutation({
    mutationFn: clearConfigOverrides,
    onSuccess: () => {
      setDraft({})
      qc.invalidateQueries({ queryKey: ['config'] })
    },
  })

  const saveFileMut = useMutation({
    mutationFn: saveConfigToFile,
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ['config'] })
      setDraft({})
      setFileSaved(`Saved ${res.changes} values to config.py`)
      setTimeout(() => setFileSaved(null), 5000)
    },
  })

  if (isLoading || !cfg) return <div className="text-gray-400 text-sm">Loading config...</div>

  const effectiveValue = (key: string): number | boolean => {
    if (key in draft) return draft[key]
    if (key in cfg.overrides) return cfg.overrides[key]

    if (key === 'weight_cross_momentum') return cfg.SIGNAL_WEIGHTS.cross_momentum
    if (key === 'weight_ibs') return cfg.SIGNAL_WEIGHTS.ibs

    // Martin Luk fields: strip ml_ prefix to look up in MARTIN_LUK dict
    if (key.startsWith('ml_')) {
      const mlKey = key.slice(3)
      // Map override key back to config key
      const fieldMap: Record<string, string> = {
        'ema_fast': 'ema_fast', 'ema_mid': 'ema_mid', 'ema_slow': 'ema_slow',
        'adr_period': 'adr_period', 'adr_min_pct': 'adr_min_pct',
        'breakout_confirm': 'breakout_confirm_close', 'inside_day': 'inside_day_enabled',
        'ema_convergence': 'ema_convergence_pct', 'max_stop_pct': 'max_stop_pct',
        'risk_per_trade': 'risk_per_trade_pct', 'risk_drawdown': 'risk_drawdown_pct',
        'drawdown_threshold': 'drawdown_threshold',
        'max_position_pct': 'max_position_pct', 'max_exposure': 'max_total_exposure',
        'partial_1_r': 'partial_1_r', 'partial_1_pct': 'partial_1_pct',
        'partial_2_r': 'partial_2_r', 'partial_2_pct': 'partial_2_pct',
        'trail_ema': 'trail_ema', 'exit_ema': 'exit_ema',
        'health_strong': 'health_strong_pct', 'health_cautious': 'health_cautious_pct',
        'cost_per_trade': 'cost_per_trade_pct',
      }
      const configKey = fieldMap[mlKey] ?? mlKey
      return cfg.MARTIN_LUK?.[configKey] ?? 0
    }

    const field = FIELDS.find(f => f.key === key)!
    const sectionToDict: Record<string, Record<string, number | boolean>> = {
      'MA Regime Filter':           cfg.MA_REGIME as Record<string, number | boolean>,
      'Cross-Sectional Momentum':   cfg.CROSS_MOMENTUM as Record<string, number | boolean>,
      'IBS Mean Reversion':         cfg.IBS as Record<string, number | boolean>,
      'Position Sizing':            cfg.SIZING as Record<string, number | boolean>,
      'Stock Quality Filter':       (cfg.STOCK_FILTER || {}) as Record<string, number | boolean>,
      'Transaction Costs':          cfg.COSTS as Record<string, number | boolean>,
    }
    return sectionToDict[field.section]?.[key] ?? 0
  }

  const handleChange = (key: string, value: number | boolean) => {
    setDraft(prev => ({ ...prev, [key]: value }))
  }

  const handleSave = () => {
    const merged = { ...cfg.overrides, ...draft }
    saveMut.mutate(merged)
  }

  const handleSaveToFile = () => {
    if (!confirm('Write current overrides permanently into config.py? This makes them the new defaults.')) return
    // First save any unsaved draft, then write to file
    if (Object.keys(draft).length > 0) {
      const merged = { ...cfg.overrides, ...draft }
      saveMut.mutate(merged, {
        onSuccess: () => saveFileMut.mutate(),
      })
    } else {
      saveFileMut.mutate()
    }
  }

  const hasDraft = Object.keys(draft).length > 0
  const tabFields = FIELDS.filter(f => f.strategy === tab)
  const sections = [...new Set(tabFields.map(f => f.section))]

  const TABS: { id: StrategyTab; label: string }[] = [
    { id: 'carver', label: 'Carver — Momentum + Mean Reversion' },
    { id: 'martin_luk', label: 'Martin Luk — Swing Breakout' },
    { id: 'shared', label: 'Shared Settings' },
  ]

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-100">Configuration</h1>
        <div className="flex items-center gap-2">
          {saved && <span className="text-success text-sm">Saved!</span>}
          {fileSaved && <span className="text-success text-sm">{fileSaved}</span>}
          {cfg.has_overrides && (
            <button className="btn-secondary text-sm flex items-center gap-1.5"
              onClick={() => clearMut.mutate()}>
              <RotateCcw size={13} /> Reset to defaults
            </button>
          )}
          <button className="btn-primary flex items-center gap-1.5" onClick={handleSave}
            disabled={!hasDraft || saveMut.isPending}>
            <Save size={14} />
            {saveMut.isPending ? 'Saving...' : 'Save Overrides'}
          </button>
          {cfg.has_overrides && (
            <button
              className="px-3 py-2 text-sm rounded-lg border border-warning/40 text-warning hover:bg-warning/10 transition-colors flex items-center gap-1.5 disabled:opacity-50"
              onClick={handleSaveToFile}
              disabled={saveFileMut.isPending}
            >
              <HardDrive size={14} />
              {saveFileMut.isPending ? 'Writing...' : 'Save to File'}
            </button>
          )}
        </div>
      </div>

      {cfg.has_overrides && (
        <div className="card bg-primary/10 border-primary/30">
          <p className="text-sm text-gray-300">
            <span className="text-primary font-semibold">Active overrides:</span>{' '}
            {Object.keys(cfg.overrides).join(', ')}
          </p>
        </div>
      )}

      <p className="text-xs text-gray-500">
        Change values then click <strong className="text-gray-400">Save Overrides</strong> to apply on next backtest.
        Use <strong className="text-warning">Save to File</strong> to write overrides permanently into config.py.
      </p>

      {/* Strategy tabs */}
      <div className="flex gap-2 border-b border-border pb-1">
        {TABS.map(t => (
          <button
            key={t.id}
            className={`px-4 py-2 text-sm font-medium rounded-t-lg transition-colors ${
              tab === t.id
                ? 'bg-card border border-b-0 border-border text-primary'
                : 'text-gray-500 hover:text-gray-300'
            }`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Fields for active tab */}
      {sections.map(section => (
        <div key={section} className="card space-y-4">
          <h2 className="text-base font-semibold text-gray-200 pb-2 border-b border-border">{section}</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {tabFields.filter(f => f.section === section).map(field => {
              const current = effectiveValue(field.key)
              const isDirty = field.key in draft
              const isOverride = !isDirty && field.key in cfg.overrides

              return (
                <div key={field.key} className={`space-y-1 ${isDirty ? 'border-l-2 border-primary pl-3' : isOverride ? 'border-l-2 border-warning/60 pl-3' : ''}`}>
                  <div className="flex items-center justify-between">
                    <label className="text-sm font-medium text-gray-300">{field.label}</label>
                    <div className="flex items-center gap-2">
                      {isDirty && <span className="text-xs text-primary">modified</span>}
                      {isOverride && !isDirty && <span className="text-xs text-warning">override</span>}
                      <span className="text-xs text-gray-500 font-mono">{fmt(current, field.type)}</span>
                    </div>
                  </div>
                  {field.type === 'boolean' ? (
                    <div className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={current as boolean}
                        onChange={e => handleChange(field.key, e.target.checked)}
                        className="w-4 h-4 accent-primary"
                      />
                      <span className="text-sm text-gray-400">{current ? 'Enabled' : 'Disabled'}</span>
                    </div>
                  ) : (
                    <input
                      type="number"
                      className="input text-sm"
                      value={current as number}
                      min={field.min}
                      max={field.max}
                      step={field.step}
                      onChange={e => handleChange(field.key, parseFloat(e.target.value))}
                    />
                  )}
                  <p className="text-xs text-gray-500">{field.description}</p>
                </div>
              )
            })}
          </div>
        </div>
      ))}

      {/* Read-only info panels (only show on Carver tab) */}
      {tab === 'carver' && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="card">
            <h2 className="text-base font-semibold text-gray-200 mb-3">FDM & Forecast</h2>
            <div className="space-y-2 text-sm text-gray-300">
              <div className="flex justify-between">
                <span>FDM (Forecast Diversification Multiplier)</span>
                <span className="font-mono text-gray-100">{cfg.FDM}</span>
              </div>
              <div className="flex justify-between">
                <span>Forecast Cap (±)</span>
                <span className="font-mono text-gray-100">{cfg.FORECAST_CAP}</span>
              </div>
            </div>
            <p className="text-xs text-gray-600 mt-2">Scalar values — edit config.py directly to change.</p>
          </div>

          <div className="card">
            <h2 className="text-base font-semibold text-gray-200 mb-3">Backtest Engine</h2>
            <div className="space-y-2 text-sm text-gray-300">
              {Object.entries(cfg.BACKTEST).map(([k, v]) => (
                <div key={k} className="flex justify-between">
                  <span className="text-gray-400">{k}</span>
                  <span className="font-mono text-gray-100">{String(v)}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Universe (show on shared tab) */}
      {tab === 'shared' && (
        <div className="card">
          <h2 className="text-base font-semibold text-gray-200 mb-3">Universe ({cfg.UNIVERSE.length} stocks)</h2>
          <div className="flex flex-wrap gap-2">
            {cfg.UNIVERSE.map(t => (
              <span key={t} className="text-xs bg-primary/15 text-primary px-2.5 py-1 rounded-full font-semibold">
                {t.replace('.VN', '')}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
