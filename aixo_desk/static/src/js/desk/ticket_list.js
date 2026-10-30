import { Component, onMounted, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { Icon, PRIORITY_LABEL, PRIORITY_NUM, attempt, deskRpc } from "./helpers";

const VIEW_LIST = [
    ["all", "All Tickets"], ["my_open", "My Open Tickets"], ["unassigned", "Unassigned Tickets"],
    ["overdue", "Overdue Tickets"], ["closed", "Closed Tickets"],
];
const SORTS = [["created", "Newest first"], ["due", "Due date"], ["subject", "Subject"], ["status", "Status"]];
const STATUS_CLASS = { open: "is-open", on_hold: "is-hold", escalated: "is-escalated", closed: "is-closed" };
const STORE = "aixo_desk.list";

function stored(key, fallback) {
    try {
        const value = JSON.parse(window.localStorage.getItem(`${STORE}.${key}`));
        return value === null ? fallback : value;
    } catch {
        return fallback;
    }
}

function remember(key, value) {
    try {
        window.localStorage.setItem(`${STORE}.${key}`, JSON.stringify(value));
    } catch {
        // private mode: the preference just won't persist
    }
}

export class TicketList extends Component {
    static template = "aixo_desk.TicketList";
    static components = { Icon };
    static props = { csrf: { type: String, optional: true } };

    setup() {
        this.views = VIEW_LIST;
        this.sorts = SORTS;
        this.statusClass = STATUS_CLASS;
        this.priorityLabel = PRIORITY_LABEL;
        this.priorityNum = PRIORITY_NUM;
        this.state = useState({
            view: "all", search: "", sort: "created", page: 1, tag: 0,
            data: null, loading: true, classic: stored("classic", false), showCount: false,
            viewsOpen: true, starred: stored("starred", []), hover: 0, menu: null, tagsOpen: false,
        });
        this.searchTimer = null;
        onMounted(() => this.load());
    }

    async load() {
        this.state.loading = true;
        const data = await attempt(() => deskRpc("/desk/api/ticket/list", {
            view: this.state.view, search: this.state.search, sort: this.state.sort,
            page: this.state.page, tag_id: this.state.tag || undefined,
        }));
        if (data) {
            this.state.data = data;
        }
        this.state.loading = false;
    }

    setView(view) {
        Object.assign(this.state, { view, page: 1, tag: 0, tagsOpen: false });
        this.load();
    }

    setTag(tagId) {
        Object.assign(this.state, { view: "all", tag: tagId, page: 1 });
        this.load();
    }

    onSearch(ev) {
        this.state.search = ev.target.value;
        clearTimeout(this.searchTimer);
        this.searchTimer = setTimeout(() => {
            this.state.page = 1;
            this.load();
        }, 300);
    }

    setSort(ev) {
        this.state.sort = ev.target.value;
        this.load();
    }

    go(delta) {
        this.state.page += delta;
        this.load();
    }

    toggleClassic() {
        this.state.classic = !this.state.classic;
        remember("classic", this.state.classic);
    }

    get isStarred() {
        return this.state.starred.includes(this.state.view);
    }

    toggleStar() {
        const list = this.isStarred
            ? this.state.starred.filter((v) => v !== this.state.view)
            : [...this.state.starred, this.state.view];
        this.state.starred = list;
        remember("starred", list);
    }

    get title() {
        const data = this.state.data;
        if (this.state.tag && data) {
            const tag = data.tags.find((t) => t.id === this.state.tag);
            return `Tag: ${tag ? tag.name : ""}`;
        }
        return data ? data.title : "Tickets";
    }

    get lastPage() {
        const data = this.state.data;
        return data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
    }

    get pageLabel() {
        const data = this.state.data;
        if (!data || !data.total) {
            return "";
        }
        const from = (data.page - 1) * data.page_size + 1;
        return `${from}–${Math.min(data.total, from + data.page_size - 1)} of ${data.total}`;
    }

    async changeStatus(ticket, state) {
        this.state.menu = null;
        if (state === "closed") {
            window.location.href = `/desk/ticket/${ticket.id}#close`;
            return;
        }
        const data = await attempt(() => deskRpc("/desk/api/ticket/update", { id: ticket.id, values: { state } }));
        if (data) {
            Object.assign(ticket, data.ticket);
            this.load();
        }
    }

    async assign(ticket, ownerId) {
        this.state.menu = null;
        const data = await attempt(() => deskRpc("/desk/api/ticket/update", { id: ticket.id, values: { owner_id: ownerId } }));
        if (data) {
            Object.assign(ticket, data.ticket);
            this.load();
        }
    }

    toggleMenu(kind, id) {
        const key = `${kind}:${id}`;
        this.state.menu = this.state.menu === key ? null : key;
    }
}

registry.category("public_components").add("aixo_desk.TicketList", TicketList);
