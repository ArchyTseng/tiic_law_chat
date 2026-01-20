// frontend/scripts/gete_f1_domain_imports.mjs
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'

const domainDir = join(process.cwd(), 'src', 'types', 'domain')
const importPattern = /from\s+['"][^'"]*types\/http/
const requirePattern = /require\(['"][^'"]*types\/http/

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

const files = walk(domainDir)
const violations = []

for (const file of files) {
  const content = readFileSync(file, 'utf8')
  if (importPattern.test(content) || requirePattern.test(content)) {
    violations.push(file)
  }
}

if (violations.length > 0) {
  console.error('[gate:f1-domain] Forbidden import from types/http detected:')
  for (const file of violations) {
    console.error(`- ${file}`)
  }
  process.exit(1)
}

console.log('[gate:f1-domain] OK: no types/http imports in domain.')
