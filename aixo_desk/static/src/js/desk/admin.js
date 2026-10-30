import { Component, onMounted, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { Icon, PRIORITY_LABEL, attempt, deskRpc, toast } from "./helpers";

const STATUS_CLASS = { open: "is-open", on_hold: "is-hold", escalated: "is-escalated", closed: "is-closed" };
const CREATE_ITEMS = [
    ["New ticket", "/desk/ticket/new", "plus"], ["New employee", "/desk/admin/people?add=employee", "userPlus"],
    ["New customer", "/desk/admin/people?tab=customers&add=customer", "user"],
    ["New team", "/desk/admin/people?tab=teams&add=team", "users"], ["New project", "/desk/projects?new=1", "folder"],
];

export class AdminHome extends Component {
    static template = "aixo_desk.AdminHome";
    static components = { Icon };
    static props = {};

    setup() {
        this.statusClass = STATUS_CLASS;
        this.priorityLabel = PRIORITY_LABEL;
        this.createItems = CREATE_ITEMS;
        this.state = useState({
            view: "all", search: "", page: 1, data: null, loading: true, selected: {}, bulk: 0, createOpen: false,
        });
        onMounted(() => this.load());
    }

    async load() {
        this.state.loading = true;
        const data = await attempt(() => deskRpc("/desk/api/admin/tickets", {
            view: this.state.view, search: this.state.search, page: this.state.page,
        }));
        if (data) {
            this.state.data = data;
            if (!this.state.bulk && data.agents.length) {
                this.state.bulk = data.agents[0].id;
            }
        }
        this.state.loading = false;
    }

    setView(view) {
        Object.assign(this.state, { view, page: 1, selected: {} });
        this.load();
    }

    onSearch(ev) {
        this.state.search = ev.target.value;
        clearTimeout(this.timer);
        this.timer = setTimeout(() => {
            this.state.page = 1;
            this.load();
        }, 300);
    }

    go(delta) {
        this.state.page += delta;
        this.state.selected = {};
        this.load();
    }

    get selectedIds() {
        return Object.keys(this.state.selected).filter((id) => this.state.selected[id]).map(Number);
    }

    toggle(ticket) {
        this.state.selected[ticket.id] = !this.state.selected[ticket.id];
    }

    get allSelected() {
        const tickets = this.state.data ? this.state.data.tickets : [];
        return tickets.length > 0 && tickets.every((t) => this.state.selected[t.id]);
    }

    toggleAll() {
        const value = !this.allSelected;
        for (const t of this.state.data.tickets) {
            this.state.selected[t.id] = value;
        }
    }

    clear() {
        this.state.selected = {};
    }

    async assign(ids, ownerId) {
        const data = await attempt(() => deskRpc("/desk/api/admin/assign", { ids, owner_id: ownerId || undefined }));
        if (data) {
            toast(data.message, "ok");
            this.state.selected = {};
            await this.load();
        }
    }

    assignOne(ticket, ev) {
        return this.assign([ticket.id], Number(ev.target.value));
    }

    assignBulk() {
        return this.assign(this.selectedIds, this.state.bulk);
    }

    get maxLoad() {
        const loads = this.state.data ? this.state.data.workload.map((w) => w.open) : [];
        return Math.max(3, ...loads);
    }

    get lastPage() {
        const d = this.state.data;
        return d ? Math.max(1, Math.ceil(d.total / d.page_size)) : 1;
    }
}

const FORMS = {
    employees: { add: "Add employee", create: "Create employee", title: "New employee" },
    customers: { add: "Add customer", create: "Create customer", title: "New customer" },
    teams: { add: "Create team", create: "Create team", title: "New team" },
};

export class AdminPeople extends Component {
    static template = "aixo_desk.AdminPeople";
    static components = { Icon };
    static props = { add: { type: String, optional: true }, tab: { type: String, optional: true } };

    setup() {
        this.forms = FORMS;
        this.state = useState({
            tab: FORMS[this.props.tab] ? this.props.tab : "employees", search: "", data: null,
            form: null, tried: false, showPw: false, saving: false,
        });
        onMounted(async () => {
            await this.load();
            if (this.props.add) {
                this.openForm();
            }
        });
    }

    async load() {
        const data = await attempt(() => deskRpc("/desk/api/admin/people", { search: this.state.search }));
        if (data) {
            this.state.data = data;
        }
    }

    setTab(tab) {
        Object.assign(this.state, { tab, search: "", form: null });
        this.load();
    }

    onSearch(ev) {
        this.state.search = ev.target.value;
        clearTimeout(this.timer);
        this.timer = setTimeout(() => this.load(), 250);
    }

    get rows() {
        return this.state.data ? this.state.data[this.state.tab] : [];
    }

    get tabs() {
        const counts = this.state.data ? this.state.data.counts : {};
        return [["employees", "Employees", "userPlus"], ["customers", "Customers", "user"], ["teams", "Teams", "users"]]
            .map(([key, label, icon]) => ({ key, label, icon, count: counts[key] ?? "" }));
    }

    // -------------------------------------------------------------------- form
    openForm(row = null) {
        const tab = this.state.tab;
        const opts = this.state.data ? this.state.data.options : { teams: [] };
        const base = {
            employees: { name: "", phone: "", role: "agent", team_id: opts.teams[0] ? opts.teams[0].id : 0, email: "", password: "", send_login: true, force_change: true },
            customers: { name: "", company: "", phone: "", plan: "free", email: "", password: "", send_login: true },
            teams: { name: "", lead_id: 0, department: "Support", description: "", member_ids: [] },
        }[tab];
        if (row && tab === "employees") {
            Object.assign(base, { name: row.name, phone: row.phone, role: row.role, team_id: row.team_id });
        } else if (row && tab === "teams") {
            Object.assign(base, { name: row.name, lead_id: row.lead_id, department: row.department, description: row.description, member_ids: [...row.member_ids] });
        }
        this.state.form = { id: row ? row.id : 0, values: base };
        Object.assign(this.state, { tried: false, showPw: false });
        setTimeout(() => document.querySelector(".ax-dialog input")?.focus(), 30);
    }

    closeForm() {
        this.state.form = null;
    }

    get isEdit() {
        return !!(this.state.form && this.state.form.id);
    }

    async generate() {
        const data = await attempt(() => deskRpc("/desk/api/admin/generate-password"));
        if (data) {
            this.state.form.values.password = data.password;
            this.state.showPw = true;
        }
    }

    toggleMember(id) {
        const values = this.state.form.values;
        values.member_ids = values.member_ids.includes(id) ? values.member_ids.filter((m) => m !== id) : [...values.member_ids, id];
    }

    get formErrors() {
        const v = this.state.form.values;
        const errors = {};
        errors.name = !v.name.trim();
        if (!this.isEdit && this.state.tab !== "teams") {
            errors.email = !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v.email.trim());
            errors.password = v.password.length < 8;
        }
        return errors;
    }

    async save() {
        this.state.tried = true;
        if (Object.values(this.formErrors).some(Boolean)) {
            return;
        }
        const tab = this.state.tab;
        const { id, values } = this.state.form;
        let route;
        let params;
        if (tab === "teams") {
            route = "/desk/api/admin/team/save";
            params = { team_id: id || undefined, values };
        } else if (id) {
            route = "/desk/api/admin/employee/update";
            params = { id, values: { name: values.name, phone: values.phone, role: values.role, team_id: values.team_id } };
        } else {
            route = tab === "employees" ? "/desk/api/admin/employee/create" : "/desk/api/admin/customer/create";
            params = { values };
        }
        this.state.saving = true;
        const data = await attempt(() => deskRpc(route, params));
        this.state.saving = false;
        if (data) {
            toast(data.message, "ok");
            this.state.form = null;
            await this.load();
        }
    }

    async toggleUser(row) {
        const verb = row.active ? "Deactivate" : "Reactivate";
        if (row.active && !window.confirm(`${verb} ${row.name}? They will no longer be able to log in.`)) {
            return;
        }
        const data = await attempt(() => deskRpc("/desk/api/admin/user/toggle", { id: row.id }));
        if (data) {
            toast(data.message, "ok");
            await this.load();
        }
    }

    async invite(row) {
        const data = await attempt(() => deskRpc("/desk/api/admin/user/invite", { id: row.id }));
        if (data) {
            toast(data.message, "ok");
        }
    }
}

