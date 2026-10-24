import { BookOpenText, Bot, Camera, LayoutDashboard, Settings } from 'lucide-react'

export const NAV_ITEMS = [
  // `tab` is the little coloured index-tab on the sidebar edge
  { id: 'dashboard', label: 'my study space', icon: LayoutDashboard, tab: 'bg-butter-deep' },
  { id: 'notebook', label: 'peek at my notebook', icon: Camera, tab: 'bg-sage-deep' },
  { id: 'reading', label: "things i've been reading", icon: BookOpenText, tab: 'bg-butter-deep' },
  { id: 'tutor', label: 'ask a little question', icon: Bot, tab: 'bg-sage-deep' },
  { id: 'settings', label: 'settings', icon: Settings, tab: 'bg-paper-deep' },
]
