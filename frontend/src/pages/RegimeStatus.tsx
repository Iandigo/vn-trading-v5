import { useQuery } from '@tanstack/react-query'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { fetchRegime } from '../api/client'
import MetricCard from '../components/MetricCard'

const fmtPct = (v: number | null | undefined) =>
  v == null ? '—' : `${v >= 0 ? '+' : ''}${(v * 100).toFixed(1)}%`

export default function RegimeStatus() {
  const { data: regime, isLoading, error, refetch } = useQuery({
    queryKey: ['regime'],
    queryFn: fetchRegime,
    staleTime: 5 * 60_000,   // 5 min — no need to refetch on every page visit
    gcTime:   30 * 60_000,   // 30 min — keep cached data in memory across navigations
    retry: 1,
  })

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3 text-gray-400">
        <p className="animate-pulse">Fetching VNIndex data...</p>
        <p className="text-xs text-gray-600">This may take a moment (fetching ~300 days of data)</p>
      </div>
    )
  }

  if (error || !regime?.available) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold text-gray-100">Regime Status</h1>
        <div className="card border-danger/30 bg-danger/5">
          <p className="text-danger font-semibold">Could not fetch live data</p>
          <p className="text-sm text-gray-400 mt-1">{regime?.error ?? 'Check your internet connection.'}</p>
          <button className="btn-secondary mt-3 text-sm" onClick={() => refetch()}>Retry</button>
        </div>
      </div>
    )
  }

  const isBull = regime.regime === 'BULL'

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-100">Current Market Regime</h1>
        <button className="btn-secondary text-sm" onClick={() => refetch()}>Refresh</button>
      </div>

      {/* Regime banner */}
      <div className={`card border ${isBull ? 'bg-success/10 border-success/30' : 'bg-danger/10 border-danger/30'}`}>
        <div className="flex items-center gap-3">
          <span className="text-3xl">{isBull ? '🟢' : '🔴'}</span>
          <div>
            <p className={`text-2xl font-bold ${isBull ? 'text-success' : 'text-danger'}`}>
              {regime.regime} REGIME
            </p>
            <p className="text-sm text-gray-400 mt-0.5">
              {isBull
                ? 'Full position sizing active. New long entries allowed.'
                : 'BEAR REGIME — No new long entries. Existing positions with half sizing.'}
            </p>
          </div>
        </div>
      </div>

      {/* Key metrics */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <MetricCard
          label="Regime"
          value={regime.regime}
          highlight={isBull ? 'green' : 'red'}
          sub={`${regime.days_in_regime} trading days`}
        />
        <MetricCard
          label="VNIndex vs MA200"
          value={fmtPct(regime.pct_vs_ma200)}
          highlight={regime.pct_vs_ma200 != null && regime.pct_vs_ma200 >= 0 ? 'green' : 'red'}
          sub={regime.index_close ? `Index: ${regime.index_close.toLocaleString()}` : undefined}
        />
        <MetricCard
          label="MA200"
          value={regime.ma200 ? regime.ma200.toLocaleString() : '—'}
          sub="200-day moving average"
        />
        <MetricCard
          label="Effective τ"
          value={fmtPct(regime.effective_tau)}
          sub={`${fmtPct(regime.target_vol)} × ${regime.tau_multiplier}`}
          highlight={isBull ? 'green' : 'red'}
        />
      </div>

      {/* VNIndex vs MA200 chart */}
      {regime.chart_data && regime.chart_data.length > 0 && (
        <div className="card">
          <h2 className="text-lg font-semibold mb-4 text-gray-200">VNIndex vs 200-day MA</h2>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={regime.chart_data} margin={{ top: 4, right: 8, left: 8, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2d3748" />
              <XAxis dataKey="date" tick={{ fill: '#718096', fontSize: 11 }}
                tickFormatter={d => d.slice(0, 7)} interval="preserveStartEnd" />
              <YAxis tick={{ fill: '#718096', fontSize: 11 }} width={60}
                domain={['auto', 'auto']} tickFormatter={v => v.toLocaleString()} />
              <Tooltip
                contentStyle={{ background: '#1e2130', border: '1px solid #2d3748', borderRadius: 8 }}
                labelStyle={{ color: '#a0aec0' }}
                formatter={(v: number, name: string) => [v.toLocaleString(), name === 'vnindex' ? 'VNIndex' : 'MA200']}
              />
              <Legend formatter={(v: string) => v === 'vnindex' ? 'VNIndex' : 'MA200 (200d)'} />
              <Line type="monotone" dataKey="vnindex" stroke="#1B6CA8" strokeWidth={2}
                dot={false} name="vnindex" />
              <Line type="monotone" dataKey="ma200" stroke="#E85D24" strokeWidth={1.5}
                strokeDasharray="5 5" dot={false} name="ma200" connectNulls={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Signal weights table */}
      <div className="card">
        <h2 className="text-base font-semibold mb-4 text-gray-200">Signal Weights — Current Regime</h2>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-gray-500 text-xs uppercase border-b border-border">
              <th className="py-2 pr-8 text-left">Signal</th>
              <th className="py-2 pr-8 text-right">Weight</th>
              <th className="py-2 text-left">Status</th>
            </tr>
          </thead>
          <tbody>
            <tr className="border-b border-border/40">
              <td className="py-2.5 pr-8 text-gray-300 font-medium">MA Regime Filter</td>
              <td className="py-2.5 pr-8 text-right text-gray-500">—</td>
              <td className="py-2.5">
                <span className={isBull ? 'tag-bull' : 'tag-bear'}>
                  {isBull ? `BULL — full τ (${fmtPct(regime.target_vol)})` : `BEAR — τ × 0.5 = ${fmtPct(regime.effective_tau)}`}
                </span>
              </td>
            </tr>
            <tr className="border-b border-border/40">
              <td className="py-2.5 pr-8 text-gray-300 font-medium">Cross-Sectional Momentum</td>
              <td className="py-2.5 pr-8 text-right font-mono text-gray-300">
                {((regime.signal_weights?.cross_momentum ?? 0.55) * 100).toFixed(0)}%
              </td>
              <td className="py-2.5">
                <span className={isBull ? 'tag-bull' : 'bg-gray-700/50 text-gray-400 text-xs font-semibold px-2 py-0.5 rounded-full'}>
                  {isBull ? 'Active' : 'No new entries'}
                </span>
              </td>
            </tr>
            <tr className="border-b border-border/40">
              <td className="py-2.5 pr-8 text-gray-300 font-medium">IBS Mean Reversion</td>
              <td className="py-2.5 pr-8 text-right font-mono text-gray-300">
                {((regime.signal_weights?.ibs ?? 0.15) * 100).toFixed(0)}%
              </td>
              <td className="py-2.5">
                <span className={isBull ? 'tag-bull' : 'tag-bear'}>
                  {isBull ? 'Active (BULL only)' : 'Disabled (BEAR)'}
                </span>
              </td>
            </tr>
            <tr>
              <td className="py-2.5 pr-8 text-gray-300 font-medium">Target Volatility (τ)</td>
              <td className="py-2.5 pr-8 text-right font-mono text-gray-300">
                {fmtPct(regime.target_vol)} × {regime.tau_multiplier}
              </td>
              <td className="py-2.5 text-gray-300 font-mono">
                = {fmtPct(regime.effective_tau)} effective
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div className="card bg-gray-800/30">
        <p className="text-xs text-gray-500">
          Data fetched live from VNIndex. Regime is updated weekly (every 5 trading days) to prevent whipsaw.
          The MA200 period and confirmation logic are fixed at design-time and not optimised for VN.
        </p>
      </div>
    </div>
  )
}
