/// <reference lib="webworker" />
/**
 * Renders every heatmap frame off the main thread and posts each one back as a transferable
 * ImageBitmap (zero-copy), starting with the hour the user is looking at.
 */
import type { HeatmapGrid } from '../api/types'
import { makeRaster, renderFrame, toGrid, type HeatmapMode } from './heatmap'

export interface RenderRequest {
  id: number
  grid: HeatmapGrid
  core: number[]
  nodes: number[]
  series: (number | null)[][][] // [field][hour][node]
  mode: HeatmapMode
  loadLb: number
  order: number[] // hour indices in render order
}

export type RenderMessage =
  | { id: number; type: 'meta'; corners: [number, number][]; width: number; height: number }
  | { id: number; type: 'frame'; hour: number; bitmap: ImageBitmap }
  | { id: number; type: 'done' }
  | { id: number; type: 'error'; message: string }

const ctx = self as unknown as DedicatedWorkerGlobalScope
let latest = 0

ctx.onmessage = async (e: MessageEvent<RenderRequest>) => {
  const req = e.data
  latest = req.id
  try {
    const raster = makeRaster({ grid: req.grid, core: req.core, nodes: req.nodes })
    ctx.postMessage({
      id: req.id,
      type: 'meta',
      corners: raster.corners,
      width: raster.width,
      height: raster.height,
    } satisfies RenderMessage)
    const canvas = new OffscreenCanvas(raster.width, raster.height)
    const g = canvas.getContext('2d')
    if (!g) throw new Error('2D canvas unavailable in worker')
    const image = new ImageData(raster.width, raster.height)
    for (const hour of req.order) {
      if (latest !== req.id) return // superseded by a newer request
      const fields = req.series.map((s) => toGrid(req.grid, req.nodes, s[hour]))
      renderFrame(raster, req.grid, fields, req.mode, req.loadLb, image.data)
      g.putImageData(image, 0, 0)
      const bitmap = canvas.transferToImageBitmap()
      ctx.postMessage({ id: req.id, type: 'frame', hour, bitmap } satisfies RenderMessage, [bitmap])
      // Yield so a newer request (e.g. mode switch) can preempt this one.
      await new Promise((r) => setTimeout(r, 0))
    }
    ctx.postMessage({ id: req.id, type: 'done' } satisfies RenderMessage)
  } catch (err) {
    ctx.postMessage({ id: req.id, type: 'error', message: String(err) } satisfies RenderMessage)
  }
}
