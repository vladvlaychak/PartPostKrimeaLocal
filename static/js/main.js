document.addEventListener('DOMContentLoaded', () => {
  const table = document.getElementById('shipmentsTable');
  const tbody = table.querySelector('tbody');
  const rows = Array.from(tbody.querySelectorAll('tr'));
  const headers = Array.from(table.querySelectorAll('th'));

  const searchInput = document.getElementById('searchInput');
  const dateFromInput = document.getElementById('dateFrom');
  const dateToInput = document.getElementById('dateTo');

  let currentSortField = null;
  let isAscending = true;

  function getCellValue(row, field) {
    const cell = row.querySelector(`td[data-field="${field}"]`) || row.cells[headers.findIndex(h => h.getAttribute('data-field') === field)];
    if (!cell) return '';

    const text = cell.innerText.trim();

    if (['mass', 'shipping_cost'].includes(field)) {
      const num = parseFloat(text.replace(/\s/g, '').replace('₽', ''));
      return isNaN(num) ? 0 : num;
    }

    return text.toLowerCase();
  }

  function sortTable(field) {
    if (currentSortField === field) {
      isAscending = !isAscending;
    } else {
      currentSortField = field;
      isAscending = true;
    }

    headers.forEach(h => {
      h.classList.remove('sorted-asc', 'sorted-desc');
      if (h.getAttribute('data-field') === currentSortField) {
        h.classList.add(isAscending ? 'sorted-asc' : 'sorted-desc');
      }
    });

    const sortedRows = [...rows].sort((a, b) => {
      const aVal = getCellValue(a, field);
      const bVal = getCellValue(b, field);

      if (typeof aVal === 'number' && typeof bVal === 'number') {
        return isAscending ? aVal - bVal : bVal - aVal;
      } else {
        if (aVal < bVal) return isAscending ? -1 : 1;
        if (aVal > bVal) return isAscending ? 1 : -1;
        return 0;
      }
    });

    tbody.innerHTML = '';
    sortedRows.forEach(row => tbody.appendChild(row));

    applyFilters();
  }

  function applyFilters() {
    const searchTerm = searchInput.value.toLowerCase();
    const fromDate = dateFromInput.value;
    const toDate = dateToInput.value;

    rows.forEach(row => {
      const matchesSearch = row.innerText.toLowerCase().includes(searchTerm);

      const dateCell = row.querySelector('td[data-date]');
      const rowDateStr = dateCell ? dateCell.getAttribute('data-date') : '';

      let matchesDateRange = true;

      if (fromDate && rowDateStr) {
        if (rowDateStr < fromDate) matchesDateRange = false;
      }

      if (toDate && rowDateStr) {
        const toEndOfDay = `${toDate}T23:59:59`;
        if (rowDateStr > toEndOfDay) matchesDateRange = false;
      }

      row.style.display = (matchesSearch && matchesDateRange) ? '' : 'none';
    });
  }

  headers.forEach(header => {
    header.addEventListener('click', () => {
      const field = header.getAttribute('data-field');
      if (field) sortTable(field);
    });
  });

  searchInput.addEventListener('input', applyFilters);
  dateFromInput.addEventListener('change', applyFilters);
  dateToInput.addEventListener('change', applyFilters);

  dateToInput.valueAsDate = new Date();
});
  



