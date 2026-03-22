import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { RefreshCw, TrendingUp, TrendingDown, Minus, ShieldCheck, ShieldAlert, ShieldOff, ArrowRight } from 'lucide-react'
import { fetchScanner, recordTrade } from '../api/client'
import type { ScannerStock } from '../types'
import { fmtVnd } from '../utils/format'

interface Props {
  onTrade: () => void
}

const CLASS_STYLES: Record<string, { bg: string; text: string; icon: React.FC<{ size?: number; className?: string }> }> = {
  LEAD:      { bg: 'bg-success/15', text: 'text-success', icon: TrendingUp },
  WEAKENING: { bg: 'bg-warning/15', text: 'text-warning', icon: Minus },
  LAGGARD:   { bg: 'bg-danger/15',  text: 'text-danger',  icon: TrendingDown },
  NO_DATA:   { bg: 'bg-gray-500/15', text: 'text-gray-500', icon: Minus },
}

const HEALTH_STYLES: Record<string, { bg: string; text: string; icon: React.FC<{ size?: number; className?: string }> }> = {
  STRONG:   { bg: 'bg-success/10 border-success/30', text: 'text-success', icon: ShieldCheck },
  CAUTIOUS: { bg: 'bg-warning/10 border-warning/30', text: 'text-warning', icon: ShieldAlert },
  WEAK:     { bg: 'bg-danger/10 border-danger/30',   text: 'text-danger',  icon: ShieldOff },
  UNKNOWN:  { bg: 'bg-gray-500/10 border-gray-500/30', text: 'text-gray-500', icon: ShieldOff },
}

