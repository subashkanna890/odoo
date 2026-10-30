import { Component, onMounted, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { Icon, attempt, deskRpc, toast } from "./helpers";

const SECTIONS = [["projects", "Projects", "folder"], ["milestones", "Milestones", "flag"], ["timesheets", "Timesheets", "clock"], ["tasks", "Tasks", "tasks"]];
const STATE_CLASS = { planning: "is-planning", in_progress: "is-progress", on_hold: "is-pause", completed: "is-closed" };
const STATE_DOT = { planning: "#0E3B2F", in_progress: "#E08A00", on_hold: "#8A94A6", completed: "#2FB463" };
const TINTS = [["#E1F2CF", "#2F6B0E"], ["#FFE9D6", "#8A3B00"], ["#E3F5EA", "#0F5F34"], ["#F1E4FF", "#5B1E99"], ["#FDE7E7", "#A11A1A"], ["#E6F4F6", "#0B5F6B"]];

const initials = (name) => name.split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();

export class ProjectList extends Component {
    static template = "aixo_desk.ProjectList";
    static components = { Icon };
    static props = { is_admin: { type: Boolean, optional: true }, new: { type: Boolean, optional: true } };

    setup() {
        this.sections = SECTIONS;
        this.stateClass = STATE_CLASS;
        this.stateDot = STATE_DOT;
        this.state = useState({
            section: "projects", view: "all", layout: "list", data: null, loading: true,
            modal: this.props.new, form: this.blankForm(), drag: 0, dragOver: "",
        });
        onMounted(() => this.load());
    }

    blankForm() {
        return { name: "", partner_id: 0, date_start: "", date_due: "", state: "planning", member_ids: [] };
    }

    async load() {
        this.state.loading = true;
        const data = await attempt(() => deskRpc("/desk/api/projects/list", {
            view: this.state.view, section: this.state.section,
        }));
        if (data) {
            this.state.data = data;
        }
        this.state.loading = false;
    }

    setSection(section) {
        this.state.section = section;
        this.load();
    }

    setView(view) {
        Object.assign(this.state, { view, section: "projects" });
        this.load();
    }

    tint(project) {
        const t = TINTS[project.id % TINTS.length];
        return `background:${t[0]};color:${t[1]}`;
    }

    code(project) {
        return initials(project.name);
    }

    get columns() {
        const data = this.state.data;
        return data.states.map((s) => ({
            ...s, items: data.projects.filter((p) => p.state === s.value),
        }));
    }

    get title() {
        const view = this.state.data && this.state.data.views.find((v) => v.key === this.state.view);
        const section = SECTIONS.find((s) => s[0] === this.state.section);
        return this.state.section === "projects" ? (view ? view.label : "Projects") : section[1];
    }

    // ------------------------------------------------------------ drag and drop
    onDragStart(ev, project) {
        this.state.drag = project.id;
        ev.dataTransfer.setData("text/plain", String(project.id));
        ev.dataTransfer.effectAllowed = "move";
    }

    onDragOver(ev, column) {
        ev.preventDefault();
        this.state.dragOver = column;
    }

    async onDrop(ev, column) {
        ev.preventDefault();
        const id = this.state.drag;
        Object.assign(this.state, { drag: 0, dragOver: "" });
        const project = this.state.data.projects.find((p) => p.id === id);
        if (!project || project.state === column) {
            return;
        }
        await this.move(project, column);
    }

    async move(project, state) {
        const previous = project.state;
        project.state = state; // optimistic; rolled back when the server refuses
        const data = await attempt(() => deskRpc("/desk/api/projects/move", { id: project.id, state }));
        if (data) {
            Object.assign(project, data.project);
            this.load();
        } else {
            project.state = previous;
        }
    }

    // ------------------------------------------------------------- misc actions
    async toggleStar(project) {
        const data = await attempt(() => deskRpc("/desk/api/projects/star", { id: project.id }));
        if (data) {
            project.starred = data.starred;
        }
    }

    async toggleTask(task) {
        const data = await attempt(() => deskRpc("/desk/api/projects/task", { id: task.project_id, action: "toggle", task_id: task.id }));
        if (data) {
            task.done = !task.done;
        }
    }

    async toggleMilestone(milestone) {
        const data = await attempt(() => deskRpc("/desk/api/projects/milestone", { id: milestone.project_id, action: "toggle", milestone_id: milestone.id }));
        if (data) {
            milestone.reached = !milestone.reached;
        }
    }

    openModal() {
        this.state.form = this.blankForm();
        this.state.modal = true;
    }

    toggleMember(id) {
        const members = this.state.form.member_ids;
        this.state.form.member_ids = members.includes(id) ? members.filter((m) => m !== id) : [...members, id];
    }

    async createProject() {
        const form = this.state.form;
        if (!form.name.trim()) {
            return toast("Enter a project name.", "error");
        }
        const data = await attempt(() => deskRpc("/desk/api/projects/create", {
            values: { ...form, partner_id: form.partner_id || undefined },
        }));
        if (data) {
            this.state.modal = false;
            toast(`Project ${data.project.code} created.`, "ok");
            await this.load();
        }
    }
}

export class ProjectDetail extends Component {
    static template = "aixo_desk.ProjectDetail";
    static components = { Icon };
    static props = { id: Number };

    setup() {
        this.stateClass = STATE_CLASS;
        this.state = useState({ data: null, newTask: "", newMilestone: "", milestoneDate: "", edit: null });
        onMounted(() => this.load());
    }

    async load() {
        const data = await attempt(() => deskRpc("/desk/api/projects/get", { id: this.props.id }));
        if (data) {
            this.state.data = data;
            document.title = data.name;
        }
    }

    async changeStatus(ev) {
        const data = await attempt(() => deskRpc("/desk/api/projects/update", { id: this.props.id, values: { state: ev.target.value } }));
        if (data) {
            Object.assign(this.state.data, data.project);
            toast("Status updated.", "ok");
        }
    }

    async addTask() {
        const name = this.state.newTask.trim();
        if (!name) {
            return;
        }
        const data = await attempt(() => deskRpc("/desk/api/projects/task", { id: this.props.id, action: "add", name }));
        if (data) {
            this.state.newTask = "";
            this.state.data.tasks = data.tasks;
            Object.assign(this.state.data, data.project);
        }
    }

    async taskAction(task, action) {
        const data = await attempt(() => deskRpc("/desk/api/projects/task", { id: this.props.id, action, task_id: task.id }));
        if (data) {
            this.state.data.tasks = data.tasks;
            Object.assign(this.state.data, data.project);
        }
    }

    async addMilestone() {
        const name = this.state.newMilestone.trim();
        if (!name) {
            return;
        }
        const data = await attempt(() => deskRpc("/desk/api/projects/milestone", {
            id: this.props.id, action: "add", name, date: this.state.milestoneDate || undefined,
        }));
        if (data) {
            Object.assign(this.state, { newMilestone: "", milestoneDate: "" });
            this.state.data.milestones = data.milestones;
        }
    }

    async toggleMilestone(milestone) {
        const data = await attempt(() => deskRpc("/desk/api/projects/milestone", { id: this.props.id, action: "toggle", milestone_id: milestone.id }));
        if (data) {
            this.state.data.milestones = data.milestones;
        }
    }

    async toggleStar() {
        const data = await attempt(() => deskRpc("/desk/api/projects/star", { id: this.props.id }));
        if (data) {
            this.state.data.starred = data.starred;
        }
    }

    startEdit() {
        const d = this.state.data;
        this.state.edit = { name: d.name, date_start: d.start_input, date_due: d.due_input, member_ids: [...d.member_ids] };
    }

    toggleMember(id) {
        const edit = this.state.edit;
        edit.member_ids = edit.member_ids.includes(id) ? edit.member_ids.filter((m) => m !== id) : [...edit.member_ids, id];
    }

    async saveEdit() {
        const data = await attempt(() => deskRpc("/desk/api/projects/update", { id: this.props.id, values: this.state.edit }));
        if (data) {
            this.state.edit = null;
            await this.load();
            toast("Project saved.", "ok");
        }
    }
}

registry.category("public_components").add("aixo_desk.ProjectList", ProjectList);
registry.category("public_components").add("aixo_desk.ProjectDetail", ProjectDetail);
