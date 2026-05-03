import { useEffect, useRef, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Bell, X, CheckCircle2, Eye, Volume2, VolumeX } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';

const POLL_INTERVAL_MS = 15000;
const SOUND_KEY = 'lampe_notif_sound_enabled';

// Lager en kort "ding" via WebAudio — ingen ekstra fil eller import.
function playDing() {
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.value = 880;
    gain.gain.setValueAtTime(0.0001, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.25, ctx.currentTime + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.45);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start(ctx.currentTime);
    osc.stop(ctx.currentTime + 0.5);
  } catch {
    /* lyd er valgfri — feil ignoreres */
  }
}

function formatNok(amount) {
  if (amount == null) return '';
  return new Intl.NumberFormat('nb-NO', {
    style: 'currency',
    currency: 'NOK',
    maximumFractionDigits: 0,
  }).format(amount);
}

function formatDate(iso) {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleDateString('nb-NO', {
      day: '2-digit', month: '2-digit', year: 'numeric',
    });
  } catch {
    return iso;
  }
}

export default function NotificationBell() {
  const { authFetch } = useAuth();
  const navigate = useNavigate();

  const [count, setCount] = useState(0);
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const [popupItem, setPopupItem] = useState(null);
  const [soundEnabled, setSoundEnabled] = useState(() => {
    return localStorage.getItem(SOUND_KEY) !== '0';
  });
  const [busy, setBusy] = useState(false);

  const lastSeenIdRef = useRef(0);
  const dropdownRef = useRef(null);
  const initializedRef = useRef(false);

  const refresh = useCallback(async () => {
    try {
      const res = await authFetch('/api/v1/notifications?unread_only=true&limit=20');
      if (!res.ok) return;
      const list = await res.json();
      setItems(list);
      setCount(list.length);

      // Finn høyeste ID — hvis den er ny etter første lasting, spill lyd
      const maxId = list.reduce((m, n) => (n.id > m ? n.id : m), 0);
      if (initializedRef.current && maxId > lastSeenIdRef.current) {
        // Ny notifikasjon kom inn — spill lyd og vis popup for nyeste
        const newest = list[0];
        if (soundEnabled) playDing();
        if (newest && newest.type === 'portal_order') {
          setPopupItem(newest);
        }
      }
      if (maxId > lastSeenIdRef.current) lastSeenIdRef.current = maxId;
      initializedRef.current = true;
    } catch {
      /* ignorer transient feil */
    }
  }, [authFetch, soundEnabled]);

  // Polling
  useEffect(() => {
    refresh();
    const id = setInterval(refresh, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  // Lukk dropdown ved klikk utenfor
  useEffect(() => {
    if (!open) return;
    const handler = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const toggleSound = () => {
    const next = !soundEnabled;
    setSoundEnabled(next);
    localStorage.setItem(SOUND_KEY, next ? '1' : '0');
  };

  const markRead = async (id) => {
    try {
      await authFetch(`/api/v1/notifications/${id}/read`, { method: 'POST' });
      setItems((prev) => prev.filter((n) => n.id !== id));
      setCount((c) => Math.max(0, c - 1));
    } catch { /* ignored */ }
  };

  const markAllRead = async () => {
    try {
      await authFetch('/api/v1/notifications/read-all', { method: 'POST' });
      setItems([]);
      setCount(0);
    } catch { /* ignored */ }
  };

  const openOrder = (n) => {
    if (n.related_entity_type === 'order' && n.related_entity_id) {
      markRead(n.id);
      setOpen(false);
      setPopupItem(null);
      navigate(`/bestillinger?order=${n.related_entity_id}`);
    }
  };

  const approveOrder = async (n) => {
    if (!n.related_entity_id) return;
    setBusy(true);
    try {
      const res = await authFetch(
        `/api/v1/orders/${n.related_entity_id}/approve`,
        { method: 'POST' }
      );
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Godkjenning feilet');
      }
      // Fjern fra liste — backend markerte alert som lest
      setItems((prev) => prev.filter((x) => x.id !== n.id));
      setCount((c) => Math.max(0, c - 1));
      setPopupItem(null);
    } catch (e) {
      alert(`Feil: ${e.message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="relative" ref={dropdownRef}>
        <button
          onClick={() => setOpen((o) => !o)}
          className="relative p-1.5 rounded-md text-gray-500 hover:text-gray-900 hover:bg-gray-200/60 transition-colors"
          aria-label={`Varsler (${count} uleste)`}
          title={count > 0 ? `${count} uleste varsler` : 'Ingen nye varsler'}
        >
          <Bell className="w-4 h-4" />
          {count > 0 && (
            <span className="absolute -top-0.5 -right-0.5 min-w-[1.1rem] h-[1.1rem] px-1 rounded-full bg-red-600 text-white text-[10px] font-semibold flex items-center justify-center">
              {count > 99 ? '99+' : count}
            </span>
          )}
        </button>

        {open && (
          <div className="absolute right-0 mt-2 w-80 bg-white border border-gray-200 rounded-lg shadow-lg z-50 max-h-[28rem] overflow-hidden flex flex-col">
            <div className="flex items-center justify-between px-3 py-2 border-b border-gray-200">
              <span className="text-sm font-semibold text-gray-900">Varsler</span>
              <div className="flex items-center gap-1">
                <button
                  onClick={toggleSound}
                  className="p-1 text-gray-500 hover:text-gray-900 rounded"
                  title={soundEnabled ? 'Slå av lyd' : 'Slå på lyd'}
                  aria-label="Bytt lyd"
                >
                  {soundEnabled ? <Volume2 className="w-3.5 h-3.5" /> : <VolumeX className="w-3.5 h-3.5" />}
                </button>
                {items.length > 0 && (
                  <button
                    onClick={markAllRead}
                    className="text-xs text-amber-700 hover:text-amber-900 px-2 py-1"
                  >
                    Marker alle
                  </button>
                )}
              </div>
            </div>
            <div className="flex-1 overflow-y-auto">
              {items.length === 0 ? (
                <div className="p-6 text-center text-sm text-gray-500">
                  Ingen nye varsler
                </div>
              ) : (
                items.map((n) => (
                  <div
                    key={n.id}
                    className="px-3 py-2 border-b border-gray-100 hover:bg-gray-50 cursor-pointer"
                    onClick={() => openOrder(n)}
                  >
                    <div className="flex items-start gap-2">
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-gray-900 truncate">
                          {n.title}
                        </p>
                        <p className="text-xs text-gray-600 truncate">{n.message}</p>
                        {n.delivery_date && (
                          <p className="text-xs text-gray-500 mt-0.5">
                            Levering {formatDate(n.delivery_date)}
                            {n.total_amount_incl_vat != null && (
                              <> · {formatNok(n.total_amount_incl_vat)}</>
                            )}
                          </p>
                        )}
                      </div>
                      <button
                        onClick={(e) => { e.stopPropagation(); markRead(n.id); }}
                        className="p-1 text-gray-400 hover:text-gray-700 rounded"
                        title="Marker som lest"
                      >
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        )}
      </div>

      {/* Popup-modal for nye portal-ordrer */}
      {popupItem && (
        <div
          className="fixed inset-0 z-[60] bg-black/50 flex items-center justify-center p-4"
          onClick={() => setPopupItem(null)}
        >
          <div
            className="bg-white rounded-xl shadow-2xl w-full max-w-md p-5 animate-in fade-in zoom-in-95"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start gap-3 mb-4">
              <div className="w-10 h-10 rounded-full bg-amber-100 flex items-center justify-center flex-shrink-0">
                <Bell className="w-5 h-5 text-amber-700" />
              </div>
              <div className="flex-1 min-w-0">
                <h3 className="text-base font-semibold text-gray-900">
                  {popupItem.title}
                </h3>
                <p className="text-sm text-gray-600 mt-0.5">{popupItem.message}</p>
              </div>
              <button
                onClick={() => setPopupItem(null)}
                className="p-1 text-gray-400 hover:text-gray-700 rounded"
                aria-label="Lukk"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {popupItem.type === 'portal_order' && (
              <div className="bg-gray-50 rounded-lg p-3 mb-4 space-y-1">
                {popupItem.order_no_display && (
                  <div className="flex justify-between text-sm">
                    <span className="text-gray-500">Ordre</span>
                    <span className="font-medium text-gray-900">
                      {popupItem.order_no_display}
                    </span>
                  </div>
                )}
                {popupItem.customer_name && (
                  <div className="flex justify-between text-sm">
                    <span className="text-gray-500">Kunde</span>
                    <span className="font-medium text-gray-900 truncate ml-2">
                      {popupItem.customer_name}
                    </span>
                  </div>
                )}
                {popupItem.delivery_date && (
                  <div className="flex justify-between text-sm">
                    <span className="text-gray-500">Levering</span>
                    <span className="font-medium text-gray-900">
                      {formatDate(popupItem.delivery_date)}
                    </span>
                  </div>
                )}
                {popupItem.total_amount_incl_vat != null && (
                  <div className="flex justify-between text-sm">
                    <span className="text-gray-500">Totalt inkl. mva</span>
                    <span className="font-semibold text-gray-900">
                      {formatNok(popupItem.total_amount_incl_vat)}
                    </span>
                  </div>
                )}
              </div>
            )}

            <div className="flex flex-col sm:flex-row gap-2">
              <button
                onClick={() => approveOrder(popupItem)}
                disabled={busy}
                className="flex-1 inline-flex items-center justify-center gap-2 bg-green-600 hover:bg-green-700 disabled:opacity-50 text-white font-medium px-4 py-2 rounded-md text-sm transition-colors"
              >
                <CheckCircle2 className="w-4 h-4" />
                Godkjenn
              </button>
              <button
                onClick={() => openOrder(popupItem)}
                disabled={busy}
                className="flex-1 inline-flex items-center justify-center gap-2 bg-amber-600 hover:bg-amber-700 disabled:opacity-50 text-white font-medium px-4 py-2 rounded-md text-sm transition-colors"
              >
                <Eye className="w-4 h-4" />
                Åpne ordre
              </button>
              <button
                onClick={() => { markRead(popupItem.id); setPopupItem(null); }}
                disabled={busy}
                className="sm:flex-none inline-flex items-center justify-center gap-2 bg-white hover:bg-gray-50 disabled:opacity-50 text-gray-700 border border-gray-300 font-medium px-4 py-2 rounded-md text-sm transition-colors"
              >
                Senere
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
