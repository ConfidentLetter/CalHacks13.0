import { cx } from '../../utils/format'

export function Card({ as: Tag = 'section', className, children, ...rest }) {
  return (
    <Tag className={cx('glass animate-fade-up', className)} {...rest}>
      {children}
    </Tag>
  )
}

export function CardHeader({ icon: Icon, title, subtitle, action, className }) {
  return (
    <div className={cx('flex items-start justify-between gap-3 px-5 pt-5', className)}>
      <div className="flex min-w-0 items-center gap-3">
        {Icon && (
          <span className="grid size-9 shrink-0 place-items-center rounded-xl border border-olive/12 bg-butter text-honey">
            <Icon className="size-[18px]" aria-hidden="true" />
          </span>
        )}
        <div className="min-w-0">
          <h2 className="truncate text-sm font-semibold text-olive">{title}</h2>
          {subtitle && <p className="truncate text-xs text-olive/65">{subtitle}</p>}
        </div>
      </div>
      {action && <div className="flex shrink-0 items-center gap-2">{action}</div>}
    </div>
  )
}

export function CardBody({ className, children }) {
  return <div className={cx('p-5', className)}>{children}</div>
}
