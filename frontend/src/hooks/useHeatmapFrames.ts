import { useEffect, useRef, useState } from 'react'
import type { Heatmap } from '../api/types'
import { makeRaster, modeSeries, renderFrame, toGrid, type HeatmapMode } from '../map/heatmap'
import type { RenderMessage, RenderRequest } from '../map/heatmap.worker'

export type FrameImage = ImageBitmap | HTMLCanvasElement

export interface HeatmapFrames {
  frames: (FrameImage | null)[]
  corners: [number, number][] | null
  rendered: number
  total: number
}

const EMPTY: HeatmapFrames = { frames: [], corners: null, rendered: 0, total: 0 }

/** Hours ordered outward from `start`, so the frame the user is looking at renders first. */
export function renderOrder(total: number, start: number): number[] {
  const order: number[] = []
  const s = Math.min(Math.max(0, start), total - 1)
  for (let d = 0; order.length < total; d++) {
    if (s + d < total) order.push(s + d)
    if (d > 0 && s - d >= 0) order.push(s - d)
  }
  return order
}

const supportsWorker =
  typeof Worker !== 'undefined' &&
  typeof OffscreenCanvas !== 'undefined' &&
  typeof ImageData !== 'undefined'

/**
 * Renders all hourly frames for `heatmap` in `mode`, in a Web Worker when available (main-thread
 * fallback otherwise). Returns frames as they arrive; superseded renders are discarded and their
 * bitmaps closed to free GPU/CPU memory.
 */
export function useHeatmapFrames(
  heatmap: Heatmap | null,
  mode: HeatmapMode,
  startHour: number,
  loadLb: number,
): HeatmapFrames {
  const [state, setState] = useState<HeatmapFrames>(EMPTY)
  const workerRef = useRef<Worker | null>(null)
  const reqId = useRef(0)
  // Read the start hour at render-kick-off only; slider moves must not restart rendering.
  const startRef = useRef(startHour)
  useEffect(() => {
    startRef.current = startHour
  }, [startHour])

  useEffect(() => {
    if (!heatmap) {
      setState(EMPTY) // oxlint-disable-line react/set-state-in-effect -- reset when the plan is cleared
      return
    }
    const id = ++reqId.current
    const total = heatmap.hours
    const frames: (FrameImage | null)[] = new Array(total).fill(null)
    // Closure-scoped flag (not React state): tells this effect's async callbacks to stop.
    const run = {
      cancelled: false,
      corners: null as [number, number][] | null,
      rendered: 0,
      raf: 0,
    }
    // Syncing with an external system (the render worker): reset before new frames stream in.
    setState({ frames: [...frames], corners: null, rendered: 0, total }) // oxlint-disable-line react/set-state-in-effect

    // Batch React updates: publish at most once per animation frame.
    const publish = () => {
      if (run.raf) return
      run.raf = requestAnimationFrame(() => {
        run.raf = 0
        if (!run.cancelled)
          setState({ frames: [...frames], corners: run.corners, rendered: run.rendered, total })
      })
    }

    const order = renderOrder(total, startRef.current)
    const series = modeSeries(heatmap, mode)

    if (supportsWorker) {
      if (!workerRef.current) {
        workerRef.current = new Worker(new URL('../map/heatmap.worker.ts', import.meta.url), {
          type: 'module',
        })
      }
      const worker = workerRef.current
      const onMessage = (e: MessageEvent<RenderMessage>) => {
        const msg = e.data
        if (msg.id !== id) {
          if (msg.type === 'frame') msg.bitmap.close()
          return
        }
        if (msg.type === 'meta') run.corners = msg.corners
        else if (msg.type === 'frame') {
          frames[msg.hour] = msg.bitmap
          run.rendered++
        } else if (msg.type === 'error') console.error('heatmap worker:', msg.message)
        publish()
      }
      worker.addEventListener('message', onMessage)
      const req: RenderRequest = {
        id,
        grid: heatmap.grid,
        core: heatmap.core,
        nodes: heatmap.nodes,
        series,
        mode,
        loadLb,
        order,
      }
      worker.postMessage(req)
      return () => {
        run.cancelled = true
        cancelAnimationFrame(run.raf)
        worker.removeEventListener('message', onMessage)
        frames.forEach((f) => f instanceof ImageBitmap && f.close())
      }
    }

    // Fallback: render on the main thread in small slices to keep the UI responsive.
    const raster = makeRaster({ grid: heatmap.grid, core: heatmap.core, nodes: heatmap.nodes })
    run.corners = raster.corners
    let i = 0
    const step = () => {
      if (run.cancelled || i >= order.length) return
      const hour = order[i++]
      const canvas = document.createElement('canvas')
      canvas.width = raster.width
      canvas.height = raster.height
      const g = canvas.getContext('2d')
      if (g) {
        const img = g.createImageData(raster.width, raster.height)
        const fields = series.map((s) => toGrid(heatmap.grid, heatmap.nodes, s[hour]))
        renderFrame(raster, heatmap.grid, fields, mode, loadLb, img.data)
        g.putImageData(img, 0, 0)
        frames[hour] = canvas
        run.rendered++
        publish()
      }
      setTimeout(step, 0)
    }
    step()
    return () => {
      run.cancelled = true
      cancelAnimationFrame(run.raf)
    }
  }, [heatmap, mode, loadLb])

  useEffect(() => () => workerRef.current?.terminate(), [])

  return state
}

/** The closest already-rendered frame to `hour` (so the map never flashes empty while rendering). */
export function nearestFrame(frames: (FrameImage | null)[], hour: number): FrameImage | null {
  if (frames[hour]) return frames[hour]
  for (let d = 1; d < frames.length; d++) {
    if (frames[hour - d]) return frames[hour - d]
    if (frames[hour + d]) return frames[hour + d]
  }
  return null
}
