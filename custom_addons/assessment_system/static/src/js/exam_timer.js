/**
 * Candidate Written Assessment Stepper, Live Word Counter & Auto-Saver
 * ===================================================================
 * Implements 1-question-at-a-time stepper, live word count, inline slot
 * synchronization, question navigator, and automated submission.
 */

document.addEventListener("DOMContentLoaded", () => {
    const examContainer = document.getElementById("exam_session_container");
    const timerElement = document.getElementById("exam_timer_display");
    if (!examContainer) return;

    const token = examContainer.dataset.token;
    let remainingSeconds = parseInt(examContainer.dataset.durationSeconds || "3600", 10);
    const saveIndicator = document.getElementById("auto_save_indicator");

    const questionCards = Array.from(document.querySelectorAll(".exam-question-card"));
    const totalQuestions = questionCards.length;
    let currentIndex = 0;

    // Elements
    const btnBack = document.getElementById("btn_prev_question");
    const btnNext = document.getElementById("btn_next_question");
    const btnSubmit = document.getElementById("btn_submit_exam");
    const btnSubmitModal = document.getElementById("btn_confirm_submit_modal");
    const stepperProgressBar = document.getElementById("stepper_progress_bar");
    const stepCounterText = document.getElementById("step_counter_text");
    const navPills = Array.from(document.querySelectorAll("#navigator_pill_container .nav-pill-btn"));

    // 1. Show Question at Index
    function showQuestion(index) {
        if (index < 0 || index >= totalQuestions) return;
        currentIndex = index;

        questionCards.forEach((card, idx) => {
            if (idx === currentIndex) {
                card.classList.remove("d-none");
            } else {
                card.classList.add("d-none");
            }
        });

        // Update Counter & Progress
        if (stepCounterText) {
            stepCounterText.textContent = `Question ${currentIndex + 1} of ${totalQuestions}`;
        }
        if (stepperProgressBar) {
            const pct = Math.round(((currentIndex + 1) / totalQuestions) * 100);
            stepperProgressBar.style.width = `${pct}%`;
        }

        // Update Back Button
        if (btnBack) {
            btnBack.disabled = (currentIndex === 0);
        }

        // Update Next / Submit Button visibility
        if (btnNext && btnSubmit) {
            if (currentIndex === totalQuestions - 1) {
                btnNext.classList.add("d-none");
                btnSubmit.classList.remove("d-none");
            } else {
                btnNext.classList.remove("d-none");
                btnSubmit.classList.add("d-none");
            }
        }

        // Update Navigator Active Ring
        navPills.forEach((pill, idx) => {
            if (idx === currentIndex) {
                pill.classList.add("active-current");
            } else {
                pill.classList.remove("active-current");
            }
        });

        updateNavigatorStatus();
    }

    // 2. Update Question Navigator Badges (Answered / Flagged)
    function updateNavigatorStatus() {
        questionCards.forEach((card, idx) => {
            const pill = navPills[idx];
            if (!pill) return;

            const qType = card.dataset.questionType;
            const reviewCheckbox = card.querySelector(".mark-review-checkbox");
            const isFlagged = reviewCheckbox ? reviewCheckbox.checked : false;

            let isAnswered = false;
            if (qType === "mcq_single" || qType === "true_false") {
                const checked = card.querySelector("input[type='radio']:checked");
                isAnswered = !!checked;
            } else if (qType === "mcq_multiple") {
                const checked = card.querySelectorAll("input[type='checkbox'].mcq-opt:checked");
                isAnswered = (checked && checked.length > 0);
            } else if (qType === "essay" || qType === "short_answer" || qType === "fill_blank") {
                const inputs = card.querySelectorAll("textarea, input.blank-inline-input, input.text-ans");
                isAnswered = Array.from(inputs).some(input => input.value.trim().length > 0);
            }

            // Apply badge styling
            pill.classList.remove("answered", "flagged");
            if (isFlagged) {
                pill.classList.add("flagged");
            }
            if (isAnswered) {
                pill.classList.add("answered");
            }
        });
    }

    // 3. Live Word Counter for Essay Questions
    function initWordCounters() {
        document.querySelectorAll(".essay-input-container").forEach(container => {
            const textarea = container.querySelector(".essay-textarea");
            const countDisplay = container.querySelector(".word-count");
            if (!textarea || !countDisplay) return;

            function calculateWords() {
                const text = textarea.value.trim();
                const words = text ? text.split(/\s+/).filter(w => w.length > 0).length : 0;
                countDisplay.textContent = words;
                updateNavigatorStatus();
            }

            textarea.addEventListener("input", calculateWords);
            calculateWords();
        });
    }

    // 4. Fill-in-the-Blank Inline Synchronizer
    function initFillInBlankSlots() {
        document.querySelectorAll(".exam-question-card[data-question-type='fill_blank']").forEach(card => {
            const inlineInput = card.querySelector(".blank-inline-input");
            const hiddenAnsInput = card.querySelector(".text-ans-hidden");
            if (!inlineInput) return;

            inlineInput.addEventListener("input", () => {
                if (hiddenAnsInput) hiddenAnsInput.value = inlineInput.value;
                updateNavigatorStatus();
            });
        });
    }

    // 5. MCQ Option Card Selection Styling
    function initOptionCardClicks() {
        document.querySelectorAll(".mcq-option-card").forEach(card => {
            const radio = card.querySelector("input[type='radio']");
            if (!radio) return;

            card.addEventListener("click", () => {
                radio.checked = true;
                const parent = card.closest(".mcq-option-grid");
                if (parent) {
                    parent.querySelectorAll(".mcq-option-card").forEach(c => c.classList.remove("selected"));
                }
                card.classList.add("selected");
                updateNavigatorStatus();
            });

            if (radio.checked) {
                card.classList.add("selected");
            }
        });

        // True/False Pills
        document.querySelectorAll(".tf-pill-button").forEach(pill => {
            const radio = pill.querySelector("input[type='radio']");
            if (!radio) return;

            pill.addEventListener("click", () => {
                radio.checked = true;
                const parent = pill.closest(".tf-container");
                if (parent) {
                    parent.querySelectorAll(".tf-pill-button").forEach(p => p.classList.remove("selected"));
                }
                pill.classList.add("selected");
                updateNavigatorStatus();
            });

            if (radio.checked) {
                pill.classList.add("selected");
            }
        });
    }

    // 6. Navigation Event Listeners
    if (btnBack) {
        btnBack.addEventListener("click", () => {
            if (currentIndex > 0) {
                showQuestion(currentIndex - 1);
            }
        });
    }

    if (btnNext) {
        btnNext.addEventListener("click", () => {
            if (currentIndex < totalQuestions - 1) {
                showQuestion(currentIndex + 1);
            }
        });
    }

    navPills.forEach((pill, idx) => {
        pill.addEventListener("click", () => showQuestion(idx));
    });

    document.querySelectorAll(".mark-review-checkbox").forEach(chk => {
        chk.addEventListener("change", updateNavigatorStatus);
    });

    // 7. Live Countdown Timer
    function updateTimer() {
        if (!timerElement) return;
        if (remainingSeconds <= 0) {
            timerElement.textContent = "00:00:00 - TIME EXPIRED";
            timerElement.classList.add("timer-danger");
            autoSubmitExam();
            return;
        }

        const hrs = Math.floor(remainingSeconds / 3600);
        const mins = Math.floor((remainingSeconds % 3600) / 60);
        const secs = remainingSeconds % 60;

        timerElement.textContent = `${String(hrs).padStart(2, '0')}:${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
        
        if (remainingSeconds < 300) {
            timerElement.classList.add("timer-danger");
        }

        remainingSeconds--;
    }

    const timerInterval = setInterval(updateTimer, 1000);

    // 8. Collect Answers Payload
    function collectAnswersPayload() {
        const payload = [];

        questionCards.forEach(card => {
            const answerId = parseInt(card.dataset.answerId, 10);
            const qType = card.dataset.questionType;
            const reviewCheckbox = card.querySelector(".mark-review-checkbox");
            const isReview = reviewCheckbox ? reviewCheckbox.checked : false;

            const item = {
                answer_id: answerId,
                is_marked_for_review: isReview,
            };

            if (qType === "mcq_single" || qType === "true_false") {
                const checked = card.querySelector("input[type='radio']:checked");
                if (checked) {
                    const parsedInt = parseInt(checked.value, 10);
                    item.selected_option_id = isNaN(parsedInt) ? false : parsedInt;
                    item.text_answer = checked.value;
                } else {
                    item.selected_option_id = false;
                    item.text_answer = "";
                }
            } else if (qType === "mcq_multiple") {
                const checkboxes = card.querySelectorAll("input[type='checkbox'].mcq-opt:checked");
                item.selected_option_ids = Array.from(checkboxes).map(c => parseInt(c.value, 10)).filter(n => !isNaN(n));
            } else if (qType === "essay" || qType === "short_answer") {
                const textarea = card.querySelector("textarea");
                item.text_answer = textarea ? textarea.value : "";
            } else if (qType === "fill_blank") {
                const inlineInput = card.querySelector(".blank-inline-input, .text-ans");
                item.text_answer = inlineInput ? inlineInput.value : "";
            }

            payload.push(item);
        });

        return payload;
    }

    // 9. Auto-Save Every 30s
    function autoSaveAnswers() {
        const payload = collectAnswersPayload();
        if (saveIndicator) saveIndicator.textContent = "Saving...";

        fetch(`/exam/session/${token}/save`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ params: { answers: payload } })
        })
        .then(res => res.json())
        .then(data => {
            if (saveIndicator) {
                const now = new Date();
                saveIndicator.textContent = `Auto-saved at ${now.toLocaleTimeString()}`;
            }
        })
        .catch(err => console.error("Auto-save error:", err));
    }

    const autoSaveInterval = setInterval(autoSaveAnswers, 30000);

    // 10. Final Submit Modal & Execution
    function openSubmitConfirmationModal() {
        let answeredCount = 0;
        let flaggedCount = 0;

        questionCards.forEach((card) => {
            const qType = card.dataset.questionType;
            const reviewCheckbox = card.querySelector(".mark-review-checkbox");
            const isFlagged = reviewCheckbox ? reviewCheckbox.checked : false;
            if (isFlagged) flaggedCount++;

            let isAnswered = false;
            if (qType === "mcq_single" || qType === "true_false") {
                const checked = card.querySelector("input[type='radio']:checked");
                isAnswered = !!checked;
            } else if (qType === "mcq_multiple") {
                const checked = card.querySelectorAll("input[type='checkbox'].mcq-opt:checked");
                isAnswered = (checked && checked.length > 0);
            } else if (qType === "essay" || qType === "short_answer" || qType === "fill_blank") {
                const inputs = card.querySelectorAll("textarea, input.blank-inline-input, input.text-ans");
                isAnswered = Array.from(inputs).some(input => input.value.trim().length > 0);
            }

            if (isAnswered) answeredCount++;
        });

        const unansweredCount = Math.max(0, totalQuestions - answeredCount);

        const summaryModalEl = document.getElementById("submitConfirmModal");
        if (summaryModalEl) {
            document.getElementById("modal_total_q").textContent = totalQuestions;
            document.getElementById("modal_answered_q").textContent = answeredCount;
            document.getElementById("modal_unanswered_q").textContent = unansweredCount;
            document.getElementById("modal_flagged_q").textContent = flaggedCount;

            const modal = new bootstrap.Modal(summaryModalEl);
            modal.show();
        } else {
            if (confirm(`Are you sure you want to finalize and submit? (${answeredCount} of ${totalQuestions} answered)`)) {
                executeFinalSubmission();
            }
        }
    }

    function executeFinalSubmission() {
        clearInterval(timerInterval);
        clearInterval(autoSaveInterval);

        const payload = collectAnswersPayload();
        fetch(`/exam/session/${token}/submit`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ params: { answers: payload } })
        })
        .then(res => res.json())
        .then(data => {
            window.location.reload();
        })
        .catch(err => alert("Submission error: " + err));
    }

    function autoSubmitExam() {
        clearInterval(timerInterval);
        clearInterval(autoSaveInterval);
        const payload = collectAnswersPayload();
        fetch(`/exam/session/${token}/submit`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ params: { answers: payload } })
        })
        .then(() => window.location.reload());
    }

    if (btnSubmit) {
        btnSubmit.addEventListener("click", openSubmitConfirmationModal);
    }
    const btnHeaderSubmit = document.getElementById("btn_header_submit");
    if (btnHeaderSubmit) {
        btnHeaderSubmit.addEventListener("click", openSubmitConfirmationModal);
    }
    if (btnSubmitModal) {
        btnSubmitModal.addEventListener("click", executeFinalSubmission);
    }

    // Initialize components
    initWordCounters();
    initFillInBlankSlots();
    initOptionCardClicks();
    showQuestion(0);
});
