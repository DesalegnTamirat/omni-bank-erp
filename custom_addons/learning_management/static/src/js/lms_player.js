/** Odoo LMS authenticated MP4 player. Progress is accepted by the server only. */
(function () {
    "use strict";

    function init() {
        const root = document.getElementById("lmsPlayerPage");
        const video = document.getElementById("lmsVideoPlayer");
        if (!root || !video) return;

        const lessonId = Number(root.dataset.lessonId);
        const heartbeatUrl = root.dataset.heartbeatUrl;
        const position = document.getElementById("lmsPlaybackPosition");
        const saved = document.getElementById("lmsSavedPosition");
        const feedback = document.getElementById("lmsPlayerFeedback");
        const retry = document.getElementById("lmsRetryProgress");
        const guardSeek = root.dataset.guardSeek === "1";
        let completed = root.dataset.completed === "1";
        let lastSavedPosition = Math.max(0, Number(root.dataset.lastPosition) || 0);
        let maxAllowedPosition = lastSavedPosition + 5;
        let sending = false;
        let pendingForcedSave = false;
        let accessDenied = false;

        function clock(seconds) {
            const time = Math.max(0, Math.floor(seconds || 0));
            return Math.floor(time / 60) + ":" + String(time % 60).padStart(2, "0");
        }

        function message(value, isError) {
            if (!feedback) return;
            feedback.textContent = value;
            feedback.classList.toggle("text-warning", Boolean(isError));
            feedback.classList.toggle("text-success", !isError && completed);
            if (retry) retry.hidden = !isError || accessDenied;
        }

        function updatePosition() {
            if (position && Number.isFinite(video.duration) && video.duration > 0) {
                position.textContent = Math.min(100, Math.round(video.currentTime / video.duration * 100)) + "%";
            }
        }

        function saveProgress(force) {
            if (sending) {
                // The final pause/end position may be newer than the request in flight.
                pendingForcedSave = pendingForcedSave || Boolean(force);
                return;
            }
            if (accessDenied || completed || (!force && video.paused) ||
                !Number.isFinite(video.currentTime) || !Number.isFinite(video.duration) || video.duration <= 0) return;

            sending = true;
            const payload = {
                jsonrpc: "2.0",
                method: "call",
                params: {
                    lesson_id: lessonId,
                    current_time: video.currentTime,
                    duration: video.duration,
                },
            };
            fetch(heartbeatUrl, {
                method: "POST",
                credentials: "same-origin",
                headers: {"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"},
                body: JSON.stringify(payload),
                keepalive: Boolean(force),
            }).then(function (response) {
                if (!response.ok) throw new Error("Progress request failed");
                return response.json();
            }).then(function (data) {
                const result = data && data.result;
                if (data.error || !result || result.status !== "success") {
                    if (result && result.code === 403) accessDenied = true;
                    throw new Error("Progress was not accepted");
                }
                if (Number.isFinite(Number(result.allowed_position))) {
                    lastSavedPosition = Number(result.allowed_position);
                    maxAllowedPosition = Math.max(maxAllowedPosition, lastSavedPosition + 5);
                    if (saved) saved.textContent = clock(lastSavedPosition);
                    if (guardSeek && !completed && video.currentTime > maxAllowedPosition + 2) {
                        video.currentTime = maxAllowedPosition;
                    }
                }
                completed = Boolean(result.is_completed);
                message(completed ? "Lesson complete. Your viewing progress was saved." :
                    "Progress saved. You can resume from this point later.", false);
            }).catch(function () {
                if (accessDenied) video.pause();
                message(accessDenied ? "Access to this lesson has ended. Return to your course." :
                    "Progress could not be saved. Check your connection and retry.", true);
            }).finally(function () {
                sending = false;
                if (pendingForcedSave) {
                    pendingForcedSave = false;
                    saveProgress(true);
                }
            });
        }

        video.addEventListener("loadedmetadata", function () {
            if (lastSavedPosition > 0 && Number.isFinite(video.duration) && video.duration > 0) {
                video.currentTime = Math.min(lastSavedPosition, Math.max(0, video.duration - 0.25));
            }
            updatePosition();
        });
        video.addEventListener("timeupdate", updatePosition);
        video.addEventListener("seeking", function () {
            if (guardSeek && !completed && video.currentTime > maxAllowedPosition + 2) {
                video.currentTime = maxAllowedPosition;
                message("Continue watching before seeking ahead.", true);
            }
        });
        video.addEventListener("ratechange", function () {
            if (guardSeek && !completed && video.playbackRate > 1) video.playbackRate = 1;
        });
        video.addEventListener("pause", function () { saveProgress(true); });
        video.addEventListener("ended", function () { saveProgress(true); });
        video.addEventListener("error", function () {
            message("The video could not load. Check your connection and try again.", true);
        });
        if (retry) retry.addEventListener("click", function () { saveProgress(true); });
        window.addEventListener("online", function () { saveProgress(true); });
        document.addEventListener("visibilitychange", function () {
            if (document.hidden) saveProgress(true);
        });
        window.setInterval(function () { saveProgress(false); }, 5000);

        if (saved) saved.textContent = clock(lastSavedPosition);
        message(completed ? "Lesson complete." : "Playback resumes from your last saved position.", false);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
