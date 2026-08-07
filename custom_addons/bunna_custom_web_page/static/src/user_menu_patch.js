/** @odoo-module **/
import { registry } from "@web/core/registry";

const menu = registry.category("user_menuitems");
const systray = registry.category("systray");

function safeRemove(reg, key) {
    try {
        reg.remove(key);
    } catch (e) {
        // key not found, skip silently
    }
}

// ---------- DEBUG: log all systray keys to identify the theme switcher ----------
console.log("=== SYSTRAY KEYS ===");
systray.getEntries().forEach(([key, value]) => {
    console.log(key, value);
});
console.log("=== END SYSTRAY KEYS ===");

// Try all possible Help keys
safeRemove(menu, "support");         // Help

// Other items
safeRemove(menu, "shortcuts");       // Shortcuts
safeRemove(menu, "odoo_account");    // My Odoo.com Account
safeRemove(menu, "install_pwa");     // Install App

// ---------- Systray (header icons) ----------
safeRemove(systray, "AppMenuTheme"); // theme switcher droplet icon (guessed key)
//safeRemove(systray, "mail.messaging_menu");             // message bubble icon
safeRemove(systray, "mail.activity_menu");              // circular arrows / activity icon

// My Preferences
// safeRemove(menu, "preferences");

// Online status
// safeRemove(menu, "im_status");