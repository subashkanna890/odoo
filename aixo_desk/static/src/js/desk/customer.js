import { Component, markup, onMounted, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { Icon, attempt, deskRpc, toast } from "./helpers";

export class CustomerHome extends Component {
    static template = "aixo_desk.CustomerHome";
    static components = { Icon };
    static props = {};

    setup() {
        this.state = useState({ view: "all", search: "", data: null, loading: true });
        onMounted(() => this.load());
    }

    async load() {
        this.state.loading = true;
        const data = await attempt(() => deskRpc("/desk/api/my/home", { view: this.state.view, search: this.state.search }));
        if (data) {
            this.state.data = data;
        }
        this.state.loading = false;
    }

    setView(view) {
        this.state.view = view;
        this.load();
    }

    onSearch(ev) {
        this.state.search = ev.target.value;
        clearTimeout(this.timer);
        this.timer = setTimeout(() => this.load(), 300);
    }

    get title() {
        const view = this.state.data && this.state.data.views.find((v) => v.key === this.state.view);
        return view ? view.label : "My requests";
    }
}

export class CustomerTicket extends Component {
    static template = "aixo_desk.CustomerTicket";
    static components = { Icon };
    static props = { id: Number, csrf: String };

    setup() {
        this.fileRef = useRef("file");
        this.state = useState({
            data: null, draft: "", pending: [], sending: false, uploading: false, comment: "", rated: false,
        });
        onMounted(() => this.load());
    }

    async load() {
        const data = await attempt(() => deskRpc("/desk/api/my/ticket", { id: this.props.id }));
        if (data) {
            this.state.data = data;
            this.state.comment = data.ticket.rating_comment;
            document.title = `#${data.ticket.number} ${data.ticket.subject}`;
        }
    }

    markup(html) {
        return markup(html || "");
    }

    get closed() {
        return this.state.data.ticket.closed;
    }

    async send() {
        const text = this.state.draft.trim();
        if (!text) {
            return toast("Write a message first.", "error");
        }
        this.state.sending = true;
        const data = await attempt(() => deskRpc("/desk/api/my/reply", {
            id: this.props.id, body: text, attachment_ids: this.state.pending.map((a) => a.id),
        }));
        this.state.sending = false;
        if (data) {
            Object.assign(this.state, { draft: "", pending: [] });
            toast("Reply sent.", "ok");
            await this.load();
        }
    }

    pickFiles() {
        this.fileRef.el?.click();
    }

    async upload(ev) {
        const files = [...ev.target.files];
        ev.target.value = "";
        this.state.uploading = true;
        for (const file of files) {
            const form = new FormData();
            form.append("csrf_token", this.props.csrf);
            form.append("file", file);
            try {
                const response = await fetch(`/desk/my/ticket/${this.props.id}/attach`, { method: "POST", body: form });
                const result = await response.json();
                if (result.ok) {
                    this.state.pending.push(...result.data.attachments);
                } else {
                    toast(result.error, "error");
                }
            } catch {
                toast(`Could not upload ${file.name}.`, "error");
            }
        }
        this.state.uploading = false;
    }

    removePending(file) {
        this.state.pending = this.state.pending.filter((f) => f.id !== file.id);
    }

    async close() {
        if (!window.confirm("Mark this request as resolved?")) {
            return;
        }
        const data = await attempt(() => deskRpc("/desk/api/my/close", { id: this.props.id }));
        if (data) {
            toast("Marked as resolved.", "ok");
            await this.load();
        }
    }

    async reopen() {
        const data = await attempt(() => deskRpc("/desk/api/my/reopen", { id: this.props.id }));
        if (data) {
            toast("Request reopened.", "ok");
            await this.load();
        }
    }

    async rate(rating) {
        const data = await attempt(() => deskRpc("/desk/api/my/rate", { id: this.props.id, rating, comment: this.state.comment }));
        if (data) {
            this.state.data.ticket.rating = rating;
            toast("Thanks for your feedback!", "ok");
        }
    }
}

export class CustomerProjects extends Component {
    static template = "aixo_desk.CustomerProjects";
    static components = { Icon };
    static props = {};

    setup() {
        this.state = useState({ data: null, open: 0 });
        onMounted(async () => {
            const data = await attempt(() => deskRpc("/desk/api/my/projects"));
            if (data) {
                this.state.data = data;
            }
        });
    }
}

registry.category("public_components").add("aixo_desk.CustomerHome", CustomerHome);
registry.category("public_components").add("aixo_desk.CustomerTicket", CustomerTicket);
registry.category("public_components").add("aixo_desk.CustomerProjects", CustomerProjects);
