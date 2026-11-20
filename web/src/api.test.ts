import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { addItem, clearWeekCache, deleteItem, loadWeek, peekWeek, WeekError, type Week } from './api'
import { weekAfterDelete } from './itemDetails'

const WEEK: Week = {
  week_start: '2026-11-16',
  timezone: 'America/Los_Angeles',
  slot_min: 15,
  feasible: true,
  blocks: [],
  frames: [],
  unscheduled: [],
  series: [],
  shortfalls: [],
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

  const request = { week_start: '2026-11-16', title: 'Gym', preset: 'days' as const, weekdays: [0], estimate_min: 60, one_block_per_day: false, keep_length: false, checkable: true, on_miss: 'reschedule' as const }

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

describe('deleteItem', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    clearWeekCache()
    fetchMock.mockReset()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('deletes and keeps only the returned week in memory', async () => {
    fetchMock.mockResolvedValueOnce(respond(200, { ...WEEK, week_start: '2026-11-23' }))
    await loadWeek('2026-11-23')
    fetchMock.mockResolvedValueOnce(respond(200, WEEK))

    expect(await deleteItem('i1', '2026-11-16')).toEqual(WEEK)

    const [url, init] = fetchMock.mock.calls[1]
    expect(url).toBe('/api/items/i1?week=2026-11-16')
    expect(init).toMatchObject({ method: 'DELETE' })
    expect(peekWeek('2026-11-16')).toEqual(WEEK)
    expect(peekWeek('2026-11-23')).toBeUndefined()
  })

  it("says when the item is already gone, and passes on other failures' messages", async () => {
    fetchMock.mockResolvedValueOnce(respond(404, { detail: 'That item no longer exists.' }))
    await expect(deleteItem('i1', '2026-11-16')).rejects.toMatchObject({ kind: 'missing' })
    fetchMock.mockResolvedValueOnce(respond(500, { detail: 'Something broke.' }))
    await expect(deleteItem('i1', '2026-11-16')).rejects.toThrow('Something broke.')
  })

  it('after navigating away: leaves the shown week alone, and it reloads when viewed again', async () => {
    // Viewing week A, start a delete, move to week B before it finishes.
    const weekB = { ...WEEK, week_start: '2026-11-23' }
    fetchMock.mockResolvedValueOnce(respond(200, weekB))
    const shown = await loadWeek('2026-11-23') // week B, on screen
    fetchMock.mockResolvedValueOnce(respond(200, WEEK))

    const returned = await deleteItem('i1', '2026-11-16') // finishes while B is viewed

    expect(weekAfterDelete('2026-11-23', returned)).toBeNull() // so the page keeps showing `shown`
    expect(shown.week_start).toBe('2026-11-23')
    expect(peekWeek('2026-11-23')).toBeUndefined() // B reloads next time it's needed
    expect(peekWeek('2026-11-16')).toEqual(WEEK) // A's fresh copy is kept
  })
})
