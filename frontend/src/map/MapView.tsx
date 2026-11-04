import 'maplibre-gl/dist/maplibre-gl.css'
import {
  setWorkerUrl,
  type ImageSource,
  type MapLayerMouseEvent,
  type Map as MlMap,
} from 'maplibre-gl'
// MapLibre 6 resolves its worker as a sibling file of its own module at runtime, which bundlers
// don't emit. Import it as an asset and point MapLibre at it explicitly (works in dev and build).
import maplibreWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'
import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import MapGL, {
  Layer,
  NavigationControl,
  Popup,
  ScaleControl,
  Source,
  type MapRef,
} from 'react-map-gl/maplibre'
import type { PlanResponse, Route } from '../api/types'
import type { FrameImage } from '../hooks/useHeatmapFrames'
import { bounds, type Position } from '../lib/geo'
import { CheckpointPopup } from '../components/CheckpointPopup'
import { checkpointsFC, stopsFC, endpointsFC, riskSegmentsFC, routesFC, trucksFC } from './geojson'
import * as L from './layers'

setWorkerUrl(maplibreWorkerUrl)

const STYLE_URL = 'https://tiles.openfreemap.org/styles/positron'
const INITIAL_VIEW = { longitude: -98.5, latitude: 39.5, zoom: 3.6 }
const HEAT_SOURCE = 'heat'
const HEAT_LAYER = 'heat-layer'
const NO_ROUTES: Route[] = []
// Stable references: react-map-gl re-applies props whose identity changes on every render.
const MAP_STYLE_CSS = { position: 'absolute', inset: 0 } as const
const INTERACTIVE_LAYERS = [L.CHECKPOINTS, L.ROUTES_HIT]
const ATTRIBUTION = { compact: true, customAttribution: 'Weather: Open-Meteo · Routing: OSRM' }

interface Props {
  plan: PlanResponse | null
  selectedId: string | null
  onSelectRoute: (id: string) => void
  heatFrame: FrameImage | null
  heatCorners: [number, number][] | null
  heatOpacity: number
  heatVisible: boolean
  truckTime: number | null
  /** Pixels covered by overlays (sidebar / bottom panel) so fitBounds keeps routes visible. */
  padding: { top: number; bottom: number; left: number; right: number }
}

type Hover = { routeIdx: number; cpIdx: number; lon: number; lat: number }

