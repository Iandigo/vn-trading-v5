interface MetricCardProps {
  label: string
  value: string
  sub?: string
  highlight?: 'green' | 'red' | 'neutral'
  small?: boolean
}

export default function MetricCard({ label, value, sub, highlight, small }: MetricCardProps) {
  const valueColor =
    highlight === 'green'
      ? 'text-success'
      : highlight === 'red'
      ? 'text-danger'
      : 'text-gray-100'

  return (
    <div className="card flex flex-col gap-1">
      <p className="text-xs text-gray-500 font-medium uppercase tracking-wider">{label}</p>
      <p className={`font-bold ${small ? 'text-xl' : 'text-2xl'} ${valueColor}`}>{value}</p>
      {sub && <p className="text-xs text-gray-500">{sub}</p>}
    </div>
  )
}
