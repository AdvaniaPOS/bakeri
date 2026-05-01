import { useEffect, useRef, useState } from 'react';
import { Search, X } from 'lucide-react';

/**
 * Felles søke-input.
 *
 * Egenskaper:
 *  - value/onChange er rent UI (rå inputtekst).
 *  - onSearch(term) kalles bare når term enten er tom (clear) eller
 *    har minst `minChars` tegn — debouncet med `debounceMs`.
 *  - Enter sender umiddelbart (overstyrer debounce + minChars-grense
 *    hvis brukeren insisterer).
 *  - Esc tømmer feltet.
 *  - X-knapp tømmer.
 *
 * Tips for god UX (innebygget):
 *  - Trim whitespace før man treffer API.
 *  - Hint vises under feltet når input er kort men ikke tomt.
 *  - aria-label for skjermleser.
 */
export default function SearchInput({
  value,
  onChange,
  onSearch,
  placeholder = 'Søk...',
  minChars = 3,
  debounceMs = 350,
  className = '',
  autoFocus = false,
  ariaLabel,
}) {
  const [touched, setTouched] = useState(false);
  const debounceRef = useRef(null);
  const lastSentRef = useRef(null); // null = ikke sendt enda; '' = sendt tom
  const onSearchRef = useRef(onSearch);
  useEffect(() => { onSearchRef.current = onSearch; }, [onSearch]);

  // Debounced trigger - bevisst IKKE avhengig av onSearch (bruker ref)
  // for aa unngaa loop naar foreldren sender ny callback hver render.
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    const trimmed = (value || '').trim();
    debounceRef.current = setTimeout(() => {
      if (trimmed.length === 0 || trimmed.length >= minChars) {
        if (trimmed !== lastSentRef.current) {
          lastSentRef.current = trimmed;
          onSearchRef.current?.(trimmed);
        }
      }
    }, debounceMs);
    return () => debounceRef.current && clearTimeout(debounceRef.current);
  }, [value, minChars, debounceMs]);

  const trimmed = (value || '').trim();
  const showHint = touched && trimmed.length > 0 && trimmed.length < minChars;

  const triggerNow = (term) => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    lastSentRef.current = term;
    onSearchRef.current?.(term);
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      triggerNow(trimmed); // Tving søk uansett lengde
    } else if (e.key === 'Escape') {
      e.preventDefault();
      onChange?.('');
      triggerNow('');
    }
  };

  const handleClear = () => {
    onChange?.('');
    triggerNow('');
  };

  return (
    <div className={`relative ${className}`}>
      <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
      <input
        type="search"
        autoComplete="off"
        spellCheck="false"
        autoFocus={autoFocus}
        aria-label={ariaLabel || placeholder}
        placeholder={placeholder}
        value={value || ''}
        onChange={(e) => { onChange?.(e.target.value); setTouched(true); }}
        onKeyDown={handleKeyDown}
        className="input pl-8 pr-8"
      />
      {value && (
        <button
          type="button"
          onClick={handleClear}
          aria-label="Tøm søk"
          className="absolute right-2 top-1/2 -translate-y-1/2 p-0.5 text-gray-400 hover:text-gray-700"
        >
          <X className="w-4 h-4" />
        </button>
      )}
      {showHint && (
        <div className="absolute left-0 right-0 top-full mt-1 text-xs text-gray-500 pl-1">
          Skriv minst {minChars} tegn (eller trykk Enter)
        </div>
      )}
    </div>
  );
}
