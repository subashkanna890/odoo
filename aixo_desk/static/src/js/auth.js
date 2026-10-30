import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";

const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";
const prefersReducedMotion = () => window.matchMedia && window.matchMedia(REDUCED_MOTION).matches;

/** Mouse-following lime glow behind the auth screens. */
export class AixoGlow extends Interaction {
    static selector = "[data-ax-glow]";
    dynamicContent = {
        _root: { "t-on-mousemove": this.onMove },
    };

    onMove(ev) {
        if (this.frame || prefersReducedMotion()) {
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

/**
 * Types the headline once. The full text is already in the HTML, so it stays
 * readable with JS off or reduced motion.
 */
export class AixoTyped extends Interaction {
    static selector = "[data-ax-typed]";

    setup() {
        const full = this.el.dataset.axTyped;
        const accent = this.el.dataset.axAccent;
        if (!full || prefersReducedMotion()) {
            return;
        }
        const split = accent ? full.indexOf(accent) : full.length;
        const accentEnd = this.el.dataset.axAccentLen ? split + Number(this.el.dataset.axAccentLen) : full.length;
        const original = this.el.innerHTML;
        let count = 0;
        this.el.classList.add("is-typing");
        const render = () => {
            const typed = full.slice(0, count);
            this.el.replaceChildren();
            this.el.append(document.createTextNode(typed.slice(0, split)));
            if (typed.length > split) {
                const span = document.createElement("span");
                span.className = "ax-accent";
                span.textContent = typed.slice(split, accentEnd);
                this.el.append(span);
                if (typed.length > accentEnd) {
                    this.el.append(document.createTextNode(typed.slice(accentEnd)));
                }
            }
        };
        render();
        this.timer = setInterval(() => {
            count += 1;
            render();
            if (count >= full.length) {
                clearInterval(this.timer);
                this.timer = null;
                this.el.classList.remove("is-typing");
            }
        }, 45);
        this.restore = original;
    }

    destroy() {
        if (this.timer) {
            clearInterval(this.timer);
        }
        if (this.restore) {
            this.el.innerHTML = this.restore;
            this.el.classList.remove("is-typing");
        }
    }
}

/** Rotates the small tips under the login hero. */
export class AixoTips extends Interaction {
    static selector = "[data-ax-tips]";

    setup() {
        this.tipEl = this.el.querySelector("[data-ax-tip]");
        this.tips = [this.tipEl.textContent.trim()].concat(
            [...this.el.querySelectorAll("[data-ax-tip-item]")].map((el) => el.textContent.trim())
        );
        if (prefersReducedMotion()) {
            return;
        }
        let index = 0;
        this.tipEl.classList.add("is-cycling");
        this.timer = setInterval(() => {
            index = (index + 1) % this.tips.length;
            this.tipEl.textContent = this.tips[index];
            this.tipEl.classList.remove("is-cycling");
            void this.tipEl.offsetWidth; // restart the CSS animation
            this.tipEl.classList.add("is-cycling");
        }, 3000);
    }

    destroy() {
        clearInterval(this.timer);
    }
}

/** Show/hide password buttons. */
export class AixoTogglePassword extends Interaction {
    static selector = ".ax-pwwrap";
    dynamicContent = {
        "[data-ax-toggle-pw]": {
            "t-on-click": () => (this.visible = !this.visible),
            "t-att-aria-label": () => (this.visible ? "Hide password" : "Show password"),
        },
        "input": {
            "t-att-type": () => (this.visible ? "text" : "password"),
        },
    };

    setup() {
        this.visible = false;
    }
}

/** Keeps the login button label in sync with the selected portal. */
export class AixoLogin extends Interaction {
    static selector = "[data-ax-login]";
    dynamicContent = {
        "input[name='portal']": { "t-on-change": this.sync },
    };

    setup() {
        this.sync();
    }

    sync() {
        const checked = this.el.querySelector("input[name='portal']:checked");
        const label = this.el.querySelector("[data-ax-submit-label]");
        if (checked && label) {
            label.textContent = `Log in as ${checked.dataset.label}`;
        }
    }
}

const SCORE_COLORS = ["#D6453D", "#D6453D", "#E08A00", "#7CC24A", "#2F7D1F"];

export function passwordScore(password) {
    return [password.length >= 8, /[A-Z]/.test(password), /[0-9]/.test(password), /[^A-Za-z0-9]/.test(password)]
        .filter(Boolean).length;
}

function paintStrength(container, password) {
    const score = passwordScore(password);
    container.querySelectorAll("span").forEach((bar, i) => {
        bar.style.background = i < score ? SCORE_COLORS[score] : "";
    });
}

/** Sign-up form: same checks as the server, shown inline before submitting. */
export class AixoSignup extends Interaction {
    static selector = "[data-ax-signup]";
    dynamicContent = {
        _root: { "t-on-submit": this.onSubmit },
        "input[name='password']": { "t-on-input": this.onPassword },
    };

    onPassword(ev) {
        paintStrength(this.el.querySelector("[data-ax-strength]"), ev.target.value);
    }

    onSubmit(ev) {
        const f = this.el.elements;
        const emailOk = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(f.email.value.trim());
        const checks = [
            [f.first, !!f.first.value.trim()],
            [f.email, emailOk],
            [f.password, f.password.value.length >= 8],
        ];
        let valid = true;
        for (const [input, ok] of checks) {
            input.classList.toggle("is-invalid", !ok);
            valid = valid && ok;
        }
        if (!f.terms.checked) {
            valid = false;
            f.terms.closest("label").style.color = "#B42318";
        }
        if (!valid) {
            ev.preventDefault();
            this.el.querySelector(".is-invalid")?.focus();
        }
    }
}

/** Three step password reset talking to the OTP routes. */
export class AixoReset extends Interaction {
    static selector = "[data-ax-reset]";
    dynamicContent = {
        "[data-ax-form='send']": { "t-on-submit.prevent": this.onSend },
        "[data-ax-form='verify']": { "t-on-submit.prevent": this.onVerify },
        "[data-ax-form='reset']": { "t-on-submit.prevent": this.onReset },
        "[data-ax-otp]": { "t-on-input": this.onOtpInput, "t-on-keydown": this.onOtpKey, "t-on-paste": this.onOtpPaste },
        "[data-ax-change]": { "t-on-click": () => this.show(1) },
        "[data-ax-resend]": { "t-on-click": this.onResend },
        "[data-ax-form='reset'] input": { "t-on-input": this.onPasswords },
    };

    setup() {
        this.email = "";
        this.boxes = [...this.el.querySelectorAll("[data-ax-otp]")];
    }

    destroy() {
        clearInterval(this.tick);
    }

    show(step) {
        this.el.querySelectorAll("[data-ax-panel]").forEach((panel) => {
            panel.hidden = panel.dataset.axPanel !== String(step);
        });
        const current = Math.min(step, 3);
        document.querySelectorAll("[data-ax-step]").forEach((item) => {
            const n = Number(item.dataset.axStep);
            item.classList.toggle("is-done", step > n);
            item.classList.toggle("is-current", step <= 3 && n === current);
        });
        this.showError("");
        const first = this.el.querySelector(`[data-ax-panel='${step}'] input`);
        first?.focus();
    }

    showError(message) {
        const box = this.el.querySelector("[data-ax-error]");
        box.textContent = message;
        box.hidden = !message;
    }

    async call(route, params) {
        try {
            const result = await rpc(route, params);
            if (!result.ok) {
                this.showError(result.error);
            }
            return result;
        } catch {
            this.showError("Something went wrong. Please try again.");
            return { ok: false };
        }
    }

    async onSend() {
        const input = this.el.querySelector("[data-ax-form='send'] input[name='email']");
        this.email = input.value.trim();
        if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(this.email)) {
            input.classList.add("is-invalid");
            return this.showError("Enter a valid email address.");
        }
        input.classList.remove("is-invalid");
        const result = await this.call("/desk/api/otp/send", { email: this.email });
        if (result.ok) {
            this.el.querySelector("[data-ax-email-label]").textContent = this.email;
            this.boxes.forEach((box) => this.setBox(box, ""));
            this.show(2);
            this.startTimer();
        }
    }

    async onResend() {
        const result = await this.call("/desk/api/otp/send", { email: this.email });
        if (result.ok) {
            this.startTimer();
        }
    }

    startTimer() {
        clearInterval(this.tick);
        let left = 30;
        const timer = this.el.querySelector("[data-ax-timer]");
        const waiting = this.el.querySelector("[data-ax-waiting]");
        const resend = this.el.querySelector("[data-ax-resend]");
        const paint = () => {
            timer.textContent = String(left).padStart(2, "0");
            waiting.hidden = left === 0;
            resend.hidden = left > 0;
        };
        paint();
        this.tick = setInterval(() => {
            left = Math.max(0, left - 1);
            paint();
            if (left === 0) {
                clearInterval(this.tick);
            }
        }, 1000);
    }

    setBox(box, value) {
        box.value = value;
        box.classList.toggle("is-filled", !!value);
        box.classList.remove("is-invalid");
    }

    onOtpInput(ev) {
        const box = ev.target;
        const digit = box.value.replace(/\D/g, "").slice(-1);
        this.setBox(box, digit);
        if (digit) {
            this.boxes[this.boxes.indexOf(box) + 1]?.focus();
        }
    }

    onOtpKey(ev) {
        const index = this.boxes.indexOf(ev.target);
        if (ev.key === "Backspace" && !ev.target.value && index > 0) {
            this.boxes[index - 1].focus();
        } else if (ev.key === "ArrowLeft" && index > 0) {
            this.boxes[index - 1].focus();
        } else if (ev.key === "ArrowRight" && index < 5) {
            this.boxes[index + 1].focus();
        }
    }

    onOtpPaste(ev) {
        const digits = (ev.clipboardData.getData("text") || "").replace(/\D/g, "").slice(0, 6);
        if (!digits) {
            return;
        }
        ev.preventDefault();
        this.boxes.forEach((box, i) => this.setBox(box, digits[i] || ""));
        this.boxes[Math.min(digits.length, 5)].focus();
    }

    async onVerify() {
        const code = this.boxes.map((box) => box.value).join("");
        if (code.length !== 6) {
            this.boxes.forEach((box) => !box.value && box.classList.add("is-invalid"));
            return this.showError("Enter the 6-digit code.");
        }
        const result = await this.call("/desk/api/otp/verify", { email: this.email, code });
        if (result.ok) {
            clearInterval(this.tick);
            this.show(3);
        } else {
            this.boxes.forEach((box) => box.classList.add("is-invalid"));
        }
    }

    onPasswords() {
        const form = this.el.querySelector("[data-ax-form='reset']");
        const password = form.elements.password.value;
        const confirm = form.elements.confirm.value;
        paintStrength(form.querySelector("[data-ax-strength]"), password);
        const mismatch = confirm.length > 0 && confirm !== password;
        form.querySelector("[data-ax-mismatch]").hidden = !mismatch;
        form.querySelector("[data-ax-reset-btn]").disabled = !(password.length >= 8 && password === confirm);
    }

    async onReset() {
        const form = this.el.querySelector("[data-ax-form='reset']");
        const result = await this.call("/desk/api/otp/reset", {
            password: form.elements.password.value,
            confirm: form.elements.confirm.value,
        });
        if (result.ok) {
            this.show(4);
        }
    }
}

for (const [name, cls] of Object.entries({
    "aixo_desk.glow": AixoGlow,
    "aixo_desk.typed": AixoTyped,
    "aixo_desk.tips": AixoTips,
    "aixo_desk.toggle_password": AixoTogglePassword,
    "aixo_desk.login": AixoLogin,
    "aixo_desk.signup": AixoSignup,
    "aixo_desk.reset": AixoReset,
})) {
    registry.category("public.interactions").add(name, cls);
}
