/**
 * jsonRepair - from LLM output extract JSON, with truncation repair.
 */

function tryRepairAndParse(s: string): any | null {
  try { return JSON.parse(s) } catch { /* repair */ }
  let repaired = s.trimEnd()
  let lastSafe = -1
  let inStr = false
  let esc = false
  for (let i = 0; i < repaired.length; i++) {
    const ch = repaired[i]
    if (esc) { esc = false; continue }
    if (ch === '\\' && inStr) { esc = true; continue }
    if (ch === '"') { inStr = !inStr; continue }
    if (!inStr && (ch === '}' || ch === ']')) lastSafe = i
  }
  if (lastSafe <= 0) return null
  repaired = repaired.slice(0, lastSafe + 1)
  repaired = repaired.replace(/,\s*([\]}])$/, '$1')
  let braces = 0
  let brackets = 0
  inStr = false
  esc = false
  for (let i = 0; i < repaired.length; i++) {
    const ch = repaired[i]
    if (esc) { esc = false; continue }
    if (ch === '\\' && inStr) { esc = true; continue }
    if (ch === '"') { inStr = !inStr; continue }
    if (inStr) continue
    if (ch === '{') braces++
    else if (ch === '}') braces--
    else if (ch === '[') brackets++
    else if (ch === ']') brackets--
  }
  repaired += ']'.repeat(Math.max(0, brackets))
  repaired += '}'.repeat(Math.max(0, braces))
  try { return JSON.parse(repaired) } catch { return null }
}

export function extractJSON(raw: any): any | null {
  if (!raw) return null
  if (typeof raw === 'object') return raw
  if (typeof raw !== 'string') return null
  const r1 = tryRepairAndParse(raw)
  if (r1) return r1
  const stripped = raw
    .replace(/^[\s\S]*?```(?:json)?\s*/i, '')
    .replace(/\s*```[\s\S]*$/, '')
  if (stripped !== raw) {
    const r2 = tryRepairAndParse(stripped)
    if (r2) return r2
  }
  const brace = raw.indexOf('{')
  const bracket = raw.indexOf('[')
  const start = brace >= 0 && (bracket < 0 || brace < bracket) ? brace : bracket
  if (start >= 0) {
    const r3 = tryRepairAndParse(raw.slice(start))
    if (r3) return r3
  }
  return null
}