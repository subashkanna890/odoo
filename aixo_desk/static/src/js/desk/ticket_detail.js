import { Component, markup, onMounted, onWillUnmount, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import {
    Icon, PRIORITY_LABEL, attempt, deskRpc, formatDuration, relative, toast,
} from "./helpers";

const TABS = [["conv", "CONVERSATIONS"], ["res", "RESOLUTION"], ["time", "TIME ENTRIES"], ["att", "ATTACHMENTS"]];
const RAIL = [
    ["props", "Ticket Properties", "props"], ["ai", "AI Insights", "bulb"], ["history", "History", "history"],
    ["tasks", "Tasks", "tasks"], ["related", "Related Tickets", "link"], ["macros", "Macros", "macro"],
];
const STATUS_CLASS = { open: "is-open", on_hold: "is-hold", escalated: "is-escalated", closed: "is-closed" };
const PRIORITIES = ["urgent", "high", "medium", "low"];

function parseHours(text) {
    const value = String(text).trim();
    const clock = value.match(/^(\d+):([0-5]?\d)$/);
    if (clock) {
        return Number(clock[1]) + Number(clock[2]) / 60;
    }
    return Number(value.replace(",", "."));
}

export class TicketDetail extends Component {
    static template = "aixo_desk.TicketDetail";
    static components = { Icon };
    static props = { id: Number, csrf: String };

    setup() {
        this.tabs = TABS;
        this.rail = RAIL;
        this.statusClass = STATUS_CLASS;
        this.priorities = PRIORITIES;
        this.priorityLabel = PRIORITY_LABEL;
        this.composerRef = useRef("composer");
        this.fileRef = useRef("file");
        this.state = useState({
            id: this.props.id, data: null, loading: true, tab: "conv", rail: "props", now: Date.now(),
            sections: { contact: true, key: true, ai: true }, switchSearch: "",
            composing: window.location.hash === "#reply", draft: "", internal: false, macroId: 0,
            pending: [], sending: false, closing: window.location.hash === "#close",
            resolution: "", notify: true, summary: null, newTag: "", tagBox: false,
            entry: null, prefs: { dvp0: true, dvp1: true, dvp2: true, tdp0: false, tdp1: true }, uploading: false,
        });
        onMounted(() => {
            this.load();
            this.timer = setInterval(() => (this.state.now = Date.now()), 1000);
            this.loadPrefs();
        });
        onWillUnmount(() => clearInterval(this.timer));
    }

    async loadPrefs() {
        const prefs = await attempt(() => deskRpc("/desk/api/prefs/get"));
        if (prefs) {
            Object.assign(this.state.prefs, prefs.toggles);
        }
    }

    async load(id = this.state.id) {
        this.state.loading = true;
        const data = await attempt(() => deskRpc("/desk/api/ticket/get", { id }));
        this.state.loading = false;
        if (!data) {
            return;
        }
        this.state.id = id;
        this.state.data = data;
        this.state.summary = null;
        this.state.resolution = data.ticket.resolution || "";
        document.title = `#${data.ticket.number} ${data.ticket.subject}`;
        this.loadSummary();
    }

    async loadSummary() {
        const summary = await attempt(() => deskRpc("/desk/api/ticket/summary", { id: this.state.id }));
        if (summary) {
            this.state.summary = summary;
        }
    }

    async open(ticket) {
        if (ticket.id === this.state.id) {
            return;
        }
        window.history.pushState({}, "", `/desk/ticket/${ticket.id}`);
        this.state.composing = false;
        this.state.draft = "";
        this.state.pending = [];
        await this.load(ticket.id);
    }

    // ---------------------------------------------------------------- display
    markup(html) {
        return markup(html || "");
    }

    get ticket() {
        return this.state.data.ticket;
    }

    get messages() {
        const list = [...this.state.data.messages];
        return this.state.prefs.dvp0 ? list.reverse() : list;
    }

    get switcher() {
        const q = this.state.switchSearch.trim().toLowerCase();
        return this.state.data.switcher.filter((t) =>
            !q || `${t.subject} ${t.number} ${t.contact}`.toLowerCase().includes(q));
    }

    get conversationLabel() {
        const n = this.state.data.messages.length + 1;
        return `${n} CONVERSATION${n === 1 ? "" : "S"}`;
    }

    tabLabel(id, fallback) {
        const d = this.state.data;
        if (id === "conv") {
            return this.conversationLabel;
        }
        if (id === "time") {
            return `${d.time_entries.length} TIME ENTRIES`;
        }
        if (id === "att") {
            return `${d.attachments.length} ATTACHMENTS`;
        }
        return fallback;
    }

    get sla() {
        const t = this.ticket;
        const now = this.state.now;
        const sla = t.sla;
        if (t.closed) {
            return { chip: "Met", cls: "is-ok", text: "Resolved" };
        }
        if (sla.responded_on) {
            const late = sla.first_response_deadline && new Date(sla.responded_on) > new Date(sla.first_response_deadline);
            return { chip: "Responded", cls: late ? "is-warn" : "is-ok", text: late ? "Responded late" : "Responded on time" };
        }
        if (sla.paused) {
            return { chip: "Paused", cls: "is-muted", text: "SLA paused while on hold" };
        }
        if (!sla.first_response_deadline) {
            return { chip: "No SLA", cls: "is-muted", text: "No SLA policy" };
        }
        const left = new Date(sla.first_response_deadline).getTime() - now;
        const cls = left < 0 ? "is-bad" : sla.status === "at_risk" ? "is-warn" : "is-ok";
        const chip = left < 0 ? "Breached" : sla.status === "at_risk" ? "At risk" : "On time";
        return { chip, cls, text: relative(sla.first_response_deadline, now) };
    }

    get timerSeconds() {
        const timer = this.state.data.timer;
        const extra = timer.running ? (this.state.now - new Date(timer.started).getTime()) / 1000 : 0;
        return timer.base_seconds + extra;
    }

    get timerText() {
        return formatDuration(this.timerSeconds);
    }

    get totalHours() {
        return this.state.data.time_entries.reduce((sum, e) => sum + e.hours, 0).toFixed(2);
    }

    // ---------------------------------------------------------------- actions
    toggleSection(name) {
        this.state.sections[name] = !this.state.sections[name];
    }

    async save(values) {
        const data = await attempt(() => deskRpc("/desk/api/ticket/update", { id: this.state.id, values }));
        if (data) {
            Object.assign(this.ticket, data.ticket, { due_input: data.due_input });
            const row = this.state.data.switcher.find((t) => t.id === this.state.id);
            if (row) {
                Object.assign(row, data.ticket);
            }
            const history = await attempt(() => deskRpc("/desk/api/ticket/get", { id: this.state.id }));
            if (history) {
                this.state.data.history = history.history;
                this.state.data.ticket.sla = history.ticket.sla;
            }
        }
        return data;
    }

    assignMe() {
        const me = this.state.data.me;
        const current = this.ticket.owner;
        return this.save({ owner_id: current && current.id === me.id ? 0 : me.id });
    }

    async addTag() {
        const name = this.state.newTag.trim();
        if (!name) {
            return;
        }
        const data = await attempt(() => deskRpc("/desk/api/ticket/tag", { id: this.state.id, add: name }));
        if (data) {
            this.ticket.tags = data.tags;
            this.state.newTag = "";
            this.state.tagBox = false;
        }
    }

    async removeTag(tag) {
        const data = await attempt(() => deskRpc("/desk/api/ticket/tag", { id: this.state.id, remove: tag.id }));
        if (data) {
            this.ticket.tags = data.tags;
        }
    }

    async toggleTimer() {
        const route = this.state.data.timer.running ? "/desk/api/timer/pause" : "/desk/api/timer/start";
        const data = await attempt(() => deskRpc(route, { id: this.state.id }));
        if (data) {
            this.state.data.timer = data.timer;
            if (data.time_entries) {
                this.state.data.time_entries = data.time_entries;
            }
        }
    }

    // ------------------------------------------------------------- composer
    openComposer(internal = false) {
        this.state.composing = true;
        this.state.internal = internal;
        this.state.tab = "conv";
        setTimeout(() => this.composerRef.el?.focus(), 30);
    }

    closeComposer() {
        this.state.composing = false;
        this.state.draft = "";
        this.state.pending = [];
        this.state.macroId = 0;
    }

    useMacro(macro) {
        this.state.draft = macro.text;
        this.state.macroId = macro.id;
        this.openComposer(this.state.internal);
    }

    async send() {
        if (!this.state.draft.trim()) {
            return toast("Write a message first.", "error");
        }
        this.state.sending = true;
        const data = await attempt(() => deskRpc("/desk/api/ticket/reply", {
            id: this.state.id, body: this.state.draft, internal: this.state.internal,
            attachment_ids: this.state.pending.map((a) => a.id), macro_id: this.state.macroId || undefined,
        }));
        this.state.sending = false;
        if (!data) {
            return;
        }
        this.state.data.messages.push(data.message);
        Object.assign(this.ticket, data.ticket);
        if (!this.state.internal) {
            this.ticket.sla.responded_on = this.ticket.sla.responded_on || new Date().toISOString();
        }
        toast(this.state.internal ? "Note added." : "Reply sent to the customer.", "ok");
        const macro = this.state.data.macros.find((m) => m.id === this.state.macroId);
        if (macro && macro.set_state === "on_hold") {
            this.ticket.state = "on_hold";
            this.ticket.state_label = "On Hold";
        }
        this.closeComposer();
        if (!this.state.internal && this.state.prefs.tdp0) {
            const index = this.state.data.switcher.findIndex((t) => t.id === this.state.id);
            const next = this.state.data.switcher[index + 1];
            if (next) {
                this.open(next);
            }
        }
    }

    pickFiles() {
        this.fileRef.el?.click();
    }

    async upload(ev) {
        const files = [...ev.target.files];
        ev.target.value = "";
        if (!files.length) {
            return;
        }
        this.state.uploading = true;
        for (const file of files) {
            const form = new FormData();
            form.append("csrf_token", this.props.csrf);
            form.append("file", file);
            try {
                const response = await fetch(`/desk/ticket/${this.state.id}/attach`, { method: "POST", body: form });
                const result = await response.json();
                if (!result.ok) {
                    toast(result.error, "error");
                    continue;
                }
                for (const attachment of result.data.attachments) {
                    this.state.data.attachments.push(attachment);
                    this.state.pending.push(attachment);
                }
            } catch {
                toast(`Could not upload ${file.name}.`, "error");
            }
        }
        this.state.uploading = false;
    }

    removePending(attachment) {
        this.state.pending = this.state.pending.filter((a) => a.id !== attachment.id);
    }

    // -------------------------------------------------------- close / reopen
    openClose() {
        this.state.closing = true;
    }

    async closeTicket() {
        const data = await attempt(() => deskRpc("/desk/api/ticket/close", {
            id: this.state.id, summary: this.state.resolution, notify: this.state.notify,
        }));
        if (data) {
            Object.assign(this.ticket, data.ticket, { closed: true, resolution: data.resolution });
            this.state.closing = false;
            this.state.tab = "res";
            await this.load();
            toast("Ticket closed.", "ok");
        }
    }

    async reopen() {
        const data = await attempt(() => deskRpc("/desk/api/ticket/reopen", { id: this.state.id }));
        if (data) {
            await this.load();
            toast("Ticket reopened.", "ok");
        }
    }

    // ------------------------------------------------------------ time entries
    newEntry() {
        this.state.entry = { id: 0, name: "", date_input: new Date().toISOString().slice(0, 10), hours: "" };
    }

    editEntry(entry) {
        this.state.entry = { id: entry.id, name: entry.name, date_input: entry.date_input, hours: String(entry.hours) };
    }

    async saveEntry() {
        const entry = this.state.entry;
        const hours = parseHours(entry.hours);
        if (!Number.isFinite(hours) || hours < 0) {
            return toast("Enter the time spent, like 1.5 or 1:30.", "error");
        }
        const data = await attempt(() => deskRpc("/desk/api/time/save", {
            id: this.state.id, entry_id: entry.id || undefined,
            values: { name: entry.name, date: entry.date_input, hours },
        }));
        if (data) {
            this.state.data.time_entries = data.time_entries;
            this.state.data.timer = data.timer;
            this.state.entry = null;
        }
    }

    async deleteEntry(entry) {
        if (!window.confirm("Delete this time entry?")) {
            return;
        }
        const data = await attempt(() => deskRpc("/desk/api/time/delete", { id: this.state.id, entry_id: entry.id }));
        if (data) {
            this.state.data.time_entries = data.time_entries;
            this.state.data.timer = data.timer;
        }
    }

    formatSize(bytes) {
        return bytes > 1048576 ? `${(bytes / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
    }
}

registry.category("public_components").add("aixo_desk.TicketDetail", TicketDetail);
