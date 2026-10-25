import { Badge } from '../ui/Badge'
import { cx } from '../../utils/format'
import { readInSeconds } from './twinModel'

/** Topics as chips, the summary sentence, hints on a sticky note, latency as a quiet footnote. */
export function SummaryStrip({ model, className }) {
  const { counts, summary, topics, hints, latencyMs, judged, analysisFailed } = model
  const secs = readInSeconds(latencyMs)
  return (
    <div className={cx('space-y-4', className)}>
      {(topics.length > 0 || judged) && (
        <div className="flex flex-wrap items-center gap-2">
          {judged && (
            <Badge tone={counts.errors ? 'red' : analysisFailed ? 'neutral' : 'green'} className={cx('text-[12px]', counts.errors && 'border-ink-red bg-ink-red/10 text-ink-red')}>
              {analysisFailed && !counts.total
                ? 'nothing readable'
                : counts.errors
                  ? `${counts.errors} error${counts.errors > 1 ? 's' : ''} caught`
                  : 'no errors caught'}
            </Badge>
          )}
          {topics.map((t) => (
            <Badge key={t} tone="violet" className="text-[12px]">
              {t}
            </Badge>
          ))}
        </div>
      )}

      {summary ? (
        <p className="text-[15px] leading-relaxed text-olive">{summary}</p>
      ) : (
        <p className="text-[15px] leading-relaxed text-olive/65">
          transcribed only — press <strong className="text-olive">Analyze my page</strong> and Pip will check each line.
        </p>
      )}

      {hints.length > 0 && (
        <aside className="sticky-note rotate-[-0.6deg] p-4 motion-reduce:rotate-0">
          <p className="flex items-center gap-1.5 font-display text-lg text-olive">
            hints
          </p>
          <ul className="mt-1.5 space-y-1.5 text-[15px] leading-relaxed text-olive">
            {hints.map((h, i) => (
              <li key={i} className="flex gap-2">
                <span aria-hidden="true">→</span>
                <span>{h}</span>
              </li>
            ))}
          </ul>
        </aside>
      )}

      <p className="text-[13px] text-olive/55 tabular-nums">
        {secs ? `read in ${secs} s` : 'latency unknown'} · {counts.total} line{counts.total === 1 ? '' : 's'}
        {counts.crossed ? ` · ${counts.crossed} crossed out` : ''}
        {counts.illegible ? ` · ${counts.illegible} illegible` : ''}
        {model.quality && model.quality.ok === false && model.quality.issues?.length ? ` · page quality: ${model.quality.issues.join(', ')}` : ''}
      </p>
    </div>
  )
}
