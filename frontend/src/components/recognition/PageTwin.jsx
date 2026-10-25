import { useRef, useState } from 'react'
import { useElementSize } from '../../hooks/useElementSize'
import { cx } from '../../utils/format'
import { LineBox } from './LineBox'

/**
 * The dewarped page with every line box drawn on top. Boxes are in dewarped-image pixels; the image's own
 * size (from the twin, else from the loaded bitmap) is the coordinate space, so the overlay is exact at any
 * rendered size. `maxHeight` keeps a tall portrait page inside the viewport; width follows.
 */
export function PageTwin({ image, lines = [], selectedId, hoveredId, onSelect, onHover, compact = false, maxHeight = 720, showBoxes = true, region = null, className }) {
  const holder = useRef(null)
  const { width: cw } = useElementSize(holder)
  const [natural, setNatural] = useState(null)
  const [broken, setBroken] = useState(false)

  const W = image?.width || natural?.width || 0
  const H = image?.height || natural?.height || 0
  // the visible window: the whole page, or the ink region (in image pixels) when `region` is given
  const view = region && W && H ? region : { x: 0, y: 0, width: W, height: H }
  const ratio = view.width && view.height ? view.width / view.height : 4 / 3
  // the full image is laid out as a "stage" inside the window; boxes are percentages of the stage
  const stage =
    W && H
      ? {
          left: `${(-view.x / view.width) * 100}%`,
          top: `${(-view.y / view.height) * 100}%`,
          width: `${(W / view.width) * 100}%`,
          height: `${(H / view.height) * 100}%`,
        }
      : { left: 0, top: 0, width: '100%', height: '100%' }

  // fit: as wide as the container, but never taller than maxHeight
  let w = cw || 0
  let h = w / ratio
  if (h > maxHeight) {
    h = maxHeight
    w = h * ratio
  }

  const coords = W && H ? { width: W, height: H } : null
  const boxes = showBoxes && coords ? lines.filter((l) => l.bbox) : []

  return (
    <div ref={holder} className={cx('w-full', className)}>
      <div
        className="relative mx-auto overflow-hidden border border-olive/70 bg-paper"
        style={w ? { width: w, height: h } : { aspectRatio: `${ratio}` }}
      >
        <div className="absolute" style={stage}>
          {image?.url && !broken ? (
            <img
              src={image.url}
              alt={compact ? 'Latest page twin' : 'Your page, flattened, with every recognized line boxed'}
              onLoad={(e) => setNatural({ width: e.currentTarget.naturalWidth, height: e.currentTarget.naturalHeight })}
              onError={() => setBroken(true)}
              className="absolute inset-0 size-full object-fill select-none"
              draggable={false}
            />
          ) : (
            <div className="ruled absolute inset-0 grid place-items-center bg-paper text-olive/55">
              <span className="flex items-center gap-2 text-sm">
                {broken ? 'page image failed to load' : 'no page image'}
              </span>
            </div>
          )}
          {boxes.length > 0 && (
            <div className={cx('absolute inset-0', compact && 'pointer-events-none')} role={compact ? undefined : 'group'} aria-label={compact ? undefined : 'Recognized lines'}>
              {boxes.map((l) => (
                <LineBox
                  key={l.id}
                  line={l}
                  image={coords}
                  compact={compact}
                  selected={l.id === selectedId}
                  hovered={l.id === hoveredId}
                  onSelect={onSelect}
                  onHover={onHover}
                />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
