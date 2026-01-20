import fs from 'node:fs'
import path from 'node:path'

const projectRoot = process.cwd()

const collectFiles = (dir) => {
  if (!fs.existsSync(dir)) return []
  const entries = fs.readdirSync(dir, { withFileTypes: true })
  const files = []
  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name)
    if (entry.isDirectory()) {
      files.push(...collectFiles(fullPath))
    } else if (entry.isFile() && (fullPath.endsWith('.ts') || fullPath.endsWith('.tsx'))) {
      files.push(fullPath)
    }
  }
  return files
}

const scan = (dir, regex, label) => {
  const files = collectFiles(dir)
  const violations = []
  for (const file of files) {
    const content = fs.readFileSync(file, 'utf8')
    if (regex.test(content)) {
      violations.push(`${label}: ${path.relative(projectRoot, file)}`)
    }
  }
  return violations
}

const errors = []

errors.push(
  ...scan(
    path.join(projectRoot, 'src', 'stores'),
    /import\s+[^;]*['"][^'"]*types\/http/,
    'stores should not import types/http',
  ),
)

errors.push(
  ...scan(
    path.join(projectRoot, 'src', 'pages'),
    /import\s+[^;]*['"][^'"]*services\//,
    'pages should not import services',
  ),
)

errors.push(
  ...scan(
    path.join(projectRoot, 'src', 'components'),
    /import\s+[^;]*['"][^'"]*services\//,
    'components should not import services',
  ),
)

if (errors.length) {
  console.error('[gate:f4] Import rule violations found:')
  for (const error of errors) {
    console.error(`- ${error}`)
  }
  process.exit(1)
}

console.log('[gate:f4] OK: import rules satisfied.')
