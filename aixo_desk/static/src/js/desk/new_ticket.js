import { Component, onMounted, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { Icon, attempt, deskRpc, toast } from "./helpers";

const EMPTY = () => ({
    contact: "", contact_id: 0, account: "", email: "", phone: "", subject: "", description: "",
    status: "open", owner_id: 0, product_id: 0, project_id: 0, due_date: "", lang_id: 0,
    priority: "", channel: "web", classification: "", template_id: 0,
});

export class NewTicket extends Component {
    static template = "aixo_desk.NewTicket";
    static components = { Icon };
    static props = { csrf: String, partner: { type: Number, optional: true } };

    setup() {
        this.state = useState({
            opts: null, v: EMPTY(), submitted: false, created: null, files: [], uploading: false,
            suggestions: [], contact: null, searching: false, relatedOpen: true, saving: false,
        });
        this.searchTimer = null;
        onMounted(() => this.load());
    }

    async load() {
        const opts = await attempt(() => deskRpc("/desk/api/newticket/options", { partner_id: this.props.partner || undefined }));
        if (!opts) {
            return;
        }
        this.state.opts = opts;
        this.state.v.owner_id = opts.me || 0;
        if (opts.contact) {
            this.pickContact(opts.contact);
        }
    }

    get isCustomer() {
        return this.state.opts && this.state.opts.mode === "customer";
    }

    get errors() {
        const v = this.state.v;
        return {
            contact: this.state.submitted && !this.isCustomer && !v.contact.trim(),
            subject: this.state.submitted && !v.subject.trim(),
        };
    }

    // ------------------------------------------------------------------ contact
    onContactInput(ev) {
        const v = this.state.v;
        v.contact = ev.target.value;
        v.contact_id = 0;
        this.state.contact = null;
        clearTimeout(this.searchTimer);
        if (!v.contact.trim()) {
            this.state.suggestions = [];
            return;
        }
        this.searchTimer = setTimeout(async () => {
            const data = await attempt(() => deskRpc("/desk/api/contact/search", { q: v.contact }));
            if (data) {
                this.state.suggestions = data.contacts;
            }
        }, 250);
    }

    pickContact(contact) {
        const v = this.state.v;
        Object.assign(v, {
            contact: contact.name, contact_id: contact.id, account: contact.account,
            email: contact.email, phone: contact.phone,
        });
        this.state.contact = contact;
        this.state.suggestions = [];
    }

    // ----------------------------------------------------------------- template
    pickTemplate(ev) {
        const template = this.state.opts.templates.find((t) => t.id === Number(ev.target.value));
        const v = this.state.v;
        v.template_id = template ? template.id : 0;
        if (!template) {
            return;
        }
        v.subject = v.subject || template.prefix;
        v.description = template.description;
        if (template.priority) {
            v.priority = template.priority;
        }
        if (template.classification) {
            v.classification = template.classification;
        }
    }

    // ------------------------------------------------------------------- upload
    async upload(files) {
        this.state.uploading = true;
        for (const file of files) {
            const form = new FormData();
            form.append("csrf_token", this.props.csrf);
            form.append("file", file);
            try {
                const response = await fetch("/desk/ticket/attach-draft", { method: "POST", body: form });
                const result = await response.json();
                if (result.ok) {
                    this.state.files.push(...result.data.attachments);
                } else {
                    toast(result.error, "error");
                }
            } catch {
                toast(`Could not upload ${file.name}.`, "error");
            }
        }
        this.state.uploading = false;
    }

    onFiles(ev) {
        const files = [...ev.target.files];
        ev.target.value = "";
        this.upload(files);
    }

    onDrop(ev) {
        ev.preventDefault();
        this.state.dragging = false;
        this.upload([...ev.dataTransfer.files]);
    }

    removeFile(file) {
        this.state.files = this.state.files.filter((f) => f.id !== file.id);
    }

    size(bytes) {
        return bytes > 1048576 ? `${(bytes / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
    }

    // ------------------------------------------------------------------- submit
    async submit() {
        this.state.submitted = true;
        const v = this.state.v;
        if (this.errors.contact || this.errors.subject) {
            return;
        }
        const values = {
            subject: v.subject, description: v.description, priority: v.priority || undefined,
            classification: v.classification || undefined, lang_id: v.lang_id || undefined,
            template_id: v.template_id || undefined, attachment_ids: this.state.files.map((f) => f.id),
        };
        if (!this.isCustomer) {
            Object.assign(values, {
                status: v.status, channel: v.channel, owner_id: v.owner_id || undefined,
                product_id: v.product_id || undefined, project_id: v.project_id || undefined,
                due_date: v.due_date || undefined,
            });
            if (v.contact_id) {
                values.contact_id = v.contact_id;
            } else {
                values.new_contact = { name: v.contact, email: v.email, phone: v.phone, account: v.account };
            }
        }
        this.state.saving = true;
        const data = await attempt(() => deskRpc("/desk/api/newticket/create", { values }));
        this.state.saving = false;
        if (data) {
            this.state.created = data;
            window.scrollTo({ top: 0 });
        }
    }

    reset() {
        const keepOwner = this.state.v.owner_id;
        this.state.v = EMPTY();
        this.state.v.owner_id = keepOwner;
        Object.assign(this.state, { submitted: false, created: null, files: [], contact: null, suggestions: [] });
        if (this.isCustomer && this.state.opts.contact) {
            this.pickContact(this.state.opts.contact);
        }
    }

    get viewHref() {
        const created = this.state.created;
        if (!created) {
            return "#";
        }
        return this.isCustomer ? `/desk/my/ticket/${created.ticket.id}` : `/desk/ticket/${created.ticket.id}`;
    }
}

registry.category("public_components").add("aixo_desk.NewTicket", NewTicket);
