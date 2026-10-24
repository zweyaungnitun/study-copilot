import { useEffect, useMemo, useRef, useState } from 'react'
import { Icon, type IconName } from './ui'

export interface Command { id: string; label: string; hint?: string; icon: IconName; group: string; run: () => void }

/** ⌘K / Ctrl+K quick switcher: fuzzy-ish filter, arrow keys to move, Enter to run. */
export function CommandPalette({ open, onClose, commands }: { open: boolean; onClose: () => void; commands: Command[] }) {
  const [q, setQ] = useState('')
  const [i, setI] = useState(0)
  const input = useRef<HTMLInputElement>(null)
  const list = useRef<HTMLDivElement>(null)

  useEffect(() => { if (open) { setQ(''); setI(0); requestAnimationFrame(() => input.current?.focus()) } }, [open])

  const items = useMemo(() => {
    const t = q.trim().toLowerCase()
    if (!t) return commands
    return commands.filter(c => `${c.label} ${c.group} ${c.hint ?? ''}`.toLowerCase().includes(t))
  }, [q, commands])

  useEffect(() => { setI(0) }, [q])
  useEffect(() => { list.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' }) }, [i])

  if (!open) return null
  const run = (c?: Command) => { if (!c) return; onClose(); c.run() }
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setI(x => Math.min(items.length - 1, x + 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setI(x => Math.max(0, x - 1)) }
    else if (e.key === 'Enter') { e.preventDefault(); run(items[i]) }
    else if (e.key === 'Escape') { e.preventDefault(); onClose() }
  }

  let lastGroup = ''
  return (
    <div className="cmdk-backdrop" onMouseDown={onClose}>
      <div className="cmdk" role="dialog" aria-modal="true" aria-label="Command palette" onMouseDown={e => e.stopPropagation()} onKeyDown={onKey}>
        <div className="cmdk-input">
          <Icon name="search" size={18} />
          <input ref={input} value={q} onChange={e => setQ(e.target.value)} placeholder="Jump to a page, track or action…"
            aria-label="Search commands" role="combobox" aria-expanded="true" aria-controls="cmdk-list" />
          <kbd>esc</kbd>
        </div>
        <div className="cmdk-list" id="cmdk-list" role="listbox" ref={list}>
          {items.length === 0 && <div className="cmdk-empty">No matches for “{q}”</div>}
          {items.map((c, idx) => {
            const head = c.group !== lastGroup ? (lastGroup = c.group) : null
            return <div key={c.id}>
              {head && <div className="cmdk-group">{head}</div>}
              <button type="button" role="option" aria-selected={idx === i} className="cmdk-item"
                onMouseMove={() => setI(idx)} onClick={() => run(c)}>
                <span className="cmdk-icon"><Icon name={c.icon} size={16} /></span>
                <span className="cmdk-label">{c.label}</span>
                {c.hint && <span className="cmdk-hint">{c.hint}</span>}
                <Icon name="arrow" size={14} />
              </button>
            </div>
          })}
        </div>
        <div className="cmdk-foot"><span><kbd>↑</kbd><kbd>↓</kbd> navigate</span><span><kbd>↵</kbd> open</span><span><kbd>⌘</kbd><kbd>K</kbd> toggle</span></div>
      </div>
    </div>
  )
}

/** Global ⌘K / Ctrl+K listener. */
export function useCommandHotkey(toggle: () => void) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); toggle() } }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [toggle])
}
