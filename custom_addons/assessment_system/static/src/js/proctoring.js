/**
 * Advanced Anti-Cheating & Proctoring Engine (FR-EXM-021 - FR-EXM-023)
 * ==============================================================================
 * Comprehensive Client-Side Security Controls:
 * 1. Screenshot & Snipping Tool Interception (PrtScn, Win+Shift+S, Alt+PrtScn) -> Auto-Disqualify
 * 2. Instant Clipboard Neutralization
 * 3. Screen Obfuscation Privacy Shield (triggers on window blur / snipping activation)
 * 4. DevTools / Print Protection (F12, Ctrl+Shift+I, Ctrl+P, Ctrl+U)
 * 5. Copy / Cut / Paste Lockout
 * 6. Tab-Switch & Window Blur Tracking with Auto-Disqualification
 */

document.addEventListener("DOMContentLoaded", () => {
    const examContainer = document.getElementById("exam_session_container");
    if (!examContainer) return;

    const token = examContainer.dataset.token;
    const maxTabSwitches = parseInt(examContainer.dataset.maxTabSwitches || "3", 10);
    let tabSwitchCount = parseInt(examContainer.dataset.tabSwitchCount || "0", 10);
    const blockScreenshot = examContainer.dataset.blockScreenshot === "1";
    let isDisqualified = false;
    let lastSwitchTime = 0;

    // Create Full-Screen Security Obfuscation Shield (Blocks Snipping Tool & Background Captures)
    const privacyShield = document.createElement("div");
    privacyShield.id = "exam_privacy_security_shield";
    privacyShield.style.cssText = `
        display: none;
        position: fixed;
        top: 0;
        left: 0;
        width: 100vw;
        height: 100vh;
        background: rgba(15, 23, 42, 0.98);
        z-index: 99999;
        color: #ffffff;
        text-align: center;
        padding-top: 20vh;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    `;
    privacyShield.innerHTML = `
        <div style="max-width: 600px; margin: 0 auto; padding: 40px; background: #1e293b; border-radius: 16px; border: 2px solid #ef4444; box-shadow: 0 20px 40px rgba(0,0,0,0.5);">
            <div style="font-size: 4rem; color: #ef4444; margin-bottom: 20px;"><i class="fa-solid fa-shield-halved"></i></div>
            <h2 style="font-size: 1.6rem; font-weight: 700; color: #f8fafc; margin-bottom: 12px;">EXAM SCREEN PROTECTED</h2>
            <p style="color: #cbd5e1; font-size: 1.05rem; line-height: 1.6; margin-bottom: 24px;">
                Screen capture and switching windows/tabs are strictly prohibited during the assessment.<br/>
                Please click back on this window to resume your examination.
            </p>
            <div style="display: inline-block; background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3); padding: 8px 18px; border-radius: 20px; font-weight: 600; font-size: 0.9rem;">
                All screenshot and window switch attempts are logged
            </div>
        </div>
    `;
    document.body.appendChild(privacyShield);

    function triggerDisqualification(reason) {
        if (isDisqualified) return;
        isDisqualified = true;

        document.body.innerHTML = `
            <div style="position:fixed;top:0;left:0;width:100vw;height:100vh;background:#450a0a;color:#ffffff;display:flex;flex-direction:column;align-items:center;justify-content:center;z-index:9999999;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;text-align:center;padding:20px;">
                <div style="background:#1e1e1e;border:3px solid #dc2626;border-radius:16px;max-width:650px;padding:40px;box-shadow:0 25px 50px -12px rgba(0,0,0,0.7);">
                    <div style="font-size:4.5rem;color:#ef4444;margin-bottom:15px;">
                        <i class="fa-solid fa-triangle-exclamation"></i>
                    </div>
                    <h1 style="color:#f87171;font-size:2rem;font-weight:800;margin-bottom:12px;letter-spacing:1px;">
                        EXAMINATION TERMINATED
                    </h1>
                    <h2 style="color:#ffffff;font-size:1.3rem;font-weight:600;margin-bottom:20px;">
                        You have been DISQUALIFIED
                    </h2>
                    <p style="color:#e2e8f0;font-size:1.05rem;line-height:1.6;margin-bottom:25px;background:rgba(239,68,68,0.15);padding:15px;border-radius:8px;border-left:4px solid #ef4444;">
                        ${reason}
                    </p>
                    <p style="color:#94a3b8;font-size:0.9rem;">
                        This incident has been permanently logged in your assessment record. You cannot resume this exam.
                    </p>
                </div>
            </div>
        `;
        setTimeout(() => {
            window.location.reload();
        }, 1500);
    }

    function reportViolation(eventType, details) {
        return fetch(`/exam/session/${token}/event`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                jsonrpc: "2.0",
                method: "call",
                params: {
                    event_type: eventType,
                    details: details || "",
                },
                id: Date.now()
            })
        })
        .then(res => res.json())
        .then(data => {
            const result = (data && data.result) ? data.result : {};
            if (result.action === "disqualified") {
                triggerDisqualification(result.message || "Security violation limit exceeded.");
            }
            return result;
        })
        .catch(err => console.error("Proctor event error:", err));
    }

    // 1. Copy / Cut / Paste & Right-Click Lockout (FR-EXM-021)
    document.addEventListener("copy", (e) => {
        e.preventDefault();
        wipeClipboard();
        reportViolation("copy_paste", "Copy attempt intercepted");
        showSecurityWarning("Copying exam content is strictly disabled.");
    });
    document.addEventListener("cut", (e) => {
        e.preventDefault();
        wipeClipboard();
        reportViolation("copy_paste", "Cut attempt intercepted");
    });
    document.addEventListener("paste", (e) => {
        e.preventDefault();
        reportViolation("copy_paste", "Paste attempt intercepted");
        showSecurityWarning("Pasting external content is disabled.");
    });
    document.addEventListener("contextmenu", (e) => {
        e.preventDefault();
        reportViolation("right_click", "Context menu / right-click blocked");
        showSecurityWarning("Right-click context menu is disabled.");
    });

    // 2. Clipboard Neutralization Helper
    function wipeClipboard() {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText("BUNNA BANK SECURE ASSESSMENT - CONTENT PROTECTED").catch(() => {});
        }
    }

    function handleScreenshotAttempt(detail) {
        wipeClipboard();
        reportViolation("screenshot", detail);
        if (blockScreenshot) {
            triggerDisqualification("Screen capture and screenshots are strictly prohibited. You have been disqualified.");
        } else {
            showPrivacyShieldTemporarily();
            showSecurityWarning("Screenshots and screen captures are strictly prohibited.");
        }
    }

    function isScreenshotKey(e) {
        return (
            e.key === "PrintScreen" ||
            e.code === "PrintScreen" ||
            e.key === "Snapshot" ||
            e.keyCode === 44 ||
            (e.shiftKey && (e.key === "S" || e.key === "s" || e.code === "KeyS") && (e.metaKey || e.ctrlKey || e.altKey)) ||
            (e.altKey && (e.key === "PrintScreen" || e.code === "PrintScreen" || e.keyCode === 44))
        );
    }

    // 3. Screenshot & DevTools Keyboard Defense (FR-EXM-022)
    window.addEventListener("keydown", (e) => {
        if (isScreenshotKey(e)) {
            e.preventDefault();
            wipeClipboard();
            handleScreenshotAttempt("PrintScreen / Snipping key intercepted");
            return false;
        }

        // Print / Save as PDF: Ctrl + P / Cmd + P
        if ((e.ctrlKey || e.metaKey) && (e.key === "p" || e.key === "P")) {
            e.preventDefault();
            reportViolation("print", "Print / Save PDF shortcut intercepted");
            showSecurityWarning("Printing or saving this exam is prohibited.");
            return false;
        }

        // View Source: Ctrl + U
        if ((e.ctrlKey || e.metaKey) && (e.key === "u" || e.key === "U")) {
            e.preventDefault();
            reportViolation("devtools", "View Source shortcut intercepted");
            return false;
        }

        // Save Webpage: Ctrl + S
        if ((e.ctrlKey || e.metaKey) && (e.key === "s" || e.key === "S") && !e.shiftKey) {
            e.preventDefault();
            return false;
        }

        // Inspect Element / Developer Tools: F12, Ctrl + Shift + I/J/C
        if (e.key === "F12" || e.keyCode === 123 || ((e.ctrlKey || e.metaKey) && e.shiftKey && ["I", "i", "J", "j", "C", "c"].includes(e.key))) {
            e.preventDefault();
            reportViolation("devtools", "Developer Tools inspection shortcut intercepted");
            showSecurityWarning("Developer Tools are strictly prohibited.");
            return false;
        }
    }, true);

    window.addEventListener("keyup", (e) => {
        if (isScreenshotKey(e)) {
            wipeClipboard();
            handleScreenshotAttempt("PrintScreen / Snipping key released");
        }
    }, true);

    // 4. Screen Privacy Shield on Focus Loss
    function showPrivacyShieldTemporarily() {
        privacyShield.style.display = "block";
        setTimeout(() => {
            if (!document.hidden) privacyShield.style.display = "none";
        }, 3000);
    }

    function handleSwitchAway(reason) {
        const now = Date.now();
        if (now - lastSwitchTime < 1000) {
            return; // Debounce rapid blur + visibilitychange events within 1s
        }
        lastSwitchTime = now;
        tabSwitchCount++;
        privacyShield.style.display = "block";
        reportViolation("tab_switch", `${reason} #${tabSwitchCount} detected`);
        if (tabSwitchCount >= maxTabSwitches) {
            triggerDisqualification(`Exceeded maximum allowed window/tab switches (${tabSwitchCount}/${maxTabSwitches}).`);
        } else {
            showSecurityWarning(`SECURITY ALERT: ${reason} detected (${tabSwitchCount}/${maxTabSwitches}). Exceeding ${maxTabSwitches} switches will result in immediate disqualification.`);
        }
    }

    window.addEventListener("blur", () => {
        handleSwitchAway("Window switch");
    });

    document.addEventListener("visibilitychange", () => {
        if (document.hidden) {
            handleSwitchAway("Tab switch");
        } else {
            if (tabSwitchCount >= maxTabSwitches) {
                triggerDisqualification(`Exceeded maximum allowed tab switches (${tabSwitchCount}/${maxTabSwitches}).`);
            } else {
                privacyShield.style.display = "none";
            }
        }
    });

    window.addEventListener("focus", () => {
        if (tabSwitchCount >= maxTabSwitches) {
            triggerDisqualification(`Exceeded maximum allowed window switches (${tabSwitchCount}/${maxTabSwitches}).`);
        } else {
            privacyShield.style.display = "none";
        }
    });

    function showSecurityWarning(msg) {
        const banner = document.getElementById("proctor_warning_banner");
        if (banner) {
            banner.innerHTML = `<i class="fa-solid fa-triangle-exclamation me-2"></i> ${msg}`;
            banner.style.display = "block";
            setTimeout(() => { banner.style.display = "none"; }, 6000);
        } else {
            console.warn(msg);
        }
    }
});
