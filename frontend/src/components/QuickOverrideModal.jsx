import { useState, useEffect, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { X, Plus, Search, Loader2, AlertCircle, CheckCircle2, Trash2, Calendar, Edit2, Info } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';

/**
 * QuickOverrideModal
 * - Brukes av "Avvik"-knapp på kundekort.
 * - Lar bruker registrere avvik (overstyringer) for én kunde på én bestemt dato,
 *   for ett eller flere produkter samtidig.
 * - Sender POST /api/v1/overrides/bulk
 *
 * Props:
 *   customer:  { id, name }
 *   onClose:   () => void
 *   onSaved?:  (created) => void
 */
export default function QuickOverrideModal({ customer, onClose, onSaved }) {
  const { authFetch } = useAuth();

  const tomorrow = useMemo(() => {
    const d = new Date();
    d.setDate(d.getDate() + 1);
    return d.toISOString().slice(0, 10);
  }, []);

  const [overrideDate, setOverrideDate] = useState(tomorrow);
  const [productSearch, setProductSearch] = useState('');
  const [allProducts, setAllProducts] = useState([]);
  const [loadingProducts, setLoadingProducts] = useState(true);
  const [lines, setLines] = useState([]); // [{product_id, name, quantity, reason}]
  const [globalReason, setGlobalReason] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [savedCount, setSavedCount] = useState(0);
  const [showPicker, setShowPicker] = useState(false);
  const [existingOrder, setExistingOrder] = useState(null);
  const [loadingOrder, setLoadingOrder] = useState(false);
  const [orderLoaded, setOrderLoaded] = useState(false); // tracker om vi allerede har for-fyllt fra ordre

  // Hent produkter
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await authFetch('/api/v1/products?page_size=2000&is_active=true');
        if (!res.ok) throw new Error('Kunne ikke hente produkter');
        const data = await res.json();
        if (!cancelled) setAllProducts(data.items || []);
      } catch (e) {
        if (!cancelled) setError(e.message);
      } finally {
        if (!cancelled) setLoadingProducts(false);
      }
    })();
    return () => { cancelled = true; };
  }, [authFetch]);

  const productById = useMemo(() => {
    const m = new Map();
    for (const p of allProducts) m.set(p.id, p);
    return m;
  }, [allProducts]);

  // Slå opp eksisterende ordre når kunde+dato endres
  useEffect(() => {
    if (!customer?.id || !overrideDate) {
      setExistingOrder(null);
      return;
    }
    let cancelled = false;
    setLoadingOrder(true);
    setOrderLoaded(false);
    (async () => {
      try {
        const res = await authFetch(
          `/api/v1/orders?customer_id=${customer.id}&from_date=${overrideDate}&to_date=${overrideDate}&page_size=5`
        );
        if (!res.ok) return;
        const data = await res.json();
        if (cancelled) return;
        const order = (data.items || [])[0] || null;
        setExistingOrder(order);
      } catch {
        /* ignore */
      } finally {
        if (!cancelled) setLoadingOrder(false);
      }
    })();
    return () => { cancelled = true; };
  }, [customer?.id, overrideDate, authFetch]);

  // Forhåndsutfyll linjer fra eksisterende ordre (kun hvis brukeren ikke har lagt til noe selv)
  const loadLinesFromOrder = () => {
    if (!existingOrder?.lines) return;
    const fromOrder = existingOrder.lines.map((l) => ({
      product_id: l.product_id,
      name: l.product_name || productById.get(l.product_id)?.name || `Produkt ${l.product_id}`,
      sku: l.product_sku || productById.get(l.product_id)?.sku || '',
      quantity: l.quantity,
      reason: '',
    }));
    setLines(fromOrder);
    setOrderLoaded(true);
  };

  const pickerResults = useMemo(() => {
    const term = productSearch.trim().toLowerCase();
    const inUse = new Set(lines.map((l) => l.product_id));
    return allProducts
      .filter((p) => !inUse.has(p.id))
      .filter((p) => !term || p.name.toLowerCase().includes(term) || (p.sku || '').toLowerCase().includes(term))
      .slice(0, 30);
  }, [allProducts, productSearch, lines]);

  const addLine = (product) => {
    setLines((prev) => [
      ...prev,
      { product_id: product.id, name: product.name, sku: product.sku, quantity: 1, reason: '' },
    ]);
    setProductSearch('');
    setShowPicker(false);
  };

  const updateLine = (productId, patch) => {
    setLines((prev) => prev.map((l) => (l.product_id === productId ? { ...l, ...patch } : l)));
  };

  const removeLine = (productId) => {
    setLines((prev) => prev.filter((l) => l.product_id !== productId));
  };

  const submit = async () => {
    if (!customer?.id || lines.length === 0) return;
    setSaving(true);
    setError(null);
    try {
      const payload = {
        customer_id: customer.id,
        override_date: overrideDate,
        lines: lines.map((l) => ({
          product_id: l.product_id,
          quantity: Math.max(0, parseInt(l.quantity, 10) || 0),
          reason: (l.reason || globalReason || '').trim() || null,
        })),
      };
      const res = await authFetch('/api/v1/overrides/bulk', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(`Lagring feilet: ${txt || res.status}`);
      }
      const created = await res.json();
      setSavedCount(created.length);
      onSaved && onSaved(created);
      // Auto-close kort etter suksess
      setTimeout(() => onClose(), 1200);
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-2xl max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b">
          <div>
            <h3 className="font-semibold text-lg">Avvik / Overstyring</h3>
            <p className="text-sm text-gray-500">{customer?.name}</p>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-gray-100 rounded">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {savedCount > 0 ? (
            <div className="flex items-center gap-3 p-4 bg-green-50 border border-green-200 rounded-lg text-green-700">
              <CheckCircle2 className="w-5 h-5" />
              <span>Lagret {savedCount} avvik for {overrideDate}.</span>
            </div>
          ) : (
            <>
              {/* Dato */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Dato</label>
                <div className="relative">
                  <Calendar className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
                  <input
                    type="date"
                    value={overrideDate}
                    onChange={(e) => setOverrideDate(e.target.value)}
                    className="w-full pl-9 pr-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-amber-500 focus:border-transparent"
                  />
                </div>
                <p className="text-xs text-gray-500 mt-1">
                  Antall under erstatter fastbestilling for denne datoen. Sett 0 for å «droppe» et produkt.
                </p>
              </div>

              {/* Eksisterende ordre for valgt dato */}
              {loadingOrder ? (
                <div className="flex items-center gap-2 p-3 bg-gray-50 border border-gray-200 rounded-lg text-sm text-gray-500">
                  <Loader2 className="w-4 h-4 animate-spin" /> Sjekker om det finnes ordre for denne datoen...
                </div>
              ) : existingOrder ? (
                <div className="p-3 bg-blue-50 border border-blue-200 rounded-lg text-sm text-blue-900 space-y-2">
                  <div className="flex items-start gap-2">
                    <Info className="w-4 h-4 mt-0.5 flex-shrink-0" />
                    <div className="flex-1">
                      <div className="font-medium">
                        Ordre #{existingOrder.id} finnes for {overrideDate}
                      </div>
                      <div className="text-xs text-blue-700 mt-0.5">
                        {existingOrder.lines?.length || 0} linjer · status: {existingOrder.status}
                        {existingOrder.is_locked ? ' · LÅST (etter cut-off)' : ''}
                      </div>
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2 pt-1">
                    {!orderLoaded && lines.length === 0 && (
                      <button
                        type="button"
                        onClick={loadLinesFromOrder}
                        className="text-xs px-3 py-1.5 bg-white border border-blue-300 rounded text-blue-700 hover:bg-blue-100 font-medium"
                      >
                        Last inn ordrelinjer som utgangspunkt
                      </button>
                    )}
                    <Link
                      to={`/bestillinger?edit=${existingOrder.id}`}
                      onClick={onClose}
                      className="text-xs px-3 py-1.5 bg-white border border-blue-300 rounded text-blue-700 hover:bg-blue-100 font-medium inline-flex items-center gap-1"
                    >
                      <Edit2 className="w-3 h-3" /> Åpne ordre i Bestillinger
                    </Link>
                  </div>
                  <p className="text-[11px] text-blue-700 leading-snug">
                    Tips: Avvik registrert her overstyrer fastbestillingen ved regenerering. For å endre den faktiske ordren nå,
                    bruk «Rediger ordre»-knappen.
                  </p>
                </div>
              ) : (
                <div className="p-2 text-xs text-gray-500">
                  Ingen ordre funnet for denne datoen — avviket vil gjelde når ordren genereres.
                </div>
              )}

              {/* Globalt grunnlag */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Felles årsak (valgfritt)</label>
                <input
                  type="text"
                  placeholder="F.eks. «Helligdag», «Kunde ringte», «Stengt»..."
                  value={globalReason}
                  onChange={(e) => setGlobalReason(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-amber-500 focus:border-transparent"
                />
              </div>

              {/* Produkter */}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <label className="block text-sm font-medium text-gray-700">Produkter</label>
                  <button
                    type="button"
                    onClick={() => setShowPicker((s) => !s)}
                    className="text-sm text-amber-600 hover:text-amber-700 flex items-center gap-1 font-medium"
                  >
                    <Plus className="w-4 h-4" /> Legg til produkt
                  </button>
                </div>

                {/* Picker */}
                {showPicker && (
                  <div className="border border-gray-200 rounded-lg mb-3 bg-gray-50">
                    <div className="p-2 border-b border-gray-200 bg-white rounded-t-lg">
                      <div className="relative">
                        <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                        <input
                          autoFocus
                          type="text"
                          placeholder="Søk produkt..."
                          value={productSearch}
                          onChange={(e) => setProductSearch(e.target.value)}
                          className="w-full pl-9 pr-3 py-1.5 text-sm border border-gray-200 rounded"
                        />
                      </div>
                    </div>
                    <div className="max-h-48 overflow-y-auto">
                      {loadingProducts ? (
                        <div className="p-3 text-center text-sm text-gray-500">
                          <Loader2 className="w-4 h-4 inline animate-spin" /> Laster...
                        </div>
                      ) : pickerResults.length === 0 ? (
                        <div className="p-3 text-center text-sm text-gray-500">Ingen treff.</div>
                      ) : (
                        pickerResults.map((p) => (
                          <button
                            key={p.id}
                            type="button"
                            onClick={() => addLine(p)}
                            className="w-full text-left px-3 py-2 hover:bg-amber-50 border-b border-gray-100 text-sm flex items-center justify-between"
                          >
                            <span>
                              <span className="font-medium text-gray-900">{p.name}</span>
                              <span className="text-xs text-gray-400 ml-2">{p.sku}</span>
                            </span>
                            <Plus className="w-4 h-4 text-amber-600" />
                          </button>
                        ))
                      )}
                    </div>
                  </div>
                )}

                {/* Linjer */}
                {lines.length === 0 ? (
                  <div className="text-center py-8 text-gray-400 text-sm border border-dashed border-gray-200 rounded-lg">
                    Ingen produkter lagt til ennå.
                  </div>
                ) : (
                  <div className="space-y-2">
                    {lines.map((line) => {
                      const p = productById.get(line.product_id);
                      return (
                        <div key={line.product_id} className="flex items-center gap-2 p-2 border border-gray-200 rounded-lg">
                          <div className="flex-1 min-w-0">
                            <div className="font-medium text-sm text-gray-900 truncate">{line.name}</div>
                            <div className="text-xs text-gray-400 truncate">
                              {line.sku} {p?.unit ? `· ${p.unit}` : ''}
                            </div>
                          </div>
                          <input
                            type="number"
                            min="0"
                            inputMode="numeric"
                            value={line.quantity}
                            onChange={(e) => updateLine(line.product_id, { quantity: e.target.value })}
                            className="w-20 px-2 py-1.5 text-center border border-gray-300 rounded focus:ring-2 focus:ring-amber-500 focus:border-transparent"
                          />
                          <input
                            type="text"
                            placeholder="Årsak..."
                            value={line.reason}
                            onChange={(e) => updateLine(line.product_id, { reason: e.target.value })}
                            className="flex-1 px-2 py-1.5 text-sm border border-gray-200 rounded focus:ring-2 focus:ring-amber-500 focus:border-transparent"
                          />
                          <button
                            type="button"
                            onClick={() => removeLine(line.product_id)}
                            className="p-1.5 text-gray-300 hover:text-red-600"
                            title="Fjern"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>

              {error && (
                <div className="flex items-start gap-2 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
                  <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
                  <span>{error}</span>
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        {savedCount === 0 && (
          <div className="flex items-center justify-end gap-2 p-4 border-t bg-gray-50 rounded-b-xl">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg"
              disabled={saving}
            >
              Avbryt
            </button>
            <button
              type="button"
              onClick={submit}
              disabled={saving || lines.length === 0}
              className="btn-primary flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {saving ? (
                <><Loader2 className="w-4 h-4 animate-spin" /> Lagrer...</>
              ) : (
                <>Lagre {lines.length > 0 ? `(${lines.length})` : ''}</>
              )}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
