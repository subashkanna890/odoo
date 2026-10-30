import { Component, onMounted, onWillUnmount, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { Icon, applyPrefs, attempt, deskRpc, toast } from "./helpers";

const CUSTOMER_NAV = [
    { key: "requests", label: "My requests", href: "/desk/my" },
    { key: "projects", label: "Projects", href: "/desk/my/projects" },
];
const NAV = [
    { key: "tickets", label: "Tickets", href: "/desk", adminHref: "/desk/admin" },
    { key: "projects", label: "Projects", href: "/desk/projects" },
    { key: "customers", label: "Customers", href: "/desk/customers" },
    { key: "employees", label: "Employees", href: "/desk/admin/people", admin: true },
    { key: "reports", label: "Reports", href: "/desk/admin/reports", admin: true },
    { key: "analytics", label: "Analytics", href: "/desk/analytics" },
];
const KIND_ICON = { assign: "assign", mention: "mention", sla: "sla", reply: "reply", email_failure: "email" };
const KIND_CLASS = { assign: "is-assign", mention: "is-mention", sla: "is-sla", reply: "is-reply", email_failure: "is-sla" };
const FILTERS = [["all", "All"], ["unread", "Unread"], ["mentions", "Mentions"], ["assignments", "Assignments"], ["flagged", "Flagged"]];
const STATUS_DOT = { online: "#2FB463", away: "#E08A00", offline: "#9AA1B0" };
const THEMES = [["red", "#D6453D"], ["green", "#1E9E57"], ["blue", "#0E3B2F"], ["yellow", "#D9A400"], ["orange", "#E8771A"]];
const FONTS = [["inter", "Inter"], ["roboto", "Roboto"], ["lato", "Lato"], ["open_sans", "Open Sans"], ["poppins", "Poppins"]];
const SIZES = [["xs", "Extra small"], ["s", "Small"], ["m", "Medium"], ["l", "Large"], ["xl", "Extra large"]];
const PREF_CARDS = [
    ["tdp", "Ticket Default Preferences", "Set frequently used ticket actions as the default preference to optimize your ticket handling experience.",
        ["Open next ticket after reply", "Reply to all by default", "Show draft reminder before leaving"]],
    ["dvp", "Detail View Preferences", "Personalize the detail view by setting your preferred viewing preferences.",
        ["Show newest conversation first", "Keep properties panel open", "Show AI summary at top"]],
    ["acc", "Accessibility Controls", "Make your helpdesk and digital experience more accessible and usable.",
        ["High contrast text", "Reduce motion", "Underline links"]],
    ["ess", "Employee Self-Service Preferences", "Enhance the usability of your digital helpdesk experience.",
        ["Show self-service portal link", "Suggest articles while typing"]],
];

/** Keeps Tab inside an open drawer and closes it on Escape. */
function trapFocus(ev, root, close) {
    if (ev.key === "Escape") {
        close();
        return;
    }
    if (ev.key !== "Tab" || !root) {
        return;
    }
    const focusable = [...root.querySelectorAll("a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex='-1'])")]
        .filter((el) => el.offsetParent !== null);
    if (!focusable.length) {
        return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (ev.shiftKey && document.activeElement === first) {
        ev.preventDefault();
        last.focus();
    } else if (!ev.shiftKey && document.activeElement === last) {
        ev.preventDefault();
        first.focus();
    }
}

export class Topbar extends Component {
    static template = "aixo_desk.Topbar";
    static components = { Icon };
    static props = {
        user: Object, active: String, csrf: String, show_edition: { type: Boolean, optional: true },
    };

    setup() {
        this.drawerRef = useRef("drawer");
        this.state = useState({
            drawer: null, unread: 0, notifications: [], failures: [], filter: "all", tab: "all", menu: false,
            profile: null, prefs: null, query: "", expanded: {}, recipient: {}, busy: false,
        });
        this.filters = FILTERS;
        this.statusDot = STATUS_DOT;
        this.themes = THEMES;
        this.fonts = FONTS;
        this.sizes = SIZES;
        this.cards = PREF_CARDS;
        this.kindIcon = KIND_ICON;
        this.kindClass = KIND_CLASS;
        this.onPush = (payload) => this.onPush_(payload);
        onMounted(() => this.start());
        onWillUnmount(() => this.env.services.bus_service?.unsubscribe?.("aixo_desk/notification", this.onPush));
    }

    get isCustomer() {
        return this.props.user.role === "customer";
    }

    get nav() {
        if (this.isCustomer) {
            return CUSTOMER_NAV;
        }
        const admin = this.props.user.role === "admin";
        return NAV.filter((item) => !item.admin || admin).map((item) => ({
            ...item, href: admin && item.adminHref ? item.adminHref : item.href,
        }));
    }

    async start() {
        if (!this.isCustomer) {
            const unread = await attempt(() => deskRpc("/desk/api/notifications/unread"));
            if (unread) {
                this.state.unread = unread.unread;
            }
        }
        const prefs = await attempt(() => deskRpc("/desk/api/prefs/get"));
        if (prefs) {
            this.state.prefs = prefs;
            applyPrefs(prefs);
        }
        const bus = this.isCustomer ? null : this.env.services.bus_service;
        if (bus) {
            bus.subscribe("aixo_desk/notification", this.onPush);
            bus.start?.();
        }
    }

    onPush_(payload) {
        this.state.unread += payload.is_read ? 0 : 1;
        toast(payload.text);
        if (this.state.drawer === "notifications") {
            this.loadNotifications();
        }
    }

    // ----------------------------------------------------------------- drawers
    async open(name) {
        this.state.drawer = name;
        this.state.menu = false;
        if (name === "notifications") {
            await this.loadNotifications();
        } else if (name === "profile") {
            this.state.profile = this.isCustomer ? { ...this.props.user, channels: {} }
                : await attempt(() => deskRpc("/desk/api/profile/get"));
        } else if (name === "prefs" && !this.state.prefs) {
            this.state.prefs = await attempt(() => deskRpc("/desk/api/prefs/get"));
        }
        setTimeout(() => this.drawerRef.el?.querySelector("button, a, input")?.focus(), 30);
    }

    close() {
        this.state.drawer = null;
    }

    onKeydown(ev) {
        trapFocus(ev, this.drawerRef.el, () => this.close());
    }

    // ----------------------------------------------------------- notifications
    async loadNotifications() {
        const data = await attempt(() => deskRpc("/desk/api/notifications/list", { filter: this.state.filter }));
        if (data) {
            this.state.notifications = data.items;
            this.state.failures = data.failures;
            this.state.unread = data.unread;
        }
    }

    async setFilter(value) {
        this.state.filter = value;
        this.state.menu = false;
        await this.loadNotifications();
    }

    async markAllRead() {
        const data = await attempt(() => deskRpc("/desk/api/notifications/read"));
        if (data) {
            this.state.unread = data.unread;
            this.state.notifications.forEach((n) => (n.is_read = true));
        }
    }

    async openTicket(notification) {
        const data = await attempt(() => deskRpc("/desk/api/notifications/read", { id: notification.id }));
        if (data) {
            notification.is_read = true;
            this.state.unread = data.unread;
        }
    }

    async toggleFlag(notification) {
        const data = await attempt(() => deskRpc("/desk/api/notifications/flag", { id: notification.id }));
        if (data) {
            notification.flagged = data.flagged;
            if (this.state.filter === "flagged" && !data.flagged) {
                this.state.notifications = this.state.notifications.filter((n) => n.id !== notification.id);
            }
        }
    }

    async retry(notification, withRecipient) {
        const email = withRecipient ? (this.state.recipient[notification.id] || "").trim() : undefined;
        const data = await attempt(() => deskRpc("/desk/api/notifications/retry", { id: notification.id, email }));
        if (data) {
            toast(data.retried ? "Retrying the failed email." : "Nothing left to send.");
            await this.loadNotifications();
        }
    }

    // ----------------------------------------------------------------- profile
    async setAvailability(value) {
        const data = await attempt(() => deskRpc("/desk/api/profile/status", { availability: value }));
        if (data) {
            this.state.profile = data;
        }
    }

    async cycleChannel(channel) {
        const order = ["online", "away", "offline"];
        const current = this.state.profile.channels[channel];
        const next = order[(order.indexOf(current) + 1) % 3];
        const data = await attempt(() => deskRpc("/desk/api/profile/status", { channel, state: next }));
        if (data) {
            this.state.profile = data;
        }
    }

    get presenceDot() {
        const profile = this.state.profile;
        const availability = profile ? profile.availability : this.props.user.availability;
        return STATUS_DOT[availability] || STATUS_DOT.online;
    }

    // ------------------------------------------------------------- preferences
    async savePref(values) {
        const data = await attempt(() => deskRpc("/desk/api/prefs/save", { values }));
        if (data) {
            this.state.prefs = data;
            applyPrefs(data);
        }
    }

    toggleCard(id) {
        this.state.expanded[id] = !this.state.expanded[id];
    }

    matches(text) {
        const q = this.state.query.trim().toLowerCase();
        return !q || text.toLowerCase().includes(q);
    }

    get visibleCards() {
        return this.cards.filter(([, title, desc, options]) => this.matches(`${title} ${desc} ${options.join(" ")}`));
    }

    get showAppearance() { return this.matches("Appearance mode night light auto"); }
    get showTheme() { return this.matches("Theme color red green blue yellow orange"); }
    get showFont() { return this.matches("Display Font Type Size"); }
    get nothingFound() {
        return !this.showAppearance && !this.showTheme && !this.showFont && !this.visibleCards.length;
    }
}

registry.category("public_components").add("aixo_desk.Topbar", Topbar);
