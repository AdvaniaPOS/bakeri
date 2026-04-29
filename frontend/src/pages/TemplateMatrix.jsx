import { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
  ArrowLeft, Save, Search, Plus, X, AlertCircle, CheckCircle2, Loader2, AlertTriangle,
} from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import QuickOverrideModal from '../components/QuickOverrideModal';

const DAYS = [
  { dow: 1, label: 'Man' },
  { dow: 2, label: 'Tir' },
  { dow: 3, label: 'Ons' },
  { dow: 4, label: 'Tor' },
  { dow: 5, label: 'Fre' },
  { dow: 6, label: 'Lør' },
  { dow: 7, label: 'Søn' },
];

/**
 * TemplateMatrix
 * - URL: /maler/kunde/:customerId
 * - Henter (eller oppretter) aktiv MasterTemplate for kunden.
 * - Viser matrise: rader = produkter, kolonner = ukedager, celler = antall.
 * - Inline edit + debounced autosave (800 ms) via PUT /templates/{id}/matrix.
 */
export default function TemplateMatrix() {
  const { customerId } = useParams();
  const { authFetch } = useAuth();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [customer, setCustomer] = useState(null);
  const [template, setTemplate] = useState(null);          // {id, name, ...}
  const [allProducts, setAllProducts] = useState([]);       // [{id, name, category, unit}]
  const [matrix, setMatrix] = useState({});                 // { [productId]: { [dow]: qty } }
  const [activeProductIds, setActiveProductIds] = useState([]); // visningsrekkefølge

  const [search, setSearch] = useState('');
  const [showProductPicker, setShowProductPicker] = useState(false);
  const [productPickerSearch, setProductPickerSearch] = useState('');

  const [saveState, setSaveState] = useState('idle'); // idle | dirty | saving | saved | error
  const saveTimerRef = useRef(null);
  const dirtyRef = useRef(false);
  const [showOverride, setShowOverride] = useState(false);
  const [affectedPrompt, setAffectedPrompt] = useState(null); // {draft_count, non_draft_count, locked_count}
  const [applying, setApplying] = useState(false);

  // -------------------------------------------------------------------------
  // Initial load
  // -------------------------------------------------------------------------
  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [custRes, prodRes, tplListRes] = await Promise.all([
          authFetch(`/api/v1/customers/${customerId}`),
          authFetch(`/api/v1/products?page_size=2000&is_active=true`),
          authFetch(`/api/v1/templates?customer_id=${customerId}&is_active=true`),
        ]);
        if (!custRes.ok) throw new Error('Kunne ikke hente kunde');
        if (!prodRes.ok) throw new Error('Kunne ikke hente produkter');
        if (!tplListRes.ok) throw new Error('Kunne ikke hente maler');

        const cust = await custRes.json();
        const prods = await prodRes.json();
        const tplList = await tplListRes.json();

        let tpl = Array.isArray(tplList) ? tplList[0] : null;

        // Hvis ingen aktiv mal: opprett en tom
        if (!tpl) {
          const createRes = await authFetch('/api/v1/templates', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              customer_id: Number(customerId),
              name: 'Standard Ukentlig Ordre',
              is_active: true,
              items: [],
            }),
          });
          if (!createRes.ok) throw new Error('Kunne ikke opprette mal');
          tpl = await createRes.json();
        }

        // Hent matrix
        const matrixRes = await authFetch(`/api/v1/templates/${tpl.id}/matrix`);
        if (!matrixRes.ok) throw new Error('Kunne ikke hente matrise');
        const matrixData = await matrixRes.json();

        if (cancelled) return;

        // matrix.matrix er { productId: { dayOfWeek: qty } } men nøkler kan være strings
        const normalized = {};
        const initialIds = [];
        for (const [pid, days] of Object.entries(matrixData.matrix || {})) {
          const idNum = Number(pid);
          normalized[idNum] = {};
          for (const [d, q] of Object.entries(days || {})) {
            normalized[idNum][Number(d)] = Number(q) || 0;
          }
          initialIds.push(idNum);
        }

        setCustomer(cust);
        setTemplate(tpl);
        setAllProducts(prods.items || []);
        setMatrix(normalized);
        setActiveProductIds(initialIds);
        setSaveState('idle');
      } catch (err) {
        if (!cancelled) setError(err.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, [customerId, authFetch]);

  // -------------------------------------------------------------------------
  // Lagring (debounced)
  // -------------------------------------------------------------------------
  const flushSave = useCallback(async () => {
    if (!template) return;
    if (!dirtyRef.current) return;
    dirtyRef.current = false;
    setSaveState('saving');
    try {
      const payload = {};
      for (const [pid, days] of Object.entries(matrix)) {
        const dayMap = {};
        for (const [d, q] of Object.entries(days || {})) {
          const qty = Number(q) || 0;
          if (qty > 0) dayMap[d] = qty;
        }
        payload[pid] = dayMap;
      }
      const res = await authFetch(`/api/v1/templates/${template.id}/matrix`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error('Lagring feilet');
      setSaveState('saved');
      setTimeout(() => {
        setSaveState((s) => (s === 'saved' ? 'idle' : s));
      }, 1500);

      // Sjekk om det finnes fremtidige ordrer som kan påvirkes.
      try {
        const countRes = await authFetch(`/api/v1/templates/${template.id}/affected-orders`);
        if (countRes.ok) {
          const counts = await countRes.json();
          if ((counts.draft_count || 0) + (counts.non_draft_count || 0) > 0) {
            setAffectedPrompt(counts);
          }
        }
      } catch (_) {
        // ignorer
      }
    } catch (e) {
      console.error(e);
      setSaveState('error');
    }
  }, [authFetch, template, matrix]);

  const scheduleSave = useCallback(() => {
    dirtyRef.current = true;
    setSaveState('dirty');
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(() => {
      flushSave();
    }, 800);
  }, [flushSave]);

  // Cleanup pending save på unmount
  useEffect(() => {
    return () => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    };
  }, []);

  // -------------------------------------------------------------------------
  // Mutators
  // -------------------------------------------------------------------------
  const setCellQty = (productId, dow, value) => {
    const qty = value === '' ? 0 : Math.max(0, parseInt(value, 10) || 0);
    setMatrix((prev) => ({
      ...prev,
      [productId]: { ...(prev[productId] || {}), [dow]: qty },
    }));
    scheduleSave();
  };

  const addProductRow = (productId) => {
    if (activeProductIds.includes(productId)) return;
    setActiveProductIds((prev) => [...prev, productId]);
    setMatrix((prev) => ({ ...prev, [productId]: prev[productId] || {} }));
    setShowProductPicker(false);
    setProductPickerSearch('');
  };

  const removeProductRow = (productId) => {
    if (!confirm('Fjerne dette produktet fra malen? Alle antall slettes.')) return;
    setActiveProductIds((prev) => prev.filter((id) => id !== productId));
    setMatrix((prev) => {
      const copy = { ...prev };
      delete copy[productId];
      return copy;
    });
    scheduleSave();
  };

  // -------------------------------------------------------------------------
  // Derived
  // -------------------------------------------------------------------------
  const productById = useMemo(() => {
    const m = new Map();
    for (const p of allProducts) m.set(p.id, p);
    return m;
  }, [allProducts]);

  const visibleRows = useMemo(() => {
    const term = search.trim().toLowerCase();
    return activeProductIds
      .map((id) => productById.get(id))
      .filter(Boolean)
      .filter((p) => !term || p.name.toLowerCase().includes(term) || (p.sku || '').toLowerCase().includes(term));
  }, [activeProductIds, productById, search]);

  const pickerProducts = useMemo(() => {
    const term = productPickerSearch.trim().toLowerCase();
    const inUse = new Set(activeProductIds);
    return allProducts
      .filter((p) => !inUse.has(p.id))
      .filter((p) => !term || p.name.toLowerCase().includes(term) || (p.sku || '').toLowerCase().includes(term))
      .slice(0, 50);
  }, [allProducts, activeProductIds, productPickerSearch]);

  const weekTotal = (productId) => {
    const days = matrix[productId] || {};
    return DAYS.reduce((s, d) => s + (Number(days[d.dow]) || 0), 0);
  };

  const dayTotal = (dow) => {
    let s = 0;
    for (const pid of activeProductIds) {
      s += Number((matrix[pid] || {})[dow]) || 0;
    }
    return s;
  };

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------
  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-gray-500">
        <Loader2 className="w-6 h-6 animate-spin mr-2" /> Laster...
      </div>
    );
  }

  if (error) {
    return (
      <div className="card border-red-200 bg-red-50 text-red-700 flex items-center gap-3">
        <AlertCircle className="w-5 h-5" /> {error}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Topbar */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link to="/kunder" className="p-2 text-gray-500 hover:bg-gray-100 rounded-lg" title="Tilbake til kunder">
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <div>
            <h1 className="text-2xl font-bold text-gray-900">{customer?.name}</h1>
            <p className="text-sm text-gray-500">
              Fastbestilling — {template?.name}
              {customer?.susoft_customer_id && ` · SuSoft: ${customer.susoft_customer_id}`}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowOverride(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-orange-50 hover:bg-orange-100 text-orange-700 rounded-lg font-medium"
            title="Registrer avvik for én dag"
          >
            <AlertTriangle className="w-4 h-4" /> Avvik
          </button>
          <SaveIndicator state={saveState} onSaveNow={flushSave} />
        </div>
      </div>

      {/* Verktøylinje */}
      <div className="card flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[240px]">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            placeholder="Filtrer produkter i malen..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-9 pr-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-amber-500 focus:border-transparent"
          />
        </div>
        <button
          onClick={() => setShowProductPicker(true)}
          className="btn-primary flex items-center gap-2"
        >
          <Plus className="w-4 h-4" /> Legg til produkt
        </button>
      </div>

      {/* Matrise */}
      <div className="card overflow-x-auto p-0">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="text-left px-4 py-3 font-medium text-gray-600 sticky left-0 bg-gray-50">Produkt</th>
              {DAYS.map((d) => (
                <th key={d.dow} className="px-2 py-3 text-center font-medium text-gray-600 w-20">{d.label}</th>
              ))}
              <th className="px-3 py-3 text-center font-medium text-gray-600 w-20">Sum</th>
              <th className="w-10"></th>
            </tr>
          </thead>
          <tbody>
            {visibleRows.length === 0 && (
              <tr>
                <td colSpan={DAYS.length + 3} className="text-center py-12 text-gray-500">
                  {activeProductIds.length === 0
                    ? 'Ingen produkter i malen ennå. Klikk "Legg til produkt".'
                    : 'Ingen produkter matcher søket.'}
                </td>
              </tr>
            )}
            {visibleRows.map((p) => (
              <tr key={p.id} className="border-b border-gray-100 hover:bg-amber-50/30">
                <td className="px-4 py-2 sticky left-0 bg-white">
                  <div className="font-medium text-gray-900">{p.name}</div>
                  <div className="text-xs text-gray-400">
                    {p.sku} {p.category ? `· ${p.category}` : ''} {p.unit ? `· ${p.unit}` : ''}
                  </div>
                </td>
                {DAYS.map((d) => {
                  const qty = (matrix[p.id] || {})[d.dow] || 0;
                  return (
                    <td key={d.dow} className="px-1 py-1 text-center">
                      <input
                        type="number"
                        min="0"
                        inputMode="numeric"
                        value={qty === 0 ? '' : qty}
                        placeholder="–"
                        onChange={(e) => setCellQty(p.id, d.dow, e.target.value)}
                        className={`w-16 text-center px-2 py-1 border rounded focus:ring-2 focus:ring-amber-500 focus:border-transparent ${
                          qty > 0 ? 'border-amber-200 bg-amber-50' : 'border-gray-200'
                        }`}
                      />
                    </td>
                  );
                })}
                <td className="px-3 py-2 text-center font-semibold text-gray-900">{weekTotal(p.id)}</td>
                <td className="px-2">
                  <button
                    onClick={() => removeProductRow(p.id)}
                    className="p-1 text-gray-300 hover:text-red-600"
                    title="Fjern fra mal"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
          {visibleRows.length > 0 && (
            <tfoot className="bg-gray-50 border-t-2 border-gray-200">
              <tr>
                <td className="px-4 py-3 font-semibold text-gray-700 sticky left-0 bg-gray-50">Total per dag</td>
                {DAYS.map((d) => (
                  <td key={d.dow} className="px-2 py-3 text-center font-semibold text-gray-900">{dayTotal(d.dow)}</td>
                ))}
                <td className="px-3 py-3 text-center font-bold text-amber-700">
                  {DAYS.reduce((s, d) => s + dayTotal(d.dow), 0)}
                </td>
                <td></td>
              </tr>
            </tfoot>
          )}
        </table>
      </div>

      {/* Produkt-velger modal */}
      {showProductPicker && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-lg max-h-[80vh] flex flex-col">
            <div className="flex items-center justify-between p-4 border-b">
              <h3 className="font-semibold">Legg til produkt i malen</h3>
              <button
                onClick={() => { setShowProductPicker(false); setProductPickerSearch(''); }}
                className="p-1 hover:bg-gray-100 rounded"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-4 border-b">
              <div className="relative">
                <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                <input
                  autoFocus
                  type="text"
                  placeholder="Søk etter produkt..."
                  value={productPickerSearch}
                  onChange={(e) => setProductPickerSearch(e.target.value)}
                  className="w-full pl-9 pr-3 py-2 border border-gray-300 rounded-lg"
                />
              </div>
            </div>
            <div className="flex-1 overflow-y-auto">
              {pickerProducts.length === 0 ? (
                <div className="p-6 text-center text-gray-500 text-sm">Ingen treff.</div>
              ) : (
                pickerProducts.map((p) => (
                  <button
                    key={p.id}
                    onClick={() => addProductRow(p.id)}
                    className="w-full text-left px-4 py-2 hover:bg-amber-50 border-b border-gray-100 flex items-center justify-between"
                  >
                    <div>
                      <div className="font-medium text-gray-900">{p.name}</div>
                      <div className="text-xs text-gray-400">{p.sku} {p.category ? `· ${p.category}` : ''}</div>
                    </div>
                    <Plus className="w-4 h-4 text-amber-600" />
                  </button>
                ))
              )}
            </div>
          </div>
        </div>
      )}

      {/* Quick override modal */}
      {showOverride && customer && (
        <QuickOverrideModal
          customer={customer}
          onClose={() => setShowOverride(false)}
        />
      )}

      {/* Apply-til-eksisterende-ordrer prompt */}
      {affectedPrompt && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl shadow-xl max-w-md w-full m-4">
            <div className="p-5 border-b">
              <h3 className="text-lg font-semibold flex items-center gap-2">
                <AlertTriangle className="w-5 h-5 text-amber-600" /> Oppdater eksisterende ordrer?
              </h3>
            </div>
            <div className="p-5 space-y-3 text-sm">
              <p>Du har endret malen. Fremtidige ordrer for denne kunden:</p>
              <ul className="space-y-1 pl-2">
                <li>• <strong>{affectedPrompt.draft_count}</strong> kladd-ordrer (oppdateres automatisk hvis du velger «Ja»)</li>
                <li>• <strong>{affectedPrompt.non_draft_count}</strong> bekreftede / klar-for-leveranse ordrer</li>
                {affectedPrompt.locked_count > 0 && (
                  <li className="text-gray-500">• {affectedPrompt.locked_count} låste ordrer (uendret)</li>
                )}
              </ul>
              <p className="text-xs text-gray-500">
                Bekreftede ordrer vil sendes til SuSoft på nytt. Låste ordrer (etter cut-off) endres aldri.
              </p>
            </div>
            <div className="p-5 border-t flex flex-col gap-2">
              <button
                disabled={applying}
                onClick={async () => {
                  setApplying(true);
                  try {
                    const res = await authFetch(
                      `/api/v1/templates/${template.id}/apply-to-existing-orders?include_non_draft=true`,
                      { method: 'POST' }
                    );
                    if (!res.ok) {
                      const txt = await res.text();
                      let msg = txt;
                      try { msg = JSON.parse(txt).detail || txt; } catch (_) {}
                      throw new Error(msg || `HTTP ${res.status}`);
                    }
                    const data = await res.json();
                    alert(`Oppdaterte ${data.total_updated} ordrer (${data.updated_draft} kladd, ${data.updated_non_draft} bekreftede).`);
                    setAffectedPrompt(null);
                  } catch (e) {
                    alert(`Feil: ${e.message}`);
                  } finally {
                    setApplying(false);
                  }
                }}
                className="btn-primary w-full justify-center"
              >
                {applying ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle2 className="w-4 h-4" />}
                Ja, oppdater alle ({affectedPrompt.draft_count + affectedPrompt.non_draft_count})
              </button>
              <button
                disabled={applying || affectedPrompt.draft_count === 0}
                onClick={async () => {
                  setApplying(true);
                  try {
                    const res = await authFetch(
                      `/api/v1/templates/${template.id}/apply-to-existing-orders?include_non_draft=false`,
                      { method: 'POST' }
                    );
                    if (!res.ok) {
                      const txt = await res.text();
                      let msg = txt;
                      try { msg = JSON.parse(txt).detail || txt; } catch (_) {}
                      throw new Error(msg || `HTTP ${res.status}`);
                    }
                    const data = await res.json();
                    alert(`Oppdaterte ${data.updated_draft} kladd-ordrer.`);
                    setAffectedPrompt(null);
                  } catch (e) {
                    alert(`Feil: ${e.message}`);
                  } finally {
                    setApplying(false);
                  }
                }}
                className="btn-secondary w-full justify-center disabled:opacity-50"
              >
                Bare kladd-ordrer ({affectedPrompt.draft_count})
              </button>
              <button
                disabled={applying}
                onClick={() => setAffectedPrompt(null)}
                className="text-sm text-gray-500 hover:text-gray-700 py-1"
              >
                Avbryt — ikke oppdater eksisterende ordrer
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function SaveIndicator({ state, onSaveNow }) {
  if (state === 'saving') {
    return (
      <span className="text-sm text-gray-500 flex items-center gap-2">
        <Loader2 className="w-4 h-4 animate-spin" /> Lagrer...
      </span>
    );
  }
  if (state === 'saved') {
    return (
      <span className="text-sm text-green-600 flex items-center gap-2">
        <CheckCircle2 className="w-4 h-4" /> Lagret
      </span>
    );
  }
  if (state === 'dirty') {
    return (
      <button onClick={onSaveNow} className="text-sm text-amber-600 hover:text-amber-700 flex items-center gap-2">
        <Save className="w-4 h-4" /> Ulagrede endringer (lagrer automatisk)
      </button>
    );
  }
  if (state === 'error') {
    return (
      <button onClick={onSaveNow} className="text-sm text-red-600 hover:text-red-700 flex items-center gap-2">
        <AlertCircle className="w-4 h-4" /> Lagring feilet — klikk for å prøve igjen
      </button>
    );
  }
  return null;
}
