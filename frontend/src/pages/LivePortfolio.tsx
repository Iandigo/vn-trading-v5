import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'
import { Plus, Trash2 } from 'lucide-react'
import { fetchPortfolio, recordTrade, deleteTrade, deleteHolding, fetchUniverse } from '../api/client'
import type { PortfolioHolding } from '../types'
import { fmtVnd } from '../utils/format'

const COLORS = ['#1B6CA8', '#3BB57A', '#E85D24', '#f59e0b', '#8b5cf6', '#06b6d4',
                 '#ec4899', '#10b981', '#f97316', '#6366f1', '#14b8a6', '#e11d48']

export default function LivePortfolio() {
  const qc = useQueryClient()
  const { data: portfolio, isLoading } = useQuery({
    queryKey: ['portfolio'],
    queryFn: fetchPortfolio,
    refetchInterval: 30_000,
  })
  const { data: universe = [] } = useQuery({ queryKey: ['universe'], queryFn: fetchUniverse })

  // Trade form state
  const [showForm, setShowForm] = useState(false)
  const [formTicker, setFormTicker] = useState('')
  const [formAction, setFormAction] = useState<'BUY' | 'SELL'>('BUY')
  const [formShares, setFormShares] = useState(100)
  const [formPrice, setFormPrice] = useState(0)
  const [formStop, setFormStop] = useState<number | ''>('')
  const [formStrategy, setFormStrategy] = useState('martin_luk')
  const [formNote, setFormNote] = useState('')

  const tradeMut = useMutation({
    mutationFn: recordTrade,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['portfolio'] })
      setShowForm(false)
      setFormTicker('')
      setFormShares(100)
      setFormPrice(0)
      setFormStop('')
      setFormNote('')
    },
  })

  const deleteTradesMut = useMutation({
    mutationFn: deleteTrade,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['portfolio'] }),
  })

  const deleteHoldingMut = useMutation({
    mutationFn: deleteHolding,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['portfolio'] }),
  })

  const handleSubmitTrade = () => {
    if (!formTicker || formShares <= 0 || formPrice <= 0) return
    const stopPrice = typeof formStop === 'number' && formStop > 0 ? formStop : undefined
    const rValue = stopPrice ? formPrice - stopPrice : undefined
    tradeMut.mutate({
      ticker: formTicker,
      action: formAction,
      shares: formShares,
      price: formPrice,
      stop_price: stopPrice,
      r_value: rValue,
      strategy: formStrategy,
      note: formNote || undefined,
    })
  }

  if (isLoading) return <div className="text-gray-400 text-sm">Loading portfolio...</div>

  const holdings = portfolio?.holdings ?? {}
  const holdingEntries = Object.entries(holdings)
  const trades = portfolio?.trades ?? []

  // Parse holdings - support both old format (number) and new format (object)
  const parsedHoldings: Array<{ ticker: string; data: PortfolioHolding }> = holdingEntries.map(([ticker, val]) => {
    if (typeof val === 'number') {
      return { ticker, data: { shares: val, avg_price: 0 } }
    }
    return { ticker, data: val as PortfolioHolding }
  })

  const pieData = parsedHoldings
    .filter(h => h.data.shares > 0)
    .map(h => ({
      name: h.ticker.replace('.VN', ''),
      value: h.data.shares * (h.data.avg_price || 1),
    }))

  const totalValue = parsedHoldings.reduce((sum, h) => sum + h.data.shares * (h.data.avg_price || 0), 0)

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-100">Portfolio</h1>
        <button className="btn-primary text-sm flex items-center gap-2" onClick={() => setShowForm(!showForm)}>
          <Plus size={14} /> Record Trade
        </button>
      </div>

      {/* Trade entry form */}
      {showForm && (
        <div className="card border border-primary/30 space-y-4">
          <h2 className="text-base font-semibold text-gray-200">Record a Trade</h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div>
              <label className="label">Ticker</label>
              <select className="select" value={formTicker} onChange={e => setFormTicker(e.target.value)}>
                <option value="">Select...</option>
                {universe.map(t => (
                  <option key={t} value={t}>{t.replace('.VN', '')}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="label">Action</label>
              <div className="flex gap-2 mt-1">
                <button className={`flex-1 py-1.5 rounded text-sm font-semibold ${
                  formAction === 'BUY' ? 'bg-success/20 text-success' : 'bg-card text-gray-400'
                }`} onClick={() => setFormAction('BUY')}>BUY</button>
                <button className={`flex-1 py-1.5 rounded text-sm font-semibold ${
                  formAction === 'SELL' ? 'bg-danger/20 text-danger' : 'bg-card text-gray-400'
                }`} onClick={() => setFormAction('SELL')}>SELL</button>
              </div>
            </div>
            <div>
              <label className="label">Shares</label>
              <input type="number" className="input" value={formShares} min={100} step={100}
                onChange={e => setFormShares(+e.target.value)} />
            </div>
            <div>
              <label className="label">Price (VND)</label>
              <input type="number" className="input" value={formPrice} min={0}
                onChange={e => setFormPrice(+e.target.value)} />
            </div>
            <div>
              <label className="label">Stop Price (optional)</label>
              <input type="number" className="input" value={formStop} min={0}
                onChange={e => setFormStop(e.target.value ? +e.target.value : '')}
                placeholder="For Luk trades" />
            </div>
            <div>
              <label className="label">Strategy</label>
              <select className="select" value={formStrategy} onChange={e => setFormStrategy(e.target.value)}>
                <option value="martin_luk">Martin Luk</option>
                <option value="carver">Carver</option>
                <option value="manual">Manual</option>
              </select>
            </div>
            <div className="md:col-span-2">
              <label className="label">Note (optional)</label>
              <input type="text" className="input" value={formNote}
                onChange={e => setFormNote(e.target.value)}
                placeholder="e.g. prior high breakout, EMA convergence..." />
            </div>
          </div>
          <div className="flex items-center gap-3">
            <button className="btn-primary text-sm px-6" onClick={handleSubmitTrade}
              disabled={tradeMut.isPending || !formTicker || formPrice <= 0}>
              {tradeMut.isPending ? 'Recording...' : 'Record Trade'}
            </button>
            <button className="btn-secondary text-sm" onClick={() => setShowForm(false)}>Cancel</button>
            {formPrice > 0 && formShares > 0 && (
              <span className="text-xs text-gray-500">
                Value: {fmtVnd(formPrice * formShares)}
                {typeof formStop === 'number' && formStop > 0 && formAction === 'BUY' && (
                  <> · Risk/share: {(formPrice - formStop).toLocaleString()} VND · Risk: {fmtVnd((formPrice - formStop) * formShares)}</>
                )}
              </span>
            )}
          </div>
        </div>
      )}

      {/* Portfolio summary */}
      {parsedHoldings.length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
          <div className="card">
            <p className="label">Open Positions</p>
            <p className="text-3xl font-bold text-gray-100">{parsedHoldings.length}</p>
          </div>
          <div className="card">
            <p className="label">Total Value (at avg price)</p>
            <p className="text-2xl font-bold text-gray-100">{fmtVnd(totalValue)}</p>
          </div>
          <div className="card">
            <p className="label">Total Trades</p>
            <p className="text-2xl font-bold text-gray-100">{trades.length}</p>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Holdings table */}
        <div className="card">
          <h2 className="text-base font-semibold mb-4 text-gray-200">Current Holdings</h2>
          {parsedHoldings.length === 0 ? (
            <p className="text-sm text-gray-500">No positions. Use the scanner to find breakout signals, or record a trade above.</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 text-xs uppercase border-b border-border">
                  <th className="py-2 pr-3 text-left">Ticker</th>
                  <th className="py-2 pr-3 text-right">Shares</th>
                  <th className="py-2 pr-3 text-right">Avg Price</th>
                  <th className="py-2 pr-3 text-right">Stop</th>
                  <th className="py-2 pr-3 text-left">Strategy</th>
                  <th className="py-2 pr-3"></th>
                </tr>
              </thead>
              <tbody>
                {parsedHoldings.map(({ ticker, data }) => (
                  <tr key={ticker} className="border-b border-border/40 hover:bg-white/2">
                    <td className="py-2.5 pr-3 font-semibold text-gray-200">{ticker.replace('.VN', '')}</td>
                    <td className="py-2.5 pr-3 text-right font-mono text-gray-300">
                      {data.shares.toLocaleString()}
                    </td>
                    <td className="py-2.5 pr-3 text-right font-mono text-gray-300">
                      {data.avg_price ? data.avg_price.toLocaleString() : '—'}
                    </td>
                    <td className="py-2.5 pr-3 text-right font-mono text-danger">
                      {data.stop_price ? data.stop_price.toLocaleString() : '—'}
                    </td>
                    <td className="py-2.5 pr-3">
                      {data.strategy && (
                        <span className={`text-xs px-2 py-0.5 rounded-full font-semibold ${
                          data.strategy === 'martin_luk' ? 'bg-primary/20 text-primary' :
                          data.strategy === 'carver' ? 'bg-success/20 text-success' :
                          'bg-gray-500/20 text-gray-400'
                        }`}>
                          {data.strategy === 'martin_luk' ? 'Luk' : data.strategy === 'carver' ? 'Carver' : data.strategy}
                        </span>
                      )}
                    </td>
                    <td className="py-2.5">
                      <button
                        onClick={() => { if (confirm(`Delete ${ticker.replace('.VN', '')} position?`)) deleteHoldingMut.mutate(ticker) }}
                        className="text-gray-600 hover:text-danger transition-colors"
                        disabled={deleteHoldingMut.isPending}
                      >
                        <Trash2 size={13} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Allocation pie */}
        {pieData.length > 0 && (
          <div className="card">
            <h2 className="text-base font-semibold mb-4 text-gray-200">Allocation (by value)</h2>
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
                  formatter={(v: number) => [fmtVnd(v), 'Value']}
                />
                <Legend formatter={(v: string) => <span className="text-gray-300 text-sm">{v}</span>} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      {/* Luk position details (for holdings with stop/r_value) */}
      {parsedHoldings.some(h => h.data.stop_price) && (
        <div className="card">
          <h2 className="text-base font-semibold mb-4 text-gray-200">Position Details — Martin Luk Trades</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 text-xs uppercase border-b border-border">
                  {['Ticker', 'Entry', 'Stop', 'R-Value', '3R Target', '5R Target', 'Shares', 'Pattern', 'Entry Date', ''].map(h => (
                    <th key={h} className="py-2 pr-4 text-left whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {parsedHoldings.filter(h => h.data.stop_price).map(({ ticker, data }) => {
                  const rVal = data.r_value ?? (data.avg_price - (data.stop_price ?? 0))
                  const target3r = data.avg_price + 3 * rVal
                  const target5r = data.avg_price + 5 * rVal
                  return (
                    <tr key={ticker} className="border-b border-border/40 hover:bg-white/2">
                      <td className="py-2.5 pr-4 font-semibold text-gray-200">{ticker.replace('.VN', '')}</td>
                      <td className="py-2.5 pr-4 font-mono text-gray-300">{data.avg_price.toLocaleString()}</td>
                      <td className="py-2.5 pr-4 font-mono text-danger">{data.stop_price?.toLocaleString()}</td>
                      <td className="py-2.5 pr-4 font-mono text-gray-300">{rVal.toLocaleString()}</td>
                      <td className="py-2.5 pr-4 font-mono text-success">{Math.round(target3r).toLocaleString()}</td>
                      <td className="py-2.5 pr-4 font-mono text-success">{Math.round(target5r).toLocaleString()}</td>
                      <td className="py-2.5 pr-4 font-mono text-gray-300">{data.shares.toLocaleString()}</td>
                      <td className="py-2.5 pr-4 text-xs text-gray-400">{data.pattern?.replace('_', ' ') ?? '—'}</td>
                      <td className="py-2.5 pr-4 text-xs text-gray-400">{data.entry_date ?? '—'}</td>
                      <td className="py-2.5">
                        <button
                          onClick={() => { if (confirm(`Delete position ${ticker.replace('.VN', '')}?`)) deleteHoldingMut.mutate(ticker) }}
                          className="text-gray-600 hover:text-danger transition-colors"
                          disabled={deleteHoldingMut.isPending}
                        >
                          <Trash2 size={13} />
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Trade log */}
      {trades.length > 0 && (
        <div className="card">
          <h2 className="text-base font-semibold mb-4 text-gray-200">Trade Log</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 text-xs uppercase border-b border-border">
                  {['Date', 'Ticker', 'Action', 'Shares', 'Price', 'Value', 'Fee', 'Strategy', 'Note', ''].map(h => (
                    <th key={h} className="py-2 pr-4 text-left">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[...trades].reverse().map((t, i) => (
                  <tr key={i} className="border-b border-border/40 hover:bg-white/2">
                    <td className="py-2 pr-4 text-gray-400">{t.date?.slice(0, 10)}</td>
                    <td className="py-2 pr-4 font-semibold text-gray-200">{(t.ticker ?? '').replace('.VN', '')}</td>
                    <td className={`py-2 pr-4 font-semibold ${t.action === 'BUY' ? 'text-success' : 'text-danger'}`}>
                      {t.action}
                    </td>
                    <td className="py-2 pr-4 font-mono text-gray-300">{t.shares?.toLocaleString()}</td>
                    <td className="py-2 pr-4 font-mono text-gray-300">{t.price?.toLocaleString()}</td>
                    <td className="py-2 pr-4 font-mono text-gray-300">{fmtVnd(t.value)}</td>
                    <td className="py-2 pr-4 font-mono text-gray-400">{t.fee?.toLocaleString()}</td>
                    <td className="py-2 pr-4">
                      {(t as any).strategy && (
                        <span className={`text-xs px-2 py-0.5 rounded-full font-semibold ${
                          (t as any).strategy === 'martin_luk' ? 'bg-primary/20 text-primary' :
                          (t as any).strategy === 'carver' ? 'bg-success/20 text-success' :
                          'bg-gray-500/20 text-gray-400'
                        }`}>
                          {(t as any).strategy === 'martin_luk' ? 'Luk' : (t as any).strategy}
                        </span>
                      )}
                    </td>
                    <td className="py-2 pr-4 text-xs text-gray-500 max-w-32 truncate">
                      {(t as any).note || (t as any).pattern?.replace('_', ' ') || ''}
                    </td>
                    <td className="py-2">
                      <button onClick={() => deleteTradesMut.mutate(trades.length - 1 - i)}
                        className="text-gray-600 hover:text-danger transition-colors">
                        <Trash2 size={13} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {parsedHoldings.length === 0 && trades.length === 0 && (
        <div className="flex flex-col items-center justify-center h-40 gap-3 text-gray-400">
          <p>No holdings or trades recorded yet.</p>
          <p className="text-sm">Go to <span className="text-primary font-semibold">Live Scanner</span> to find breakout signals, or use the <span className="text-primary font-semibold">Record Trade</span> button above.</p>
        </div>
      )}
    </div>
  )
}
