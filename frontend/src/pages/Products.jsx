import { useState, useEffect, useMemo } from 'react';
import { Search, Filter, Plus, Edit2, Trash2, RefreshCw, Package, Eye, EyeOff, X } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import Pagination from '../components/Pagination';
import SearchInput from '../components/SearchInput';

// Category names in Norwegian
const categoryNames = {
  'BROD': 'Brød',
  'BOLLER': 'Boller',
  'WIENERBROD': 'Wienerbrød',
  'KAKER': 'Kaker',
  'SMABAKST': 'Småbakst',
  'SMORBROD': 'Smørbrød',
  'KAFFE': 'Kaffe & Drikke',
  'KAKESTK': 'Kake (stykk)',
  'KAKEHEL': 'Kake (hel)',
  'MINVANN': 'Mineralvann',
  'FERSK': 'Ferskvarer',
};

const categoryColors = {
  'BROD': 'bg-amber-100 text-amber-800',
  'BOLLER': 'bg-orange-100 text-orange-800',
  'WIENERBROD': 'bg-yellow-100 text-yellow-800',
  'KAKER': 'bg-pink-100 text-pink-800',
  'SMABAKST': 'bg-purple-100 text-purple-800',
  'SMORBROD': 'bg-green-100 text-green-800',
  'KAFFE': 'bg-brown-100 text-stone-800',
  'KAKESTK': 'bg-rose-100 text-rose-800',
  'KAKEHEL': 'bg-red-100 text-red-800',
  'MINVANN': 'bg-blue-100 text-blue-800',
  'FERSK': 'bg-teal-100 text-teal-800',
};

