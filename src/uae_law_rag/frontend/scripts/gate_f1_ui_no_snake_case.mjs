import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'

const uiDir = join(process.cwd(), 'src', 'types', 'ui')
const snakeCasePattern = /\b[a-z]+_[a-z0-9_]+\b/g
const allowedTerms = new Set(['chat_view', 'evidence_view'])

const walk = (dir) => {
  const entries = readdirSync(dir)
  return entries.flatMap((entry) => {
    const fullPath = join(dir, entry)
    const stats = statSync(fullPath)
    if (stats.isDirectory()) {
      return walk(fullPath)
    }
    if (fullPath.endsWith('.ts') || fullPath.endsWith('.tsx')) {
      return [fullPath]
    }
    return []
  })
}

const files = walk(uiDir)
const violations = []

for (const file of files) {
  const content = readFileSync(file, 'utf8')
  const matches = content.match(snakeCasePattern) || []
  const disallowed = matches.filter((match) => !allowedTerms.has(match))
  if (disallowed.length > 0) {
    violations.push(file)
  }
}

if (violations.length > 0) {
  console.error('[gate:f1-ui] Snake_case detected in UI types:')
  for (const file of violations) {
    console.error(`- ${file}`)
  }
  process.exit(1)
}

console.log('[gate:f1-ui] OK: no snake_case in UI types.')