export default function Scanner({ onTrade }: Props) {
  const qc = useQueryClient()
  const [equity, setEquity] = useState(500_000_000)
  const [equityInput, setEquityInput] = useState('500000000')
  const [filter, setFilter] = useState<'all' | 'LEAD' | 'signals'>('all')

  const applyEquity = () => {
    const v = parseInt(equityInput, 10)
    if (!isNaN(v) && v >= 100_000_000) setEquity(v)
  }

  const { data: scanner, isLoading, isRefetching, refetch } = useQuery({
    queryKey: ['scanner', equity],
    queryFn: () => fetchScanner(30, equity),
    staleTime: 60_000,
  })

  const tradeMut = useMutation({
    mutationFn: recordTrade,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['portfolio'] })
      onTrade()
    },
  })

  const handleQuickBuy = (stock: ScannerStock) => {
    if (!stock.breakout) return
    tradeMut.mutate({
      ticker: stock.ticker,
      action: 'BUY',
      shares: stock.breakout.shares,
      price: stock.breakout.entry_price,
      stop_price: stock.breakout.stop_price,
      r_value: stock.breakout.r_value,
      pattern: stock.breakout.pattern,
      strategy: 'martin_luk',
    })
  }

  const stocks = scanner?.stocks ?? []
  const filtered = stocks.filter(s => {
    if (filter === 'LEAD') return s.classification === 'LEAD'
    if (filter === 'signals') return s.breakout !== null
    return true
  })

  const health = scanner?.market_health
  const healthStyle = HEALTH_STYLES[health?.health ?? 'UNKNOWN']
  const HealthIcon = healthStyle.icon

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-100">Live Scanner — Martin Luk Signals</h1>
        <button
          className="btn-secondary text-sm flex items-center gap-2"
          onClick={() => refetch()}
          disabled={isLoading || isRefetching}
        >
          <RefreshCw size={14} className={isRefetching ? 'animate-spin' : ''} />
          {isRefetching ? 'Scanning...' : 'Refresh'}
        </button>
      </div>

      {isLoading && (
        <div className="text-gray-400 text-sm flex items-center gap-2">
          <RefreshCw size={14} className="animate-spin" /> Scanning VN30 stocks...
        </div>
      )}

      {scanner && !scanner.available && (
        <div className="card border bg-danger/10 border-danger/30">
          <p className="text-danger font-semibold">Scanner unavailable</p>
          <p className="text-sm text-gray-300 mt-1">{scanner.error}</p>
        </div>
      )}

      {scanner?.available && (
        <>
          {/* Market Health Banner */}
          <div className={`card border ${healthStyle.bg} flex items-center gap-4`}>
            <HealthIcon size={28} className={healthStyle.text} />
            <div className="flex-1">
              <p className={`text-lg font-bold ${healthStyle.text}`}>
                Market Health: {health?.health}
              </p>
              <p className="text-sm text-gray-300">
                {health?.leader_count} / {health?.total_stocks} leaders ({((health?.leader_pct ?? 0) * 100).toFixed(0)}%)
                {' · '}Risk multiplier: {health?.risk_multiplier}x
              </p>
            </div>
            <div className="text-right">
              <p className="text-xs text-gray-500">Scan date</p>
              <p className="text-sm text-gray-300 font-mono">{scanner.scan_date}</p>
            </div>
          </div>

          {/* Summary cards */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            <div className="card">
              <p className="label">Leaders</p>
              <p className="text-2xl font-bold text-success">{scanner.summary.lead}</p>
            </div>
            <div className="card">
              <p className="label">Weakening</p>
              <p className="text-2xl font-bold text-warning">{scanner.summary.weakening}</p>
            </div>
            <div className="card">
              <p className="label">Laggards</p>
              <p className="text-2xl font-bold text-danger">{scanner.summary.laggard}</p>
            </div>
            <div className="card">
              <p className="label">Breakout Signals</p>
              <p className="text-2xl font-bold text-primary">{scanner.summary.signals}</p>
            </div>
            <div className="card">
              <p className="label">Scanning Equity</p>
              <p className="text-lg font-bold text-gray-200">{fmtVnd(equity)}</p>
              <input type="number" className="input mt-1 text-xs" value={equityInput}
                onChange={e => setEquityInput(e.target.value)}
                onBlur={applyEquity}
                onKeyDown={e => e.key === 'Enter' && applyEquity()}
                step={50_000_000} min={100_000_000} />
              <p className="text-[10px] text-gray-600 mt-0.5">Press Enter to apply</p>
            </div>
          </div>

          {/* Breakout Signals (highlighted) */}
          {filtered.some(s => s.breakout) && (
            <div className="card border border-primary/30 bg-primary/5">
              <h2 className="text-base font-semibold text-primary mb-3">Active Breakout Signals</h2>
              <div className="space-y-3">
                {filtered.filter(s => s.breakout).map(stock => {
                  const b = stock.breakout!
                  return (
                    <div key={stock.ticker} className="flex items-center gap-4 p-3 bg-bg rounded-lg">
                      <div className="flex-1">
                        <div className="flex items-center gap-2">
                          <span className="font-bold text-gray-100">{stock.ticker.replace('.VN', '')}</span>
                          <span className="text-xs px-2 py-0.5 rounded-full bg-primary/20 text-primary font-semibold">
                            {b.pattern.replace('_', ' ')}
                          </span>
                          <span className="text-xs px-2 py-0.5 rounded-full bg-success/20 text-success font-semibold">
                            LEAD
                          </span>
                        </div>
                        <div className="flex items-center gap-4 mt-1 text-xs text-gray-400">
                          <span>Entry: <span className="text-gray-200 font-mono">{b.entry_price.toLocaleString()}</span></span>
                          <span>Stop: <span className="text-danger font-mono">{b.stop_price.toLocaleString()}</span></span>
                          <span>R-value: <span className="text-gray-200 font-mono">{b.r_value.toLocaleString()}</span></span>
                          <span>3R target: <span className="text-success font-mono">{b.target_3r.toLocaleString()}</span></span>
                          <span>5R target: <span className="text-success font-mono">{b.target_5r.toLocaleString()}</span></span>
                        </div>
                        <div className="flex items-center gap-4 mt-1 text-xs text-gray-400">
                          <span>Shares: <span className="text-gray-200 font-semibold">{b.shares.toLocaleString()}</span></span>
                          <span>Position: <span className="text-gray-200">{fmtVnd(b.position_value)}</span></span>
                          <span>Risk: <span className="text-warning">{fmtVnd(b.risk_amount)}</span></span>
                          <span>ADR: <span className="text-gray-200">{stock.adr?.toFixed(1)}%</span></span>
                        </div>
                      </div>
                      <button
                        className="btn-primary text-sm px-4 py-2 flex items-center gap-1 whitespace-nowrap"
                        onClick={() => handleQuickBuy(stock)}
                        disabled={tradeMut.isPending || b.shares === 0}
                      >
                        Buy {b.shares} <ArrowRight size={14} />
                      </button>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* Position Allocation Summary */}
          {filtered.some(s => s.breakout) && (() => {
            const signals = filtered.filter(s => s.breakout)
            const totalValue = signals.reduce((s, st) => s + (st.breakout?.position_value ?? 0), 0)
            const totalRisk = signals.reduce((s, st) => s + (st.breakout?.risk_amount ?? 0), 0)
            const exposurePct = (totalValue / equity) * 100
            const maxPositions = Math.floor(0.80 / 0.10)  // 80% exposure / 10% per stock = 8
            const riskPct = (totalRisk / equity) * 100
            return (
              <div className="card border border-gray-700">
                <h2 className="text-base font-semibold text-gray-200 mb-3">Position Allocation</h2>
                <div className="grid grid-cols-2 md:grid-cols-5 gap-3 text-sm">
                  <div>
                    <p className="text-gray-500 text-xs">Active Signals</p>
                    <p className="text-gray-200 font-bold">{signals.length} stocks</p>
                  </div>
                  <div>
                    <p className="text-gray-500 text-xs">Max Positions</p>
                    <p className="text-gray-200 font-bold">{maxPositions} stocks</p>
                    <p className="text-[10px] text-gray-600">80% / 10% per stock</p>
                  </div>
                  <div>
                    <p className="text-gray-500 text-xs">Total Exposure</p>
                    <p className={`font-bold ${exposurePct > 80 ? 'text-danger' : exposurePct > 50 ? 'text-warning' : 'text-success'}`}>
                      {fmtVnd(totalValue)} ({exposurePct.toFixed(1)}%)
                    </p>
                  </div>
                  <div>
                    <p className="text-gray-500 text-xs">Total Risk</p>
                    <p className="text-warning font-bold">
                      {fmtVnd(totalRisk)} ({riskPct.toFixed(2)}%)
                    </p>
                  </div>
                  <div>
                    <p className="text-gray-500 text-xs">Risk Per Trade</p>
                    <p className="text-gray-200 font-bold">0.75% of equity</p>
                    <p className="text-[10px] text-gray-600">Halved in drawdowns</p>
                  </div>
                </div>
              </div>
            )
          })()}

          {/* Filter bar */}
          <div className="flex items-center gap-2">
            {(['all', 'LEAD', 'signals'] as const).map(f => (
              <button key={f}
                className={`text-sm px-3 py-1.5 rounded-lg transition-colors ${
                  filter === f ? 'bg-primary/20 text-primary' : 'bg-card text-gray-400 hover:text-gray-200'
                }`}
                onClick={() => setFilter(f)}
              >
                {f === 'all' ? `All (${stocks.length})` :
                 f === 'LEAD' ? `Leaders (${scanner.summary.lead})` :
                 `Signals (${scanner.summary.signals})`}
              </button>
            ))}
          </div>

          {/* Stock table */}
          <div className="card overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 text-xs uppercase border-b border-border">
                  {['Ticker', 'Class', 'Close', 'EMA 9', 'EMA 21', 'EMA 50', 'ADR %', 'Signal'].map(h => (
                    <th key={h} className="py-2 pr-4 text-left whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.map(stock => {
                  const cls = CLASS_STYLES[stock.classification] ?? CLASS_STYLES.NO_DATA
                  const ClsIcon = cls.icon
                  return (
                    <tr key={stock.ticker} className={`border-b border-border/40 hover:bg-white/2 ${
                      stock.breakout ? 'bg-primary/5' : ''
                    }`}>
                      <td className="py-2.5 pr-4 font-semibold text-gray-200">
                        {stock.ticker.replace('.VN', '')}
                      </td>
                      <td className="py-2.5 pr-4">
                        <span className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-semibold ${cls.bg} ${cls.text}`}>
                          <ClsIcon size={12} />
                          {stock.classification}
                        </span>
                      </td>
                      <td className="py-2.5 pr-4 font-mono text-gray-300">
                        {stock.close?.toLocaleString() ?? '—'}
                      </td>
                      <td className="py-2.5 pr-4 font-mono text-gray-400">
                        {stock.ema_9?.toLocaleString() ?? '—'}
                      </td>
                      <td className="py-2.5 pr-4 font-mono text-gray-400">
                        {stock.ema_21?.toLocaleString() ?? '—'}
                      </td>
                      <td className="py-2.5 pr-4 font-mono text-gray-400">
                        {stock.ema_50?.toLocaleString() ?? '—'}
                      </td>
                      <td className={`py-2.5 pr-4 font-mono ${
                        (stock.adr ?? 0) >= 2.5 ? 'text-success' : 'text-gray-400'
                      }`}>
                        {stock.adr != null ? `${stock.adr.toFixed(1)}%` : '—'}
                      </td>
                      <td className="py-2.5">
                        {stock.breakout ? (
                          <span className="text-xs px-2 py-0.5 rounded-full bg-primary/20 text-primary font-semibold">
                            {stock.breakout.pattern.replace('_', ' ')}
                          </span>
                        ) : (
                          <span className="text-xs text-gray-600">—</span>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {/* How to use guide */}
          <div className="card">
            <h2 className="text-base font-semibold text-gray-200 mb-2">How to Use This Scanner</h2>
            <ol className="text-sm text-gray-400 space-y-1.5 list-decimal list-inside">
              <li>Check <span className="text-gray-200">Market Health</span> — only take full-size trades when STRONG, half size when CAUTIOUS, skip when WEAK</li>
              <li>Look for <span className="text-primary">breakout signals</span> on LEAD stocks with ADR above 2.5%</li>
              <li>Each signal shows <span className="text-gray-200">recommended shares</span> based on 0.75% risk per trade — the scanner calculates how many shares to buy so your max loss equals 0.75% of equity</li>
              <li>Hold up to <span className="text-gray-200">8 positions max</span> (10% per stock, 80% total exposure)</li>
              <li>Click <span className="text-primary">Buy</span> to record the trade in your portfolio with stop and R-value</li>
              <li>Monitor your positions in the <span className="text-gray-200">Portfolio</span> page</li>
              <li>Exit rules: stop loss hit → sell 25% at 3R → sell 25% at 5R → trail remainder with EMA(9) → full exit below EMA(21)</li>
            </ol>
          </div>
        </>
      )}
    </div>
  )
}
