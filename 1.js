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
