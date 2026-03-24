import { useState } from 'react'
import type { Page } from './types'
import Sidebar from './components/Sidebar'
import BacktestResults from './pages/BacktestResults'
import BacktestTrades from './pages/BacktestTrades'
import BacktestHistory from './pages/BacktestHistory'
import PermutationTest from './pages/PermutationTest'
import RegimeStatus from './pages/RegimeStatus'
import LivePortfolio from './pages/LivePortfolio'
import Scanner from './pages/Scanner'
import Config from './pages/Config'
import RunBacktest from './pages/RunBacktest'
import CarverSignals from './pages/CarverSignals'

export default function App() {
  const [page, setPage] = useState<Page>('scanner')

  const renderPage = () => {
    switch (page) {
      case 'scanner':     return <Scanner onTrade={() => setPage('portfolio')} />
      case 'results':     return <BacktestResults />
      case 'trades':      return <BacktestTrades />
      case 'history':     return <BacktestHistory />
      case 'permutation': return <PermutationTest />
      case 'regime':      return <RegimeStatus />
      case 'portfolio':   return <LivePortfolio />
      case 'config':      return <Config />
      case 'run':         return <RunBacktest onDone={() => setPage('results')} />
      case 'carver':      return <CarverSignals />
      default:            return <Scanner onTrade={() => setPage('portfolio')} />
    }
  }

  return (
    <div className="flex min-h-screen bg-bg">
      <Sidebar current={page} onChange={setPage} />
      <main className="flex-1 p-6 overflow-auto">
        {renderPage()}
      </main>
    </div>
  )
}
