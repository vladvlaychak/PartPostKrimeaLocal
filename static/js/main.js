document.addEventListener("DOMContentLoaded", () => {
    const input = document.getElementById("shipmentNumber");
    const searchButton = document.getElementById("shipmentSearchButton");
    const clearButton = document.getElementById("shipmentClearButton");
    const status = document.getElementById("shipmentSearchStatus");
    const result = document.getElementById("shipmentSearchResult");
    const statsBadge = document.getElementById("statsBadge");
    const filtersForm = document.getElementById("filtersForm");
    const searchInput = document.getElementById("searchInput");
    let searchMode = "shpi";

    function normalize(value) {
        return String(value || "").trim().toUpperCase().replace(/[^A-ZА-ЯЁ0-9]+/g, "");
    }
    function escapeHtml(value) {
        const el = document.createElement("div");
        el.textContent = value == null ? "" : String(value);
        return el.innerHTML;
    }
    function setStatus(message, type = "") {
        status.textContent = message;
        status.className = `shipment-search-status ${type}`;
    }
    function clearResult() {
        result.hidden = true;
        result.innerHTML = "";
        setStatus("");
    }
    function formatNumber(value) {
        if (value === null || value === undefined || value === "") return "—";
        const n = Number(value);
        return Number.isNaN(n) ? escapeHtml(value) : n.toLocaleString("ru-RU", {maximumFractionDigits: 2});
    }
    function formatDate(value) {
        return value ? String(value).replace("T", " ").substring(0, 19) : "—";
    }
    function shipmentCard(shipment) {
        return `<div class="shipment-result-header"><span class="result-success-icon">✓</span><div><div class="result-title">ОТПРАВЛЕНИЕ НАЙДЕНО</div><div class="result-number">${escapeHtml(shipment.shpi)}</div></div></div>
        <div class="shipment-result-grid">
        <div class="result-item"><span>Внутренний номер</span><strong>${escapeHtml(shipment.internal_number || "—")}</strong></div>
        <div class="result-item"><span>Получатель</span><strong>${escapeHtml(shipment.recipient || "—")}</strong></div>
        <div class="result-item"><span>Телефон</span><strong>${escapeHtml(shipment.phone || "—")}</strong></div>
        <div class="result-item"><span>Почтовый индекс</span><strong>${escapeHtml(shipment.index_code || "—")}</strong></div>
        <div class="result-item"><span>Масса</span><strong>${formatNumber(shipment.mass)}</strong></div>
        <div class="result-item"><span>Стоимость</span><strong>${formatNumber(shipment.shipping_cost)} ₽</strong></div>
        <div class="result-item result-item-full"><span>Адрес</span><strong>${escapeHtml(shipment.address || "—")}</strong></div>
        <div class="result-item result-item-full"><span>Комментарий</span><strong>${escapeHtml(shipment.comment || "—")}</strong></div>
        <div class="result-item"><span>Дата загрузки</span><strong>${escapeHtml(formatDate(shipment.uploaded_at))}</strong></div>
        </div>`;
    }
    function renderShipments(shipments) {
        result.innerHTML = shipments.map(shipmentCard).join("");
        result.hidden = false;
    }
    async function search() {
        const number = normalize(input.value);
        clearResult();
        if (!number) {
            setStatus(searchMode === "shpi" ? "Введите номер отправления" : "Введите внутренний номер", "status-warning");
            input.focus(); return;
        }
        input.value = number;
        searchButton.disabled = true;
        const oldText = searchButton.textContent;
        searchButton.textContent = "Поиск...";
        setStatus("Выполняется поиск...", "status-loading");
        try {
            const url = searchMode === "shpi"
                ? `/api/shipment?shpi=${encodeURIComponent(number)}`
                : `/api/internal-number?number=${encodeURIComponent(number)}`;
            const response = await fetch(url, {headers: {"Accept": "application/json"}});
            const data = await response.json();
            if (!response.ok) throw new Error(data.message || "Ошибка выполнения поиска");
            if (!data.found) {
                setStatus(data.message || "Ничего не найдено", "status-not-found"); return;
            }
            const shipments = searchMode === "shpi"
                ? (data.shipment ? [data.shipment] : [])
                : (Array.isArray(data.shipments)
                    ? data.shipments
                    : (data.shipment ? [data.shipment] : []));

            if (!shipments.length) {
                setStatus(data.message || "Ничего не найдено", "status-not-found");
                return;
            }

            setStatus(
                shipments.length > 1
                    ? `Найдено отправлений: ${shipments.length}`
                    : "Отправление найдено",
                "status-success"
            );

            renderShipments(shipments);
            result.scrollIntoView({
                behavior: "smooth",
                block: "nearest"
            });
        } catch (error) {
            console.error(error);
            setStatus(error.message || "Не удалось выполнить поиск", "status-error");
        } finally {
            searchButton.disabled = false;
            searchButton.textContent = oldText;
        }
    }

    document.querySelectorAll(".search-mode").forEach(button => {
        button.addEventListener("click", () => {
            searchMode = button.dataset.mode;
            document.querySelectorAll(".search-mode").forEach(b => b.classList.toggle("active", b === button));
            input.value = "";
            clearResult();
            input.placeholder = searchMode === "shpi" ? "Например: RA123456789RU" : "Например: 123456";
            input.focus();
        });
    });
    searchButton.addEventListener("click", search);
    input.addEventListener("keydown", event => {
        if (event.key === "Enter") { event.preventDefault(); search(); }
        if (event.key === "Escape") { input.value = ""; clearResult(); input.focus(); }
    });
    clearButton.addEventListener("click", () => { input.value = ""; clearResult(); input.focus(); });

    document.querySelectorAll(".shpi-button").forEach(button => {
        button.addEventListener("click", () => {
            searchMode = "shpi";
            document.querySelectorAll(".search-mode").forEach(b => b.classList.toggle("active", b.dataset.mode === "shpi"));
            input.value = button.dataset.shpi || "";
            window.scrollTo({top: 0, behavior: "smooth"});
            setTimeout(search, 250);
        });
    });

    if (searchInput && filtersForm) {
        let timeoutId;
        searchInput.addEventListener("input", () => {
            clearTimeout(timeoutId);
            timeoutId = setTimeout(() => filtersForm.submit(), 500);
        });
    }

    fetch("/api/stats")
        .then(r => r.json())
        .then(data => {
            if (data.success && data.stats) {
                statsBadge.textContent = `В базе: ${Number(data.stats.total || 0).toLocaleString("ru-RU")}`;
            }
        })
        .catch(() => { statsBadge.textContent = "Статистика недоступна"; });
});