export class AdminReports extends Component {
    static template = "aixo_desk.AdminReports";
    static components = { Icon };
    static props = {};

    setup() {
        this.state = useState({ tab: "emp", days: 7, data: null, loading: true });
        this.periods = [[7, "Last 7 days"], [30, "Last 30 days"], [90, "Last 90 days"]];
        onMounted(() => this.load());
    }

    async load() {
        this.state.loading = true;
        const data = await attempt(() => deskRpc("/desk/api/admin/reports", { tab: this.state.tab, days: this.state.days }));
        if (data) {
            this.state.data = data;
        }
        this.state.loading = false;
    }

    setTab(tab) {
        this.state.tab = tab;
        this.state.data = null;
        this.load();
    }

    setDays(days) {
        this.state.days = days;
        this.load();
    }

    exportUrl(fmt) {
        return `/desk/admin/reports/export.${fmt}?tab=${this.state.tab}&days=${this.state.days}`;
    }

    slaColor(value) {
        return value === null ? "#9AA1B0" : value >= 90 ? "#2FB463" : value >= 80 ? "#E08A00" : "#D6453D";
    }

    csatClass(value) {
        return value === null ? "" : value >= 4.5 ? "is-good" : value >= 4 ? "" : "is-bad";
    }

    maxTickets() {
        return this.state.data && this.state.data.tab === "cust"
            ? Math.max(1, ...this.state.data.rows.map((r) => r.tickets)) : 1;
    }
}

registry.category("public_components").add("aixo_desk.AdminHome", AdminHome);
registry.category("public_components").add("aixo_desk.AdminPeople", AdminPeople);
registry.category("public_components").add("aixo_desk.AdminReports", AdminReports);
