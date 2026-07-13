// 把一条 curl 命令串解析成 { method, url, headers, body }。
// 纯前端字符串解析，不执行任何 shell，无注入风险。
// 支持常见形态：-X/--request、-H/--header、-d/--data/--data-raw/--data-binary、
// --url、-G(--get)、跨行反斜杠续行、单/双引号包裹。

function tokenize(input) {
  // 去掉行尾续行反斜杠，合并成单行
  const merged = input.replace(/\\\r?\n/g, ' ')
  const tokens = []
  let i = 0
  const n = merged.length
  while (i < n) {
    // 跳过空白
    while (i < n && /\s/.test(merged[i])) i++
    if (i >= n) break
    let token = ''
    while (i < n && !/\s/.test(merged[i])) {
      const ch = merged[i]
      if (ch === "'" || ch === '"') {
        // 读到匹配的引号
        const quote = ch
        i++
        while (i < n && merged[i] !== quote) {
          if (merged[i] === '\\' && quote === '"' && i + 1 < n) {
            token += merged[i + 1]
            i += 2
          } else {
            token += merged[i]
            i++
          }
        }
        i++ // 跳过收尾引号
      } else {
        token += ch
        i++
      }
    }
    tokens.push(token)
  }
  return tokens
}

export function parseCurl(raw) {
  const text = (raw || '').trim()
  if (!text) throw new Error('curl 命令为空')
  const tokens = tokenize(text)
  if (!tokens.length || tokens[0] !== 'curl') {
    throw new Error('不是有效的 curl 命令（应以 curl 开头）')
  }

  const result = { method: '', url: '', headers: {}, body: null }
  const bodyParts = []
  let forceGet = false

  for (let i = 1; i < tokens.length; i++) {
    const t = tokens[i]
    const next = () => tokens[++i]

    if (t === '-X' || t === '--request') {
      result.method = (next() || '').toUpperCase()
    } else if (t === '-H' || t === '--header') {
      const h = next() || ''
      const idx = h.indexOf(':')
      if (idx > -1) {
        const key = h.slice(0, idx).trim()
        const val = h.slice(idx + 1).trim()
        if (key) result.headers[key] = val
      }
    } else if (t === '-d' || t === '--data' || t === '--data-raw' || t === '--data-binary' || t === '--data-ascii') {
      bodyParts.push(next() || '')
    } else if (t === '--url') {
      result.url = next() || ''
    } else if (t === '-G' || t === '--get') {
      forceGet = true
    } else if (t === '-b' || t === '--cookie') {
      const c = next() || ''
      if (c) result.headers['Cookie'] = c
    } else if (t === '-A' || t === '--user-agent') {
      const ua = next() || ''
      if (ua) result.headers['User-Agent'] = ua
    } else if (t === '-e' || t === '--referer') {
      const ref = next() || ''
      if (ref) result.headers['Referer'] = ref
    } else if (t === '-u' || t === '--user') {
      // 基础认证：转成 Authorization 头
      const cred = next() || ''
      if (cred) result.headers['Authorization'] = 'Basic ' + btoa(cred)
    } else if (t.startsWith('-')) {
      // 其它带值的 flag（如 --compressed 无值）尽量跳过；带值的常见形式已在上面覆盖
      // 这里对未知的单字符/长 flag 不吞后一个 token，避免误吃 url
      continue
    } else if (!result.url) {
      // 第一个非 flag 裸参数当作 url
      result.url = t
    }
  }

  if (bodyParts.length) result.body = bodyParts.join('&')

  // method 推断：显式 -X 优先；否则有 body 且非 -G → POST，其余 GET
  if (!result.method) {
    result.method = result.body && !forceGet ? 'POST' : 'GET'
  }
  if (forceGet) result.method = 'GET'

  if (!result.url) throw new Error('未能从 curl 命令中解析出 URL')
  return result
}
