import chatDebugFixture from '@/fixtures/chat_debug.json'
import { normalizeChatResponse } from '@/services/normalize_chat'
import type { ChatResponseDTO } from '@/types/http/chat_response'

describe('normalizeChatResponse', () => {
  const fixture: ChatResponseDTO = chatDebugFixture

  it('keeps debug evidence and prompt_debug reachable', () => {
    expect(fixture.debug?.evidence?.document_ids.length).toBeGreaterThan(0)
    expect(fixture.debug?.prompt_debug?.context_items.length).toBeGreaterThan(0)

    const normalized = normalizeChatResponse(fixture)
    expect(normalized.debug?.evidence).toBeDefined()
    expect(normalized.debug?.promptDebug).toBeDefined()
  })

  it('tolerates empty citations and missing locator', () => {
    const emptyCitations: ChatResponseDTO = { ...fixture, citations: [] }
    expect(() => normalizeChatResponse(emptyCitations)).not.toThrow()
    expect(normalizeChatResponse(emptyCitations).evidence.citations).toHaveLength(0)

    const missingLocator = JSON.parse(JSON.stringify(fixture)) as ChatResponseDTO
    // Simulate a server payload with a missing locator (runtime-only edge case).
    delete (missingLocator.citations[0] as unknown as { locator?: unknown }).locator

    const normalized = normalizeChatResponse(missingLocator)
    expect(normalized.evidence.citations[0]?.locator).toEqual(expect.any(Object))
  })

  it('marks run degraded when retrieval fails and generation succeeds', () => {
    const degraded = {
      ...fixture,
      status: 'success',
      debug: {
        ...fixture.debug,
        gate: {
          retrieval: { passed: false, status: 'fail', reasons: ['timeout'] },
          generation: { passed: true, status: 'pass', reasons: [] },
          evaluator: { passed: true, status: 'pass', reasons: [] },
        },
      },
    } as ChatResponseDTO

    const normalized = normalizeChatResponse(degraded)
    expect(normalized.run.status).toBe('degraded')

    const retrieval = normalized.run.steps.find((step) => step.step === 'retrieval')
    const generation = normalized.run.steps.find((step) => step.step === 'generation')
    expect(retrieval?.status).toBe('degraded')
    expect(retrieval?.reasons).toEqual(['timeout'])
    expect(generation?.status).toBe('success')
  })
})
