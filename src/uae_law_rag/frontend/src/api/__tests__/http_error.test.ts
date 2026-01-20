import { HttpError, requestJson } from '@/api/http'
import type { ErrorResponseDTO } from '@/types/http/error_response'

type MockHeaders = {
  get: (key: string) => string | null
}

type MockResponse = {
  ok: boolean
  status: number
  headers: MockHeaders
  text: () => Promise<string>
}

const makeHeaders = (headers: Record<string, string> = {}): MockHeaders => {
  return {
    get: (key: string) => {
      const normalized = key.toLowerCase()
      for (const [headerKey, value] of Object.entries(headers)) {
        if (headerKey.toLowerCase() === normalized) return value
      }
      return null
    },
  }
}

const makeResponse = (status: number, body: string, headers?: Record<string, string>): MockResponse => {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: makeHeaders(headers),
    text: async () => body,
  }
}

describe('requestJson', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('wraps non-2xx JSON errors into HttpError', async () => {
    const payload: ErrorResponseDTO = {
      error: {
        code: 'bad_request',
        message: 'invalid',
        trace_id: 'trace-err',
        detail: {},
      },
    }

    const fetchMock = vi.fn().mockResolvedValue(
      makeResponse(400, JSON.stringify(payload), { 'x-request-id': 'req-err' }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(requestJson('/api/fail')).rejects.toBeInstanceOf(HttpError)
    await expect(requestJson('/api/fail')).rejects.toMatchObject({
      info: {
        status: 400,
        traceId: 'trace-err',
        requestId: 'req-err',
        response_json: payload,
      },
    })
  })

  it('throws HttpError when response is not JSON', async () => {
    const fetchMock = vi.fn().mockResolvedValue(makeResponse(200, 'not-json'))
    vi.stubGlobal('fetch', fetchMock)

    await expect(requestJson('/api/text')).rejects.toMatchObject({
      info: {
        status: 200,
        message: 'Response is not valid JSON',
      },
    })
  })

  it('wraps network/abort errors into HttpError with status 0', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error('aborted'))
    vi.stubGlobal('fetch', fetchMock)

    await expect(requestJson('/api/timeout')).rejects.toMatchObject({
      info: {
        status: 0,
      },
    })
  })
})
