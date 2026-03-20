import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { RotateCcw, Save } from 'lucide-react'
import { fetchConfig, saveConfig, clearConfigOverrides } from '../api/client'

interface FieldDef {
  key: string
  label: string
  description: string
  type: 'number' | 'boolean'
  min?: number
  max?: number
  step?: number
  section: string
}

const FIELDS: FieldDef[] = [
  // MA Regime
  { key: 'ma_period',           label: 'MA Period',              description: 'Moving average period for regime detection. Keep at 200 (global standard).', type: 'number', min: 50, max: 500, step: 1, section: 'MA Regime Filter' },
  { key: 'confirm_days',        label: 'Confirm Days',           description: 'Days index must stay above/below MA before regime flips. Prevents whipsaw.', type: 'number', min: 1, max: 10, step: 1, section: 'MA Regime Filter' },
  { key: 'bear_tau_multiplier', label: 'Bear τ Multiplier',      description: 'Multiply target vol by this in BEAR regime. 0.5 = half sizing.', type: 'number', min: 0.1, max: 1.0, step: 0.05, section: 'MA Regime Filter' },
  { key: 'bear_new_entries',    label: 'Allow New Entries in Bear', description: 'If false, no new long positions when regime = BEAR. Existing positions still managed.', type: 'boolean', section: 'MA Regime Filter' },

  // Cross Momentum
  { key: 'lookback_days',        label: 'Lookback Days',         description: '3-month return lookback period. Keep at 63 (academic consensus).', type: 'number', min: 21, max: 252, step: 1, section: 'Cross-Sectional Momentum' },
  { key: 'skip_recent_days',     label: 'Skip Recent Days',      description: 'Skip most recent N days to avoid short-term reversal bias.', type: 'number', min: 0, max: 21, step: 1, section: 'Cross-Sectional Momentum' },
  { key: 'rebalance_every_days', label: 'Rebalance Every (days)', description: 'Monthly rebalance keeps cost drag low.', type: 'number', min: 5, max: 63, step: 1, section: 'Cross-Sectional Momentum' },
  { key: 'top_pct',              label: 'Top % (Buy Zone)',       description: 'Top N% of ranked stocks get positive forecast (BUY signal).', type: 'number', min: 0.1, max: 0.6, step: 0.05, section: 'Cross-Sectional Momentum' },
  { key: 'bottom_pct',           label: 'Bottom % (Reduce Zone)', description: 'Bottom N% of ranked stocks get negative forecast (REDUCE signal).', type: 'number', min: 0.1, max: 0.6, step: 0.05, section: 'Cross-Sectional Momentum' },

  // IBS
  { key: 'oversold_threshold',    label: 'IBS Oversold < ',   description: 'IBS below this = closed near daily low = oversold signal.', type: 'number', min: 0.05, max: 0.40, step: 0.01, section: 'IBS Mean Reversion' },
  { key: 'overbought_threshold',  label: 'IBS Overbought > ', description: 'IBS above this = closed near daily high = overbought signal.', type: 'number', min: 0.60, max: 0.95, step: 0.01, section: 'IBS Mean Reversion' },
  { key: 'only_in_bull_regime',   label: 'BULL Regime Only',  description: 'Only trade IBS in BULL regime. IBS in BEAR = catching falling knives.', type: 'boolean', section: 'IBS Mean Reversion' },

  // Signal weights
  { key: 'weight_cross_momentum', label: 'Cross-Momentum Weight', description: 'Weight of cross-momentum signal. Weights sum to 0.70 (0.30 = cash).', type: 'number', min: 0.1, max: 0.9, step: 0.01, section: 'Signal Weights' },
  { key: 'weight_ibs',            label: 'IBS Weight',            description: 'Weight of IBS signal. Keep low (counter-trend, low frequency).', type: 'number', min: 0.0, max: 0.40, step: 0.01, section: 'Signal Weights' },

  // Position sizing
  { key: 'target_vol',        label: 'Target Vol (τ)',      description: 'Portfolio target volatility. 0.25 = 25%. Raised from Carver\'s 0.20 for VN high-correlation environment.', type: 'number', min: 0.10, max: 0.50, step: 0.01, section: 'Position Sizing' },
  { key: 'buffer_fraction',   label: 'Buffer Fraction',     description: 'Only trade when position drifts outside ±N% of optimal. 0.30 = ±30% band. Wider = fewer trades.', type: 'number', min: 0.05, max: 0.50, step: 0.01, section: 'Position Sizing' },
  { key: 'max_position_pct',  label: 'Max Position %',      description: 'Maximum single-stock concentration as % of total capital.', type: 'number', min: 0.05, max: 0.30, step: 0.01, section: 'Position Sizing' },
  { key: 'vol_lookback',      label: 'Vol Lookback (days)',  description: 'Days of returns used for volatility estimation. 60 = smoother; 20 = reactive but noisy.', type: 'number', min: 10, max: 120, step: 5, section: 'Position Sizing' },

  // Stock Quality Filter
  { key: 'filter_enabled',       label: 'Enable Stock Filter',     description: 'Pre-filter stocks by volume and history before backtesting. Removes illiquid names.', type: 'boolean', section: 'Stock Quality Filter' },
  { key: 'min_avg_volume',       label: 'Min Avg Volume (shares)', description: 'Minimum average daily trading volume. Stocks below this are excluded.', type: 'number', min: 100000, max: 5000000, step: 100000, section: 'Stock Quality Filter' },
  { key: 'volume_lookback_days', label: 'Volume Lookback (days)',  description: 'Period over which average volume is computed.', type: 'number', min: 20, max: 120, step: 5, section: 'Stock Quality Filter' },
  { key: 'min_history_days',     label: 'Min History (days)',      description: 'Stocks with fewer trading days of data are excluded.', type: 'number', min: 100, max: 500, step: 10, section: 'Stock Quality Filter' },

  // Costs
  { key: 'cost_per_trade_pct', label: 'Cost Per Trade (%)', description: 'TCBS: ~0.25% per side (brokerage 0.15% + stamp). Applies to every buy and sell.', type: 'number', min: 0.001, max: 0.01, step: 0.0001, section: 'Transaction Costs' },
]

