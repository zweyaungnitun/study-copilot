import confetti from 'canvas-confetti'

const COLORS = ['#5b5bd6', '#8b8bf0', '#18181b', '#a3bfdc', '#a2cfb0', '#dcae92']

/** A short confetti burst for real milestones (chapter done, day done). Skipped under reduced motion. */
export function celebrate(origin: { x: number; y: number } = { x: 0.5, y: 0.35 }) {
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) return
  const base = { origin, colors: COLORS, ticks: 200, scalar: 0.9, disableForReducedMotion: true }
  void confetti({ ...base, particleCount: 70, spread: 62, startVelocity: 38 })
  void confetti({ ...base, particleCount: 40, spread: 110, startVelocity: 26, decay: 0.92 })
}

/** Where on screen an element is, as confetti's 0-1 origin. */
export const originOf = (el: Element | null) => {
  const r = el?.getBoundingClientRect()
  return r ? { x: (r.left + r.width / 2) / innerWidth, y: (r.top + r.height / 2) / innerHeight } : undefined
}
