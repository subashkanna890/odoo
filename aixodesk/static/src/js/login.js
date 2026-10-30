/** @odoo-module **/

/* ==========================================================================
   AixoDesk Login Portal - Interaction Script
   Handles password toggle, validation, loading state, and notice modals
   ========================================================================== */

document.addEventListener('DOMContentLoaded', function () {
    initPasswordToggle();
    initFormValidation();
    initNoticeHandlers();
    initModalControls();
});

/**
 * Initializes eye icon password visibility toggle
 */
function initPasswordToggle() {
    const toggleBtns = document.querySelectorAll('.aixodesk-pwd-toggle');
    
    toggleBtns.forEach(function (btn) {
        btn.addEventListener('click', function (e) {
            e.preventDefault();
            const wrapper = btn.closest('.aixodesk-password-wrapper') || btn.parentElement;
            const input = wrapper ? wrapper.querySelector('input') : null;
            if (!input) return;

            const isPassword = input.type === 'password';
            input.type = isPassword ? 'text' : 'password';

            // Toggle SVG icon
            const eyeIcon = btn.querySelector('.icon-eye');
            const eyeOffIcon = btn.querySelector('.icon-eye-off');
            if (eyeIcon && eyeOffIcon) {
                if (isPassword) {
                    eyeIcon.style.display = 'none';
                    eyeOffIcon.style.display = 'block';
                    btn.setAttribute('aria-label', 'Hide password');
                } else {
                    eyeIcon.style.display = 'block';
                    eyeOffIcon.style.display = 'none';
                    btn.setAttribute('aria-label', 'Show password');
                }
            }
        });
    });
}

/**
 * Client-side validation and submission loading state
 */
function initFormValidation() {
    const forms = document.querySelectorAll('.aixodesk-form');
    if (!forms.length) return;

    forms.forEach(function (form) {
        const emailInput = form.querySelector('input[type="email"], input[name="login"]');
        const pwdInput = form.querySelector('input[name="password"]');
        const submitBtn = form.querySelector('.aixodesk-btn-continue');

        // Auto-focus logic
        if (emailInput && !emailInput.value.trim()) {
            emailInput.focus();
        } else if (pwdInput && !pwdInput.value.trim()) {
            pwdInput.focus();
        }

        form.addEventListener('submit', function (e) {
            let hasError = false;

            // Reset previous invalid states
            if (emailInput) emailInput.classList.remove('is-invalid');
            if (pwdInput) pwdInput.classList.remove('is-invalid');

            // Email validation
            if (emailInput) {
                const emailVal = emailInput.value.trim();
                if (!emailVal || !emailVal.includes('@') || !emailVal.includes('.')) {
                    emailInput.classList.add('is-invalid');
                    emailInput.focus();
                    hasError = true;
                }
            }

            // Password validation (only for forms that have a password field)
            if (!hasError && pwdInput) {
                const pwdVal = pwdInput.value;
                if (!pwdVal) {
                    pwdInput.classList.add('is-invalid');
                    pwdInput.focus();
                    hasError = true;
                }
            }

            if (hasError) {
                e.preventDefault();
                return false;
            }

            // Trigger loading state on valid submit
            if (submitBtn) {
                submitBtn.classList.add('is-loading');
                submitBtn.disabled = true;
                // Timeout fallback if navigation doesn't trigger
                setTimeout(function () {
                    submitBtn.disabled = false;
                    submitBtn.classList.remove('is-loading');
                }, 8000);
            }
        });

        // Remove invalid style on user input
        [emailInput, pwdInput].forEach(function (inp) {
            if (!inp) return;
            inp.addEventListener('input', function () {
                if (inp.classList.contains('is-invalid')) {
                    inp.classList.remove('is-invalid');
                }
            });
        });
    });
}

/**
 * Notice handlers for unconfigured Google OAuth, registration disabled, etc.
 */
function initNoticeHandlers() {
    const modal = document.getElementById('aixoNoticeModal');
    const modalTitle = document.getElementById('aixoModalTitle');
    const modalDesc = document.getElementById('aixoModalDesc');

    function openModal(title, message) {
        if (!modal) return;
        if (modalTitle) modalTitle.textContent = title;
        if (modalDesc) modalDesc.textContent = message;
        modal.classList.add('is-active');
    }

    // Google OAuth button
    const googleBtn = document.querySelector('.aixodesk-google-btn');
    if (googleBtn) {
        googleBtn.addEventListener('click', function (e) {
            const isUnconfigured = googleBtn.getAttribute('data-unconfigured') === 'true';
            const href = googleBtn.getAttribute('href');

            if (isUnconfigured || !href || href === '#' || href === 'javascript:void(0);') {
                e.preventDefault();
                openModal(
                    'Google Authentication',
                    'Google Sign-In is not currently configured for this database. Administrators can configure Google OAuth credentials in Settings > General Settings > Integrations.'
                );
            }
        });
    }

    // Other notice triggers
    const noticeTriggers = document.querySelectorAll('.aixodesk-notice-trigger');
    noticeTriggers.forEach(function (trigger) {
        trigger.addEventListener('click', function (e) {
            e.preventDefault();
            const type = trigger.getAttribute('data-notice-type');
            if (type === 'signup_disabled') {
                openModal(
                    'Registration Restricted',
                    'Public self-registration is closed for this portal. Please contact your support administrator to request an account.'
                );
            } else if (type === 'reset_disabled') {
                openModal(
                    'Password Recovery',
                    'Self-service password recovery is currently disabled. Please contact your support team or administrator to reset your credentials.'
                );
            }
        });
    });
}

/**
 * Modal dismiss helpers
 */
function initModalControls() {
    const modal = document.getElementById('aixoNoticeModal');
    if (!modal) return;

    const closeBtn = modal.querySelector('.aixodesk-modal-btn');
    if (closeBtn) {
        closeBtn.addEventListener('click', function () {
            modal.classList.remove('is-active');
        });
    }

    modal.addEventListener('click', function (e) {
        if (e.target === modal) {
            modal.classList.remove('is-active');
        }
    });

    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && modal.classList.contains('is-active')) {
            modal.classList.remove('is-active');
        }
    });
}
