import { useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Search, Filter, Plus, Eye, Edit2, Trash2, Truck, Clock, CheckCircle, XCircle, RefreshCw, Send, Loader2, X, Check, AlertTriangle, FileText, EyeOff, Undo2, Download } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';

const statusConfig = {
  draft: { label: 'Kladd', color: 'badge-neutral', icon: Clock },
  pending: { label: 'Venter', color: 'badge-warning', icon: Clock },
  confirmed: { label: 'Bekreftet', color: 'badge-info', icon: CheckCircle },
  ready_for_delivery: { label: 'Klar for levering', color: 'badge-info', icon: CheckCircle },
  in_transit: { label: 'Under levering', color: 'badge-amber', icon: Truck },
  delivered: { label: 'Levert', color: 'badge-success', icon: CheckCircle },
  cancelled: { label: 'Kansellert', color: 'badge-danger', icon: XCircle },
};

export default function Orders() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { authFetch } = useAuth();
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [updatingOrderId, setUpdatingOrderId] = useState(null);
  const [editingOrderId, setEditingOrderId] = useState(null);
  const [selectedOrderIds, setSelectedOrderIds] = useState(new Set());
  // 'visible' = standard (skjuler is_deleted), 'hidden' = kun skjulte
  const [visibilityFilter, setVisibilityFilter] = useState('visible');
  // Bulk-fakturering: { running, total, current, done, results: [{orderId, ok, message}] }
  const [bulkProgress, setBulkProgress] = useState(null);

  // Fetch orders from API
  const fetchOrders = async () => {
    setLoading(true);
    try {
      const qs = visibilityFilter === 'hidden' ? '?only_hidden=true' : '';
      const response = await authFetch(`/api/v1/orders${qs}`);
      if (!response.ok) throw new Error('Kunne ikke hente bestillinger');
      const data = await response.json();
      // Map API response to UI format
      const mappedOrders = (data.items || []).map(o => ({
        id: o.id,
        orderId: o.order_no_display || `ORD-${o.id}`,
        reference: o.reference || '',
        customer: o.customer_name || `Kunde #${o.customer_id}`,
        customerId: o.customer_id,
        deliveryDate: o.delivery_date,
        items: o.lines?.length || 0,
        total: o.total_amount_incl_vat || 0,
        status: o.status,
        syncStatus: o.sync_status,
        syncError: o.sync_error_message,
        susoftOrderId: o.susoft_order_id,
        susoftInvoiceNo: o.susoft_invoice_no,
        invoicedAt: o.invoiced_at,
        isHidden: o.is_hidden,
        needsReview: !!o.needs_review,
        createdAt: o.created_at
      }));
      setOrders(mappedOrders);
    } catch (err) {
      console.error('Fetch error:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // Update order status
  const updateOrderStatus = async (orderId, newStatus) => {
    setUpdatingOrderId(orderId);
    try {
      const response = await authFetch(`/api/v1/orders/${orderId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: newStatus })
      });
      
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Kunne ikke oppdatere status');
      }
      
      const updatedOrder = await response.json();
      
      // Update local state
      setOrders(prev => prev.map(o => 
        o.id === orderId ? {
          ...o,
          status: updatedOrder.status,
          syncStatus: updatedOrder.sync_status,
          syncError: updatedOrder.sync_error_message,
          susoftOrderId: updatedOrder.susoft_order_id
        } : o
      ));
      
      if (newStatus === 'ready_for_delivery' && updatedOrder.sync_status === 'synced') {
        alert('Ordre sendt til SuSoft!');
      } else if (newStatus === 'ready_for_delivery' && updatedOrder.sync_status === 'failed') {
        alert('Ordre satt som klar for levering, men SuSoft-synkronisering feilet. Se feilmelding.');
      }
    } catch (err) {
      console.error('Update error:', err);
      alert(`Feil: ${err.message}`);
    } finally {
      setUpdatingOrderId(null);
    }
  };

  // Send ordre til SuSoft (POST /order). Omgår cutoff-låsen.
  const sendToSusoft = async (order) => {
    setUpdatingOrderId(order.id);
    try {
      const res = await authFetch(`/api/v1/orders/${order.id}/send-to-susoft`, { method: 'POST' });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || 'Sending feilet');
      }
      const updated = await res.json();
      setOrders((prev) => prev.map((o) =>
        o.id === order.id ? {
          ...o,
          status: updated.status,
          syncStatus: updated.sync_status,
          syncError: updated.sync_error_message,
          susoftOrderId: updated.susoft_order_id,
          susoftInvoiceNo: updated.susoft_invoice_no,
          invoicedAt: updated.invoiced_at,
        } : o
      ));
      alert(`Ordre sendt til SuSoft (id: ${updated.susoft_order_id}).`);
    } catch (err) {
      alert(`Feil: ${err.message}`);
    } finally {
      setUpdatingOrderId(null);
    }
  };

  // Nullstill SuSoft-koblingen p\u00e5 ordren (POST /reset-susoft).
  // Brukes hvis ordren ble sendt med feil/manglende data og slettet manuelt i SuSoft.
  const resetSusoftLink = async (order) => {
    if (!confirm(
      `Nullstille SuSoft-kobling for ordre ${order.orderId}?\n\n` +
      `Husk \u00e5 slette ordren manuelt i SuSoft f\u00f8rst!\n` +
      `Etterp\u00e5 kan du trykke "Send" for \u00e5 opprette p\u00e5 nytt med riktige beløp.`
    )) return;
    setUpdatingOrderId(order.id);
    try {
      const res = await authFetch(`/api/v1/orders/${order.id}/reset-susoft`, { method: 'POST' });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `HTTP ${res.status}`);
      }
      const updated = await res.json();
      setOrders((prev) => prev.map((o) =>
        o.id === order.id ? {
          ...o,
          syncStatus: updated.sync_status,
          syncError: updated.sync_error_message,
          susoftOrderId: updated.susoft_order_id,
        } : o
      ));
    } catch (err) {
      alert(`Feil: ${err.message}`);
    } finally {
      setUpdatingOrderId(null);
    }
  };

  // Send ordre som faktura til SuSoft (POST /invoice)
  const invoiceOrder = async (order) => {
    if (!confirm(`Fakturere ordre ${order.orderId} for ${order.customer}?\n\nDette sender ordren som faktura til SuSoft og kan ikke angres.`)) return;
    setUpdatingOrderId(order.id);
    try {
      await invoiceOrderRaw(order);
      alert(`Faktura opprettet i SuSoft.`);
    } catch (err) {
      alert(`Feil: ${err.message}`);
    } finally {
      setUpdatingOrderId(null);
    }
  };

  // Lavniv\u00e5: gj\u00f8r selve POST /invoice + state-oppdatering. Kaster ved feil.
  const invoiceOrderRaw = async (order) => {
    const res = await authFetch(`/api/v1/orders/${order.id}/invoice`, { method: 'POST' });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || `HTTP ${res.status}`);
    }
    const updated = await res.json();
    setOrders((prev) => prev.map((o) =>
      o.id === order.id ? {
        ...o,
        status: updated.status,
        syncStatus: updated.sync_status,
        syncError: updated.sync_error_message,
        susoftOrderId: updated.susoft_order_id,
        susoftInvoiceNo: updated.susoft_invoice_no,
        invoicedAt: updated.invoiced_at,
      } : o
    ));
    return updated;
  };

  // Bulk-fakturering: send valgte ordrer en og en (sekvensiell kø).
  const bulkInvoice = async () => {
    const ids = Array.from(selectedOrderIds);
    const targets = orders.filter((o) => ids.includes(o.id) && !o.susoftInvoiceNo && o.status !== 'cancelled');
    if (targets.length === 0) {
      alert('Ingen valgte ordrer kan faktureres (allerede fakturert eller kansellert).');
      return;
    }
    if (!confirm(`Fakturere ${targets.length} ordre(r) i SuSoft?\n\nOrdrene sendes en og en. Dette kan ikke angres.`)) return;

    setBulkProgress({ running: true, total: targets.length, current: 0, done: 0, results: [] });

    const results = [];
    for (let i = 0; i < targets.length; i++) {
      const order = targets[i];
      setBulkProgress((p) => ({ ...p, current: i + 1, currentOrderId: order.orderId }));
      try {
        const updated = await invoiceOrderRaw(order);
        results.push({
          orderId: order.orderId,
          customer: order.customer,
          ok: true,
          message: `Faktura #${updated.susoft_invoice_no}`,
        });
      } catch (err) {
        results.push({
          orderId: order.orderId,
          customer: order.customer,
          ok: false,
          message: err.message,
        });
      }
      setBulkProgress((p) => ({ ...p, done: i + 1, results: [...results] }));
    }

    setBulkProgress((p) => ({ ...p, running: false, results }));
    // Tøm utvalget for fakturerte (vellykkede)
    const succeededIds = new Set(
      results.filter((r) => r.ok).map((r) => targets.find((t) => t.orderId === r.orderId)?.id).filter(Boolean)
    );
    setSelectedOrderIds((prev) => new Set(Array.from(prev).filter((id) => !succeededIds.has(id))));
  };

  const toggleSelectOrder = (orderId) => {
    setSelectedOrderIds((prev) => {
      const next = new Set(prev);
      if (next.has(orderId)) next.delete(orderId);
      else next.add(orderId);
      return next;
    });
  };

  const toggleSelectAllVisible = () => {
    const visibleSelectable = filteredOrders.filter((o) => !o.susoftInvoiceNo && o.status !== 'cancelled');
    const allSelected = visibleSelectable.length > 0 && visibleSelectable.every((o) => selectedOrderIds.has(o.id));
    setSelectedOrderIds((prev) => {
      const next = new Set(prev);
      if (allSelected) {
        visibleSelectable.forEach((o) => next.delete(o.id));
      } else {
        visibleSelectable.forEach((o) => next.add(o.id));
      }
      return next;
    });
  };

  // Slett ordre (eller skjul hvis sendt til SuSoft)
  const deleteOrder = async (order) => {
    const inSusoft = !!order.susoftOrderId || !!order.susoftInvoiceNo;
    const msg = inSusoft
      ? `Skjule ordre ${order.orderId} for ${order.customer}?\n\nOrdren er overført til SuSoft og kan ikke slettes — den blir kun skjult fra listen. Du kan hente den frem igjen via filteret "Skjulte".`
      : `Slette ordre ${order.orderId} for ${order.customer}?\n\nDette kan ikke angres.`;
    if (!confirm(msg)) return;
    setUpdatingOrderId(order.id);
    try {
      const res = await authFetch(`/api/v1/orders/${order.id}`, { method: 'DELETE' });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || 'Kunne ikke slette/skjule ordre');
      }
      setOrders((prev) => prev.filter((o) => o.id !== order.id));
    } catch (err) {
      alert(`Feil: ${err.message}`);
    } finally {
      setUpdatingOrderId(null);
    }
  };

  // Gjenopprett (vis igjen) en skjult ordre
  const restoreOrder = async (order) => {
    setUpdatingOrderId(order.id);
    try {
      const res = await authFetch(`/api/v1/orders/${order.id}/restore`, { method: 'POST' });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || 'Kunne ikke gjenopprette ordre');
      }
      // Fjern fra nåværende liste (vi er enten i 'visible' og den var ikke der, eller 'hidden' og den skal nullstilles)
      setOrders((prev) => prev.filter((o) => o.id !== order.id));
    } catch (err) {
      alert(`Feil: ${err.message}`);
    } finally {
      setUpdatingOrderId(null);
    }
  };

  useEffect(() => {
    fetchOrders();
  }, [visibilityFilter]);

  // Åpne edit-modal automatisk hvis ?edit=ID i URL (f.eks. fra Avvik-knapp på kunde)
  useEffect(() => {
    const editId = searchParams.get('edit');
    if (editId) {
      const id = parseInt(editId, 10);
      if (!Number.isNaN(id)) setEditingOrderId(id);
      // Fjern query-param så den ikke åpnes igjen ved navigasjon
      const next = new URLSearchParams(searchParams);
      next.delete('edit');
      setSearchParams(next, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  const filteredOrders = orders.filter(o => {
    const customerName = o.customer || '';
    const orderId = o.orderId || '';
    const matchesSearch = customerName.toLowerCase().includes(search.toLowerCase()) ||
                         orderId.toLowerCase().includes(search.toLowerCase());
    const matchesStatus = statusFilter === 'all' || o.status === statusFilter;
    return matchesSearch && matchesStatus;
  });

  const formatDate = (dateStr) => {
    if (!dateStr) return '-';
    const date = new Date(dateStr);
    return date.toLocaleDateString('nb-NO', { day: 'numeric', month: 'short' });
  };

  if (loading) {
    return (
      <div className="p-8 flex items-center justify-center">
        <RefreshCw className="w-6 h-6 animate-spin text-amber-600" />
        <span className="ml-2 text-gray-500">Laster bestillinger...</span>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-[1400px] mx-auto">
      {/* Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">Bestillinger</h1>
          <p className="page-subtitle">{orders.length} bestillinger totalt</p>
        </div>
        <div className="flex gap-2">
          {selectedOrderIds.size > 0 && (
            <button
              onClick={bulkInvoice}
              className="px-3 py-1.5 bg-blue-600 text-white text-sm font-medium rounded hover:bg-blue-700 flex items-center gap-1.5"
              title="Fakturer valgte ordrer i SuSoft (en og en)"
            >
              <FileText className="w-4 h-4" /> Fakturer valgte ({selectedOrderIds.size})
            </button>
          )}
          <button onClick={fetchOrders} className="btn-secondary" title="Oppdater">
            <RefreshCw className="w-4 h-4" /> Oppdater
          </button>
          <button onClick={() => navigate('/bestillinger/ny')} className="btn-primary">
            <Plus className="w-4 h-4" /> Ny bestilling
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-md text-sm text-red-700">{error}</div>
      )}

      <div className="card p-0 overflow-hidden">
        {/* Filter-bar */}
        <div className="px-3 py-2 border-b border-gray-200 flex flex-wrap items-center gap-2 bg-white">
          <div className="flex items-center gap-1 bg-gray-100 rounded-md p-0.5">
            <button
              onClick={() => setVisibilityFilter('visible')}
              className={`px-3 py-1 rounded text-xs font-medium whitespace-nowrap transition-colors ${
                visibilityFilter === 'visible' ? 'bg-white shadow-sm text-gray-900' : 'text-gray-600 hover:text-gray-900'
              }`}
              title="Vis aktive ordrer"
            >
              Aktive
            </button>
            <button
              onClick={() => setVisibilityFilter('hidden')}
              className={`px-3 py-1 rounded text-xs font-medium whitespace-nowrap transition-colors flex items-center gap-1 ${
                visibilityFilter === 'hidden' ? 'bg-white shadow-sm text-gray-900' : 'text-gray-600 hover:text-gray-900'
              }`}
              title="Vis kun skjulte ordrer"
            >
              <EyeOff className="w-3 h-3" /> Skjulte
            </button>
          </div>
          <div className="flex items-center gap-1 bg-gray-100 rounded-md p-0.5 overflow-x-auto">
            <button
              onClick={() => setStatusFilter('all')}
              className={`px-3 py-1 rounded text-xs font-medium whitespace-nowrap transition-colors ${
                statusFilter === 'all' ? 'bg-white shadow-sm text-gray-900' : 'text-gray-600 hover:text-gray-900'
              }`}
            >
              Alle ({orders.length})
            </button>
            {Object.entries(statusConfig).map(([key, config]) => {
              const count = orders.filter(o => o.status === key).length;
              if (count === 0) return null;
              return (
                <button
                  key={key}
                  onClick={() => setStatusFilter(key)}
                  className={`px-3 py-1 rounded text-xs font-medium whitespace-nowrap transition-colors ${
                    statusFilter === key ? 'bg-white shadow-sm text-gray-900' : 'text-gray-600 hover:text-gray-900'
                  }`}
                >
                  {config.label} ({count})
                </button>
              );
            })}
          </div>
          <div className="relative flex-1 min-w-[220px]">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              type="text"
              placeholder="Søk og filtrer..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="input pl-8"
            />
          </div>
        </div>

        {filteredOrders.length === 0 ? (
          <div className="text-center py-16 text-gray-500 text-sm">
            {orders.length === 0 ? (
              <>
                <p className="text-base font-medium text-gray-700 mb-1">Ingen bestillinger ennå</p>
                <p>Klikk "Ny bestilling" for å opprette din første ordre</p>
              </>
            ) : (
              <p>Ingen bestillinger matcher søket</p>
            )}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="shop-table">
              <thead>
                <tr>
                  <th className="w-8">
                    <input
                      type="checkbox"
                      onChange={toggleSelectAllVisible}
                      checked={(() => {
                        const sel = filteredOrders.filter((o) => !o.susoftInvoiceNo && o.status !== 'cancelled');
                        return sel.length > 0 && sel.every((o) => selectedOrderIds.has(o.id));
                      })()}
                      title="Velg alle synlige (ufakturerte)"
                    />
                  </th>
                  <th>Ordre</th>
                  <th>Kunde</th>
                  <th>Ref.</th>
                  <th>Leveringsdato</th>
                  <th>Varer</th>
                  <th className="text-right">Total</th>
                  <th>Status</th>
                  <th>SuSoft</th>
                  <th className="text-right">Handlinger</th>
                </tr>
              </thead>
              <tbody>
                {filteredOrders.map((order) => {
                  const status = statusConfig[order.status] || { label: order.status, color: 'badge-neutral', icon: Clock };
                  const StatusIcon = status.icon;
                  return (
                    <tr key={order.id}>
                      <td>
                        {!order.susoftInvoiceNo && order.status !== 'cancelled' && (
                          <input
                            type="checkbox"
                            checked={selectedOrderIds.has(order.id)}
                            onChange={() => toggleSelectOrder(order.id)}
                          />
                        )}
                      </td>
                      <td>
                        <span className="font-mono font-medium text-gray-900">{order.orderId}</span>
                        {order.needsReview && (
                          <span className="ml-2 inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-amber-100 text-amber-800 text-[10px] font-semibold uppercase tracking-wide" title="Portal-ordre venter på godkjenning">
                            Trenger godkjenning
                          </span>
                        )}
                      </td>
                      <td className="text-gray-700">{order.customer}</td>
                      <td className="text-gray-500 text-sm">{order.reference || <span className="text-gray-300">&mdash;</span>}</td>
                      <td className="text-gray-700">{formatDate(order.deliveryDate)}</td>
                      <td className="text-gray-500">{order.items} varer</td>
                      <td className="text-right font-medium text-gray-900">
                        kr {(order.total || 0).toLocaleString('nb-NO', { minimumFractionDigits: 2 })}
                      </td>
                      <td>
                        <span className={`badge ${status.color}`}>
                          <StatusIcon className="w-3 h-3" />
                          {status.label}
                        </span>
                      </td>
                      <td>
                        {order.susoftOrderId ? (
                          <span className="badge badge-success" title={`SuSoft ID: ${order.susoftOrderId}`}>Synkronisert</span>
                        ) : order.syncStatus === 'failed' ? (
                          <span className="badge badge-danger cursor-help" title={order.syncError || 'Synkronisering feilet'}>Feilet</span>
                        ) : order.syncStatus === 'pending' ? (
                          <span className="badge badge-warning">Venter</span>
                        ) : (
                          <span className="text-gray-400 text-xs">—</span>
                        )}
                      </td>
                      <td>
                        <div className="flex items-center justify-end gap-1">
                          <button onClick={() => setEditingOrderId(order.id)} className="p-1.5 text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded" title="Se detaljer / rediger">
                            <Eye className="w-3.5 h-3.5" />
                          </button>
                          <button onClick={() => setEditingOrderId(order.id)} className="p-1.5 text-gray-400 hover:text-amber-700 hover:bg-amber-50 rounded" title="Rediger">
                            <Edit2 className="w-3.5 h-3.5" />
                          </button>
                          <button
                            onClick={async () => {
                              try {
                                const { openPdf } = await import('../utils/pdf');
                                await openPdf(authFetch, `/api/v1/reports/pdf/order/${order.id}/confirmation`);
                              } catch (e) { setError(e.message || 'Kunne ikke åpne PDF'); }
                            }}
                            className="p-1.5 text-gray-400 hover:text-blue-700 hover:bg-blue-50 rounded"
                            title="Ordrebekreftelse (PDF)"
                          >
                            <Download className="w-3.5 h-3.5" />
                          </button>
                          <button
                            onClick={async () => {
                              try {
                                const { openPdf } = await import('../utils/pdf');
                                await openPdf(authFetch, `/api/v1/reports/order/${order.id}/delivery.pdf`);
                              } catch (e) { setError(e.message || 'Kunne ikke åpne PDF'); }
                            }}
                            className="p-1.5 text-gray-400 hover:text-emerald-700 hover:bg-emerald-50 rounded"
                            title="Leveringsbekreftelse (PDF)"
                          >
                            <FileText className="w-3.5 h-3.5" />
                          </button>
                          {visibilityFilter === 'hidden' ? (
                            <button
                              onClick={() => restoreOrder(order)}
                              disabled={updatingOrderId === order.id}
                              className="p-1.5 text-gray-400 hover:text-green-700 hover:bg-green-50 rounded disabled:opacity-50"
                              title="Gjenopprett (vis i listen igjen)"
                            >
                              <Undo2 className="w-3.5 h-3.5" />
                            </button>
                          ) : (
                            <button
                              onClick={() => deleteOrder(order)}
                              disabled={updatingOrderId === order.id}
                              className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded disabled:opacity-50"
                              title={(order.susoftOrderId || order.susoftInvoiceNo) ? 'Skjul ordre (kan ikke slettes — er i SuSoft)' : 'Slett ordre'}
                            >
                              {(order.susoftOrderId || order.susoftInvoiceNo)
                                ? <EyeOff className="w-3.5 h-3.5" />
                                : <Trash2 className="w-3.5 h-3.5" />}
                            </button>
                          )}
                          {!order.susoftOrderId && order.status !== 'cancelled' && (
                            <button
                              onClick={() => sendToSusoft(order)}
                              disabled={updatingOrderId === order.id}
                              className="ml-1 px-2.5 py-1 bg-green-600 text-white text-xs font-medium rounded hover:bg-green-700 disabled:opacity-50 disabled:cursor-wait flex items-center gap-1"
                              title="Send ordren til SuSoft (ignorerer cut-off)"
                            >
                              {updatingOrderId === order.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Send className="w-3 h-3" />}
                              Send
                            </button>
                          )}
                          {order.susoftOrderId && order.syncStatus === 'failed' && (
                            <button
                              onClick={() => sendToSusoft(order)}
                              disabled={updatingOrderId === order.id}
                              className="ml-1 px-2.5 py-1 bg-orange-600 text-white text-xs font-medium rounded hover:bg-orange-700 disabled:opacity-50 disabled:cursor-wait flex items-center gap-1"
                              title="Prøv igjen"
                            >
                              {updatingOrderId === order.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
                              Prøv igjen
                            </button>
                          )}
                          {order.susoftInvoiceNo ? (
                            <span
                              className="ml-1 px-2.5 py-1 bg-gray-100 text-gray-700 text-xs font-medium rounded flex items-center gap-1"
                              title={`Fakturert ${order.invoicedAt ? new Date(order.invoicedAt).toLocaleString('nb-NO') : ''}`}
                            >
                              <FileText className="w-3 h-3" />
                              Faktura #{order.susoftInvoiceNo}
                            </span>
                          ) : (
                            order.status !== 'cancelled' && (
                              <button
                                onClick={() => invoiceOrder(order)}
                                disabled={updatingOrderId === order.id}
                                className="ml-1 px-2.5 py-1 bg-blue-600 text-white text-xs font-medium rounded hover:bg-blue-700 disabled:opacity-50 disabled:cursor-wait flex items-center gap-1"
                                title="Send som faktura til SuSoft"
                              >
                                {updatingOrderId === order.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <FileText className="w-3 h-3" />}
                                Fakturer
                              </button>
                            )
                          )}
                          {order.susoftOrderId && !order.susoftInvoiceNo && (
                            <button
                              onClick={() => resetSusoftLink(order)}
                              disabled={updatingOrderId === order.id}
                              className="ml-1 px-2 py-1 text-xs text-gray-500 hover:text-red-600 hover:bg-red-50 rounded disabled:opacity-50"
                              title="Nullstill SuSoft-kobling (re-send med riktige beløp)"
                            >
                              Nullstill
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {editingOrderId && (
        <OrderEditModal
          orderId={editingOrderId}
          onClose={() => setEditingOrderId(null)}
          onSaved={() => { setEditingOrderId(null); fetchOrders(); }}
          onDeleted={() => { setEditingOrderId(null); fetchOrders(); }}
        />
      )}

      {bulkProgress && (
        <BulkInvoiceModal
          progress={bulkProgress}
          onClose={() => setBulkProgress(null)}
        />
      )}
    </div>
  );
}

function BulkInvoiceModal({ progress, onClose }) {
  const { running, total, current, done, results = [], currentOrderId } = progress;
  const okCount = results.filter((r) => r.ok).length;
  const failCount = results.filter((r) => !r.ok).length;
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg shadow-xl max-w-lg w-full max-h-[80vh] flex flex-col">
        <div className="px-5 py-3 border-b border-gray-200 flex items-center justify-between">
          <h2 className="text-base font-semibold text-gray-900">
            {running ? 'Fakturerer ordrer...' : 'Fakturering ferdig'}
          </h2>
          {!running && (
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
              <X className="w-5 h-5" />
            </button>
          )}
        </div>

        <div className="px-5 py-4 border-b border-gray-200">
          <div className="flex justify-between text-sm text-gray-600 mb-1">
            <span>{done} av {total} fullf\u00f8rt</span>
            <span>{pct}%</span>
          </div>
          <div className="w-full bg-gray-200 rounded-full h-2">
            <div
              className="bg-blue-600 h-2 rounded-full transition-all"
              style={{ width: `${pct}%` }}
            />
          </div>
          {running && currentOrderId && (
            <p className="text-xs text-gray-500 mt-2 flex items-center gap-1">
              <Loader2 className="w-3 h-3 animate-spin" /> Behandler {currentOrderId} ({current}/{total})
            </p>
          )}
          {!running && (
            <p className="text-xs text-gray-600 mt-2">
              <span className="text-green-700 font-medium">{okCount} OK</span>
              {failCount > 0 && <span className="text-red-700 font-medium ml-3">{failCount} feilet</span>}
            </p>
          )}
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-2">
          <ul className="text-sm divide-y divide-gray-100">
            {results.map((r, i) => (
              <li key={i} className="py-2 flex items-start gap-2">
                {r.ok ? (
                  <Check className="w-4 h-4 text-green-600 mt-0.5 flex-shrink-0" />
                ) : (
                  <AlertTriangle className="w-4 h-4 text-red-600 mt-0.5 flex-shrink-0" />
                )}
                <div className="flex-1 min-w-0">
                  <div className="font-mono text-xs text-gray-700">{r.orderId} \u2014 {r.customer}</div>
                  <div className={`text-xs ${r.ok ? 'text-gray-600' : 'text-red-700'} break-words`}>{r.message}</div>
                </div>
              </li>
            ))}
          </ul>
        </div>

        {!running && (
          <div className="px-5 py-3 border-t border-gray-200 flex justify-end">
            <button onClick={onClose} className="btn-primary text-sm">Lukk</button>
          </div>
        )}
      </div>
    </div>
  );
}

function OrderEditModal({ orderId, onClose, onSaved, onDeleted }) {
  const { authFetch } = useAuth();
  const [order, setOrder] = useState(null);
  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [deliveryDate, setDeliveryDate] = useState('');
  const [referenceText, setReferenceText] = useState('');
  const [internalNotes, setInternalNotes] = useState('');
  const [customerNotes, setCustomerNotes] = useState('');
  const [amendments, setAmendments] = useState([]);
  const [showAmendForm, setShowAmendForm] = useState(false);
  const [amendReason, setAmendReason] = useState('');
  const [amendNewRef, setAmendNewRef] = useState('');
  const [showAddPicker, setShowAddPicker] = useState(false);
  const [pickerSearch, setPickerSearch] = useState('');
  // Lokal state for quantity per linje, slik at vi unngår race mellom onBlur og Lagre.
  const [pendingQtys, setPendingQtys] = useState({}); // {[lineId]: number}

  const load = async () => {
    setLoading(true);
    try {
      const [ordRes, prodRes] = await Promise.all([
        authFetch(`/api/v1/orders/${orderId}`),
        authFetch(`/api/v1/products?page_size=2000&is_active=true`),
      ]);
      if (!ordRes.ok) throw new Error('Kunne ikke hente ordre');
      if (!prodRes.ok) throw new Error('Kunne ikke hente produkter');
      const ord = await ordRes.json();
      const prods = await prodRes.json();
      setOrder(ord);
      setProducts(prods.items || []);
      setDeliveryDate(ord.delivery_date || '');
      setReferenceText(ord.reference || '');
      setInternalNotes(ord.internal_notes || '');
      setCustomerNotes(ord.customer_notes || '');
      // Hent amendments (best-effort)
      try {
        const aRes = await authFetch(`/api/v1/orders/${orderId}/amendments`);
        if (aRes.ok) setAmendments(await aRes.json());
      } catch { /* ignore */ }
      // Initialiser lokale qty-verdier fra serveren
      const qtyMap = {};
      (ord.lines || []).forEach((l) => { qtyMap[l.id] = l.quantity; });
      setPendingQtys(qtyMap);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [orderId]);

  const isLocked = order?.is_locked;
  const productById = new Map(products.map((p) => [p.id, p]));

  const updateLineQty = async (line, newQty) => {
    if (newQty < 1) return;
    try {
      const res = await authFetch(`/api/v1/orders/${orderId}/lines/${line.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ quantity: newQty }),
      });
      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || 'Kunne ikke oppdatere linje');
      }
      await load();
    } catch (e) {
      alert(`Feil: ${e.message}`);
    }
  };

  const removeLine = async (line) => {
    if (!confirm(`Fjerne ${line.quantity}× ${productById.get(line.product_id)?.name || 'produkt'}?`)) return;
    try {
      const res = await authFetch(`/api/v1/orders/${orderId}/lines/${line.id}`, { method: 'DELETE' });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || 'Kunne ikke slette linje');
      }
      await load();
    } catch (e) {
      alert(`Feil: ${e.message}`);
    }
  };

  const addProduct = async (productId) => {
    try {
      const res = await authFetch(`/api/v1/orders/${orderId}/lines`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ product_id: productId, quantity: 1 }),
      });
      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || 'Kunne ikke legge til linje');
      }
      setShowAddPicker(false);
      setPickerSearch('');
      await load();
    } catch (e) {
      alert(`Feil: ${e.message}`);
    }
  };

  const saveHeader = async () => {
    setSaving(true);
    try {
      // 1) Flush alle pending qty-endringer FØRST (await sekvensielt)
      const lineEdits = (order?.lines || []).filter((l) => {
        const newQty = pendingQtys[l.id];
        return newQty != null && newQty !== l.quantity && newQty >= 1;
      });
      for (const l of lineEdits) {
        const res = await authFetch(`/api/v1/orders/${orderId}/lines/${l.id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ quantity: pendingQtys[l.id] }),
        });
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.detail || `Kunne ikke lagre linje ${l.id}`);
        }
      }

      // 2) Lagre header-felter
      const body = {};
      if (deliveryDate && deliveryDate !== order.delivery_date) body.delivery_date = deliveryDate;
      if (referenceText !== (order.reference || '')) body.reference = referenceText || null;
      if (internalNotes !== (order.internal_notes || '')) body.internal_notes = internalNotes;
      if (customerNotes !== (order.customer_notes || '')) body.customer_notes = customerNotes;
      if (Object.keys(body).length > 0) {
        const res = await authFetch(`/api/v1/orders/${orderId}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.detail || 'Kunne ikke lagre');
        }
      }
      onSaved();
    } catch (e) {
      alert(`Feil: ${e.message}`);
    } finally {
      setSaving(false);
    }
  };

  const deleteOrderHere = async () => {
    if (!confirm(`Slette ordre #${orderId}?\n\nDette kan ikke angres.`)) return;
    try {
      const res = await authFetch(`/api/v1/orders/${orderId}`, { method: 'DELETE' });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || 'Kunne ikke slette');
      }
      onDeleted();
    } catch (e) {
      alert(`Feil: ${e.message}`);
    }
  };

  const filteredPickerProducts = (() => {
    const term = pickerSearch.trim().toLowerCase();
    const inUse = new Set((order?.lines || []).map((l) => l.product_id));
    return products
      .filter((p) => !inUse.has(p.id))
      .filter((p) => !term || p.name.toLowerCase().includes(term) || (p.sku || '').toLowerCase().includes(term))
      .slice(0, 50);
  })();

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-xl max-w-3xl w-full max-h-[92vh] overflow-y-auto m-4">
        <div className="p-5 border-b flex items-center justify-between sticky top-0 bg-white z-10">
          <div>
            <h2 className="text-lg font-semibold">
              Ordre #{orderId}{order ? ` — ${order.customer_name || `Kunde ${order.customer_id}`}` : ''}
            </h2>
            {order && (
              <p className="text-xs text-gray-500">
                Status: {order.status} · Sync: {order.sync_status}
                {order.susoft_order_id ? ` · SuSoft #${order.susoft_order_id}` : ''}
              </p>
            )}
          </div>
          <button onClick={onClose} className="p-2 hover:bg-gray-100 rounded"><X className="w-5 h-5" /></button>
        </div>

        <div className="p-5 space-y-5">
          {error && (
            <div className="p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">{error}</div>
          )}

          {loading ? (
            <div className="flex items-center justify-center py-10 text-gray-500">
              <RefreshCw className="w-5 h-5 animate-spin mr-2" /> Laster...
            </div>
          ) : (
            <>
              {isLocked && (
                <div className="p-3 bg-amber-50 border border-amber-200 rounded text-sm text-amber-800 flex items-start gap-2">
                  <AlertTriangle className="w-4 h-4 mt-0.5 flex-shrink-0" />
                  <div>
                    Ordren er låst etter cut-off (kl. 15:00 dagen før levering). Endringer er ikke tillatt.
                  </div>
                </div>
              )}

              {/* Header-felt */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="label">Leveringsdato</label>
                  <input
                    type="date"
                    value={deliveryDate}
                    onChange={(e) => setDeliveryDate(e.target.value)}
                    disabled={isLocked}
                    className="input"
                  />
                </div>
                <div>
                  <label className="label">Total inkl. mva</label>
                  <div className="input bg-gray-50 font-medium">
                    kr {Number(order?.total_amount_incl_vat || 0).toLocaleString('nb-NO', { minimumFractionDigits: 2 })}
                  </div>
                </div>
                <div className="col-span-2">
                  <label className="label">Referanse (PO-nr / plan / prosjekt)</label>
                  <input
                    type="text"
                    value={referenceText}
                    onChange={(e) => setReferenceText(e.target.value)}
                    placeholder="F.eks. Plan-Q4-2026 eller PO-1234"
                    className="input"
                  />
                  <p className="text-xs text-gray-500 mt-1">
                    Vises på leveringsbekreftelsen. Endring etter cut-off logges som avvik.
                  </p>
                </div>
                <div className="col-span-2">
                  <label className="label">Interne notater</label>
                  <textarea
                    value={internalNotes}
                    onChange={(e) => setInternalNotes(e.target.value)}
                    disabled={isLocked}
                    rows={2}
                    className="input"
                  />
                </div>
                <div className="col-span-2">
                  <label className="label">Notater til kunde</label>
                  <textarea
                    value={customerNotes}
                    onChange={(e) => setCustomerNotes(e.target.value)}
                    disabled={isLocked}
                    rows={2}
                    className="input"
                  />
                </div>
              </div>

              {/* Linjer */}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <h3 className="font-medium text-gray-900">Linjer ({order?.lines?.length || 0})</h3>
                  {!isLocked && (
                    <button
                      onClick={() => setShowAddPicker((v) => !v)}
                      className="text-sm text-amber-700 hover:text-amber-800 flex items-center gap-1"
                    >
                      <Plus className="w-4 h-4" /> Legg til produkt
                    </button>
                  )}
                </div>

                {showAddPicker && !isLocked && (
                  <div className="mb-3 border rounded-md p-3 bg-gray-50">
                    <input
                      type="text"
                      placeholder="Søk produkt..."
                      value={pickerSearch}
                      onChange={(e) => setPickerSearch(e.target.value)}
                      className="input mb-2"
                      autoFocus
                    />
                    <div className="max-h-48 overflow-y-auto space-y-1">
                      {filteredPickerProducts.length === 0 ? (
                        <p className="text-sm text-gray-500 italic">Ingen treff</p>
                      ) : filteredPickerProducts.map((p) => (
                        <button
                          key={p.id}
                          onClick={() => addProduct(p.id)}
                          className="w-full text-left px-2 py-1.5 text-sm hover:bg-amber-100 rounded flex justify-between"
                        >
                          <span>{p.name}</span>
                          <span className="text-gray-500 text-xs">{p.sku || ''}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                <div className="border rounded-md divide-y">
                  {(order?.lines || []).length === 0 ? (
                    <p className="p-4 text-sm text-gray-500 italic text-center">Ingen linjer</p>
                  ) : (order.lines || []).map((line) => {
                    const product = productById.get(line.product_id);
                    return (
                      <div key={line.id} className="flex items-center gap-2 p-2.5">
                        <div className="flex-1">
                          <div className="text-sm font-medium text-gray-900">{product?.name || `Produkt #${line.product_id}`}</div>
                          <div className="text-xs text-gray-500">
                            {(() => {
                              const qty = Number(line.quantity) || 0;
                              const incl = Number(line.line_amount_incl_vat) || 0;
                              const unitIncl = qty > 0 ? incl / qty : Number(line.unit_price) || 0;
                              return `kr ${unitIncl.toLocaleString('nb-NO', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} pr. stk`;
                            })()}
                            {line.is_adhoc_quantity && line.original_template_quantity != null && (
                              <span className="ml-2 text-amber-700">(opprinnelig {line.original_template_quantity})</span>
                            )}
                          </div>
                        </div>
                        <input
                          type="number"
                          min="1"
                          value={pendingQtys[line.id] ?? line.quantity}
                          disabled={isLocked}
                          onChange={(e) => {
                            const v = parseInt(e.target.value, 10);
                            setPendingQtys((prev) => ({ ...prev, [line.id]: Number.isNaN(v) ? '' : v }));
                          }}
                          className={`input w-20 text-right ${pendingQtys[line.id] != null && pendingQtys[line.id] !== line.quantity ? 'border-amber-400 bg-amber-50' : ''}`}
                        />
                        <div className="w-24 text-right text-sm font-medium text-gray-900">
                          kr {Number(line.line_amount_incl_vat).toLocaleString('nb-NO', { minimumFractionDigits: 2 })}
                        </div>
                        <button
                          onClick={() => removeLine(line)}
                          disabled={isLocked}
                          className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded disabled:opacity-30"
                          title="Fjern linje"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Avvik / Endringer */}
              <div className="border-t pt-4">
                <div className="flex items-center justify-between mb-2">
                  <h3 className="font-medium text-gray-900">Avvik / Endringer ({amendments.length})</h3>
                  <button
                    onClick={() => setShowAmendForm((v) => !v)}
                    className="text-sm text-amber-700 hover:text-amber-800 flex items-center gap-1"
                  >
                    <Plus className="w-4 h-4" /> Registrer avvik
                  </button>
                </div>
                {showAmendForm && (
                  <div className="mb-3 border rounded-md p-3 bg-amber-50 space-y-2">
                    <div>
                      <label className="label">Begrunnelse / årsak</label>
                      <textarea
                        value={amendReason}
                        onChange={(e) => setAmendReason(e.target.value)}
                        rows={2}
                        className="input"
                        placeholder="F.eks. Manglende rundstykker — erstattet med..."
                      />
                    </div>
                    <div>
                      <label className="label">Ny referanse (valgfri — overskriver ordrereferanse)</label>
                      <input
                        type="text"
                        value={amendNewRef}
                        onChange={(e) => setAmendNewRef(e.target.value)}
                        className="input"
                      />
                    </div>
                    <div className="flex justify-end gap-2">
                      <button onClick={() => { setShowAmendForm(false); setAmendReason(''); setAmendNewRef(''); }} className="btn-secondary text-sm">Avbryt</button>
                      <button
                        onClick={async () => {
                          if (!amendReason.trim()) { alert('Begrunnelse er påkrevd'); return; }
                          try {
                            const res = await authFetch(`/api/v1/orders/${orderId}/amendments`, {
                              method: 'POST',
                              headers: { 'Content-Type': 'application/json' },
                              body: JSON.stringify({
                                reason: amendReason.trim(),
                                reference: amendNewRef.trim() || null,
                              }),
                            });
                            if (!res.ok) {
                              const err = await res.json().catch(() => ({}));
                              throw new Error(err.detail || 'Kunne ikke lagre avvik');
                            }
                            setShowAmendForm(false);
                            setAmendReason('');
                            setAmendNewRef('');
                            await load();
                          } catch (e) {
                            alert(`Feil: ${e.message}`);
                          }
                        }}
                        className="btn-primary text-sm"
                      >
                        Lagre avvik
                      </button>
                    </div>
                  </div>
                )}
                {amendments.length === 0 ? (
                  <p className="text-sm text-gray-500">Ingen registrerte endringer.</p>
                ) : (
                  <div className="space-y-2">
                    {amendments.map((a) => (
                      <div key={a.id} className="border rounded p-2 text-sm bg-white">
                        <div className="flex justify-between text-xs text-gray-500">
                          <span>{new Date(a.amended_at).toLocaleString('nb-NO')}</span>
                          {a.reference && <span>Ny ref: <strong>{a.reference}</strong></span>}
                        </div>
                        <div className="text-gray-900 mt-1">{a.reason}</div>
                        {a.changes_summary && <div className="text-gray-600 text-xs mt-1">{a.changes_summary}</div>}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </>
          )}
        </div>

        <div className="p-5 border-t flex justify-between gap-3 sticky bottom-0 bg-white">
          <button
            onClick={deleteOrderHere}
            disabled={isLocked || saving}
            className="px-4 py-2 text-red-600 hover:bg-red-50 rounded-lg flex items-center gap-2 disabled:opacity-50"
          >
            <Trash2 className="w-4 h-4" /> Slett ordre
          </button>
          <div className="flex gap-2">
            <button onClick={onClose} className="btn-secondary">Lukk</button>
            <button
              onClick={saveHeader}
              disabled={isLocked || saving}
              className="btn-primary disabled:opacity-50"
            >
              {saving ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
              Lagre endringer
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
