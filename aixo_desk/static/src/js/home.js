import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";

const reducedMotion = () => window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Calls ``callback`` once when the element is at least ``threshold`` visible. */
function whenVisible(el, threshold, callback) {
    if (typeof IntersectionObserver === "undefined") {
        callback();
        return null;
    }
    const observer = new IntersectionObserver((entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
            observer.disconnect();
            callback();
        }
    }, { threshold });
    observer.observe(el);
    return observer;
}

/** Hero: waits for the headline to finish typing, then fades in the rest. */
export class AixoHero extends Interaction {
    static selector = ".ax-hero-section";

    setup() {
        this.el.classList.add("is-js");
        const headline = this.el.querySelector("[data-ax-typed]");
        const ready = () => this.el.classList.add("is-ready");
        if (reducedMotion() || !headline) {
            return ready();
        }
        this.timer = setInterval(() => {
            if (!headline.classList.contains("is-typing")) {
                clearInterval(this.timer);
                ready();
            }
        }, 120);
        // never leave the content hidden if typing is interrupted
        this.fallback = setTimeout(ready, 4500);
    }

    destroy() {
        clearInterval(this.timer);
        clearTimeout(this.fallback);
        this.el.classList.remove("is-js", "is-ready");
    }
}

/** Word-by-word statement, then the dark panel rises. Replay restarts it. */
export class AixoStory extends Interaction {
    static selector = "[data-ax-story]";
    dynamicContent = {
        "[data-ax-replay]": { "t-on-click": this.replay },
        _root: { "t-on-mousemove": this.onMove },
    };

    setup() {
        this.statement = this.el.querySelector("[data-ax-statement]");
        this.original = this.statement.innerHTML;
        this.words = this.statement.textContent.trim().split(/\s+/);
        this.el.classList.add("is-js");
        this.statement.replaceChildren(...this.words.map((word) => {
            const span = document.createElement("span");
            span.className = "ax-word w-far";
            span.textContent = `${word} `;
            return span;
        }));
        this.spans = [...this.statement.children];
        this.el.dataset.phase = "0";
        if (reducedMotion()) {
            return this.finish();
        }
        this.observer = whenVisible(this.el, 0.35, () => this.play());
    }

    destroy() {
        this.stop();
        this.observer?.disconnect();
        this.statement.innerHTML = this.original;
        this.el.classList.remove("is-js");
        delete this.el.dataset.phase;
    }

    stop() {
        clearInterval(this.timer);
        clearTimeout(this.later);
    }

    paint(shown) {
        this.spans.forEach((span, i) => {
            const d = shown - i;
            span.className = "ax-word " + (d >= 3 ? "" : d >= 1 ? "w-mid" : d >= -2 ? "w-soon" : "w-far");
        });
    }

    play() {
        this.stop();
        let shown = 0;
        this.timer = setInterval(() => {
            shown += 1;
            this.paint(Math.min(shown, this.words.length + 3));
            if (shown >= this.words.length + 3) {
                clearInterval(this.timer);
                this.later = setTimeout(() => (this.el.dataset.phase = "1"), 1100);
            }
        }, 110);
    }

    finish() {
        this.paint(this.words.length + 3);
        this.el.dataset.phase = "1";
    }

    replay() {
        this.stop();
        this.el.dataset.phase = "0";
        this.paint(0);
        if (reducedMotion()) {
            return this.finish();
        }
        this.later = setTimeout(() => this.play(), 700);
    }

    onMove(ev) {
        if (this.frame || reducedMotion()) {
            return;
        }
        const rect = this.el.getBoundingClientRect();
        const x = ((ev.clientX - rect.left) / rect.width) * 100;
        const y = ((ev.clientY - rect.top) / rect.height) * 100;
        this.frame = requestAnimationFrame(() => {
            this.frame = null;
            this.el.style.setProperty("--ax-gx", `${x}%`);
            this.el.style.setProperty("--ax-gy", `${y}%`);
        });
    }
}

/** Portal cards slide up when the section scrolls into view. */
export class AixoPortals extends Interaction {
    static selector = ".ax-portals";

    setup() {
        this.el.classList.add("is-js");
        const show = () => this.el.querySelectorAll(".ax-reveal").forEach((card) => card.classList.add("is-in"));
        if (reducedMotion()) {
            return show();
        }
        this.observer = whenVisible(this.el, 0.35, show);
    }

    destroy() {
        this.observer?.disconnect();
        this.el.classList.remove("is-js");
        this.el.querySelectorAll(".ax-reveal").forEach((card) => card.classList.remove("is-in"));
    }
}

/**
 * "Get a demo" modal. Every trigger is a real link to /aixo-desk/demo, so the
 * form still works without JavaScript; here we open it in a <dialog> instead.
 */
export class AixoDemo extends Interaction {
    static selector = "#wrapwrap";
    dynamicContent = {
        "[data-ax-demo-open]": { "t-on-click.prevent": this.open },
        "[data-ax-demo-close]": { "t-on-click": this.close },
        "[data-ax-demo-dialog]": { "t-on-click": this.onBackdrop },
        "[data-ax-demo-form]": { "t-on-submit.prevent": this.submit },
    };

    setup() {
        this.dialog = this.el.querySelector("[data-ax-demo-dialog]");
    }

    open() {
        if (this.dialog && typeof this.dialog.showModal === "function") {
            this.dialog.showModal();
            this.dialog.querySelector("input[name='name']")?.focus();
        } else {
            window.location.href = "/aixo-desk/demo";
        }
    }

    close() {
        this.dialog.close();
    }

    onBackdrop(ev) {
        if (ev.target === this.dialog) {
            this.close();
        }
    }

    showError(form, message) {
        const box = form.querySelector("[data-ax-error]");
        box.textContent = message;
        box.hidden = !message;
    }

    async submit(ev) {
        const form = ev.currentTarget;
        const data = Object.fromEntries(new FormData(form).entries());
        if (!data.name.trim()) {
            form.elements.name.classList.add("is-invalid");
            return this.showError(form, "Enter your name.");
        }
        if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(data.email.trim())) {
            form.elements.email.classList.add("is-invalid");
            return this.showError(form, "Enter a valid work email.");
        }
        const submit = form.querySelector("button[type='submit']");
        submit.disabled = true;
        try {
            const result = await rpc("/desk/api/demo-request", data);
            if (!result.ok) {
                return this.showError(form, result.error);
            }
            const content = this.dialog.querySelector("[data-ax-demo-content]");
            const first = result.data.name || "";
            content.innerHTML = "";
            const box = document.createElement("div");
            box.className = "ax-done";
            box.setAttribute("role", "status");
            const title = document.createElement("h2");
            title.textContent = first ? `Thank you, ${first}!` : "Thank you!";
            const text = document.createElement("p");
            text.textContent = "We've received your request and will email you within one business day to set up your demo.";
            box.append(title, text);
            content.append(box);
        } catch {
            this.showError(form, "Something went wrong. Please try again.");
        } finally {
            submit.disabled = false;
        }
    }
}

for (const [name, cls] of Object.entries({
    "aixo_desk.hero": AixoHero,
    "aixo_desk.story": AixoStory,
    "aixo_desk.portals": AixoPortals,
    "aixo_desk.demo": AixoDemo,
})) {
    registry.category("public.interactions").add(name, cls);
}
