/**
 * Minimal Python syntax highlighter — no external dependencies.
 * Returns HTML string with <span> tags for colour-coding.
 * Processes line by line; handles the most common patterns.
 */

const PY_KEYWORDS = new Set([
  'False','None','True','and','as','assert','async','await',
  'break','class','continue','def','del','elif','else','except',
  'finally','for','from','global','if','import','in','is','lambda',
  'nonlocal','not','or','pass','raise','return','try','while','with','yield',
  'self','cls',
])

function escapeHtml(s) {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

export function highlightPython(code) {
  if (!code) return ''

  const lines = code.split('\n')
  const out = []

  for (const line of lines) {
    out.push(highlightLine(line))
  }

  return out.join('\n')
}

function highlightLine(line) {
  // Comment line
  const commentIdx = findCommentStart(line)
  let codePart = commentIdx >= 0 ? line.slice(0, commentIdx) : line
  const commentPart = commentIdx >= 0 ? line.slice(commentIdx) : ''

  // Process code part token by token
  const result = tokenize(codePart)
  const commentHtml = commentPart
    ? `<span class="nf-code-cmt">${escapeHtml(commentPart)}</span>`
    : ''

  return result + commentHtml
}

function findCommentStart(line) {
  // Naive: find # not inside a string
  let inStr = null
  for (let i = 0; i < line.length; i++) {
    const c = line[i]
    if (!inStr && (c === '"' || c === "'")) {
      // Check for triple quote
      const triple = line.slice(i, i + 3)
      if (triple === '"""' || triple === "'''") {
        inStr = triple
        i += 2
      } else {
        inStr = c
      }
    } else if (inStr) {
      if (inStr.length === 3 && line.slice(i, i + 3) === inStr) {
        inStr = null
        i += 2
      } else if (inStr.length === 1 && c === inStr && line[i-1] !== '\\') {
        inStr = null
      }
    } else if (c === '#') {
      return i
    }
  }
  return -1
}

function tokenize(code) {
  // Simple regex-based tokenizer: decorators, strings, identifiers, numbers
  const re = /(@\w+)|("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|"""[\s\S]*?"""|'''[\s\S]*?''')|(\b\d+\.?\d*\b)|([A-Za-z_]\w*)|([^\w\s]|\s+)/g

  let result = ''
  let m

  while ((m = re.exec(code)) !== null) {
    const [full, decorator, str, num, ident, other] = m

    if (decorator) {
      result += `<span class="nf-code-dec">${escapeHtml(full)}</span>`
    } else if (str) {
      result += `<span class="nf-code-str">${escapeHtml(full)}</span>`
    } else if (num) {
      result += `<span class="nf-code-num">${escapeHtml(full)}</span>`
    } else if (ident) {
      if (PY_KEYWORDS.has(full)) {
        result += `<span class="nf-code-kw">${escapeHtml(full)}</span>`
      } else if (/^[A-Z]/.test(full)) {
        // ClassName heuristic
        result += `<span class="nf-code-fn">${escapeHtml(full)}</span>`
      } else {
        result += escapeHtml(full)
      }
    } else {
      result += escapeHtml(full)
    }
  }

  return result
}