export default function Products() {
  const { authFetch } = useAuth();
  const [products, setProducts] = useState([]);
  const [search, setSearch] = useState('');
  const [selectedCategory, setSelectedCategory] = useState('all');
  const [statusFilter, setStatusFilter] = useState('active');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [selectedIds, setSelectedIds] = useState(() => new Set());
  const [allCategories, setAllCategories] = useState([]);
  const [editingProduct, setEditingProduct] = useState(null);

  const fetchProducts = async (searchTerm = '') => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ page_size: '500' });
      if (statusFilter === 'active') params.set('is_active', 'true');
      else if (statusFilter === 'inactive') params.set('is_active', 'false');
      if (searchTerm.trim()) params.set('search', searchTerm.trim());
      const response = await authFetch(`/api/v1/products?${params.toString()}`);
      if (!response.ok) throw new Error('Kunne ikke hente produkter');
      const data = await response.json();
      // Map API fields to component expected format
      const mapped = (data.items || []).map(p => ({
        id: p.susoft_product_id || p.id,
        dbId: p.id,
        name: p.name,
        description: p.description || '',
        category: p.category || 'ANNET',
        retailPrice: p.default_price || 0,
        unit: p.unit || 'stk',
        active: p.is_active,
        allergens: p.allergens || '',
        batch_size: p.batch_size ?? 1,
        production_step: p.production_step || '',
        production_lead_minutes: p.production_lead_minutes ?? 0,
        production_days: p.production_days ?? 0,
      }));
      setProducts(mapped);
      setError(null);
    } catch (err) {
      console.error('Error loading products:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    // Hent ved monter + naar status endres. Soketekst trigges via SearchInput.
    fetchProducts(search);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter]);

  // Hent alle kategorier (uavhengig av status/sok-filter) for kategorimenyen
  useEffect(() => {
    (async () => {
      try {
        const r = await authFetch('/api/v1/products/categories');
        if (!r.ok) return;
        const cats = await r.json();
        const sorted = (cats || [])
          .filter(Boolean)
          .sort((a, b) => (categoryNames[a] || a).localeCompare(categoryNames[b] || b, 'no'));
        setAllCategories(sorted);
      } catch { /* ignore */ }
    })();
  }, []);

  const toggleActive = async (product) => {
    const next = !product.active;
    if (!next && !confirm(`Skjul "${product.name}"? Produktet blir skjult fra lister.`)) return;
    try {
      const response = await authFetch(`/api/v1/products/${product.dbId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_active: next })
      });
      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.detail || 'Kunne ikke endre status');
      }
      setProducts((prev) => prev.map(p => p.dbId === product.dbId ? { ...p, active: next } : p));
    } catch (err) {
      alert(err.message);
    }
  };

  const toggleSelected = (dbId) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(dbId)) next.delete(dbId); else next.add(dbId);
      return next;
    });
  };

  const bulkSetActive = async (isActive) => {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) return;
    const verb = isActive ? 'vise' : 'skjule';
    if (!confirm(`Vil du ${verb} ${ids.length} valgte ${ids.length === 1 ? 'produkt' : 'produkter'}?`)) return;
    try {
      const response = await authFetch('/api/v1/products/bulk/set-active', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids, is_active: isActive })
      });
      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.detail || 'Kunne ikke oppdatere');
      }
      setProducts((prev) => prev.map(p => ids.includes(p.dbId) ? { ...p, active: isActive } : p));
      setSelectedIds(new Set());
    } catch (err) {
      alert(err.message);
    }
  };

  // Get unique categories (kombiner alle kjente med de som finnes i synlige produkter)
  const categories = [...new Set([...allCategories, ...products.map(p => p.category)])]
    .filter(Boolean)
    .sort((a, b) => (categoryNames[a] || a).localeCompare(categoryNames[b] || b, 'no'));
  const activeCount = products.filter(p => p.active).length;
  const inactiveCount = products.length - activeCount;

  // Filter products (search now done server-side)
  const filteredProducts = products.filter(p => {
    const matchesCategory = selectedCategory === 'all' || p.category === selectedCategory;
    const matchesStatus =
      statusFilter === 'all' ||
      (statusFilter === 'active' && p.active) ||
      (statusFilter === 'inactive' && !p.active);
    return matchesCategory && matchesStatus;
  });

  // Group by category for display
  const groupedProducts = filteredProducts.reduce((acc, product) => {
    const cat = product.category;
    if (!acc[cat]) acc[cat] = [];
    acc[cat].push(product);
    return acc;
  }, {});

  // Reset page when filters change
  useEffect(() => { setPage(1); setSelectedIds(new Set()); }, [search, statusFilter, selectedCategory, pageSize]);

  const pagedProducts = useMemo(() => {
    const start = (page - 1) * pageSize;
    return filteredProducts.slice(start, start + pageSize);
  }, [filteredProducts, page, pageSize]);

  if (loading && products.length === 0) {
    return (
      <div className="p-8 flex items-center justify-center">
        <RefreshCw className="w-6 h-6 animate-spin text-amber-600" />
        <span className="ml-2 text-gray-500">Laster produkter...</span>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-[1400px] mx-auto">
      {/* Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">Produkter</h1>
          <p className="page-subtitle">{products.length} produkter fra databasen</p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => fetchProducts(search)} className="btn-secondary" title="Oppdater">
            <RefreshCw className="w-4 h-4" /> Oppdater
          </button>
          <button className="btn-primary">
            <Plus className="w-4 h-4" /> Nytt produkt
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-md text-sm text-red-700">{error}</div>
      )}

      <div className="card p-0 overflow-hidden">
        {/* Filter-bar */}
        <div className="px-3 py-2 border-b border-gray-200 flex flex-wrap items-center gap-2 bg-white">
          <div className="flex gap-1 bg-gray-100 rounded-md p-0.5">
            <button
              onClick={() => setStatusFilter('all')}
              className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                statusFilter === 'all' ? 'bg-white shadow-sm text-gray-900' : 'text-gray-600 hover:text-gray-900'
              }`}
            >
              Alle ({products.length})
            </button>
            <button
              onClick={() => setStatusFilter('active')}
              className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                statusFilter === 'active' ? 'bg-white shadow-sm text-gray-900' : 'text-gray-600 hover:text-gray-900'
              }`}
            >
              Aktive ({activeCount})
            </button>
            <button
              onClick={() => setStatusFilter('inactive')}
              className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                statusFilter === 'inactive' ? 'bg-white shadow-sm text-gray-900' : 'text-gray-600 hover:text-gray-900'
              }`}
            >
              Skjulte ({inactiveCount})
            </button>
          </div>
          <select
            value={selectedCategory}
            onChange={(e) => setSelectedCategory(e.target.value)}
            className="input w-auto min-w-[220px]"
          >
            <option value="all">Alle kategorier</option>
            {categories.map(cat => (
              <option key={cat} value={cat}>{categoryNames[cat] || cat}</option>
            ))}
          </select>
          <div className="relative flex-1 min-w-[220px]">
            <SearchInput
              value={search}
              onChange={setSearch}
              onSearch={(term) => fetchProducts(term)}
              placeholder="Sok produkt (min. 3 tegn, Enter for aa tvinge)"
              minChars={3}
              ariaLabel="Sok produkter"
            />
          </div>
        </div>

        {filteredProducts.length === 0 ? (
          <div className="text-center py-16">
            <Package className="w-10 h-10 text-gray-300 mx-auto mb-3" />
            <h3 className="text-base font-medium text-gray-700 mb-1">Ingen produkter funnet</h3>
            <p className="text-sm text-gray-500">Prøv å endre søket eller filteret</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            {selectedIds.size > 0 && (
              <div className="px-3 py-2 border-b border-amber-200 bg-amber-50 flex items-center gap-2 text-sm flex-wrap">
                <span className="font-medium text-amber-900">{selectedIds.size} valgt</span>
                <button onClick={() => bulkSetActive(false)} className="btn-secondary !py-1 !text-xs">
                  <EyeOff className="w-3.5 h-3.5" /> Skjul valgte
                </button>
                <button onClick={() => bulkSetActive(true)} className="btn-secondary !py-1 !text-xs">
                  <Eye className="w-3.5 h-3.5" /> Vis valgte
                </button>
                <button onClick={() => setSelectedIds(new Set())} className="text-xs text-gray-600 hover:text-gray-900 ml-auto">
                  Fjern utvalg
                </button>
              </div>
            )}
            <table className="shop-table">
              <thead>
                <tr>
                  <th className="w-8">
                    <input
                      type="checkbox"
                      checked={pagedProducts.length > 0 && pagedProducts.every(p => selectedIds.has(p.dbId))}
                      onChange={(e) => {
                        const next = new Set(selectedIds);
                        if (e.target.checked) pagedProducts.forEach(p => next.add(p.dbId));
                        else pagedProducts.forEach(p => next.delete(p.dbId));
                        setSelectedIds(next);
                      }}
                      title="Velg alle paa siden"
                    />
                  </th>
                  <th>Produkt</th>
                  <th>Kategori</th>
                  <th>SKU</th>
                  <th className="text-right">Pris</th>
                  <th>Enhet</th>
                  <th>Status</th>
                  <th className="text-right">Handlinger</th>
                </tr>
              </thead>
              <tbody>
                {pagedProducts.map((product) => (
                  <tr key={product.id} className={selectedIds.has(product.dbId) ? 'bg-amber-50/50' : ''}>
                    <td>
                      <input
                        type="checkbox"
                        checked={selectedIds.has(product.dbId)}
                        onChange={() => toggleSelected(product.dbId)}
                      />
                    </td>
                    <td>
                      <div className="flex items-center gap-2.5">
                        <div className="w-7 h-7 bg-amber-100 rounded flex items-center justify-center flex-shrink-0">
                          <Package className="w-3.5 h-3.5 text-amber-600" />
                        </div>
                        <div className="min-w-0">
                          <div className="font-medium text-gray-900 truncate">{product.name}</div>
                          {product.description && (
                            <div className="text-xs text-gray-500 truncate max-w-[300px]">{product.description}</div>
                          )}
                          {product.allergens && (
                            <div className="text-xs text-amber-700 truncate max-w-[300px]" title={product.allergens}>
                              Allergener: {product.allergens}
                            </div>
                          )}
                        </div>
                      </div>
                    </td>
                    <td>
                      <span className={`badge ${categoryColors[product.category] ? '' : 'badge-neutral'} ${categoryColors[product.category] || ''}`}>
                        {categoryNames[product.category] || product.category || '—'}
                      </span>
                    </td>
                    <td className="text-gray-500 text-xs font-mono">{product.id}</td>
                    <td className="text-right font-medium text-gray-900">
                      kr {(product.retailPrice || 0).toLocaleString('nb-NO', { minimumFractionDigits: 2 })}
                    </td>
                    <td className="text-gray-700 text-xs">{product.unit}</td>
                    <td>
                      <span className={`badge ${product.active ? 'badge-success' : 'badge-neutral'}`}>
                        {product.active ? 'Aktiv' : 'Skjult'}
                      </span>
                    </td>
                    <td>
                      <div className="flex items-center justify-end gap-1">
                        <button
                          onClick={() => toggleActive(product)}
                          className={`p-1.5 rounded ${
                            product.active
                              ? 'text-gray-400 hover:text-amber-700 hover:bg-amber-50'
                              : 'text-amber-600 hover:text-green-700 hover:bg-green-50'
                          }`}
                          title={product.active ? 'Skjul produkt' : 'Vis produkt igjen'}
                        >
                          {product.active ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                        </button>
                        <button onClick={() => setEditingProduct(product)} className="p-1.5 text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded" title="Rediger produksjonsfelt">
                          <Edit2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pagination
              page={page}
              pageSize={pageSize}
              total={filteredProducts.length}
              onPageChange={setPage}
              onPageSizeChange={setPageSize}
            />
          </div>
        )}
      </div>

      {editingProduct && (
        <ProductionEditModal
          product={editingProduct}
          onClose={() => setEditingProduct(null)}
          onSaved={(updated) => {
            setProducts((prev) => prev.map(p => p.dbId === updated.dbId ? { ...p, ...updated } : p));
            setEditingProduct(null);
          }}
          authFetch={authFetch}
        />
      )}
    </div>
  );
}


function ProductionEditModal({ product, onClose, onSaved, authFetch }) {
  const [batchSize, setBatchSize] = useState(product.batch_size ?? 1);
  const [productionStep, setProductionStep] = useState(product.production_step || '');
  const [leadMinutes, setLeadMinutes] = useState(product.production_lead_minutes ?? 0);
  const [productionDays, setProductionDays] = useState(product.production_days ?? 0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const save = async (e) => {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      const response = await authFetch(`/api/v1/products/${product.dbId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          batch_size: Math.max(1, parseInt(batchSize, 10) || 1),
          production_step: productionStep.trim() || null,
          production_lead_minutes: Math.max(0, parseInt(leadMinutes, 10) || 0),
          production_days: Math.max(0, Math.min(14, parseInt(productionDays, 10) || 0)),
        }),
      });
      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.detail || 'Kunne ikke lagre');
      }
      onSaved({
        dbId: product.dbId,
        batch_size: Math.max(1, parseInt(batchSize, 10) || 1),
        production_step: productionStep.trim() || '',
        production_lead_minutes: Math.max(0, parseInt(leadMinutes, 10) || 0),
        production_days: Math.max(0, Math.min(14, parseInt(productionDays, 10) || 0)),
      });
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-md">
        <div className="flex items-center justify-between px-5 py-3 border-b">
          <h2 className="text-lg font-semibold text-gray-900">Produksjon: {product.name}</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700">
            <X className="w-5 h-5" />
          </button>
        </div>
        <form onSubmit={save} className="p-5 space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Batch-størrelse
              <span className="ml-1 text-xs text-gray-500">(antall pr. ovn/deig)</span>
            </label>
            <input
              type="number"
              min="1"
              value={batchSize}
              onChange={(e) => setBatchSize(e.target.value)}
              className="input"
              required
            />
            <p className="text-xs text-gray-500 mt-1">
              Bestilt antall rundes opp til nærmeste batch i produksjonsplanen.
            </p>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Produksjons-stasjon
            </label>
            <input
              type="text"
              value={productionStep}
              onChange={(e) => setProductionStep(e.target.value)}
              className="input"
              placeholder="f.eks. Ovn 1, Bakebenk, Stekeovn"
              maxLength={100}
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Tid pr. batch (minutter)
              <span className="ml-1 text-xs text-gray-500">(heving + steking)</span>
            </label>
            <input
              type="number"
              min="0"
              value={leadMinutes}
              onChange={(e) => setLeadMinutes(e.target.value)}
              className="input"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Produksjonsdager
              <span className="ml-1 text-xs text-gray-500">(øker tidligst leveringsdato)</span>
            </label>
            <input
              type="number"
              min="0"
              max="14"
              value={productionDays}
              onChange={(e) => setProductionDays(e.target.value)}
              className="input"
            />
            <p className="text-xs text-gray-500 mt-1">
              Antall ekstra produksjonsdager varen krever. 0 = ingen ekstra ventetid.
              Hvis ordren inneholder flere varer er det den med flest produksjonsdager som gjelder.
            </p>
          </div>
          {error && (
            <div className="p-2 bg-red-50 border border-red-200 rounded text-sm text-red-700">{error}</div>
          )}
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={onClose} className="btn-secondary">Avbryt</button>
            <button type="submit" disabled={saving} className="btn-primary">
              {saving ? 'Lagrer...' : 'Lagre'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
