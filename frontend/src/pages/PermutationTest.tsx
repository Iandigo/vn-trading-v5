import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  fetchPermutation, startPermutation,
  fetchWalkForward, startWalkForward,
  fetchWfPermutation, startWfPermutation,
  fetchJob,
} from '../api/client'
import type { Strategy } from '../types'

// ── Shared helpers ──────────────────────────────────────────────────────────

type Tab = 'is_perm' | 'walk_forward' | 'wf_perm'

function buildHistogram(values: number[], bins = 30) {
  const clean = values.filter(v => Number.isFinite(v) && Math.abs(v) < 100)
  if (clean.length < 2) return []
  const min = Math.min(...clean)
  const max = Math.max(...clean)
  const range = max - min
  if (range < 1e-10) return []
  const binWidth = range / bins
  const hist: { x: number; count: number }[] = []
  for (let i = 0; i < bins; i++) {
    const lo = min + i * binWidth
    hist.push({ x: +(lo + binWidth / 2).toFixed(4), count: clean.filter(v => v >= lo && v < lo + binWidth).length })
  }
  return hist
}

function isDataCorrupted(p: { perm_mean: number; perm_distribution: number[] }): boolean {
  if (!Number.isFinite(p.perm_mean) || Math.abs(p.perm_mean) > 100) return true
  const clean = p.perm_distribution.filter(v => Number.isFinite(v) && Math.abs(v) < 100)
  return clean.length < p.perm_distribution.length * 0.5
}

function VerdictBanner({ pValue, ciLow, ciHigh }: { pValue: number; ciLow: number; ciHigh: number }) {
  const v = pValue < 0.01
    ? { label: 'STRONG EDGE', color: 'text-success', bg: 'bg-success/10 border-success/30' }
    : pValue < 0.05
    ? { label: 'EDGE DETECTED', color: 'text-success', bg: 'bg-success/10 border-success/30' }
    : pValue < 0.10
    ? { label: 'MARGINAL', color: 'text-warning', bg: 'bg-warning/10 border-warning/30' }
    : { label: 'NO EDGE DETECTED', color: 'text-danger', bg: 'bg-danger/10 border-danger/30' }
  return (
    <div className={`card border ${v.bg}`}>
      <p className={`text-lg font-bold ${v.color}`}>{v.label}</p>
      <p className="text-sm text-gray-300 mt-1">
        p-value: <span className="font-mono font-semibold">{pValue.toFixed(4)}</span>{' '}
        (95% CI: [{ciLow.toFixed(4)}, {ciHigh.toFixed(4)}])
      </p>
    </div>
  )
}

function MetricCard({ label, value, sub, color }: { label: string; value: string; sub: string; color?: string }) {
  return (
    <div className="card">
      <p className="label">{label}</p>
      <p className={`text-2xl font-bold ${color || 'text-gray-100'}`}>{value}</p>
      <p className="text-xs text-gray-500 mt-1">{sub}</p>
    </div>
  )
}

