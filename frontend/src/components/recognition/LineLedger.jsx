import { LedgerRow } from './LedgerRow'

/** The lines in reading order on a ruled-paper card. */
export function LineLedger({ lines, selectedId, hoveredId, onSelect, onHover, className }) {
  return (
    <section className={className} aria-label="Lines read on this page">
      <ol className="bg-white max-h-[760px] divide-y divide-dotted divide-olive/20 overflow-y-auto border border-olive/70 bg-white">
        {lines.map((l) => (
          <LedgerRow key={l.id} line={l} selected={l.id === selectedId} hovered={l.id === hoveredId} onSelect={onSelect} onHover={onHover} />
        ))}
      </ol>
    </section>
  )
}