function MapViewImpl({
  plan,
  selectedId,
  onSelectRoute,
  heatFrame,
  heatCorners,
  heatOpacity,
  heatVisible,
  truckTime,
  padding,
}: Props) {
  const mapRef = useRef<MapRef>(null)
  const [styleReady, setStyleReady] = useState(false)
  const [hover, setHover] = useState<Hover | null>(null)
  const hoverIdRef = useRef<number | null>(null)

  const routes = plan?.routes ?? NO_ROUTES
  const selected = routes.find((r) => r.id === selectedId)

  // Memoised GeoJSON: only rebuilt (and re-uploaded to the GPU) when plan/selection change.
  const routesData = useMemo(() => routesFC(routes, selectedId), [routes, selectedId])
  const segmentsData = useMemo(() => riskSegmentsFC(selected), [selected])
  const stopsData = useMemo(() => stopsFC(selected), [selected])
  const checkpointsData = useMemo(() => checkpointsFC(routes, selectedId), [routes, selectedId])
  const endpointsData = useMemo(
    () => (plan ? endpointsFC(plan.request.origin, plan.request.destination) : null),
    [plan],
  )
  const trucksData = useMemo(
    () => (truckTime === null ? null : trucksFC(routes, truckTime, selectedId)),
    [routes, truckTime, selectedId],
  )

  // Fit the map to a new plan.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !plan) return
    const pts = plan.routes.flatMap((r) => r.geometry as Position[])
    if (pts.length) map.fitBounds(bounds(pts), { padding, duration: 900, maxZoom: 11 })
    // eslint-disable-next-line react-hooks/exhaustive-deps -- refit only when the plan changes
  }, [plan])

  // ---- Heatmap: imperative image source so slider moves are a single texture swap ----------
  const heatAdded = useRef(false)
  useEffect(() => {
    const map = mapRef.current?.getMap() as MlMap | undefined
    if (!map || !styleReady) return
    if (!heatCorners || !heatFrame) {
      if (map.getLayer(HEAT_LAYER)) map.setLayoutProperty(HEAT_LAYER, 'visibility', 'none')
      return
    }
    const coords = heatCorners as [
      [number, number],
      [number, number],
      [number, number],
      [number, number],
    ]
    const src = map.getSource(HEAT_SOURCE) as ImageSource | undefined
    if (!src) {
      map.addSource(HEAT_SOURCE, { type: 'image', coordinates: coords } as never)
      ;(map.getSource(HEAT_SOURCE) as ImageSource).updateImage({ image: heatFrame } as never)
      map.addLayer(
        {
          id: HEAT_LAYER,
          type: 'raster',
          source: HEAT_SOURCE,
          paint: {
            'raster-opacity': heatOpacity,
            'raster-fade-duration': 0,
            'raster-resampling': 'linear',
          },
        },
        map.getLayer(L.ROUTES_HIT) ? L.ROUTES_HIT : undefined,
      )
      heatAdded.current = true
    } else {
      src.updateImage({ image: heatFrame, coordinates: coords } as never)
    }
    map.setLayoutProperty(HEAT_LAYER, 'visibility', heatVisible ? 'visible' : 'none')
  }, [heatFrame, heatCorners, heatVisible, styleReady, heatOpacity])

  useEffect(() => {
    const map = mapRef.current?.getMap() as MlMap | undefined
    if (map?.getLayer(HEAT_LAYER)) map.setPaintProperty(HEAT_LAYER, 'raster-opacity', heatOpacity)
  }, [heatOpacity])

  // ---- Interaction ------------------------------------------------------------------------
  const setHoverState = useCallback((id: number | null) => {
    const map = mapRef.current?.getMap()
    if (!map) return
    if (hoverIdRef.current !== null)
      map.setFeatureState({ source: 'checkpoints', id: hoverIdRef.current }, { hover: false })
    if (id !== null) map.setFeatureState({ source: 'checkpoints', id }, { hover: true })
    hoverIdRef.current = id
  }, [])

  const onMouseMove = useCallback(
    (e: MapLayerMouseEvent) => {
      const f = e.features?.find((x) => x.layer.id === L.CHECKPOINTS)
      const map = mapRef.current?.getMap()
      if (map) map.getCanvas().style.cursor = e.features?.length ? 'pointer' : ''
      if (!f) {
        if (hoverIdRef.current !== null) {
          setHoverState(null)
          setHover(null)
        }
        return
      }
      const id = f.id as number
      if (id === hoverIdRef.current) return
      setHoverState(id)
      const routeIdx = routes.findIndex((r) => r.id === f.properties.routeId)
      const [lon, lat] = (f.geometry as GeoJSON.Point).coordinates
      setHover({ routeIdx, cpIdx: f.properties.index as number, lon, lat })
    },
    [routes, setHoverState],
  )

  const onMouseLeave = useCallback(() => {
    setHoverState(null)
    setHover(null)
  }, [setHoverState])

  const onLoad = useCallback((e: { target: MlMap }) => {
    setStyleReady(true)
    // Dev-only handle for debugging and performance measurement.
    if (import.meta.env.DEV) (window as unknown as { __map?: unknown }).__map = e.target
  }, [])

  const onClick = useCallback(
    (e: MapLayerMouseEvent) => {
      const f = e.features?.[0]
      const id = (f?.properties?.routeId ?? f?.properties?.id) as string | undefined
      if (id) onSelectRoute(id)
    },
    [onSelectRoute],
  )

  const hoveredRoute = hover ? routes[hover.routeIdx] : undefined
  const hoveredCp = hoveredRoute?.checkpoints[hover!.cpIdx]

  return (
    <MapGL
      ref={mapRef}
      initialViewState={INITIAL_VIEW}
      mapStyle={STYLE_URL}
      style={MAP_STYLE_CSS}
      interactiveLayerIds={INTERACTIVE_LAYERS}
      onMouseMove={onMouseMove}
      onMouseLeave={onMouseLeave}
      onClick={onClick}
      onLoad={onLoad}
      dragRotate={false}
      pitchWithRotate={false}
      attributionControl={ATTRIBUTION}
      reuseMaps
    >
      <NavigationControl position="top-right" showCompass={false} />
      <ScaleControl position="bottom-right" unit="imperial" />

      <Source id="routes" type="geojson" data={routesData}>
        <Layer {...L.routesHit} />
        <Layer {...L.routesCasing} />
        <Layer {...L.routesLine} />
      </Source>
      <Source id="segments" type="geojson" data={segmentsData}>
        <Layer {...L.riskSegments} />
      </Source>
      <Source id="routes-labels" type="geojson" data={routesData}>
        <Layer {...L.routeLabels} />
      </Source>
      <Source id="checkpoints" type="geojson" data={checkpointsData}>
        <Layer {...L.checkpoints} />
      </Source>
      {endpointsData && (
        <Source id="endpoints" type="geojson" data={endpointsData}>
          <Layer {...L.endpoints} />
          <Layer {...L.endpointLabels} />
        </Source>
      )}
      <Source id="rest-stops" type="geojson" data={stopsData}>
        <Layer {...L.restStops} />
        <Layer {...L.restStopLabels} />
      </Source>
      {trucksData && (
        <Source id="trucks" type="geojson" data={trucksData}>
          <Layer {...L.trucks} />
          <Layer {...L.truckLabels} />
        </Source>
      )}

      {hover && hoveredRoute && hoveredCp && (
        <Popup
          longitude={hover.lon}
          latitude={hover.lat}
          closeButton={false}
          closeOnClick={false}
          offset={12}
          maxWidth="300px"
          className="cp-popup"
        >
          <CheckpointPopup route={hoveredRoute} checkpoint={hoveredCp} />
        </Popup>
      )}
    </MapGL>
  )
}

export const MapView = memo(MapViewImpl)
