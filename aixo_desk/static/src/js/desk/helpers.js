import { Component, xml } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";

/** Icon paths (24x24, stroke) taken from the design files. */
export const ICONS = {
    web: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM3 12h18M12 3c2.5 2.7 3.8 5.7 3.8 9s-1.3 6.3-3.8 9c-2.5-2.7-3.8-5.7-3.8-9S9.5 5.7 12 3z",
    email: "M3 6h18v12H3zM3 6l9 7 9-7",
    phone: "M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2z",
    chat: "M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z",
    whatsapp: "M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z",
    bell: "M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9M10 21a2 2 0 0 0 4 0",
    clock: "M12 5a8 8 0 1 1 0 16 8 8 0 0 1 0-16zM12 9v4l2 2",
    calendar: "M4 5h16v16H4zM4 10h16M9 3v4M15 3v4",
    chevronDown: "M6 9l6 6 6-6",
    chevronUp: "M6 15l6-6 6 6",
    chevronRight: "M9 6l6 6-6 6",
    star: "M12 3l2.8 5.8 6.2.9-4.5 4.4 1 6.2L12 17.3 6.5 20.3l1-6.2L3 9.7l6.2-.9z",
    search: "M11 4a7 7 0 1 1 0 14 7 7 0 0 1 0-14zM21 21l-5-5",
    plus: "M12 5v14M5 12h14",
    close: "M6 6l12 12M18 6L6 18",
    reply: "M9 14L4 9l5-5M4 9h11a5 5 0 0 1 5 5v6",
    user: "M12 3a4 4 0 1 1 0 8 4 4 0 0 1 0-8zM4 21a8 8 0 0 1 16 0",
    userPlus: "M9 3a4 4 0 1 1 0 8 4 4 0 0 1 0-8zM2 21a7 7 0 0 1 14 0M19 8v6M16 11h6",
    users: "M9 3.5a3.5 3.5 0 1 1 0 7 3.5 3.5 0 0 1 0-7zM2 20a7 7 0 0 1 14 0M16 14a5 5 0 0 1 6 5",
    attach: "M21 11l-9 9a6 6 0 0 1-8.5-8.5l9-9a4 4 0 0 1 5.7 5.7l-9 9a2 2 0 0 1-2.8-2.8l8.5-8.5",
    sparkle: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z",
    props: "M4 4h16v16H4zM8 9h8M8 13h8M8 17h5",
    bulb: "M9 18h6M10 22h4M12 2a7 7 0 0 0-4 12.7V17h8v-2.3A7 7 0 0 0 12 2z",
    history: "M3 12a9 9 0 1 0 3-6.7L3 8M3 3v5h5M12 7v5l3 2",
    tasks: "M9 12l2 2 4-4M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z",
    link: "M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7",
    macro: "M15 4V2M15 16v-2M8 9h2M20 9h2M17.8 11.8l1.4 1.4M17.8 6.2l1.4-1.4M3 21l9-9M12.2 6.2L10.8 4.8",
    flag: "M5 21V4M5 4h11l-2 4 2 4H5",
    download: "M12 4v12M6 12l6 6 6-6M4 21h16",
    trash: "M4 7h16M9 7V4h6v3M6 7l1 14h10l1-14",
    edit: "M4 20l4-1 11-11-3-3L5 16zM14 6l3 3",
    play: "M2 1l9 5-9 5z",
    pause: "M2 1h3v10H2zM7 1h3v10H7z",
    check: "M5 12l5 5 9-10",
    briefcase: "M4 7h16v13H4zM9 7V4h6v3",
    refresh: "M3 12a9 9 0 0 1 15-6.7L21 8M21 3v5h-5M21 12a9 9 0 0 1-15 6.7L3 16M3 21v-5h5",
    external: "M14 3h7v7M21 3l-9 9M19 14v6H4V5h6",
    menu: "M4 6h16M4 12h16M4 18h16",
    tag: "M20.6 13.4l-7.2 7.2a2 2 0 0 1-2.8 0L3 13V3h10l7.6 7.6a2 2 0 0 1 0 2.8z",
    grid: "M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z",
    folder: "M3 6h7l2 2h9v11H3z",
    mention: "M16 12a4 4 0 1 1-1.2-2.8M16 8v5a2 2 0 0 0 4 0v-1a8 8 0 1 0-3.1 6.3",
    sla: "M12 13m-8 0a8 8 0 1 0 16 0a8 8 0 1 0-16 0M12 9v4l2 2M9 2h6",
    assign: "M16 21v-2a4 4 0 0 0-8 0v2M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8M19 8v6M16 11h6",
};

