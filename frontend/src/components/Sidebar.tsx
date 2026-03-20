import {
  BarChart2,
  BookOpen,
  Clock,
  FlaskConical,
  LayoutDashboard,
  Play,
  Settings,
  Thermometer,
  Wallet,
} from 'lucide-react'
import type { Page } from '../types'

interface SidebarProps {
  current: Page
  onChange: (page: Page) => void
}

const NAV: { id: Page; label: string; icon: React.FC<{ size?: number; className?: string }> }[] = [
  { id: 'results',     label: 'Backtest Results',  icon: BarChart2 },
  { id: 'trades',      label: 'Backtest Trades',   icon: BookOpen },
  { id: 'history',     label: 'Backtest History',  icon: Clock },
  { id: 'permutation', label: 'Permutation Test',  icon: FlaskConical },
  { id: 'regime',      label: 'Regime Status',     icon: Thermometer },
  { id: 'portfolio',   label: 'Live Portfolio',    icon: Wallet },
  { id: 'config',      label: 'Config',            icon: Settings },
  { id: 'run',         label: 'Run Backtest',      icon: Play },
]

export default function Sidebar({ current, onChange }: SidebarProps) {
  return (
    <aside className="w-56 flex-shrink-0 bg-card border-r border-border flex flex-col min-h-screen">
      {/* Logo */}
      <div className="px-5 py-4 border-b border-border">
        <div className="flex items-center gap-2">
          <span className="text-2xl">🇻🇳</span>
          <div>
            <p className="font-bold text-gray-100 text-sm leading-tight">VN Trading v5</p>
            <p className="text-xs text-gray-500">HOSE Framework</p>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 py-3">
        {NAV.map(({ id, label, icon: Icon }) => {
          const active = current === id
          return (
            <button
              key={id}
              onClick={() => onChange(id)}
              className={`w-full flex items-center gap-3 px-5 py-2.5 text-sm transition-colors duration-100 text-left ${
                active
                  ? 'bg-primary/15 text-primary border-r-2 border-primary'
                  : 'text-gray-400 hover:text-gray-200 hover:bg-white/5'
              }`}
            >
              <Icon size={15} className={active ? 'text-primary' : ''} />
              <span className="font-medium">{label}</span>
            </button>
          )
        })}
      </nav>

      {/* Footer */}
      <div className="px-5 py-3 border-t border-border text-xs text-gray-600">
        Semi-automatic HOSE strategy
      </div>
    </aside>
  )
}
