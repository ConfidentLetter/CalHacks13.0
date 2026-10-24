import { AlertCircle, CheckCircle2, HelpCircle, Lightbulb, Sparkles } from 'lucide-react'
import { Badge } from '../ui/Badge'
import { EmptyState, ErrorState, LoadingDots, Skeleton } from '../ui/Feedback'
import { cx, formatClock } from '../../utils/format'

const STEP = {
  correct: { icon: CheckCircle2, color: 'text-sage-ink', label: 'Correct' },
  error: { icon: AlertCircle, color: 'text-clay', label: 'Issue' },
  unclear: { icon: HelpCircle, color: 'text-honey', label: 'Check' },
}

export function AnalysisPanel({ analysis, hasSnapshot, onRetry }) {
  const { data, loading, error } = analysis

  if (loading) {
    return (
      <div className="space-y-3" aria-live="polite">
        <div className="flex items-center gap-2 text-sm text-honey">
          <LoadingDots label="Analyzing" /> Analyzing your page…
        </div>
        <Skeleton className="h-4 w-11/12" />
        <Skeleton className="h-4 w-3/4" />
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-16 w-full" />
      </div>
    )
  }
  if (error) return <ErrorState message={`Analysis failed: ${error}`} onRetry={onRetry} />
  if (!data) {
    return (
      <EmptyState
        icon={Sparkles}
        title={hasSnapshot ? 'Ready to analyze' : 'Nothing to analyze yet'}
        description={
          hasSnapshot
            ? 'Press “Analyze My Work” to check each step of the handwritten solution.'
            : 'Capture or refresh a snapshot first.'
        }
      />
    )
  }

  const steps = data.steps || []
  const issues = steps.filter((s) => s.status === 'error').length

  return (
    <div className="animate-fade-up space-y-5" aria-live="polite">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={issues ? 'red' : 'green'}>{issues ? `${issues} issue${issues > 1 ? 's' : ''} found` : 'All steps look correct'}</Badge>
        {(data.topics || []).map((t) => (
          <Badge key={t} tone="violet">
            {t}
          </Badge>
        ))}
        {data.analyzedAt && <span className="ml-auto text-[11px] text-olive/55">Analyzed {formatClock(data.analyzedAt)}</span>}
      </div>

      <p className="text-sm leading-relaxed text-olive">{data.summary}</p>

      {steps.length > 0 && (
        <ol className="space-y-2">
          {steps.map((s, i) => {
            const k = STEP[s.status] || STEP.unclear
            const Icon = k.icon
            return (
              <li
                key={i}
                className={cx(
                  'flex gap-3 rounded-sm border p-3',
                  s.status === 'error' ? 'border-clay/40 bg-clay/10' : 'border-olive/8 bg-olive/4',
                )}
              >
                <Icon className={cx('mt-0.5 size-4 shrink-0', k.color)} aria-label={k.label} />
                <div className="min-w-0">
                  <p className="font-mono text-[13px] text-olive">{s.label}</p>
                  {s.note && <p className="mt-0.5 text-xs leading-relaxed text-olive/65">{s.note}</p>}
                </div>
              </li>
            )
          })}
        </ol>
      )}

      {data.hints?.length > 0 && (
        <div className="rounded-sm border border-sage-deep bg-sage/50 p-3.5">
          <p className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold text-sage-ink">
            <Lightbulb className="size-3.5" aria-hidden="true" /> Hints
          </p>
          <ul className="list-disc space-y-1 pl-5 text-xs leading-relaxed text-olive/80">
            {data.hints.map((h, i) => (
              <li key={i}>{h}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
