/** Bunna Bank LMS — Interactive In-Screen Text Article & Guide Viewer.
 *  Handles live reading timer, in-screen confirmation button,
 *  and instant asynchronous lesson completion and next-lesson progression.
 */
(function () {
    "use strict";

    function init() {
        const root = document.getElementById("lmsTextPage");
        if (!root) return;

        const lessonId = Number(root.dataset.lessonId);
        const completeBtn = document.getElementById("lmsConfirmCompleteBtn");
        const actionBox = document.getElementById("lmsTextActionBox");
        const completedBox = document.getElementById("lmsTextCompletedBox");
        const timerEl = document.getElementById("lmsTextTimer");
        const completionCard = document.querySelector(".o_lms_completion_card");
        const metaStatus = document.querySelector(".o_lms_lesson_meta");

        let completed = root.dataset.completed === "1";
        let secondsReading = 0;
        let isSubmitting = false;

        /* ---- Live Reading Time Tracker ---- */
        function formatTime(s) {
            const m = Math.floor(s / 60);
            const sec = s % 60;
            return m + ":" + String(sec).padStart(2, "0");
        }

        const timerInterval = setInterval(function () {
            secondsReading++;
            if (timerEl) {
                timerEl.innerHTML = '<i class="fa fa-clock-o me-1" aria-hidden="true"></i> Reading time: ' + formatTime(secondsReading);
            }
        }, 1000);

        /* ---- Dynamic Completion UI Update ---- */
        function setCompletedUI(completedAt, nextUrl, nextName) {
            completed = true;
            if (actionBox) {
                actionBox.style.display = "none";
            }
            if (completedBox) {
                completedBox.style.display = "block";
            }
            if (completionCard) {
                completionCard.innerHTML = `
                    <div class="o_lms_completion_done">
                        <div class="o_lms_completion_icon">
                            <i class="fa fa-check-circle fa-2x" aria-hidden="true"></i>
                        </div>
                        <div>
                            <div class="o_lms_completion_title">Article Completed!</div>
                            <div class="o_lms_completion_sub">Great work — you have reviewed this study material.</div>
                        </div>
                    </div>
                `;
            }
            if (metaStatus) {
                const completeBadge = metaStatus.querySelector(".o_lms_meta_complete");
                if (!completeBadge) {
                    const reqItem = metaStatus.querySelector(".o_lms_meta_item:last-child");
                    if (reqItem) {
                        reqItem.className = "o_lms_meta_item o_lms_meta_complete";
                        reqItem.innerHTML = '<i class="fa fa-check-circle" aria-hidden="true"></i> Completed';
                    }
                }
            }

            // Unlock and activate Next Lesson buttons
            const disabledBtns = document.querySelectorAll(".o_lms_btn_disabled");
            disabledBtns.forEach(function (btn) {
                btn.classList.remove("o_lms_btn_disabled");
                btn.classList.add("o_lms_btn_success");
                const targetUrl = btn.dataset.href || nextUrl;
                if (targetUrl) {
                    btn.setAttribute("href", targetUrl);
                    btn.removeAttribute("title");
                }
            });
        }

        /* ---- Mark Complete Click Handler ---- */
        if (completeBtn) {
            completeBtn.addEventListener("click", function () {
                if (isSubmitting || completed) return;
                isSubmitting = true;
                completeBtn.disabled = true;
                const originalContent = completeBtn.innerHTML;
                completeBtn.innerHTML = '<i class="fa fa-spinner fa-spin me-2" aria-hidden="true"></i> Confirming completion...';

                fetch("/lms/text/complete", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        "X-Requested-With": "XMLHttpRequest",
                    },
                    body: JSON.stringify({
                        jsonrpc: "2.0",
                        method: "call",
                        params: { lesson_id: lessonId },
                    }),
                })
                .then(function (response) {
                    if (!response.ok) throw new Error("HTTP error " + response.status);
                    return response.json();
                })
                .then(function (payload) {
                    const result = payload && payload.result ? payload.result : null;
                    if (result && result.status === "success") {
                        setCompletedUI(result.date_completed, result.next_url, result.next_lesson_name);
                    } else {
                        const errMsg = (payload && payload.error && payload.error.data && payload.error.data.message)
                            || (result && result.message)
                            || "Failed to confirm completion. Please try again.";
                        alert(errMsg);
                        completeBtn.disabled = false;
                        completeBtn.innerHTML = originalContent;
                        isSubmitting = false;
                    }
                })
                .catch(function (err) {
                    console.error("Completion error:", err);
                    alert("Could not reach the LMS server. Please check your network and try again.");
                    completeBtn.disabled = false;
                    completeBtn.innerHTML = originalContent;
                    isSubmitting = false;
                });
            });
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
