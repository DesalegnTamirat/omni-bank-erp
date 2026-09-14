/**
 * Advanced Anti-Cheating & Screenshot Prevention Engine (FR-EXM-021 - FR-EXM-023)
 * ==============================================================================
 * Comprehensive Client-Side Security Controls:
 * 1. Screenshot & Snipping Tool Interception (PrtScn, Win+Shift+S, Cmd+Shift+3/4/5)
 * 2. Instant Clipboard Neutralization
 * 3. Screen Obfuscation Privacy Shield (triggers on window blur / snipping activation)
 * 4. DevTools / Print Protection (F12, Ctrl+Shift+I, Ctrl+P, Ctrl+U)
 * 5. Copy / Cut / Paste Lockout
 * 6. Tab-Switch & Visibility Tracking with Auto-Disqualification
 */

document.addEventListener("DOMContentLoaded", () => {
    const examContainer = document.getElementById("exam_session_container");
    if (!examContainer) return;

    const token = examContainer.dataset.token;
    const maxTabSwitches = parseInt(examContainer.dataset.maxTabSwitches || "3", 10);
    let tabSwitchCount = 0;

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
                Screen capture and application switching are strictly prohibited during the assessment.<br/>
                Please click back on this window to resume your examination.
            </p>
            <div style="display: inline-block; background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3); padding: 8px 18px; border-radius: 20px; font-weight: 600; font-size: 0.9rem;">
                All screenshot attempts are logged
            </div>
        </div>
    `;
    document.body.appendChild(privacyShield);

    function reportViolation(eventType, details) {
        fetch(`/exam/session/${token}/event`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                params: {
                    event_type: eventType,
                    details: details || "",
                }
            })
        })
        .then(res => res.json())
        .then(data => {
            const result = data.result || {};
            if (result.action === "disqualified") {
                alert("CRITICAL NOTICE: You have exceeded the allowable security violation limit and have been automatically DISQUALIFIED from this examination.");
                window.location.reload();
            }
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

    // 3. Screenshot & DevTools Keyboard Defense (FR-EXM-022)
    document.addEventListener("keydown", (e) => {
        // PrintScreen key
        if (e.key === "PrintScreen" || e.keyCode === 44) {
            e.preventDefault();
            wipeClipboard();
            showPrivacyShieldTemporarily();
            reportViolation("screenshot", "PrintScreen key press intercepted");
            showSecurityWarning("Screenshots and screen captures are strictly prohibited.");
            return false;
        }

        // Windows Snipping Tool: Win + Shift + S or Shift + Windows key
        if (e.shiftKey && (e.key === "S" || e.key === "s") && (e.metaKey || e.ctrlKey)) {
            e.preventDefault();
            wipeClipboard();
            showPrivacyShieldTemporarily();
            reportViolation("screenshot", "Snipping tool shortcut (Win+Shift+S) detected");
            showSecurityWarning("Snipping tool is disabled during the exam.");
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
    });

    document.addEventListener("keyup", (e) => {
        if (e.key === "PrintScreen" || e.keyCode === 44) {
            wipeClipboard();
        }
    });

    // 4. Screen Privacy Shield on Focus Loss (Protects against external snipping tools)
    function showPrivacyShieldTemporarily() {
        privacyShield.style.display = "block";
        setTimeout(() => {
            privacyShield.style.display = "none";
        }, 3000);
    }

    window.addEventListener("blur", () => {
        // Obfuscate screen when window loses focus (e.g. snipping tool overlay activated)
        privacyShield.style.display = "block";
    });

    window.addEventListener("focus", () => {
        // Restore screen when candidate refocuses window
        privacyShield.style.display = "none";
    });

    // 5. Tab-Switch & Visibility Lockout (FR-EXM-023)
    document.addEventListener("visibilitychange", () => {
        if (document.hidden) {
            privacyShield.style.display = "block";
            tabSwitchCount++;
            reportViolation("tab_switch", `Tab switch #${tabSwitchCount} detected`);
            showSecurityWarning(`SECURITY ALERT: Tab switch detected (${tabSwitchCount}/${maxTabSwitches}). Exceeding ${maxTabSwitches} tab switches will result in immediate disqualification.`);
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