const sections = [...new Set(FIELDS.map(f => f.section))]

function fmt(v: number | boolean, type: 'number' | 'boolean') {
  if (type === 'boolean') return v ? 'true' : 'false'
  if (typeof v === 'number') {
    return v < 0.01 ? v.toFixed(4) : v < 0.1 ? v.toFixed(3) : v < 1 ? v.toFixed(2) : v.toString()
  }
  return String(v)
}

export default function Config() {
  const qc = useQueryClient()
  const { data: cfg, isLoading } = useQuery({ queryKey: ['config'], queryFn: fetchConfig })

  // Local overrides being edited in the form
  const [draft, setDraft] = useState<Record<string, number | boolean>>({})
  const [saved, setSaved] = useState(false)

  const saveMut = useMutation({
    mutationFn: saveConfig,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['config'] })
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

  if (isLoading || !cfg) return <div className="text-gray-400 text-sm">Loading config...</div>

  // Effective value = draft override → saved override → config default
  const effectiveValue = (key: string): number | boolean => {
    if (key in draft) return draft[key]
    if (key in cfg.overrides) return cfg.overrides[key]

    // Special cases where field key != config key
    if (key === 'weight_cross_momentum') return cfg.SIGNAL_WEIGHTS.cross_momentum
    if (key === 'weight_ibs') return cfg.SIGNAL_WEIGHTS.ibs

    // For all other keys the field.key matches the config dict key directly
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
    // Merge draft into existing overrides
    const merged = { ...cfg.overrides, ...draft }
    saveMut.mutate(merged)
    setDraft({})
  }

  const hasDraft = Object.keys(draft).length > 0

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-100">Configuration</h1>
        <div className="flex items-center gap-2">
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
          {saved && <span className="text-success text-sm">Saved!</span>}
        </div>
      </div>

      {cfg.has_overrides && (
        <div className="card bg-primary/10 border-primary/30">
          <p className="text-sm text-gray-300">
            <span className="text-primary font-semibold">Active overrides:</span>{' '}
            {Object.keys(cfg.overrides).join(', ')}. These will be applied on the next backtest run.
          </p>
        </div>
      )}

      <p className="text-xs text-gray-500">
        Overrides apply to the next backtest run. The original <code className="text-gray-400">config.py</code> is unchanged.
        All dict-based parameters take effect immediately. Scalar parameters (FDM, FORECAST_CAP) require a server restart.
      </p>

      {sections.map(section => (
        <div key={section} className="card space-y-4">
          <h2 className="text-base font-semibold text-gray-200 pb-2 border-b border-border">{section}</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {FIELDS.filter(f => f.section === section).map(field => {
              const current = effectiveValue(field.key)
              const isDirty = field.key in draft
              const isOverride = !isDirty && field.key in cfg.overrides

              return (
                <div key={field.key} className={`space-y-1 ${isDirty ? 'border-l-2 border-primary pl-3' : isOverride ? 'border-l-2 border-warning/60 pl-3' : ''}`}>
                  <div className="flex items-center justify-between">
                    <label className="text-sm font-medium text-gray-300">{field.label}</label>
                    <div className="flex items-center gap-2">
                      {isDirty && <span className="text-xs text-primary">modified</span>}
                      {isOverride && !isDirty && <span className="text-xs text-warning">override active</span>}
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

      {/* Read-only info panels */}
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
          <p className="text-xs text-gray-600 mt-2">These scalar values require a server restart to change.</p>
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

      {/* Universe */}
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

      {/* Anti-overfitting checklist */}
      <div className="card">
        <h2 className="text-base font-semibold text-gray-200 mb-3">Anti-Overfitting Checklist</h2>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-gray-500 text-xs uppercase border-b border-border">
              <th className="py-2 pr-6 text-left">Parameter</th>
              <th className="py-2 pr-6 text-left">Value</th>
              <th className="py-2 text-left">Justification</th>
            </tr>
          </thead>
          <tbody className="text-gray-400">
            {[
              ['MA period', '200', 'Global standard. Not optimised for VN.'],
              ['Momentum lookback', '63 days', '= 3 months. Round number, academic consensus.'],
              ['Momentum skip', '5 days', '= 1 week. Avoids short-term reversal bias.'],
              ['IBS oversold', '0.20', 'Textbook value.'],
              ['IBS overbought', '0.80', 'Textbook value.'],
              ['Rebalance freq', '21 days', '= Monthly. Cost-driven, not optimised.'],
              ['Buffer zone', '30%', 'Wider than Carver default (20%) for illiquid VN market.'],
              ['τ (target vol)', '25%', 'Raised from 20% for VN high correlation.'],
              ['Regime update', 'Weekly', 'Prevents whipsaw. Not optimised frequency.'],
            ].map(([param, val, reason]) => (
              <tr key={param} className="border-b border-border/40">
                <td className="py-2 pr-6 font-medium text-gray-300">{param}</td>
                <td className="py-2 pr-6 font-mono text-gray-200">{val}</td>
                <td className="py-2">{reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
