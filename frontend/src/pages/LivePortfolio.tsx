import { useQuery } from '@tanstack/react-query'
import { Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'
import { fetchPortfolio } from '../api/client'

const COLORS = ['#1B6CA8', '#3BB57A', '#E85D24', '#f59e0b', '#8b5cf6', '#06b6d4',
                 '#ec4899', '#10b981', '#f97316', '#6366f1', '#14b8a6', '#e11d48']

export default function LivePortfolio() {
  const { data: portfolio, isLoading } = useQuery({
    queryKey: ['portfolio'],
    queryFn: fetchPortfolio,
    refetchInterval: 30_000,
  })

  if (isLoading) return <div className="text-gray-400 text-sm">Loading portfolio...</div>

  if (!portfolio?.available) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold text-gray-100">Live Portfolio</h1>
        <div className="flex flex-col items-center justify-center h-64 gap-4 text-gray-400">
          <p>No live holdings recorded yet.</p>
          <div className="card text-left w-full max-w-lg">
            <p className="text-sm font-semibold text-gray-300 mb-2">To record a trade:</p>
            <pre className="text-xs text-gray-400 bg-bg p-3 rounded overflow-x-auto">{`from portfolio.tracker import PortfolioTracker
tracker = PortfolioTracker()
tracker.record_trade("VCB.VN", action="BUY", shares=500, price=88500)`}</pre>
          </div>
        </div>
      </div>
    )
  }

  const holdings = portfolio.holdings
  const holdingEntries = Object.entries(holdings)
  const pieData = holdingEntries.map(([ticker, shares]) => ({
    name: ticker.replace('.VN', ''),
    value: shares as number,
  }))

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-100">Live Portfolio</h1>

      <div className="card inline-flex items-center gap-2">
        <span className="text-3xl font-bold text-gray-100">{portfolio.open_positions}</span>
        <span className="text-gray-400">open positions</span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Holdings table */}
        <div className="card">
          <h2 className="text-base font-semibold mb-4 text-gray-200">Current Holdings</h2>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-gray-500 text-xs uppercase border-b border-border">
                <th className="py-2 pr-6 text-left">Ticker</th>
                <th className="py-2 text-right">Shares</th>
              </tr>
            </thead>
            <tbody>
              {holdingEntries.map(([ticker, shares]) => (
                <tr key={ticker} className="border-b border-border/40 hover:bg-white/2">
                  <td className="py-2.5 pr-6 font-semibold text-gray-200">{ticker}</td>
                  <td className="py-2.5 text-right font-mono text-gray-300">
                    {(shares as number).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Allocation pie */}
        {pieData.length > 0 && (
          <div className="card">
            <h2 className="text-base font-semibold mb-4 text-gray-200">Allocation (by shares)</h2>
            <ResponsiveContainer width="100%" height={280}>
              <PieChart>
                <Pie data={pieData} dataKey="value" nameKey="name" cx="50%" cy="50%"
                  innerRadius={60} outerRadius={100} paddingAngle={2}>
                  {pieData.map((_, i) => (
                    <Cell key={i} fill={COLORS[i % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{ background: '#1e2130', border: '1px solid #2d3748', borderRadius: 8 }}
                  formatter={(v: number) => [v.toLocaleString() + ' shares', '']}
                />
                <Legend formatter={(v: string) => <span className="text-gray-300 text-sm">{v}</span>} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      {/* Trade log */}
      {portfolio.trades.length > 0 && (
        <div className="card">
          <h2 className="text-base font-semibold mb-4 text-gray-200">Recent Trade Log</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 text-xs uppercase border-b border-border">
                  {['Date', 'Ticker', 'Action', 'Shares', 'Price', 'Fee'].map(h => (
                    <th key={h} className="py-2 pr-4 text-left">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[...portfolio.trades].reverse().map((t, i) => (
                  <tr key={i} className="border-b border-border/40 hover:bg-white/2">
                    <td className="py-2 pr-4 text-gray-400">{t.date?.slice(0, 10)}</td>
                    <td className="py-2 pr-4 font-semibold text-gray-200">{t.ticker}</td>
                    <td className={`py-2 pr-4 font-semibold ${t.action === 'BUY' ? 'text-success' : 'text-danger'}`}>
                      {t.action}
                    </td>
                    <td className="py-2 pr-4 font-mono text-gray-300">{t.shares?.toLocaleString()}</td>
                    <td className="py-2 pr-4 font-mono text-gray-300">{t.price?.toLocaleString()}</td>
                    <td className="py-2 font-mono text-gray-400">{t.fee?.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
