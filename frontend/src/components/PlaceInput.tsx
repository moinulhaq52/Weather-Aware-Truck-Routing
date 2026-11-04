import { useQuery } from '@tanstack/react-query'
import { useEffect, useId, useRef, useState } from 'react'
import { geocode } from '../api/client'
import type { Place } from '../api/types'

interface Props {
  label: string
  value: Place | null
  onChange: (place: Place | null) => void
  placeholder?: string
  error?: string
}

const MIN_CHARS = 3
const DEBOUNCE_MS = 300

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

/** Accessible place autocomplete (WAI-ARIA combobox pattern) backed by /api/geocode. */
export function PlaceInput({ label, value, onChange, placeholder, error }: Props) {
  const id = useId()
  const [text, setText] = useState(value?.label ?? '')
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const blurTimer = useRef<ReturnType<typeof setTimeout>>(undefined)

  // Keep the text in sync when the value changes from outside (swap, presets): React's
  // "adjust state when a prop changes" pattern, which avoids an extra effect-driven render.
  const [prevValue, setPrevValue] = useState(value)
  if (value !== prevValue) {
    setPrevValue(value)
    setText(value?.label ?? '')
  }

  const q = useDebounced(text.trim(), DEBOUNCE_MS)
  const enabled = open && q.length >= MIN_CHARS && q !== value?.label
  const { data, isFetching, isError } = useQuery({
    queryKey: ['geocode', q.toLowerCase()],
    queryFn: ({ signal }) => geocode(q, signal),
    enabled,
    staleTime: 10 * 60_000,
    retry: false,
  })
  const results = enabled ? (data ?? []) : []

  const choose = (p: Place) => {
    onChange(p)
    setText(p.label)
    setOpen(false)
  }

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!results.length) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setOpen(true)
      setActive((a) => (a + 1) % results.length)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((a) => (a - 1 + results.length) % results.length)
    } else if (e.key === 'Enter' && open) {
      e.preventDefault()
      choose(results[active])
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  const listId = `${id}-list`
  const showList =
    open && enabled && (results.length > 0 || (!isFetching && data !== undefined) || isError)

  return (
    <div className="field place-field">
      <label htmlFor={id}>{label}</label>
      <div className="place-input-wrap">
        <input
          id={id}
          type="text"
          role="combobox"
          aria-expanded={showList}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={showList && results[active] ? `${listId}-${active}` : undefined}
          aria-invalid={Boolean(error)}
          autoComplete="off"
          placeholder={placeholder}
          value={text}
          onChange={(e) => {
            setText(e.target.value)
            setActive(0)
            setOpen(true)
            if (value) onChange(null) // typed over a chosen place: it's no longer selected
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => {
            blurTimer.current = setTimeout(() => setOpen(false), 150)
          }}
          onKeyDown={onKeyDown}
        />
        {isFetching && <span className="spinner small" aria-hidden />}
      </div>
      {showList && (
        <ul
          id={listId}
          role="listbox"
          className="place-list"
          onMouseDown={(e) => e.preventDefault()}
        >
          {isError && <li className="place-empty">Place search is unavailable right now.</li>}
          {!isError && results.length === 0 && <li className="place-empty">No matching places.</li>}
          {results.map((p, i) => (
            <li
              key={`${p.label}-${p.lat}-${p.lon}`}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === active}
              className={i === active ? 'active' : undefined}
              onMouseEnter={() => setActive(i)}
              onClick={() => choose(p)}
            >
              {p.label}
            </li>
          ))}
        </ul>
      )}
      {error && <div className="field-error">{error}</div>}
    </div>
  )
}
