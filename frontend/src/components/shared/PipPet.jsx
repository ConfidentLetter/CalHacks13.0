import { cx } from '../../utils/format'

// Pip, drawn as a 16×13 pixel sprite with plain SVG rects (no image assets).
// O = olive outline, s = sage body, b = butter cheeks. Eyes and mouth are drawn per state.
const BODY = [
  '....OOOOOOOO....',
  '..OOssssssssOO..',
  '.OssssssssssssO.',
  'OssssssssssssssO',
  'OssssssssssssssO',
  'OssssssssssssssO',
  'OsbbssssssssbbsO',
  'OssssssssssssssO',
  'OssssssssssssssO',
  '.OssssssssssssO.',
  '..OOssssssssOO..',
  '...OO......OO...',
  '...OO......OO...',
]
const FILL = { O: 'var(--color-olive)', s: 'var(--color-sage)', b: 'var(--color-butter-deep)' }

function px(rows, color, key) {
  const out = []
  rows.forEach((row, y) =>
    [...row].forEach((c, x) => {
      if (c === '#') out.push(<rect key={`${key}-${x}-${y}`} x={x} y={y} width="1.02" height="1.02" fill={color} />)
    }),
  )
  return out
}

// 16-wide overlays; '#' = olive pixel.
const EYES = {
  open: ['', '', '', '', '....##....##....', '....##....##....'],
  wide: ['', '', '', '....##....##....', '....##....##....', '....##....##....'],
  up: ['', '', '', '....##....##....', '', ''],
  happy: ['', '', '', '', '...#..#..#..#...', '....##....##....'],
}
const MOUTHS = {
  line: ['', '', '', '', '', '', '', '', '......####......'],
  smile: ['', '', '', '', '', '', '', '.....#....#.....', '......####......'],
  o: ['', '', '', '', '', '', '', '.......##.......', '.......##.......'],
  open: ['', '', '', '', '', '', '', '......####......', '......#..#......', '......####......'],
}

/**
 * state: 'ready' | 'listening' | 'sending' | 'thinking' | 'speaking'
 * expression (from the backend): 'neutral' | 'encouraging' | 'curious' | 'celebrating' | 'thinking'
 */
export function PipPet({ state = 'ready', expression = 'neutral', size = 120 }) {
  const eyes =
    state === 'listening' ? 'wide' : state === 'thinking' ? 'up' : expression === 'celebrating' || expression === 'encouraging' ? 'happy' : 'open'
  const mouth =
    state === 'listening' ? 'o' : expression === 'encouraging' || expression === 'celebrating' ? 'smile' : expression === 'curious' ? 'o' : 'line'

  return (
    <div className={cx('pip relative inline-block', `pip-${state}`)} style={{ width: size, height: size }} aria-hidden="true">
      <svg viewBox="-2 -4 20 18" width={size} height={size} shapeRendering="crispEdges" className="pip-body">
        {BODY.map((row, y) =>
          [...row].map((c, x) => FILL[c] && <rect key={`${x}-${y}`} x={x} y={y} width="1.02" height="1.02" fill={FILL[c]} />),
        )}
        <g className="pip-eyes">{px(EYES[eyes], 'var(--color-olive)', 'e')}</g>
        {state === 'speaking' ? (
          <>
            <g className="pip-mouth-a">{px(MOUTHS.open, 'var(--color-olive)', 'ma')}</g>
            <g className="pip-mouth-b">{px(MOUTHS.line, 'var(--color-olive)', 'mb')}</g>
          </>
        ) : (
          px(MOUTHS[mouth], 'var(--color-olive)', 'm')
        )}
        {state === 'thinking' && (
          <g className="pip-dots">
            <rect x="11" y="-3" width="1" height="1" fill="var(--color-olive)" />
            <rect x="13" y="-3" width="1" height="1" fill="var(--color-olive)" />
            <rect x="15" y="-3" width="1" height="1" fill="var(--color-olive)" />
          </g>
        )}
        {state === 'listening' && (
          <g className="pip-waves" fill="var(--color-clay)">
            <rect x="-2" y="4" width="1" height="3" />
            <rect x="17" y="4" width="1" height="3" />
          </g>
        )}
        {expression === 'celebrating' && state !== 'listening' && (
          <g fill="var(--color-butter-deep)">
            <rect x="0" y="-2" width="1" height="1" />
            <rect x="15" y="-1" width="1" height="1" />
          </g>
        )}
      </svg>
    </div>
  )
}
