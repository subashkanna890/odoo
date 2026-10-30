import { Component, onMounted, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { Icon, attempt, deskRpc, toast } from "./helpers";

const LETTERS = ["ALL", ..."ABCDEFGHIJKLMNOPQRSTUVWXYZ"];
const STORE = "aixo_desk.customers";

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
        // storage unavailable: the choice just won't persist
    }
}

export class CustomerList extends Component {
    static template = "aixo_desk.CustomerList";
    static components = { Icon };
    static props = {};

    setup() {
        this.letters = LETTERS;
        this.state = useState({
            view: "all", letter: "ALL", search: "", data: null, loading: true,
            classic: stored("classic", false), allOpen: true, starred: stored("starred", ["all"]),
        });
        onMounted(() => this.load());
    }

    async load() {
        this.state.loading = true;
        const data = await attempt(() => deskRpc("/desk/api/customers/list", {
            view: this.state.view, letter: this.state.letter, search: this.state.search,
        }));
        if (data) {
            this.state.data = data;
        }
        this.state.loading = false;
    }

    setView(key) {
        Object.assign(this.state, { view: key, letter: "ALL" });
        this.load();
    }

    setLetter(letter) {
        this.state.letter = letter;
        this.load();
    }

    onSearch(ev) {
        this.state.search = ev.target.value;
        clearTimeout(this.timer);
        this.timer = setTimeout(() => this.load(), 300);
    }

    toggleClassic() {
        this.state.classic = !this.state.classic;
        remember("classic", this.state.classic);
    }

    isStarred(key) {
        return this.state.starred.includes(key);
    }

    toggleStar(key) {
        this.state.starred = this.isStarred(key)
            ? this.state.starred.filter((k) => k !== key)
            : [...this.state.starred, key];
        remember("starred", this.state.starred);
    }

    get title() {
        const view = this.state.data && this.state.data.views.find((v) => v.key === this.state.view);
        return view ? view.label : "Contacts";
    }

    get starredViews() {
        return this.state.data ? this.state.data.views.filter((v) => this.isStarred(v.key)) : [];
    }

    get otherViews() {
        return this.state.data ? this.state.data.views.filter((v) => !this.isStarred(v.key)) : [];
    }
}

const SECTION_FIELDS = [
    ["email", "Email", "email"], ["desk_email2", "Secondary email", "email"], ["phone", "Phone", "tel"],
    ["desk_mobile", "Mobile", "tel"], ["city", "City", "text"], ["desk_linkedin", "LinkedIn", "text"],
    ["desk_facebook", "Facebook", "text"],
];
const TABS = [["overview", "OVERVIEW"], ["history", "HISTORY"], ["activities", "ACTIVITIES"], ["interaction", "TICKET INTERACTION"]];
const STATUS_CLASS = { open: "is-open", on_hold: "is-hold", escalated: "is-escalated", closed: "is-closed" };

export class CustomerDetail extends Component {
    static template = "aixo_desk.CustomerDetail";
    static components = { Icon };
    static props = { id: Number, is_admin: { type: Boolean, optional: true } };

    setup() {
        this.fields = SECTION_FIELDS;
        this.tabs = TABS;
        this.statusClass = STATUS_CLASS;
        this.letters = LETTERS;
        this.state = useState({
            id: this.props.id, data: null, list: null, tab: "overview", ticketTab: "all", letter: "ALL", search: "",
            editing: "", draft: "", newTag: "", tagBox: false,
        });
        onMounted(async () => {
            await this.load();
            this.loadList();
        });
    }

    async load(id = this.state.id) {
        const data = await attempt(() => deskRpc("/desk/api/customers/get", { id }));
        if (data) {
            this.state.id = id;
            this.state.data = data;
            document.title = data.name;
        }
    }

    async loadList() {
        const data = await attempt(() => deskRpc("/desk/api/customers/list", {
            view: "all", letter: this.state.letter, search: this.state.search,
        }));
        if (data) {
            this.state.list = data;
        }
    }

    async select(contact) {
        window.history.pushState({}, "", `/desk/customer/${contact.id}`);
        this.state.tab = "overview";
        this.state.ticketTab = "all";
        this.state.editing = "";
        await this.load(contact.id);
    }

    onSearch(ev) {
        this.state.search = ev.target.value;
        clearTimeout(this.timer);
        this.timer = setTimeout(() => this.loadList(), 300);
    }

    setLetter(letter) {
        this.state.letter = letter;
        this.loadList();
    }

    get shownTickets() {
        const tickets = this.state.data.tickets;
        const tab = this.state.ticketTab;
        return tickets.filter((t) => tab === "all" || (tab === "open" && ["open", "escalated"].includes(t.state))
            || (tab === "on_hold" && t.state === "on_hold") || (tab === "closed" && t.state === "closed"));
    }

    get ticketTabs() {
        const s = this.state.data.stats;
        return [["all", `ALL (${s.all})`], ["open", `OPEN (${s.open})`], ["on_hold", `ON HOLD (${s.on_hold})`], ["closed", `CLOSED (${s.closed})`]];
    }

    get circle() {
        const c = 2 * Math.PI * 26;
        return `${((c * this.state.data.stats.health_score) / 100).toFixed(1)} ${c.toFixed(1)}`;
    }

    get healthLabel() {
        return this.state.data.stats.health === "healthy" ? "Healthy" : "Needs attention";
    }

    // ----------------------------------------------------------- inline editing
    edit(key) {
        this.state.editing = key;
        this.state.draft = String(this.state.data.props[key] ?? "");
        setTimeout(() => document.querySelector(".ax-inline-input")?.focus(), 20);
    }

    cancelEdit() {
        this.state.editing = "";
    }

    async commit(key, value = this.state.draft) {
        const old = String(this.state.data.props[key] ?? "");
        this.state.editing = "";
        if (String(value) === old) {
            return;
        }
        const data = await attempt(() => deskRpc("/desk/api/customers/update", { id: this.state.id, values: { [key]: value } }));
        if (data) {
            toast("Saved.", "ok");
            await this.load();
            this.loadList();
        }
    }

    onKey(ev, key) {
        if (ev.key === "Enter") {
            this.commit(key);
        } else if (ev.key === "Escape") {
            this.cancelEdit();
        }
    }

    async addTag() {
        const name = this.state.newTag.trim();
        if (!name) {
            return;
        }
        const data = await attempt(() => deskRpc("/desk/api/customers/tag", { id: this.state.id, add: name }));
        if (data) {
            this.state.data.tags = data.tags;
            Object.assign(this.state, { newTag: "", tagBox: false });
        }
    }

    async removeTag(tag) {
        const data = await attempt(() => deskRpc("/desk/api/customers/tag", { id: this.state.id, remove: tag.id }));
        if (data) {
            this.state.data.tags = data.tags;
        }
    }

    languageName(code) {
        const lang = this.state.data.languages.find((l) => l.code === code);
        return lang ? lang.name : code || "—";
    }

    ownerName(id) {
        const owner = this.state.data.owners.find((o) => o.id === id);
        return owner ? owner.name : "—";
    }
}

registry.category("public_components").add("aixo_desk.CustomerList", CustomerList);
registry.category("public_components").add("aixo_desk.CustomerDetail", CustomerDetail);