function DistributionChart({ data, metric, realValue, realLabel }: {
  data: { x: number; count: number }[]
  metric: string
  realValue: number
  realLabel: string
}) {
  if (data.length === 0) return (
    <div className="card text-center text-gray-400 py-8">
      <p>Distribution chart unavailable.</p>
    </div>
  )
  return (
    <div className="card">
      <h2 className="text-lg font-semibold mb-1 text-gray-200">Permutation Distribution</h2>
      <p className="text-xs text-gray-500 mb-4">
        Each bar = how many random shuffles achieved that {metric.toUpperCase()}.
        The orange line = {realLabel}. Further right = better.
      </p>
      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={data} margin={{ top: 20, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#2d3748" />
          <XAxis dataKey="x" type="number" domain={['dataMin', 'dataMax']}
            tick={{ fill: '#718096', fontSize: 11 }}
            tickFormatter={(v: number) => v.toFixed(2)} />
          <YAxis tick={{ fill: '#718096', fontSize: 11 }} width={35} />
          <Tooltip contentStyle={{ background: '#1e2130', border: '1px solid #2d3748', borderRadius: 8 }}
            labelFormatter={(v: number) => `${metric.toUpperCase()}: ${Number(v).toFixed(3)}`}
            formatter={(v: number) => [v, 'Count']} />
          <Bar dataKey="count" fill="#9FE1CB" opacity={0.85} radius={[2, 2, 0, 0]} />
          <ReferenceLine x={realValue} stroke="#E85D24" strokeWidth={2.5} strokeDasharray="4 2"
            label={{ value: `${realLabel}: ${realValue.toFixed(3)}`, fill: '#E85D24', fontSize: 12, position: 'top' }} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

function ProgressBar({ stage, progress }: { stage: string; progress: number }) {
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs text-gray-400">
        <span>{stage || 'Starting...'}</span>
        <span>{progress}%</span>
      </div>
      <div className="w-full h-2 bg-gray-700 rounded-full overflow-hidden">
        <div className="h-full bg-primary rounded-full transition-all duration-500"
          style={{ width: `${progress}%` }} />
      </div>
    </div>
  )
}

function PValueTable() {
  return (
    <div className="card">
      <h2 className="text-base font-semibold mb-2 text-gray-200">Interpretation Guide</h2>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-gray-500 text-xs uppercase border-b border-border">
            <th className="py-2 pr-6 text-left">p-value</th>
            <th className="py-2 text-left">Meaning</th>
          </tr>
        </thead>
        <tbody>
          {[
            ['< 0.01', 'Strong edge — only 1% of random strategies do this well.', 'text-success'],
            ['0.01 - 0.05', 'Edge detected — 95% confidence. Acceptable for live trading.', 'text-success'],
            ['0.05 - 0.10', 'Marginal — some signal but noisy. Consider more data.', 'text-warning'],
            ['> 0.10', 'No edge — the strategy may be no better than random.', 'text-danger'],
          ].map(([pv, meaning, color]) => (
            <tr key={pv} className="border-b border-border/40">
              <td className={`py-2 pr-6 font-mono font-semibold ${color}`}>{pv}</td>
              <td className="py-2 text-gray-300">{meaning}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Shared job hook ─────────────────────────────────────────────────────────

function useJob(invalidateKey: string) {
  const qc = useQueryClient()
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
        qc.invalidateQueries({ queryKey: [invalidateKey] })
      }
    }
  }, [jobData, qc, invalidateKey])

  const isRunning = !!jobId && !jobDone && jobData?.status === 'running'
  const progress = jobData?.progress ?? 0

  return { jobId, jobDone, jobData, isRunning, progress, setJobId, setJobDone }
}

// ── Tab 1: In-Sample Permutation ────────────────────────────────────────────

function InSamplePermTab() {
  const { data: perm } = useQuery({ queryKey: ['permutation'], queryFn: fetchPermutation })
  const [nPerm, setNPerm] = useState(100)
  const [years, setYears] = useState(3)
  const [nStocks, setNStocks] = useState(10)
  const [useReal, setUseReal] = useState(false)
  const [metric, setMetric] = useState<'sharpe' | 'cagr'>('sharpe')
  const [strategy, setStrategy] = useState<Strategy>('carver')

  const job = useJob('permutation')
  const runMut = useMutation({
    mutationFn: startPermutation,
    onSuccess: (id: string) => { job.setJobId(id); job.setJobDone(false) },
  })

  const p = perm?.available ? perm : null
  const corrupted = p ? isDataCorrupted(p) : false
  const histData = p && !corrupted ? buildHistogram(p.perm_distribution) : []

  return (
    <div className="space-y-6">
      {/* Controls */}
      <div className="card space-y-4">
        <div>
          <h2 className="text-base font-semibold text-gray-200">Step 2: In-Sample Permutation Test</h2>
          <p className="text-xs text-gray-500 mt-1">
            Shuffles returns to destroy signals, re-runs full backtest on each. Tests if your
            in-sample performance is statistically better than random.
          </p>
        </div>
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
            <input type="number" className="input" value={nPerm} min={10} max={1000} onChange={e => setNPerm(+e.target.value)} />
          </div>
          <div>
            <label className="label">Years</label>
            <input type="number" className="input" value={years} min={1} max={10} onChange={e => setYears(+e.target.value)} />
          </div>
          <div>
            <label className="label">Stocks</label>
            <input type="number" className="input" value={nStocks} min={5} max={30} onChange={e => setNStocks(+e.target.value)} />
          </div>
          <div>
            <label className="label">Metric</label>
            <select className="select" value={metric} onChange={e => setMetric(e.target.value as 'sharpe' | 'cagr')}>
              <option value="sharpe">Sharpe</option>
              <option value="cagr">CAGR</option>
            </select>
          </div>
          <div>
            <label className="label">Data</label>
            <div className="flex items-center gap-2 mt-2">
              <input type="checkbox" id="realIS" checked={useReal} onChange={e => setUseReal(e.target.checked)} className="w-4 h-4 accent-primary" />
              <label htmlFor="realIS" className="text-sm text-gray-300">Real data</label>
            </div>
          </div>
        </div>
        <div className="space-y-2">
          <div className="flex items-center gap-3">
            <button className="btn-primary" disabled={job.isRunning}
              onClick={() => runMut.mutate({ n_perm: nPerm, years, n_stocks: nStocks, use_real: useReal, metric, strategy })}>
              {job.isRunning ? 'Running...' : 'Run Permutation Test'}
            </button>
            {job.jobDone && job.jobData?.status === 'failed' && <p className="text-sm text-danger">{job.jobData.error}</p>}
            {job.jobDone && job.jobData?.status === 'completed' && <p className="text-sm text-success">Complete!</p>}
          </div>
          {job.isRunning && <ProgressBar stage={job.jobData?.stage || ''} progress={job.progress} />}
        </div>
      </div>

      {!p && <div className="flex items-center justify-center h-32 text-gray-400">No results yet. Run the test above.</div>}

      {p && corrupted && (
        <div className="card border bg-warning/10 border-warning/30">
          <p className="text-warning font-semibold">Previous results are invalid</p>
          <p className="text-sm text-gray-300 mt-1">Re-run the test to get valid results.</p>
        </div>
      )}

      {p && !corrupted && (
        <>
          <VerdictBanner pValue={p.p_value} ciLow={p.p_ci_low} ciHigh={p.p_ci_high} />
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <MetricCard label={`Real ${p.metric.toUpperCase()}`} value={`${p.real_value > 0 ? '+' : ''}${p.real_value.toFixed(3)}`} sub="Your strategy's in-sample metric" />
            <MetricCard label={`Perm Mean`} value={`${p.perm_mean > 0 ? '+' : ''}${p.perm_mean.toFixed(3)}`} sub="Average from random shuffles" />
            <MetricCard label="p-value" value={p.p_value.toFixed(4)} sub="Lower = better" color={p.p_value < 0.05 ? 'text-success' : p.p_value < 0.10 ? 'text-warning' : 'text-danger'} />
            <MetricCard label="Beats Real" value={`${p.n_beats_real} / ${p.n_permutations}`} sub="Shuffles that outperformed" />
          </div>
          <DistributionChart data={histData} metric={p.metric} realValue={p.real_value} realLabel="Real" />
          <PValueTable />
        </>
      )}
    </div>
  )
}

// ── Tab 2: Walk-Forward Test ────────────────────────────────────────────────

function WalkForwardTab() {
  const { data: wf } = useQuery({ queryKey: ['walkForward'], queryFn: fetchWalkForward })
  const [years, setYears] = useState(10)
  const [trainYears, setTrainYears] = useState(3)
  const [testMonths, setTestMonths] = useState(6)
  const [nStocks, setNStocks] = useState(10)
  const [metric, setMetric] = useState<'sharpe' | 'cagr'>('sharpe')
  const [strategy, setStrategy] = useState<Strategy>('carver')
  const [useReal, setUseReal] = useState(true)

  const job = useJob('walkForward')
  const runMut = useMutation({
    mutationFn: startWalkForward,
    onSuccess: (id: string) => { job.setJobId(id); job.setJobDone(false) },
  })

  const w = wf?.available ? wf : null

  const verdictStyle = (v: string) => {
    if (v === 'PASS') return { color: 'text-success', bg: 'bg-success/10 border-success/30' }
    if (v === 'MARGINAL') return { color: 'text-warning', bg: 'bg-warning/10 border-warning/30' }
    return { color: 'text-danger', bg: 'bg-danger/10 border-danger/30' }
  }

  return (
    <div className="space-y-6">
      <div className="card space-y-4">
        <div>
          <h2 className="text-base font-semibold text-gray-200">Step 3: Walk-Forward Test</h2>
          <p className="text-xs text-gray-500 mt-1">
            Splits data into rolling train/test windows. Grid-searches parameters on each training window,
            then tests with best params on the out-of-sample window. Measures if performance holds OOS.
          </p>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-7 gap-4">
          <div>
            <label className="label">Strategy</label>
            <select className="select" value={strategy} onChange={e => setStrategy(e.target.value as Strategy)}>
              <option value="carver">Carver</option>
              <option value="martin_luk">Martin Luk</option>
            </select>
          </div>
          <div>
            <label className="label">Total Years</label>
            <input type="number" className="input" value={years} min={3} max={15} onChange={e => setYears(+e.target.value)} />
          </div>
          <div>
            <label className="label">Train Years</label>
            <input type="number" className="input" value={trainYears} min={1} max={5} onChange={e => setTrainYears(+e.target.value)} />
          </div>
          <div>
            <label className="label">Test Months</label>
            <input type="number" className="input" value={testMonths} min={3} max={12} onChange={e => setTestMonths(+e.target.value)} />
          </div>
          <div>
            <label className="label">Stocks</label>
            <input type="number" className="input" value={nStocks} min={5} max={30} onChange={e => setNStocks(+e.target.value)} />
          </div>
          <div>
            <label className="label">Metric</label>
            <select className="select" value={metric} onChange={e => setMetric(e.target.value as 'sharpe' | 'cagr')}>
              <option value="sharpe">Sharpe</option>
              <option value="cagr">CAGR</option>
            </select>
          </div>
          <div>
            <label className="label">Data</label>
            <div className="flex items-center gap-2 mt-2">
              <input type="checkbox" id="realWF" checked={useReal} onChange={e => setUseReal(e.target.checked)} className="w-4 h-4 accent-primary" />
              <label htmlFor="realWF" className="text-sm text-gray-300">Real data</label>
            </div>
          </div>
        </div>
        <div className="space-y-2">
          <div className="flex items-center gap-3">
            <button className="btn-primary" disabled={job.isRunning}
              onClick={() => runMut.mutate({ years, train_years: trainYears, test_months: testMonths, n_stocks: nStocks, strategy, metric, use_real: useReal })}>
              {job.isRunning ? 'Running...' : 'Run Walk-Forward Test'}
            </button>
            {job.jobDone && job.jobData?.status === 'failed' && <p className="text-sm text-danger">{job.jobData.error}</p>}
            {job.jobDone && job.jobData?.status === 'completed' && <p className="text-sm text-success">Complete!</p>}
          </div>
          {job.isRunning && <ProgressBar stage={job.jobData?.stage || ''} progress={job.progress} />}
        </div>
      </div>

      {!w && <div className="flex items-center justify-center h-32 text-gray-400">No walk-forward results yet.</div>}

      {w && (() => {
        const vs = verdictStyle(w.verdict)
        return (
          <>
            {/* Verdict */}
            <div className={`card border ${vs.bg}`}>
              <p className={`text-lg font-bold ${vs.color}`}>Walk-Forward: {w.verdict}</p>
              <p className="text-sm text-gray-300 mt-1">
                WF Efficiency: <span className="font-mono font-semibold">{(w.wf_efficiency * 100).toFixed(0)}%</span>
                {' '}(OOS / IS ratio — above 50% is good)
              </p>
            </div>

            {/* Summary cards */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <MetricCard label={`OOS ${w.metric.toUpperCase()}`}
                value={`${w.oos_metric > 0 ? '+' : ''}${w.oos_metric.toFixed(3)}`}
                sub="Out-of-sample performance"
                color={w.oos_metric > 0 ? 'text-success' : 'text-danger'} />
              <MetricCard label={`IS Avg ${w.metric.toUpperCase()}`}
                value={`${w.is_avg_metric > 0 ? '+' : ''}${w.is_avg_metric.toFixed(3)}`}
                sub="Average in-sample (training)" />
              <MetricCard label="WF Efficiency"
                value={`${(w.wf_efficiency * 100).toFixed(0)}%`}
                sub="OOS / IS ratio (>50% good)"
                color={w.wf_efficiency > 0.5 ? 'text-success' : 'text-warning'} />
              <MetricCard label="Windows"
                value={`${w.n_windows}`}
                sub={`${w.train_years}yr train / ${w.test_months}mo test`} />
            </div>

            {/* OOS Equity Curve */}
            {w.oos_equity_curve && w.oos_equity_curve.length > 0 && (
              <div className="card">
                <h2 className="text-lg font-semibold mb-1 text-gray-200">OOS Equity Curve (Stitched)</h2>
                <p className="text-xs text-gray-500 mb-4">
                  Continuous equity built from all out-of-sample test windows.
                  This is what your strategy would have returned with rolling re-optimisation.
                </p>
                <ResponsiveContainer width="100%" height={280}>
                  <LineChart data={w.oos_equity_curve} margin={{ top: 10, right: 8, left: 10, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#2d3748" />
                    <XAxis dataKey="date" tick={{ fill: '#718096', fontSize: 10 }}
                      tickFormatter={(d: string) => d.slice(0, 7)} interval="preserveStartEnd" />
                    <YAxis tick={{ fill: '#718096', fontSize: 11 }} width={80}
                      tickFormatter={(v: number) => `${(v / 1e6).toFixed(0)}M`} />
                    <Tooltip contentStyle={{ background: '#1e2130', border: '1px solid #2d3748', borderRadius: 8 }}
                      labelFormatter={(d: string) => d}
                      formatter={(v: number) => [`${(v / 1e6).toFixed(1)}M VND`, 'Equity']} />
                    <Line type="monotone" dataKey="equity" stroke="#9FE1CB" strokeWidth={2} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}

            {/* OOS Metrics */}
            <div className="card">
              <h2 className="text-base font-semibold mb-3 text-gray-200">OOS Performance Metrics</h2>
              <div className="grid grid-cols-3 md:grid-cols-6 gap-3">
                {[
                  ['CAGR', w.oos_metrics.cagr, true],
                  ['Sharpe', w.oos_metrics.sharpe, false],
                  ['Sortino', w.oos_metrics.sortino, false],
                  ['Max DD', w.oos_metrics.max_drawdown, true],
                  ['Vol', w.oos_metrics.annual_vol, true],
                  ['Win Rate', w.oos_metrics.win_rate, true],
                ].map(([label, val, pct]) => (
                  <div key={label as string} className="text-center">
                    <p className="text-xs text-gray-500">{label as string}</p>
                    <p className="text-lg font-bold text-gray-100">
                      {pct ? `${((val as number) * 100).toFixed(1)}%` : (val as number).toFixed(3)}
                    </p>
                  </div>
                ))}
              </div>
            </div>

            {/* Per-window table */}
            <div className="card overflow-x-auto">
              <h2 className="text-base font-semibold mb-3 text-gray-200">Per-Window Breakdown</h2>
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-gray-500 text-xs uppercase border-b border-border">
                    <th className="py-2 text-left">Window</th>
                    <th className="py-2 text-left">Train Period</th>
                    <th className="py-2 text-left">Test Period</th>
                    <th className="py-2 text-right">IS {w.metric}</th>
                    <th className="py-2 text-right">OOS {w.metric}</th>
                    <th className="py-2 text-right">Efficiency</th>
                    <th className="py-2 text-left">Best Params</th>
                  </tr>
                </thead>
                <tbody>
                  {w.windows.map(win => (
                    <tr key={win.window_id} className="border-b border-border/40">
                      <td className="py-2 font-mono">W{win.window_id}</td>
                      <td className="py-2 text-gray-300">{win.train_start.slice(0, 7)} → {win.train_end.slice(0, 7)}</td>
                      <td className="py-2 text-gray-300">→ {win.test_end.slice(0, 7)}</td>
                      <td className="py-2 text-right font-mono">{win.train_metric.toFixed(3)}</td>
                      <td className={`py-2 text-right font-mono font-semibold ${win.test_metric > 0 ? 'text-success' : 'text-danger'}`}>
                        {win.test_metric.toFixed(3)}
                      </td>
                      <td className={`py-2 text-right font-mono ${win.efficiency > 0.5 ? 'text-success' : 'text-warning'}`}>
                        {(win.efficiency * 100).toFixed(0)}%
                      </td>
                      <td className="py-2 text-xs text-gray-400 font-mono">
                        {Object.entries(win.best_params).map(([k, v]) => `${k}=${v}`).join(', ')}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Interpretation */}
            <div className="card">
              <h2 className="text-base font-semibold mb-2 text-gray-200">Walk-Forward Interpretation</h2>
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-gray-500 text-xs uppercase border-b border-border">
                    <th className="py-2 pr-6 text-left">Verdict</th>
                    <th className="py-2 text-left">Meaning</th>
                  </tr>
                </thead>
                <tbody>
                  {[
                    ['PASS', 'OOS metric > 0 and WF efficiency > 50%. Strategy works out-of-sample.', 'text-success'],
                    ['MARGINAL', 'OOS metric > 0 but efficiency < 50%. Performance degrades OOS.', 'text-warning'],
                    ['FAIL', 'OOS metric <= 0. Strategy does not survive out-of-sample testing.', 'text-danger'],
                  ].map(([v, meaning, color]) => (
                    <tr key={v} className="border-b border-border/40">
                      <td className={`py-2 pr-6 font-mono font-semibold ${color}`}>{v}</td>
                      <td className="py-2 text-gray-300">{meaning}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )
      })()}
    </div>
  )
}

// ── Tab 3: Walk-Forward Permutation ─────────────────────────────────────────

function WfPermutationTab() {
  const { data: wfp } = useQuery({ queryKey: ['wfPermutation'], queryFn: fetchWfPermutation })
  const [nPerm, setNPerm] = useState(100)
  const [years, setYears] = useState(10)
  const [trainYears, setTrainYears] = useState(3)
  const [testMonths, setTestMonths] = useState(6)
  const [nStocks, setNStocks] = useState(10)
  const [metric, setMetric] = useState<'sharpe' | 'cagr'>('sharpe')
  const [strategy, setStrategy] = useState<Strategy>('carver')
  const [useReal, setUseReal] = useState(true)

  const job = useJob('wfPermutation')
  const runMut = useMutation({
    mutationFn: startWfPermutation,
    onSuccess: (id: string) => { job.setJobId(id); job.setJobDone(false) },
  })

  const p = wfp?.available ? wfp : null
  const corrupted = p ? isDataCorrupted(p as any) : false
  const histData = p && !corrupted ? buildHistogram(p.perm_distribution) : []

  return (
    <div className="space-y-6">
      <div className="card space-y-4">
        <div>
          <h2 className="text-base font-semibold text-gray-200">Step 4: Walk-Forward Permutation Test</h2>
          <p className="text-xs text-gray-500 mt-1">
            The hardest test. First runs walk-forward to get OOS metric, then shuffles data N times.
            Compares your WF OOS performance against random baselines. Passing this = strong evidence of robust edge.
          </p>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-4">
          <div>
            <label className="label">Strategy</label>
            <select className="select" value={strategy} onChange={e => setStrategy(e.target.value as Strategy)}>
              <option value="carver">Carver</option>
              <option value="martin_luk">Martin Luk</option>
            </select>
          </div>
          <div>
            <label className="label">Permutations</label>
            <input type="number" className="input" value={nPerm} min={10} max={500} onChange={e => setNPerm(+e.target.value)} />
          </div>
          <div>
            <label className="label">Total Years</label>
            <input type="number" className="input" value={years} min={3} max={15} onChange={e => setYears(+e.target.value)} />
          </div>
          <div>
            <label className="label">Train Years</label>
            <input type="number" className="input" value={trainYears} min={1} max={5} onChange={e => setTrainYears(+e.target.value)} />
          </div>
          <div>
            <label className="label">Test Months</label>
            <input type="number" className="input" value={testMonths} min={3} max={12} onChange={e => setTestMonths(+e.target.value)} />
          </div>
          <div>
            <label className="label">Stocks</label>
            <input type="number" className="input" value={nStocks} min={5} max={30} onChange={e => setNStocks(+e.target.value)} />
          </div>
          <div>
            <label className="label">Metric</label>
            <select className="select" value={metric} onChange={e => setMetric(e.target.value as 'sharpe' | 'cagr')}>
              <option value="sharpe">Sharpe</option>
              <option value="cagr">CAGR</option>
            </select>
          </div>
          <div>
            <label className="label">Data</label>
            <div className="flex items-center gap-2 mt-2">
              <input type="checkbox" id="realWFP" checked={useReal} onChange={e => setUseReal(e.target.checked)} className="w-4 h-4 accent-primary" />
              <label htmlFor="realWFP" className="text-sm text-gray-300">Real</label>
            </div>
          </div>
        </div>
        <div className="space-y-2">
          <div className="flex items-center gap-3">
            <button className="btn-primary" disabled={job.isRunning}
              onClick={() => runMut.mutate({ n_perm: nPerm, years, train_years: trainYears, test_months: testMonths, n_stocks: nStocks, strategy, metric, use_real: useReal })}>
              {job.isRunning ? 'Running...' : 'Run WF Permutation Test'}
            </button>
            {job.jobDone && job.jobData?.status === 'failed' && <p className="text-sm text-danger">{job.jobData.error}</p>}
            {job.jobDone && job.jobData?.status === 'completed' && <p className="text-sm text-success">Complete!</p>}
          </div>
          {job.isRunning && <ProgressBar stage={job.jobData?.stage || ''} progress={job.progress} />}
        </div>
      </div>

      {!p && <div className="flex items-center justify-center h-32 text-gray-400">No WF permutation results yet.</div>}

      {p && !corrupted && (
        <>
          <VerdictBanner pValue={p.p_value} ciLow={p.p_ci_low} ciHigh={p.p_ci_high} />

          {/* Note about conservative test */}
          <div className="card border bg-blue-500/10 border-blue-500/30">
            <p className="text-sm text-gray-300">
              <span className="font-semibold text-blue-400">Conservative test: </span>
              Your real metric is the walk-forward OOS value (already penalised by being out-of-sample),
              compared against in-sample permuted baselines. Passing this is the strongest evidence of real edge.
            </p>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <MetricCard label={`WF OOS ${p.metric.toUpperCase()}`}
              value={`${p.real_wf_oos_value > 0 ? '+' : ''}${p.real_wf_oos_value.toFixed(3)}`}
              sub="Walk-forward out-of-sample" />
            <MetricCard label="Perm Mean"
              value={`${p.perm_mean > 0 ? '+' : ''}${p.perm_mean.toFixed(3)}`}
              sub="Average from random shuffles" />
            <MetricCard label="p-value" value={p.p_value.toFixed(4)} sub="Lower = better"
              color={p.p_value < 0.05 ? 'text-success' : p.p_value < 0.10 ? 'text-warning' : 'text-danger'} />
            <MetricCard label="Beats WF OOS"
              value={`${p.n_beats_real} / ${p.n_permutations}`}
              sub="Shuffles that outperformed" />
          </div>

          <DistributionChart data={histData} metric={p.metric} realValue={p.real_wf_oos_value} realLabel="WF OOS" />
          <PValueTable />
        </>
      )}
    </div>
  )
}

// ── Main component ──────────────────────────────────────────────────────────

export default function PermutationTest() {
  const [tab, setTab] = useState<Tab>('is_perm')

  const tabs: { key: Tab; label: string; step: string }[] = [
    { key: 'is_perm',      label: 'In-Sample Permutation', step: 'Step 2' },
    { key: 'walk_forward',  label: 'Walk-Forward',          step: 'Step 3' },
    { key: 'wf_perm',       label: 'WF Permutation',        step: 'Step 4' },
  ]

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-100">Strategy Validation Suite</h1>
        <p className="text-sm text-gray-500 mt-1">
          4-step methodology: In-Sample Excellence → In-Sample Permutation → Walk-Forward → WF Permutation
        </p>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 bg-gray-800/50 p-1 rounded-lg">
        {tabs.map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`flex-1 py-2 px-3 rounded-md text-sm font-medium transition-colors ${
              tab === t.key
                ? 'bg-primary/20 text-primary border border-primary/30'
                : 'text-gray-400 hover:text-gray-200 hover:bg-gray-700/50'
            }`}
          >
            <span className="text-xs opacity-60 mr-1">{t.step}</span>
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {tab === 'is_perm' && <InSamplePermTab />}
      {tab === 'walk_forward' && <WalkForwardTab />}
      {tab === 'wf_perm' && <WfPermutationTab />}
    </div>
  )
}
