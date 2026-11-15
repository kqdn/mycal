import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { addItem, clearWeekCache, loadWeek, peekWeek, WeekError, type Week } from './api'

const WEEK: Week = {
  week_start: '2026-11-16',
  timezone: 'America/Los_Angeles',
  feasible: true,
  blocks: [],
  frames: [],
  unscheduled: [],
}

function respond(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

describe('week cache', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    clearWeekCache()
    fetchMock.mockReset()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('fetches a week once, then serves it from memory', async () => {
    fetchMock.mockResolvedValue(respond(200, WEEK))
    expect(peekWeek('2026-11-16')).toBeUndefined()

    await loadWeek('2026-11-16')
    expect(await loadWeek('2026-11-16')).toEqual(WEEK)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(peekWeek('2026-11-16')).toEqual(WEEK)
  })

  it('shares one request between callers that ask at the same time', async () => {
    fetchMock.mockResolvedValue(respond(200, WEEK))
    await Promise.all([loadWeek('2026-11-16'), loadWeek('2026-11-16')])
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('does not keep a failed fetch, so the next try asks again', async () => {
    fetchMock.mockResolvedValueOnce(respond(404, { detail: 'No week file' }))
    await expect(loadWeek('2026-11-23')).rejects.toBeInstanceOf(WeekError)
    expect(peekWeek('2026-11-23')).toBeUndefined()

    fetchMock.mockResolvedValueOnce(respond(200, { ...WEEK, week_start: '2026-11-23' }))
    await expect(loadWeek('2026-11-23')).resolves.toMatchObject({ week_start: '2026-11-23' })
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })
})

describe('addItem', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    clearWeekCache()
    fetchMock.mockReset()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  const request = { week_start: '2026-11-16', title: 'Gym', preset: 'days' as const, weekdays: [0], estimate_min: 60, one_block_per_day: false }

  it('posts the item and keeps only the returned week in memory', async () => {
    fetchMock.mockResolvedValueOnce(respond(200, { ...WEEK, week_start: '2026-11-23' }))
    await loadWeek('2026-11-23') // another week, now stale
    fetchMock.mockResolvedValueOnce(respond(201, WEEK))

    expect(await addItem(request)).toEqual(WEEK)

    const [url, init] = fetchMock.mock.calls[1]
    expect(url).toBe('/api/items')
    expect(init).toMatchObject({ method: 'POST', body: JSON.stringify(request) })
    expect(peekWeek('2026-11-16')).toEqual(WEEK)
    expect(peekWeek('2026-11-23')).toBeUndefined()
  })

  it("passes on the server's message when the item is refused", async () => {
    fetchMock.mockResolvedValueOnce(respond(422, { detail: "It doesn't fit." }))
    await expect(addItem(request)).rejects.toThrow("It doesn't fit.")
  })
})
