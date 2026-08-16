import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { stocks } from '../../api/endpoints';

/**
 * Ticker search with a debounced remote lookup.
 *
 * Debounced at 300ms: every keystroke is an upstream call otherwise, and
 * Yahoo rate-limits aggressively. Keyboard navigation is wired up because a
 * search box that only works with a mouse is a broken search box.
 */
export default function SymbolSearch() {
  const [term, setTerm] = useState('');
  const [debounced, setDebounced] = useState('');
  const [open, setOpen] = useState(false);
  const [highlighted, setHighlighted] = useState(0);

  const navigate = useNavigate();
  const containerRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(term.trim()), 300);
    return () => clearTimeout(timer);
  }, [term]);

  const { data, isFetching } = useQuery({
    queryKey: ['search', debounced],
    queryFn: () => stocks.search(debounced, 8),
    enabled: debounced.length >= 2,
    staleTime: 5 * 60 * 1000,
    retry: false,
  });

  const results = useMemo(() => data?.results ?? [], [data]);

  // Close on an outside click.
  useEffect(() => {
    function onPointerDown(event) {
      if (!containerRef.current?.contains(event.target)) setOpen(false);
    }
    document.addEventListener('pointerdown', onPointerDown);
    return () => document.removeEventListener('pointerdown', onPointerDown);
  }, []);

  // Focus the box with "/", the convention in every developer tool.
  useEffect(() => {
    function onKeyDown(event) {
      if (event.key === '/' && document.activeElement !== inputRef.current) {
        event.preventDefault();
        inputRef.current?.focus();
      }
    }
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, []);

  function select(symbol) {
    if (!symbol) return;
    navigate(`/stock/${encodeURIComponent(symbol)}`);
    setTerm('');
    setOpen(false);
    inputRef.current?.blur();
  }

  function onKeyDown(event) {
    if (event.key === 'Escape') {
      setOpen(false);
      return;
    }
    if (event.key === 'Enter') {
      event.preventDefault();
      select(results[highlighted]?.symbol ?? term.trim().toUpperCase());
      return;
    }
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setHighlighted((index) => Math.min(index + 1, results.length - 1));
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      setHighlighted((index) => Math.max(index - 1, 0));
    }
  }

  return (
    <div className="symbol-search" ref={containerRef}>
      <label htmlFor="symbol-search-input" className="sr-only">
        Search for a ticker or company
      </label>
      <input
        id="symbol-search-input"
        ref={inputRef}
        type="search"
        className="search-input"
        placeholder="Search ticker or company    /"
        value={term}
        autoComplete="off"
        onChange={(event) => {
          setTerm(event.target.value);
          setHighlighted(0);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
        role="combobox"
        aria-expanded={open && results.length > 0}
        aria-controls="symbol-search-results"
        aria-autocomplete="list"
      />

      {open && debounced.length >= 2 && (
        <ul className="search-results" id="symbol-search-results" role="listbox">
          {isFetching && <li className="search-hint muted">Searching…</li>}

          {!isFetching && results.length === 0 && (
            <li className="search-hint muted">
              No matches. Press Enter to open “{term.trim().toUpperCase()}” anyway.
            </li>
          )}

          {results.map((result, index) => (
            <li key={result.symbol} role="option" aria-selected={index === highlighted}>
              <button
                type="button"
                className={`search-result ${index === highlighted ? 'search-result-active' : ''}`}
                onMouseEnter={() => setHighlighted(index)}
                onClick={() => select(result.symbol)}
              >
                <span className="numeric search-symbol">{result.symbol}</span>
                <span className="search-name">{result.name}</span>
                <span className="muted search-exchange">{result.exchange}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
