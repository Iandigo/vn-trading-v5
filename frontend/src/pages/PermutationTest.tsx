import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Bar,
  BarChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { fetchPermutation, startPermutation, fetchJob } from '../api/client'
import type { Strategy } from '../types'

function buildHistogram(values: number[], bins = 30) {
  // Filter out extreme/invalid values (NaN, Inf, or abs > 100)
  const clean = values.filter(v => Number.isFinite(v) && Math.abs(v) < 100)
  if (clean.length < 2) return []
  const min = Math.min(...clean)
  const max = Math.max(...clean)
  const range = max - min
  if (range < 1e-10) return [] // All values are the same — no distribution to show
  const binWidth = range / bins
  const hist: { x: number; count: number }[] = []
  for (let i = 0; i < bins; i++) {
    const lo = min + i * binWidth
    const hi = lo + binWidth
    hist.push({ x: +(lo + binWidth / 2).toFixed(4), count: clean.filter(v => v >= lo && v < hi).length })
  }
  return hist
}

/** Check if results look corrupted (all same values, extreme numbers, etc.) */
function isDataCorrupted(p: { perm_mean: number; perm_distribution: number[] }): boolean {
  if (!Number.isFinite(p.perm_mean) || Math.abs(p.perm_mean) > 100) return true
  const clean = p.perm_distribution.filter(v => Number.isFinite(v) && Math.abs(v) < 100)
  return clean.length < p.perm_distribution.length * 0.5
}

