const API_BASE = '/api/workbot'

async function parseJsonResponse(response, fallbackMessage) {
  let body
  try {
    body = await response.json()
  } catch {
    throw new Error(`服务返回了无法解析的响应（HTTP ${response.status}）`)
  }
  if (!response.ok) {
    throw new Error(body.message || `${fallbackMessage}（HTTP ${response.status}）`)
  }
  return body.data
}

export async function queryRecords(source, token, query) {
  const endpoint = source === 'messages' ? 'messages' : 'callback-logs'
  const params = new URLSearchParams()

  Object.entries(query).forEach(([key, value]) => {
    if (value !== '' && value !== null && value !== undefined) {
      params.set(key, value)
    }
  })

  const response = await fetch(`${API_BASE}/${endpoint}?${params.toString()}`, {
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: 'application/json',
    },
  })

  return parseJsonResponse(response, '查询失败')
}

export async function queryLogFiles(token) {
  const response = await fetch(`${API_BASE}/logs`, {
    headers: { Authorization: `Bearer ${token}`, Accept: 'application/json' },
  })
  return parseJsonResponse(response, '读取日志列表失败')
}

export async function readLogFile(filename, token, tailLines = 500) {
  const response = await fetch(
    `${API_BASE}/logs/${encodeURIComponent(filename)}/content?tail_lines=${tailLines}`,
    { headers: { Authorization: `Bearer ${token}`, Accept: 'application/json' } },
  )
  return parseJsonResponse(response, '读取日志内容失败')
}

export async function downloadLogFile(filename, token) {
  const response = await fetch(`${API_BASE}/logs/${encodeURIComponent(filename)}/download`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!response.ok) {
    let message = `下载失败（HTTP ${response.status}）`
    try {
      const body = await response.json()
      message = body.message || message
    } catch {
      // Keep the HTTP status fallback for non-JSON responses.
    }
    throw new Error(message)
  }
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}
