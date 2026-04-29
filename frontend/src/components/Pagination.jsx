import { ChevronLeft, ChevronRight } from 'lucide-react';

/**
 * Reusable client-side pagination footer.
 * Props:
 *  - page: current 1-based page
 *  - pageSize: rows per page
 *  - total: total number of items (after filtering)
 *  - onPageChange(page)
 *  - onPageSizeChange(size)
 *  - pageSizeOptions: array of selectable page sizes
 */
export default function Pagination({
  page,
  pageSize,
  total,
  onPageChange,
  onPageSizeChange,
  pageSizeOptions = [20, 50, 100],
}) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const safePage = Math.min(Math.max(1, page), totalPages);
  const start = total === 0 ? 0 : (safePage - 1) * pageSize + 1;
  const end = Math.min(safePage * pageSize, total);

  return (
    <div className="px-3 py-2 border-t border-gray-200 flex items-center justify-between bg-white text-xs text-gray-600">
      <div className="flex items-center gap-2">
        <span>Vis</span>
        <select
          value={pageSize}
          onChange={(e) => onPageSizeChange(parseInt(e.target.value, 10))}
          className="input py-1 px-2 text-xs"
        >
          {pageSizeOptions.map((opt) => (
            <option key={opt} value={opt}>{opt}</option>
          ))}
        </select>
        <span>per side</span>
      </div>

      <div className="flex items-center gap-3">
        <span>
          {start}–{end} av <span className="font-medium text-gray-900">{total}</span>
        </span>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => onPageChange(safePage - 1)}
            disabled={safePage <= 1}
            className="p-1 rounded hover:bg-gray-100 disabled:opacity-40 disabled:cursor-not-allowed"
            aria-label="Forrige side"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
          <span className="px-2">
            Side <span className="font-medium text-gray-900">{safePage}</span> av {totalPages}
          </span>
          <button
            type="button"
            onClick={() => onPageChange(safePage + 1)}
            disabled={safePage >= totalPages}
            className="p-1 rounded hover:bg-gray-100 disabled:opacity-40 disabled:cursor-not-allowed"
            aria-label="Neste side"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