export default function PermutationTest() {
  const qc = useQueryClient()
  const { data: perm } = useQuery({ queryKey: ['permutation'], queryFn: fetchPermutation })

  const [nPerm, setNPerm] = useState(100)
  const [years, setYears] = useState(3)
  const [nStocks, setNStocks] = useState(10)
  const [useReal, setUseReal] = useState(false)
  const [metric, setMetric] = useState<'sharpe' | 'cagr'>('sharpe')
  const [strategy, setStrategy] = useState<Strategy>('carver')
  const [jobId, setJobId] = useState<string | null>(null)
  const [jobDone, setJobDone] = useState(false)

  const { data: jobData } = useQuery({
    queryKey: ['job', jobId],
    queryFn: () => fetchJob(jobId!),
    enabled: !!jobId && !jobDone,
    refetchInterval: jobDone ? false : 2000,
  })

  useEffect(() => {
    if (!jobData) return
    if (jobData.status === 'completed' || jobData.status === 'failed') {
      setJobDone(true)
      if (jobData.status === 'completed') {
        qc.invalidateQueries({ queryKey: ['permutation'] })
      }
    }
  }, [jobData, qc])

  const runMut = useMutation({
    mutationFn: startPermutation,
    onSuccess: (id: string) => {
      setJobId(id)
      setJobDone(false)
    },
  })

  const isRunning = jobId && !jobDone && jobData?.status === 'running'
  const progress = jobData?.progress ?? 0

  const p = perm?.available ? perm : null
  const corrupted = p ? isDataCorrupted(p) : false

  const verdict = () => {
    if (!p || corrupted) return null
    const pv = p.p_value
    if (pv < 0.01) return { label: 'STRONG EDGE', color: 'text-success', bg: 'bg-success/10 border-success/30' }
    if (pv < 0.05) return { label: 'EDGE DETECTED', color: 'text-success', bg: 'bg-success/10 border-success/30' }
    if (pv < 0.10) return { label: 'MARGINAL', color: 'text-warning', bg: 'bg-warning/10 border-warning/30' }
    return { label: 'NO EDGE DETECTED', color: 'text-danger', bg: 'bg-danger/10 border-danger/30' }
  }

  const vd = verdict()
  const histData = p && !corrupted ? buildHistogram(p.perm_distribution) : []

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-100">Permutation Test — Statistical Edge</h1>

      {/* Run panel */}
      <div className="card space-y-4">
        <h2 className="text-base font-semibold text-gray-200">Run Permutation Test</h2>
        <p className="text-xs text-gray-500">
          Shuffles daily returns to destroy momentum/regime signals, then re-runs the full backtest on each shuffle.
          If your real strategy beats most shuffles, the edge is statistically real.
        </p>
        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-4">
          <div>
            <label className="label">Strategy</label>
            <select className="select" value={strategy} onChange={e => setStrategy(e.target.value as Strategy)}>
              <option value="carver">Carver</option>
              <option value="martin_luk">Martin Luk</option>
            </select>
          </div>
          <div>
            <label className="label">Permutations</label>
            <input type="number" className="input" value={nPerm} min={10} max={1000}
              onChange={e => setNPerm(+e.target.value)} />
          </div>
          <div>
            <label className="label">Years</label>
            <input type="number" className="input" value={years} min={1} max={10}
              onChange={e => setYears(+e.target.value)} />
          </div>
          <div>
            <label className="label">Stocks</label>
            <input type="number" className="input" value={nStocks} min={5} max={30}
              onChange={e => setNStocks(+e.target.value)} />
          </div>
          <div>
            <label className="label">Metric</label>
            <select className="select" value={metric} onChange={e => setMetric(e.target.value as 'sharpe' | 'cagr')}>
              <option value="sharpe">Sharpe Ratio</option>
              <option value="cagr">CAGR</option>
            </select>
          </div>
          <div>
            <label className="label">Data Source</label>
            <div className="flex items-center gap-2 mt-2">
              <input type="checkbox" id="realPerm" checked={useReal} onChange={e => setUseReal(e.target.checked)}
                className="w-4 h-4 accent-primary" />
              <label htmlFor="realPerm" className="text-sm text-gray-300">Real data</label>
            </div>
          </div>
        </div>
        <div className="space-y-2">
          <div className="flex items-center gap-3">
            <button className="btn-primary" disabled={!!isRunning}
              onClick={() => runMut.mutate({ n_perm: nPerm, years, n_stocks: nStocks, use_real: useReal, metric, strategy })}>
              {isRunning ? 'Running...' : 'Run Permutation Test'}
            </button>
            {jobDone && jobData?.status === 'failed' && (
              <p className="text-sm text-danger">{jobData.error}</p>
            )}
            {jobDone && jobData?.status === 'completed' && (
              <p className="text-sm text-success">Complete! Results updated below.</p>
            )}
          </div>
          {isRunning && (
            <div className="space-y-1">
              <div className="flex items-center justify-between text-xs text-gray-400">
                <span>{jobData?.stage || 'Starting...'}</span>
                <span>{progress}%</span>
              </div>
              <div className="w-full h-2 bg-gray-700 rounded-full overflow-hidden">
                <div
                  className="h-full bg-primary rounded-full transition-all duration-500"
                  style={{ width: `${progress}%` }}
                />
              </div>
            </div>
          )}
        </div>
      </div>

      {!p && (
        <div className="flex flex-col items-center justify-center h-40 text-gray-400 gap-2">
          <p>No permutation test results yet. Run the test above to validate your strategy's edge.</p>
        </div>
      )}

      {/* Warning for corrupted data */}
      {p && corrupted && (
        <div className="card border bg-warning/10 border-warning/30">
          <p className="text-warning font-semibold">Previous results are invalid</p>
          <p className="text-sm text-gray-300 mt-1">
            The saved permutation data contains extreme values (perm mean: {p.perm_mean.toExponential(2)}).
            This was caused by a bug that has been fixed. Please re-run the permutation test to get valid results.
          </p>
        </div>
      )}

      {p && !corrupted && (
        <>
          {/* Verdict banner */}
          {vd && (
            <div className={`card border ${vd.bg}`}>
              <p className={`text-lg font-bold ${vd.color}`}>{vd.label}</p>
              <p className="text-sm text-gray-300 mt-1">
                p-value: <span className="font-mono font-semibold">{p.p_value.toFixed(4)}</span>{' '}
                (95% CI: [{p.p_ci_low.toFixed(4)}, {p.p_ci_high.toFixed(4)}])
              </p>
            </div>
          )}

          {/* Key metrics */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div className="card">
              <p className="label">Real Strategy {p.metric.toUpperCase()}</p>
              <p className="text-2xl font-bold text-gray-100">{p.real_value > 0 ? '+' : ''}{p.real_value.toFixed(3)}</p>
              <p className="text-xs text-gray-500 mt-1">Your strategy's actual {p.metric === 'sharpe' ? 'risk-adjusted return' : 'annualised return'}</p>
            </div>
            <div className="card">
              <p className="label">Perm. Mean {p.metric.toUpperCase()}</p>
              <p className="text-2xl font-bold text-gray-100">{p.perm_mean > 0 ? '+' : ''}{p.perm_mean.toFixed(3)}</p>
              <p className="text-xs text-gray-500 mt-1">Average from random shuffles (no momentum/regime edge)</p>
            </div>
            <div className="card">
              <p className="label">p-value</p>
              <p className={`text-2xl font-bold ${p.p_value < 0.05 ? 'text-success' : p.p_value < 0.10 ? 'text-warning' : 'text-danger'}`}>
                {p.p_value.toFixed(4)}
              </p>
              <p className="text-xs text-gray-500 mt-1">Fraction of random strategies that beat yours (lower = better)</p>
            </div>
            <div className="card">
              <p className="label">Beats Real</p>
              <p className="text-2xl font-bold text-gray-100">{p.n_beats_real} / {p.n_permutations}</p>
              <p className="text-xs text-gray-500 mt-1">How many random shuffles outperformed your strategy</p>
            </div>
          </div>

          {/* Distribution chart */}
          {histData.length > 0 ? (
            <div className="card">
              <h2 className="text-lg font-semibold mb-1 text-gray-200">Permutation Distribution</h2>
              <p className="text-xs text-gray-500 mb-4">
                Each bar = how many random shuffles achieved that {p.metric.toUpperCase()}.
                The orange line = your real strategy. Further right = better.
              </p>
              <ResponsiveContainer width="100%" height={280}>
                <BarChart data={histData} margin={{ top: 20, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#2d3748" />
                  <XAxis dataKey="x" type="number" domain={['dataMin', 'dataMax']}
                    tick={{ fill: '#718096', fontSize: 11 }}
                    tickFormatter={(v: number) => v.toFixed(2)} />
                  <YAxis tick={{ fill: '#718096', fontSize: 11 }} width={35} />
                  <Tooltip contentStyle={{ background: '#1e2130', border: '1px solid #2d3748', borderRadius: 8 }}
                    labelFormatter={(v: number) => `${p.metric.toUpperCase()}: ${Number(v).toFixed(3)}`}
                    formatter={(v: number) => [v, 'Count']} />
                  <Bar dataKey="count" fill="#9FE1CB" opacity={0.85} radius={[2, 2, 0, 0]} />
                  <ReferenceLine x={p.real_value} stroke="#E85D24" strokeWidth={2.5} strokeDasharray="4 2"
                    label={{ value: `Real: ${p.real_value.toFixed(3)}`, fill: '#E85D24', fontSize: 12, position: 'top' }} />
                </BarChart>
              </ResponsiveContainer>
              <p className="text-xs text-gray-500 mt-2">
                {p.n_permutations} permutations | {p.years} years | {p.n_stocks} stocks
              </p>
            </div>
          ) : (
            <div className="card text-center text-gray-400 py-8">
              <p>Distribution chart unavailable — permutation values may lack spread.</p>
              <p className="text-xs mt-1">Try re-running with more permutations or different parameters.</p>
            </div>
          )}

          {/* Interpretation table */}
          <div className="card">
            <h2 className="text-base font-semibold mb-2 text-gray-200">What do these metrics mean?</h2>
            <p className="text-xs text-gray-500 mb-3">
              The permutation test shuffles your historical returns randomly {p.n_permutations} times.
              Each shuffle destroys any momentum or regime patterns — so a shuffled backtest represents
              a "no-edge" baseline. If your real strategy consistently beats these random versions,
              the signals are adding real value.
            </p>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 text-xs uppercase border-b border-border">
                  <th className="py-2 pr-6 text-left">p-value</th>
                  <th className="py-2 text-left">Meaning</th>
                </tr>
              </thead>
              <tbody>
                {[
                  ['< 0.01', 'Strong edge — only 1% of random strategies do this well. High confidence.', 'text-success'],
                  ['0.01 - 0.05', 'Edge detected — 95% confidence. Acceptable for live trading.', 'text-success'],
                  ['0.05 - 0.10', 'Marginal — some signal but noisy. Consider more data or paper-trade.', 'text-warning'],
                  ['> 0.10', 'No edge detected — the strategy may be no better than random.', 'text-danger'],
                ].map(([pv, meaning, color]) => (
                  <tr key={pv} className="border-b border-border/40">
                    <td className={`py-2 pr-6 font-mono font-semibold ${color}`}>{pv}</td>
                    <td className="py-2 text-gray-300">{meaning}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}