export class Icon extends Component {
    static props = { name: String, size: { type: Number, optional: true }, fill: { type: String, optional: true } };
    static template = xml`<svg t-att-width="props.size || 16" t-att-height="props.size || 16" viewBox="0 0 24 24"
        t-att-fill="props.fill || 'none'" stroke="currentColor" stroke-width="2" stroke-linecap="round"
        stroke-linejoin="round" aria-hidden="true"><path t-att-d="icons[props.name]"/></svg>`;
    icons = ICONS;
}

/**
 * Call a desk JSON route. Resolves with ``data``; rejects with an Error whose
 * message is shown to the user. An expired session sends the user to log in.
 */
export async function deskRpc(route, params = {}) {
    let result;
    try {
        result = await rpc(route, params);
    } catch {
        throw new Error("Network problem. Please try again.");
    }
    if (result && result.ok) {
        return result.data;
    }
    if (result && result.code === "auth") {
        window.location.href = "/desk/login?redirect=" + encodeURIComponent(window.location.pathname);
    }
    if (result && result.code === "password") {
        window.location.href = "/desk/password/change";
    }
    throw new Error((result && result.error) || "Something went wrong.");
}

let toastBox;
/** Small self-contained toast (no dependency on the web client services). */
export function toast(message, type = "info") {
    if (!toastBox) {
        toastBox = document.createElement("div");
        toastBox.className = "ax-toasts";
        toastBox.setAttribute("role", "status");
        toastBox.setAttribute("aria-live", "polite");
        document.body.append(toastBox);
    }
    const el = document.createElement("div");
    el.className = `ax-toast ax-toast-${type}`;
    el.textContent = message;
    toastBox.append(el);
    setTimeout(() => el.remove(), type === "error" ? 6000 : 3500);
}

/** Runs an async action, toasting its error. Returns undefined on failure. */
export async function attempt(action) {
    try {
        return await action();
    } catch (error) {
        toast(error.message, "error");
        return undefined;
    }
}

export function formatDuration(totalSeconds) {
    const s = Math.max(0, Math.floor(totalSeconds));
    const pad = (n) => String(n).padStart(2, "0");
    return `${pad(Math.floor(s / 3600))} : ${pad(Math.floor((s % 3600) / 60))} : ${pad(s % 60)}`;
}

/** "in 2h 15m" / "overdue by 40m" relative to ``now`` (ms). */
export function relative(isoString, now) {
    if (!isoString) {
        return "";
    }
    const diff = new Date(isoString).getTime() - now;
    const abs = Math.abs(diff) / 60000;
    const days = Math.floor(abs / 1440);
    const hours = Math.floor((abs % 1440) / 60);
    const minutes = Math.floor(abs % 60);
    const text = days ? `${days}d ${hours}h` : hours ? `${hours}h ${minutes}m` : `${minutes}m`;
    return diff >= 0 ? `in ${text}` : `overdue by ${text}`;
}

/** Applies saved preferences to the page root (CSS variables read these attributes). */
export function applyPrefs(prefs) {
    const root = document.querySelector(".ax-desk");
    if (!root) {
        return;
    }
    const map = {
        theme: "theme", appearance: "appearance", font: "font", size: "size",
    };
    for (const [key, attr] of Object.entries(map)) {
        if (prefs[key]) {
            root.dataset[attr] = prefs[key];
        }
    }
    if (prefs.light_panel !== undefined) {
        root.dataset.lightPanel = prefs.light_panel ? "1" : "0";
    }
    if (prefs.toggles) {
        root.classList.toggle("ax-high-contrast", !!prefs.toggles.acc0);
        root.classList.toggle("ax-reduce-motion", !!prefs.toggles.acc1);
        root.classList.toggle("ax-underline-links", !!prefs.toggles.acc2);
    }
}

export const CHANNEL_LABEL = { email: "Email", phone: "Phone", web: "Web", chat: "Chat", whatsapp: "WhatsApp" };
export const PRIORITY_NUM = { urgent: 0, high: 1, medium: 2, low: 3 };
export const PRIORITY_LABEL = { urgent: "Urgent", high: "High", medium: "Medium", low: "Low" };
