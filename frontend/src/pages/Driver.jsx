import { useState, useEffect, useCallback, useRef } from 'react';
import {
  Truck, MapPin, Phone, Camera, CheckCircle2, AlertTriangle,
  Package, RefreshCw, Clock, Navigation, X, Edit3,
} from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';

const formatTime = (iso) => {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleTimeString('nb-NO', { hour: '2-digit', minute: '2-digit' });
};

const todayISO = () => new Date().toISOString().split('T')[0];

function StatusBadge({ status }) {
  const map = {
    delivered: { label: 'Levert', cls: 'bg-emerald-100 text-emerald-800' },
    in_transit: { label: 'Underveis', cls: 'bg-amber-100 text-amber-800' },
    ready_for_delivery: { label: 'Klar', cls: 'bg-sky-100 text-sky-800' },
    confirmed: { label: 'Bekreftet', cls: 'bg-slate-100 text-slate-700' },
    cancelled: { label: 'Kansellert', cls: 'bg-rose-100 text-rose-700' },
  };
  const m = map[status] || { label: status, cls: 'bg-slate-100 text-slate-700' };
  return <span className={`px-2 py-0.5 rounded text-xs font-semibold ${m.cls}`}>{m.label}</span>;
}

function DeliverDialog({ stop, onClose, onSubmit, busy }) {
  const [lines, setLines] = useState(() => stop.lines.map(l => ({
    line_id: l.line_id,
    delivered_quantity: l.delivered_quantity ?? l.quantity_ordered,
    waste_quantity: l.waste_quantity || 0,
    return_quantity: l.return_quantity || 0,
    product_name: l.product_name,
    unit: l.unit,
    quantity_ordered: l.quantity_ordered,
  })));
  const [notes, setNotes] = useState(stop.delivery_notes || '');
  const [photo, setPhoto] = useState(null);
  const fileRef = useRef(null);

  const handlePhoto = (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    const reader = new FileReader();
    reader.onload = () => setPhoto(reader.result);
    reader.readAsDataURL(f);
  };

  const update = (idx, field, val) => {
    const v = Math.max(0, parseInt(val, 10) || 0);
    setLines(prev => prev.map((l, i) => i === idx ? { ...l, [field]: v } : l));
  };

  const submit = () => {
    onSubmit({
      lines: lines.map(l => ({
        line_id: l.line_id,
        delivered_quantity: l.delivered_quantity,
        waste_quantity: l.waste_quantity,
        return_quantity: l.return_quantity,
      })),
      notes: notes.trim() || null,
      photo_data_url: photo,
    });
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-end sm:items-center justify-center">
      <div className="bg-white w-full sm:max-w-lg sm:rounded-xl rounded-t-2xl max-h-[92vh] overflow-y-auto">
        <div className="sticky top-0 bg-white border-b px-4 py-3 flex items-center justify-between">
          <div>
            <div className="font-bold text-slate-900">{stop.customer_name}</div>
            <div className="text-xs text-slate-500">Bekreft levering</div>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-slate-100 rounded">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-4 space-y-4">
          <div>
            <div className="text-sm font-semibold text-slate-700 mb-2">Faktisk levert</div>
            <div className="space-y-2">
              {lines.map((l, idx) => {
                const diff = l.delivered_quantity - l.quantity_ordered;
                return (
                  <div key={l.line_id} className="border rounded-lg p-2.5">
                    <div className="flex items-center justify-between mb-1">
                      <div className="font-medium text-slate-900 text-sm">{l.product_name}</div>
                      <div className="text-xs text-slate-500">Bestilt: {l.quantity_ordered} {l.unit}</div>
                    </div>
                    <div className="grid grid-cols-3 gap-2">
                      <label className="block">
                        <span className="text-[11px] text-slate-500">Levert</span>
                        <input
                          type="number"
                          inputMode="numeric"
                          value={l.delivered_quantity}
                          onChange={(e) => update(idx, 'delivered_quantity', e.target.value)}
                          className="w-full border rounded px-2 py-1.5 text-base"
                        />
                      </label>
                      <label className="block">
                        <span className="text-[11px] text-slate-500">Svinn</span>
                        <input
                          type="number"
                          inputMode="numeric"
                          value={l.waste_quantity}
                          onChange={(e) => update(idx, 'waste_quantity', e.target.value)}
                          className="w-full border rounded px-2 py-1.5 text-base"
                        />
                      </label>
                      <label className="block">
                        <span className="text-[11px] text-slate-500">Retur</span>
                        <input
                          type="number"
                          inputMode="numeric"
                          value={l.return_quantity}
                          onChange={(e) => update(idx, 'return_quantity', e.target.value)}
                          className="w-full border rounded px-2 py-1.5 text-base"
                        />
                      </label>
                    </div>
                    {diff !== 0 && (
                      <div className={`mt-1 text-xs ${diff < 0 ? 'text-rose-600' : 'text-emerald-600'}`}>
                        {diff > 0 ? '+' : ''}{diff} vs. bestilt
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          <div>
            <label className="block text-sm font-semibold text-slate-700 mb-1">Notat</label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={2}
              placeholder="Mottatt av, kommentar fra kunde, ..."
              className="w-full border rounded-lg px-3 py-2 text-base"
            />
          </div>

          <div>
            <label className="block text-sm font-semibold text-slate-700 mb-1">Bilde</label>
            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              capture="environment"
              onChange={handlePhoto}
              className="hidden"
            />
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => fileRef.current?.click()}
                className="flex items-center gap-2 px-3 py-2 border-2 border-dashed border-slate-300 rounded-lg text-sm text-slate-600 hover:bg-slate-50"
              >
                <Camera className="w-4 h-4" /> {photo ? 'Bytt bilde' : 'Ta bilde'}
              </button>
              {photo && (
                <button
                  type="button"
                  onClick={() => setPhoto(null)}
                  className="text-rose-600 text-sm"
                >Fjern</button>
              )}
            </div>
            {photo && (
              <img src={photo} alt="Levering" className="mt-2 rounded-lg max-h-48 w-auto border" />
            )}
          </div>
        </div>

        <div className="sticky bottom-0 bg-white border-t p-3 flex gap-2">
          <button
            onClick={onClose}
            disabled={busy}
            className="flex-1 px-4 py-3 border rounded-lg font-semibold text-slate-700"
          >Avbryt</button>
          <button
            onClick={submit}
            disabled={busy}
            className="flex-1 px-4 py-3 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg font-semibold disabled:opacity-50 flex items-center justify-center gap-2"
          >
            <CheckCircle2 className="w-5 h-5" /> {busy ? 'Sender ...' : 'Bekreft levert'}
          </button>
        </div>
      </div>
    </div>
  );
}

function IssueDialog({ stop, onClose, onSubmit, busy }) {
  const [type, setType] = useState('damaged');
  const [desc, setDesc] = useState('');
  const [productId, setProductId] = useState('');
  const [qty, setQty] = useState('');

  const submit = () => {
    if (!desc.trim()) return;
    onSubmit({
      issue_type: type,
      description: desc.trim(),
      product_id: productId ? parseInt(productId, 10) : null,
      quantity_affected: qty ? parseInt(qty, 10) : null,
    });
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-end sm:items-center justify-center">
      <div className="bg-white w-full sm:max-w-md sm:rounded-xl rounded-t-2xl">
        <div className="border-b px-4 py-3 flex items-center justify-between">
          <div className="font-bold text-slate-900">Registrer avvik</div>
          <button onClick={onClose} className="p-2 hover:bg-slate-100 rounded">
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="p-4 space-y-3">
          <label className="block">
            <span className="text-sm font-semibold text-slate-700">Type</span>
            <select
              value={type}
              onChange={(e) => setType(e.target.value)}
              className="w-full border rounded-lg px-3 py-2 text-base mt-1"
            >
              <option value="damaged">Skadet vare</option>
              <option value="missing">Manglende vare</option>
              <option value="wrong_product">Feil produkt</option>
              <option value="customer_refused">Kunde nektet å motta</option>
              <option value="address_not_found">Fant ikke adressen</option>
              <option value="other">Annet</option>
            </select>
          </label>
          <label className="block">
            <span className="text-sm font-semibold text-slate-700">Produkt (valgfritt)</span>
            <select
              value={productId}
              onChange={(e) => setProductId(e.target.value)}
              className="w-full border rounded-lg px-3 py-2 text-base mt-1"
            >
              <option value="">— alle / ikke spesifikt —</option>
              {stop.lines.map(l => (
                <option key={l.line_id} value={l.product_id}>{l.product_name}</option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="text-sm font-semibold text-slate-700">Antall berørt (valgfritt)</span>
            <input
              type="number"
              inputMode="numeric"
              value={qty}
              onChange={(e) => setQty(e.target.value)}
              className="w-full border rounded-lg px-3 py-2 text-base mt-1"
            />
          </label>
          <label className="block">
            <span className="text-sm font-semibold text-slate-700">Beskrivelse *</span>
            <textarea
              value={desc}
              onChange={(e) => setDesc(e.target.value)}
              rows={3}
              className="w-full border rounded-lg px-3 py-2 text-base mt-1"
              placeholder="F.eks. 3 stk. baguetter knust ved transport ..."
            />
          </label>
        </div>
        <div className="border-t p-3 flex gap-2">
          <button onClick={onClose} disabled={busy} className="flex-1 px-4 py-3 border rounded-lg font-semibold text-slate-700">Avbryt</button>
          <button
            onClick={submit}
            disabled={busy || !desc.trim()}
            className="flex-1 px-4 py-3 bg-rose-600 hover:bg-rose-700 text-white rounded-lg font-semibold disabled:opacity-50"
          >{busy ? 'Sender ...' : 'Registrer'}</button>
        </div>
      </div>
    </div>
  );
}

export default function Driver() {
  const { authFetch, user } = useAuth();
  const [date, setDate] = useState(todayISO());
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [activeStop, setActiveStop] = useState(null);
  const [issueStop, setIssueStop] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await authFetch(`/api/v1/driver/today?date=${date}`);
      if (!r.ok) throw new Error('Kunne ikke hente leveringer');
      setData(await r.json());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [authFetch, date]);

  useEffect(() => { load(); }, [load]);

  const startDelivery = async (stop) => {
    setBusy(true);
    try {
      const r = await authFetch(`/api/v1/driver/orders/${stop.order_id}/start`, { method: 'POST' });
      if (!r.ok) throw new Error('Kunne ikke starte levering');
      await load();
    } catch (e) {
      alert(e.message);
    } finally {
      setBusy(false);
    }
  };

  const submitDeliver = async (payload) => {
    if (!activeStop) return;
    setBusy(true);
    try {
      const r = await authFetch(`/api/v1/driver/orders/${activeStop.order_id}/deliver`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error(err.detail || 'Kunne ikke bekrefte levering');
      }
      setActiveStop(null);
      await load();
    } catch (e) {
      alert(e.message);
    } finally {
      setBusy(false);
    }
  };

  const submitIssue = async (payload) => {
    if (!issueStop) return;
    setBusy(true);
    try {
      const r = await authFetch(`/api/v1/driver/orders/${issueStop.order_id}/issue`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error(err.detail || 'Kunne ikke registrere avvik');
      }
      setIssueStop(null);
      alert('Avvik registrert');
    } catch (e) {
      alert(e.message);
    } finally {
      setBusy(false);
    }
  };

  const navigateTo = (stop) => {
    if (!stop.address) return;
    const q = encodeURIComponent(stop.address);
    window.open(`https://www.google.com/maps/dir/?api=1&destination=${q}`, '_blank');
  };

  return (
    <div className="max-w-3xl mx-auto px-3 sm:px-4 py-4 space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Truck className="w-6 h-6 text-amber-600" />
          <h1 className="text-xl sm:text-2xl font-bold text-slate-900">Sjåfør</h1>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="p-2 rounded-lg hover:bg-slate-100"
          title="Oppdater"
        >
          <RefreshCw className={`w-5 h-5 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      <div className="flex items-center gap-2">
        <input
          type="date"
          value={date}
          onChange={(e) => setDate(e.target.value)}
          className="border rounded-lg px-3 py-2"
        />
        {data && (
          <div className="text-sm text-slate-600 ml-auto">
            <span className="font-semibold text-slate-900">{data.completed_stops}/{data.total_stops}</span> levert ·{' '}
            <span>{data.total_items} stk</span>
          </div>
        )}
      </div>

      {error && (
        <div className="bg-rose-50 border border-rose-200 text-rose-700 rounded-lg p-3 text-sm">{error}</div>
      )}

      {loading && !data && (
        <div className="flex justify-center py-10">
          <RefreshCw className="w-6 h-6 animate-spin text-amber-600" />
        </div>
      )}

      {data && data.stops.length === 0 && !loading && (
        <div className="text-center py-12 text-slate-500">
          <Package className="w-12 h-12 mx-auto mb-2 opacity-40" />
          Ingen leveringer denne dagen.
        </div>
      )}

      <div className="space-y-3">
        {data?.stops.map((stop, idx) => {
          const isDelivered = stop.status === 'delivered';
          const isInTransit = stop.status === 'in_transit';
          return (
            <div
              key={stop.order_id}
              className={`bg-white rounded-xl border-2 p-3 sm:p-4 shadow-sm ${
                isDelivered ? 'border-emerald-200 bg-emerald-50/30' :
                isInTransit ? 'border-amber-300' : 'border-slate-200'
              }`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-start gap-3 flex-1 min-w-0">
                  <div className={`flex-shrink-0 w-10 h-10 rounded-full flex items-center justify-center font-bold ${
                    isDelivered ? 'bg-emerald-600 text-white' : 'bg-slate-200 text-slate-700'
                  }`}>
                    {isDelivered ? <CheckCircle2 className="w-5 h-5" /> : idx + 1}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="font-bold text-slate-900 truncate">
                      {stop.customer_name}
                      {stop.company_name && stop.company_name !== stop.customer_name && (
                        <span className="text-slate-500 font-normal"> · {stop.company_name}</span>
                      )}
                    </div>
                    {stop.address && (
                      <div className="text-sm text-slate-600 flex items-start gap-1 mt-0.5">
                        <MapPin className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
                        <span className="truncate">{stop.address}</span>
                      </div>
                    )}
                    {(stop.delivery_window_start || stop.delivery_window_end) && (
                      <div className="text-xs text-slate-500 flex items-center gap-1 mt-0.5">
                        <Clock className="w-3 h-3" />
                        {stop.delivery_window_start || '?'} – {stop.delivery_window_end || '?'}
                      </div>
                    )}
                    {stop.delivery_instructions && (
                      <div className="text-xs text-amber-700 bg-amber-50 rounded px-2 py-1 mt-1">
                        {stop.delivery_instructions}
                      </div>
                    )}
                  </div>
                </div>
                <div className="flex flex-col items-end gap-1">
                  <StatusBadge status={stop.status} />
                  {stop.actual_delivery_time && (
                    <div className="text-[11px] text-slate-500">{formatTime(stop.actual_delivery_time)}</div>
                  )}
                </div>
              </div>

              <div className="mt-3 grid grid-cols-2 gap-1.5 text-xs">
                {stop.lines.map(l => {
                  const delivered = l.delivered_quantity ?? null;
                  const diff = delivered !== null ? delivered - l.quantity_ordered : 0;
                  return (
                    <div key={l.line_id} className="flex items-center justify-between bg-slate-50 rounded px-2 py-1">
                      <span className="truncate">{l.product_name}</span>
                      <span className="font-semibold ml-2 whitespace-nowrap">
                        {delivered !== null ? (
                          <>
                            {delivered}/{l.quantity_ordered}
                            {diff !== 0 && (
                              <span className={diff < 0 ? 'text-rose-600 ml-1' : 'text-emerald-600 ml-1'}>
                                ({diff > 0 ? '+' : ''}{diff})
                              </span>
                            )}
                          </>
                        ) : (
                          <>{l.quantity_ordered}</>
                        )}
                      </span>
                    </div>
                  );
                })}
              </div>

              <div className="mt-3 flex flex-wrap gap-2">
                {stop.phone && (
                  <a
                    href={`tel:${stop.phone}`}
                    className="flex items-center gap-1 px-3 py-2 bg-slate-100 hover:bg-slate-200 rounded-lg text-sm text-slate-700"
                  >
                    <Phone className="w-4 h-4" /> Ring
                  </a>
                )}
                {stop.address && (
                  <button
                    onClick={() => navigateTo(stop)}
                    className="flex items-center gap-1 px-3 py-2 bg-sky-100 hover:bg-sky-200 rounded-lg text-sm text-sky-800"
                  >
                    <Navigation className="w-4 h-4" /> Naviger
                  </button>
                )}
                <button
                  onClick={() => setIssueStop(stop)}
                  className="flex items-center gap-1 px-3 py-2 bg-rose-100 hover:bg-rose-200 rounded-lg text-sm text-rose-700"
                >
                  <AlertTriangle className="w-4 h-4" /> Avvik
                </button>

                <div className="flex-1" />

                {!isDelivered && !isInTransit && (
                  <button
                    onClick={() => startDelivery(stop)}
                    disabled={busy}
                    className="flex items-center gap-1 px-3 py-2 bg-amber-600 hover:bg-amber-700 text-white rounded-lg text-sm font-semibold disabled:opacity-50"
                  >
                    <Truck className="w-4 h-4" /> Start
                  </button>
                )}
                {!isDelivered && (
                  <button
                    onClick={() => setActiveStop(stop)}
                    className="flex items-center gap-1 px-3 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-sm font-semibold"
                  >
                    <CheckCircle2 className="w-4 h-4" /> Bekreft levert
                  </button>
                )}
                {isDelivered && (
                  <button
                    onClick={() => setActiveStop(stop)}
                    className="flex items-center gap-1 px-3 py-2 border rounded-lg text-sm text-slate-700"
                  >
                    <Edit3 className="w-4 h-4" /> Rediger
                  </button>
                )}
              </div>

              {stop.delivery_photo_url && (
                <details className="mt-2">
                  <summary className="text-xs text-slate-500 cursor-pointer">Vis bilde</summary>
                  <img src={stop.delivery_photo_url} alt="Levering" className="mt-2 rounded max-h-40" />
                </details>
              )}
            </div>
          );
        })}
      </div>

      {activeStop && (
        <DeliverDialog
          stop={activeStop}
          onClose={() => setActiveStop(null)}
          onSubmit={submitDeliver}
          busy={busy}
        />
      )}
      {issueStop && (
        <IssueDialog
          stop={issueStop}
          onClose={() => setIssueStop(null)}
          onSubmit={submitIssue}
          busy={busy}
        />
      )}
    </div>
  );
}
