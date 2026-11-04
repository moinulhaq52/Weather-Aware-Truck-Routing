/** MapLibre layer styles, kept separate from components so the map code reads as structure. */
import type { ExpressionSpecification } from 'maplibre-gl'
import type { LayerProps } from 'react-map-gl/maplibre'

export const ROUTES_HIT = 'routes-hit'
export const CHECKPOINTS = 'checkpoints'

const INK = '#0f2d3a'
const MUTED = '#7c8ea3'
const FONT = ['Noto Sans Bold']

const isSelected: ExpressionSpecification = ['==', ['get', 'selected'], true]
const isHover: ExpressionSpecification = ['boolean', ['feature-state', 'hover'], false]

/** Invisible wide line so routes are easy to click. */
export const routesHit: LayerProps = {
  id: ROUTES_HIT,
  type: 'line',
  paint: { 'line-color': '#000', 'line-opacity': 0, 'line-width': 18 },
  layout: { 'line-cap': 'round', 'line-join': 'round' },
}

export const routesCasing: LayerProps = {
  id: 'routes-casing',
  type: 'line',
  paint: {
    'line-color': '#ffffff',
    'line-width': [
      'interpolate',
      ['linear'],
      ['zoom'],
      4,
      ['case', isSelected, 8, 5],
      10,
      ['case', isSelected, 14, 8],
    ],
    'line-opacity': 0.95,
  },
  layout: { 'line-cap': 'round', 'line-join': 'round' },
}

export const routesLine: LayerProps = {
  id: 'routes-line',
  type: 'line',
  paint: {
    'line-color': ['case', isSelected, INK, MUTED],
    'line-width': [
      'interpolate',
      ['linear'],
      ['zoom'],
      4,
      ['case', isSelected, 6, 3],
      10,
      ['case', isSelected, 11, 5],
    ],
    'line-opacity': ['case', isSelected, 1, 0.85],
  },
  layout: { 'line-cap': 'round', 'line-join': 'round' },
}

/** Selected route coloured by checkpoint risk, inset inside the dark outline. */
export const riskSegments: LayerProps = {
  id: 'risk-segments',
  type: 'line',
  paint: {
    'line-color': ['get', 'color'],
    'line-width': ['interpolate', ['linear'], ['zoom'], 4, 3, 10, 6.5],
  },
  layout: { 'line-cap': 'round', 'line-join': 'round' },
}

export const routeLabels: LayerProps = {
  id: 'route-labels',
  type: 'symbol',
  layout: {
    'symbol-placement': 'line-center',
    'text-field': ['get', 'name'],
    'text-font': FONT,
    'text-size': 12,
    'text-offset': [0, -1.1],
    'text-allow-overlap': false,
  },
  paint: {
    'text-color': ['case', isSelected, INK, '#4b5d70'],
    'text-halo-color': '#ffffff',
    'text-halo-width': 2,
  },
}

export const checkpoints: LayerProps = {
  id: CHECKPOINTS,
  type: 'circle',
  paint: {
    'circle-color': ['get', 'color'],
    // `zoom` must be the top-level input, so hover/selection cases live inside each zoom stop.
    'circle-radius': [
      'interpolate',
      ['linear'],
      ['zoom'],
      4,
      ['case', isHover, 8, isSelected, 4.5, 3],
      10,
      ['case', isHover, 11, isSelected, 7, 4.5],
    ],
    'circle-stroke-color': ['case', isSelected, '#ffffff', 'rgba(255,255,255,0.8)'],
    'circle-stroke-width': ['case', isSelected, 1.75, 1],
    'circle-opacity': ['case', isSelected, 1, 0.7],
    'circle-stroke-opacity': ['case', isSelected, 1, 0.7],
  },
}

export const endpoints: LayerProps = {
  id: 'endpoints',
  type: 'circle',
  paint: {
    'circle-radius': 7.5,
    'circle-color': ['match', ['get', 'role'], 'origin', '#ffffff', INK],
    'circle-stroke-color': INK,
    'circle-stroke-width': 3,
  },
}

export const endpointLabels: LayerProps = {
  id: 'endpoint-labels',
  type: 'symbol',
  layout: {
    'text-field': ['get', 'label'],
    'text-font': FONT,
    'text-size': 13,
    'text-anchor': 'top',
    'text-offset': [0, 0.9],
  },
  paint: { 'text-color': INK, 'text-halo-color': '#ffffff', 'text-halo-width': 2 },
}

/** Extra E1: truck positions at the forecast slider's time. */
export const trucks: LayerProps = {
  id: 'trucks',
  type: 'circle',
  paint: {
    'circle-radius': ['case', isSelected, 11, 8],
    'circle-color': INK,
    'circle-stroke-color': [
      'match',
      ['get', 'level'],
      0,
      '#2f9e5b',
      1,
      '#e8b10b',
      2,
      '#f07316',
      3,
      '#d62828',
      4,
      '#7b2cbf',
      '#8a94a6',
    ],
    'circle-stroke-width': 3.5,
    'circle-opacity': ['case', ['get', 'arrived'], 0.45, 1],
    'circle-stroke-opacity': ['case', ['get', 'arrived'], 0.45, 1],
  },
}

export const truckLabels: LayerProps = {
  id: 'truck-labels',
  type: 'symbol',
  layout: {
    'text-field': ['slice', ['get', 'name'], 6],
    'text-font': FONT,
    'text-size': 11,
    'text-allow-overlap': true,
    'text-ignore-placement': true,
  },
  paint: { 'text-color': '#ffffff' },
}

/** Extra E5: Hours-of-Service stops on the selected route. */
export const restStops: LayerProps = {
  id: 'rest-stops',
  type: 'circle',
  paint: {
    'circle-radius': 10,
    'circle-color': '#ffffff',
    'circle-stroke-color': INK,
    'circle-stroke-width': 2.5,
  },
}

export const restStopLabels: LayerProps = {
  id: 'rest-stop-labels',
  type: 'symbol',
  layout: {
    'text-field': ['get', 'label'],
    'text-font': FONT,
    'text-size': 9.5,
    'text-allow-overlap': true,
    'text-ignore-placement': true,
  },
  paint: { 'text-color': INK },
}
