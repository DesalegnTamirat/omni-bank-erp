/** @odoo-module **/

(function () {
    "use strict";

    async function callSessionMethod(method, args, kwargs = {}) {
        const res = await fetch("/web/dataset/call_kw", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                jsonrpc: "2.0",
                method: "call",
                params: {
                    model: "eds.session",
                    method: method,
                    args: args,
                    kwargs: kwargs,
                },
                id: Date.now(),
            }),
        });
        const data = await res.json();
        if (data.error) {
            throw new Error(data.error.data?.message || data.error.message || "Server Error");
        }
        return data.result;
    }

    function getSessionId(element) {
        if (!element) return null;
        // 1. Direct attribute on the element (cell span or button)
        let sid = element.getAttribute("data-session-id");
        if (sid && !isNaN(Number(sid)) && Number(sid) > 0) {
            return Number(sid);
        }
        // 2. Any ancestor with data-session-id (table, tr, td, wrapper)
        const container = element.closest("[data-session-id]");
        if (container) {
            sid = container.getAttribute("data-session-id");
            if (sid && !isNaN(Number(sid)) && Number(sid) > 0) {
                return Number(sid);
            }
        }
        // 3. In Odoo 19 web client, URL pathname: e.g. /odoo/action-465/1203 or /odoo/eds.session/1203
        const pathParts = window.location.pathname.split("/").filter(Boolean);
        if (pathParts.length > 0) {
            const lastPart = pathParts[pathParts.length - 1];
            if (/^\d+$/.test(lastPart) && Number(lastPart) > 0) {
                return Number(lastPart);
            }
        }
        // 4. URL hash or query params: #id=1203 or ?id=1203 or &id=1203
        const hrefMatch = window.location.href.match(/[#&?]id=(\d+)/);
        if (hrefMatch && hrefMatch[1]) {
            return Number(hrefMatch[1]);
        }
        // 5. Look up active form record in Odoo UI
        const formView = document.querySelector(".o_form_view");
        if (formView) {
            const formId = formView.dataset.resId || formView.getAttribute("data-res-id");
            if (formId && !isNaN(Number(formId)) && Number(formId) > 0) {
                return Number(formId);
            }
        }
        return null;
    }

    function recalculateRowSummary(tr) {
        if (!tr) return;
        const presentCells = tr.querySelectorAll(".eds-att-cell.is-present");
        const absentCells = tr.querySelectorAll(".eds-att-cell.is-absent");
        const allSlotCells = tr.querySelectorAll(".eds-att-cell");
        const presentCount = presentCells.length;
        const absentCount = absentCells.length;
        const totalSlots = allSlotCells.length;
        const rate = totalSlots > 0 ? (presentCount / totalSlots) * 100 : 0;
        const meets = rate >= 80.0;

        const cellPresent = tr.querySelector(".eds-row-present");
        if (cellPresent) cellPresent.textContent = presentCount;

        const cellAbsent = tr.querySelector(".eds-row-absent");
        if (cellAbsent) cellAbsent.textContent = absentCount;

        const cellRate = tr.querySelector(".eds-row-rate");
        if (cellRate) cellRate.textContent = `${rate.toFixed(1)}%`;

        const cellStatus = tr.querySelector(".eds-row-status");
        if (cellStatus) {
            if (presentCount === 0 && absentCount === 0) {
                cellStatus.innerHTML = '<span class="badge rounded-pill text-bg-light text-muted px-2 py-1" style="font-size: 0.75rem;">Not Started</span>';
            } else if (meets) {
                cellStatus.innerHTML = '<span class="badge rounded-pill text-bg-success px-2 py-1" style="font-size: 0.75rem;">Meets (&ge;80%)</span>';
            } else {
                cellStatus.innerHTML = '<span class="badge rounded-pill text-bg-danger px-2 py-1" style="font-size: 0.75rem;">Below (&lt;80%)</span>';
            }
        }
    }

    document.addEventListener("click", async function (ev) {
        // 1. Single Cell Toggle (Empty -> Present -> Absent -> Empty)
        const cell = ev.target.closest(".eds-att-cell") || ev.target.closest(".eds-att-cell-td");
        if (cell) {
            ev.preventDefault();
            ev.stopPropagation();
            if (cell.dataset.loading === "1") return;

            const span = cell.classList.contains("eds-att-cell") ? cell : cell.querySelector(".eds-att-cell");
            const td = cell.closest("td") || cell;
            const tr = cell.closest("tr");

            const sessionId = getSessionId(cell) || getSessionId(td) || (tr ? getSessionId(tr) : null);
            const rawEmpId = cell.getAttribute("data-emp-id") || td.getAttribute("data-emp-id") || (tr ? tr.getAttribute("data-emp-id") : null);
            const attDate = cell.getAttribute("data-date") || td.getAttribute("data-date");
            const attSlot = cell.getAttribute("data-slot") || td.getAttribute("data-slot") || "day";

            const empId = rawEmpId ? Number(rawEmpId) : null;

            if (!sessionId) {
                console.warn("Could not determine session ID for cell", cell);
                alert("Cannot determine session ID. Please refresh the page.");
                return;
            }
            if (!empId || isNaN(empId) || empId <= 0 || !attDate) {
                console.error("Missing employee ID or date on cell", cell, { rawEmpId, empId, attDate, attSlot });
                alert("Missing employee ID or date. Please refresh the page.");
                return;
            }

            const targetEl = span || cell;
            targetEl.dataset.loading = "1";
            targetEl.style.opacity = "0.5";
            try {
                const res = await callSessionMethod("action_toggle_attendance_cell", [
                    [sessionId],
                    empId,
                    attDate,
                    attSlot,
                ], {});

                const state = res && res.state;
                if (targetEl) {
                    if (state === "present") {
                        targetEl.className = "eds-att-cell is-present";
                        targetEl.textContent = "P";
                        targetEl.style.backgroundColor = "#d1e7dd";
                        targetEl.style.color = "#0f5132";
                        targetEl.style.border = "1px solid #badbcc";
                        targetEl.title = "Present. Click to mark Absent";
                    } else if (state === "absent") {
                        targetEl.className = "eds-att-cell is-absent";
                        targetEl.textContent = "A";
                        targetEl.style.backgroundColor = "#f8d7da";
                        targetEl.style.color = "#842029";
                        targetEl.style.border = "1px solid #f5c2c7";
                        targetEl.title = "Absent. Click to clear";
                    } else {
                        // Empty / unrecorded
                        targetEl.className = "eds-att-cell is-empty";
                        targetEl.innerHTML = "&nbsp;";
                        targetEl.style.backgroundColor = "#f8f9fa";
                        targetEl.style.color = "#6c757d";
                        targetEl.style.border = "1px dashed #ced4da";
                        targetEl.title = "Unrecorded. Click to mark Present";
                    }
                }
                if (tr) recalculateRowSummary(tr);
            } catch (err) {
                console.error("EDS Attendance toggle failed:", err);
                alert("Failed to update attendance: " + (err.message || err));
            } finally {
                targetEl.dataset.loading = "0";
                targetEl.style.opacity = "1";
            }
            return;
        }

        // 2. Day All Present
        const dayAllBtn = ev.target.closest(".eds-att-day-all");
        if (dayAllBtn) {
            ev.preventDefault();
            ev.stopPropagation();
            if (dayAllBtn.dataset.loading === "1") return;

            const th = dayAllBtn.closest("th") || dayAllBtn;
            const sessionId = getSessionId(dayAllBtn) || getSessionId(th);
            const attDate = dayAllBtn.getAttribute("data-date") || th.getAttribute("data-date");
            const attSlot = dayAllBtn.getAttribute("data-slot") || th.getAttribute("data-slot") || "day";

            if (!sessionId || !attDate) {
                alert("Cannot determine session or date for bulk update. Please refresh the page.");
                return;
            }

            dayAllBtn.dataset.loading = "1";
            dayAllBtn.style.opacity = "0.5";
            try {
                await callSessionMethod("action_mark_day_all_present", [
                    [sessionId],
                    attDate,
                    attSlot,
                ], {});

                // Update all cells in this slot
                const table = dayAllBtn.closest(".eds-attendance-matrix-table");
                if (table) {
                    const selector = `.eds-att-cell[data-date="${attDate}"][data-slot="${attSlot}"], .eds-att-cell-td[data-date="${attDate}"][data-slot="${attSlot}"] .eds-att-cell`;
                    const dayCells = table.querySelectorAll(selector);
                    dayCells.forEach((c) => {
                        c.className = "eds-att-cell is-present";
                        c.textContent = "P";
                        c.style.backgroundColor = "#d1e7dd";
                        c.style.color = "#0f5132";
                        c.style.border = "1px solid #badbcc";
                        c.title = "Present. Click to mark Absent";
                    });
                    const rows = table.querySelectorAll("tbody tr");
                    rows.forEach((tr) => recalculateRowSummary(tr));
                }
            } catch (err) {
                console.error("EDS Mark day all present failed:", err);
                alert("Failed to mark all present: " + (err.message || err));
            } finally {
                dayAllBtn.dataset.loading = "0";
                dayAllBtn.style.opacity = "1";
            }
            return;
        }
    }, true);
})();
