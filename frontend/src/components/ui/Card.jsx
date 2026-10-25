import { MathContent } from '../shared/MathTextRenderer'
import { cx } from '../../utils/format'

export function Card({ as: Tag = 'section', className, children, ...rest }) {
  return (
    <Tag className={cx('glass animate-fade-up', className)} {...rest}>
      {children}
    </Tag>
  )
}

/** Section header for a sheet: display-font title over a thin rule. `icon` is accepted but not drawn. */
export function CardHeader({ title, subtitle, action, className }) {
  return (
    <div className={cx('flex items-end justify-between gap-3 border-b border-olive/15 px-5 pt-4 pb-3', className)}>
      <div className="min-w-0">
        <h2 className="truncate text-xl text-olive"><MathContent>{title}</MathContent></h2>
        {subtitle && <p className="truncate text-[13px] text-olive/60"><MathContent>{subtitle}</MathContent></p>}
      </div>
      {action && <div className="flex shrink-0 items-center gap-2">{action}</div>}
    </div>
  )
}

export function CardBody({ className, children }) {
  return <div className={cx('p-5', className)}>{children}</div>
}
