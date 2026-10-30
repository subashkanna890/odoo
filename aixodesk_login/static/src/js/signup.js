/** @odoo-module **/
/**
 * AixoDesk Sign Up & Mobile OTP Verification Flow
 * Integrates Step 1 (Registration form) and Step 2 (Mobile OTP verification)
 */

(function () {
    'use strict';

    function initAixoDeskSignup() {
        const signupWrapper = document.querySelector('.o_axd_auth_wrapper');
        if (!signupWrapper) return;

        // Elements - Steps
        const stepSignup = document.getElementById('axd_signup_step');
        const stepOtp = document.getElementById('axd_otp_step');
        if (!stepSignup || !stepOtp) return;

        // Elements - Step 1 Form
        const signupForm = document.getElementById('axd_signup_form');
        const firstNameInput = document.getElementById('first_name');
        const lastNameInput = document.getElementById('last_name');
        const emailInput = document.getElementById('signup_email');
        const mobileInput = document.getElementById('signup_mobile');
        const countryCodeInput = document.getElementById('axd_country_code');
        const termsCheckbox = document.getElementById('signup_terms');
        const btnContinue = document.getElementById('axd_btn_continue');
        const signupAlert = document.getElementById('axd_signup_alert');

        // Country Selector
        const countryPicker = document.getElementById('axd_country_picker');
        const countryDropdown = document.getElementById('axd_country_dropdown');
        const selectedFlag = document.getElementById('axd_selected_flag');
        const selectedDial = document.getElementById('axd_selected_dial');

        // Elements - Step 2 OTP
        const targetPhoneEl = document.getElementById('axd_target_phone');
        const btnEditPhone = document.getElementById('axd_btn_edit_phone');
        const btnBack = document.getElementById('axd_btn_back');
        const otpAlert = document.getElementById('axd_otp_alert');
        const otpSlots = Array.from(document.querySelectorAll('.o_axd_otp_slot'));
        const btnVerify = document.getElementById('axd_btn_verify');
        const resendCountdown = document.getElementById('axd_resend_countdown');
        const resendTimerEl = document.getElementById('axd_resend_timer');
        const btnResend = document.getElementById('axd_btn_resend');

        // Modals
        const linkTerms = document.getElementById('axd_link_terms');
        const linkPrivacy = document.getElementById('axd_link_privacy');
        const modalTerms = document.getElementById('axd_modal_terms');
        const modalPrivacy = document.getElementById('axd_modal_privacy');

        // Theme Toggle
        const modeToggle = document.getElementById('axd_mode_toggle');

        let resendInterval = null;

        // -------------------------------------------------------------
        // Theme Toggle Setup (Shared with Login Page)
        // -------------------------------------------------------------
        let savedTheme = null;
        try {
            const urlParams = new URLSearchParams(window.location.search);
            const queryMode = urlParams.get('mode');
            if (queryMode === 'light' || queryMode === 'dark') {
                savedTheme = queryMode;
            } else {
                savedTheme = localStorage.getItem('axd-mode') || localStorage.getItem('aixodesk_theme');
            }
        } catch (e) {}

        if (savedTheme !== 'dark' && savedTheme !== 'light') {
            savedTheme = 'light';
        }

        applyTheme(savedTheme);

        if (modeToggle) {
            modeToggle.addEventListener('click', function () {
                const current = (document.body && document.body.getAttribute('data-axd-mode')) || signupWrapper.getAttribute('data-axd-mode') || 'light';
                const next = current === 'dark' ? 'light' : 'dark';

                modeToggle.classList.add('animating');
                setTimeout(function () {
                    modeToggle.classList.remove('animating');
                }, 350);

                applyTheme(next);
            });
        }

        function applyTheme(theme) {
            document.documentElement.setAttribute('data-axd-mode', theme);
            document.documentElement.setAttribute('data-theme', theme);
            document.documentElement.classList.toggle('dark', theme === 'dark');
            signupWrapper.setAttribute('data-axd-mode', theme);
            signupWrapper.setAttribute('data-theme', theme);
            signupWrapper.classList.toggle('dark', theme === 'dark');
            if (document.body) {
                document.body.setAttribute('data-axd-mode', theme);
                document.body.setAttribute('data-theme', theme);
                document.body.classList.toggle('dark', theme === 'dark');
            }
            try {
                localStorage.setItem('axd-mode', theme);
                localStorage.setItem('aixodesk_theme', theme);
            } catch (e) {}
        }

        // -------------------------------------------------------------
        // API Helper (JSON-RPC 2.0)
        // -------------------------------------------------------------
        async function callApi(url, params) {
            const response = await fetch(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: JSON.stringify({
                    jsonrpc: '2.0',
                    method: 'call',
                    params: params,
                    id: Math.floor(Math.random() * 1000000000)
                })
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const json = await response.json();
            if (json.error) {
                const errData = json.error.data || {};
                throw new Error(errData.message || json.error.message || 'An unexpected error occurred.');
            }
            return json.result !== undefined ? json.result : json;
        }

        // -------------------------------------------------------------
        // Alerts
        // -------------------------------------------------------------
        function showAlert(alertEl, message, isSuccess) {
            if (!alertEl) return;
            alertEl.textContent = message;
            alertEl.style.display = 'block';
            if (isSuccess) {
                alertEl.style.background = '#ECFDF5';
                alertEl.style.color = '#065F46';
                alertEl.style.borderColor = '#A7F3D0';
            } else {
                alertEl.style.background = '#FEF2F2';
                alertEl.style.color = '#991B1B';
                alertEl.style.borderColor = '#FECACA';
            }
        }

        function clearAlert(alertEl) {
            if (alertEl) {
                alertEl.textContent = '';
                alertEl.style.display = 'none';
            }
        }

        function clearFieldErrors() {
            ['err_first_name', 'err_last_name', 'err_email', 'err_mobile', 'err_terms'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.textContent = '';
            });
        }

        // -------------------------------------------------------------
        // Country Selector
        // -------------------------------------------------------------
        if (countryPicker && countryDropdown) {
            countryPicker.addEventListener('click', function (e) {
                e.stopPropagation();
                const isOpen = countryDropdown.style.display === 'block';
                countryDropdown.style.display = isOpen ? 'none' : 'block';
                countryPicker.setAttribute('aria-expanded', !isOpen);
            });

            countryDropdown.querySelectorAll('.o_axd_country_item').forEach(item => {
                item.addEventListener('click', function (e) {
                    e.stopPropagation();
                    const dial = this.getAttribute('data-dial');
                    const flag = this.getAttribute('data-flag');
                    const code = this.getAttribute('data-code');
                    if (selectedFlag) {
                        if (code === 'IN') {
                            selectedFlag.innerHTML = '<svg class="o_axd_flag_svg" width="20" height="14" viewBox="0 0 30 20" style="border-radius: 2px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.18); display: block;"><rect width="30" height="6.67" fill="#FF9933"/><rect y="6.67" width="30" height="6.67" fill="#FFFFFF"/><rect y="13.34" width="30" height="6.67" fill="#138808"/><circle cx="15" cy="10" r="2.2" fill="none" stroke="#000080" stroke-width="0.8"/></svg>';
                        } else {
                            selectedFlag.textContent = flag;
                        }
                    }
                    if (selectedDial) selectedDial.textContent = dial;
                    if (countryCodeInput) countryCodeInput.value = dial;
                    countryDropdown.style.display = 'none';
                    countryPicker.setAttribute('aria-expanded', 'false');
                    if (mobileInput) mobileInput.focus();
                });
            });

            document.addEventListener('click', function (e) {
                if (!countryPicker.contains(e.target) && !countryDropdown.contains(e.target)) {
                    countryDropdown.style.display = 'none';
                    countryPicker.setAttribute('aria-expanded', 'false');
                }
            });
        }

        // -------------------------------------------------------------
        // Step 1: Validation & Submit
        // -------------------------------------------------------------
        if (signupForm) {
            signupForm.addEventListener('submit', async function (e) {
                e.preventDefault();
                clearAlert(signupAlert);
                clearFieldErrors();

                const firstName = (firstNameInput?.value || '').trim();
                const lastName = (lastNameInput?.value || '').trim();
                const email = (emailInput?.value || '').trim();
                const countryCode = (countryCodeInput?.value || '+91').trim();
                const mobile = (mobileInput?.value || '').trim();
                const terms = termsCheckbox ? termsCheckbox.checked : false;

                let hasError = false;

                if (!firstName) {
                    document.getElementById('err_first_name').textContent = 'Please enter your first name.';
                    hasError = true;
                }
                if (!lastName) {
                    document.getElementById('err_last_name').textContent = 'Please enter your last name.';
                    hasError = true;
                }
                const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
                if (!email) {
                    document.getElementById('err_email').textContent = 'Please enter your email address.';
                    hasError = true;
                } else if (!emailRegex.test(email)) {
                    document.getElementById('err_email').textContent = 'Please enter a valid email address.';
                    hasError = true;
                }
                const cleanMobile = mobile.replace(/\D/g, '');
                if (!cleanMobile) {
                    document.getElementById('err_mobile').textContent = 'Please enter your mobile number.';
                    hasError = true;
                } else if (cleanMobile.length < 7 || cleanMobile.length > 15) {
                    document.getElementById('err_mobile').textContent = 'Please enter a valid mobile number (7-15 digits).';
                    hasError = true;
                }
                if (!terms) {
                    document.getElementById('err_terms').textContent = 'You must agree to the Terms of Service & Privacy Policy.';
                    hasError = true;
                }

                if (hasError) return;

                // Submit request to send OTP
                setButtonLoading(btnContinue, true, 'Sending code...');

                try {
                    const result = await callApi('/aixodesk/api/send_otp', {
                        first_name: firstName,
                        last_name: lastName,
                        email: email,
                        country_code: countryCode,
                        mobile: cleanMobile,
                        terms: terms
                    });

                    if (result.success) {
                        const formattedPhone = result.phone || `${countryCode} ${cleanMobile}`;
                        if (targetPhoneEl) targetPhoneEl.textContent = formattedPhone;

                        // Switch to Step 2
                        stepSignup.classList.add('d-none');
                        stepOtp.classList.remove('d-none');
                        window.history.pushState({ step: 'otp' }, '', '#verify');

                        // Reset & focus OTP slots
                        otpSlots.forEach(slot => { slot.value = ''; slot.classList.remove('error'); });
                        if (otpSlots[0]) otpSlots[0].focus();

                        startResendTimer(result.resend_in || 30);
                    } else {
                        showAlert(signupAlert, result.error || 'Unable to send verification code.', false);
                    }
                } catch (err) {
                    showAlert(signupAlert, err.message || 'Network error occurred. Please try again.', false);
                } finally {
                    setButtonLoading(btnContinue, false, 'Continue →');
                }
            });
        }

        // -------------------------------------------------------------
        // Step 2: OTP Slots Auto-Advance, Paste & Backspace
        // -------------------------------------------------------------
        otpSlots.forEach((slot, idx) => {
            slot.addEventListener('input', function (e) {
                // Ensure only single numeric digit
                const val = this.value.replace(/\D/g, '');
                this.value = val ? val[val.length - 1] : '';
                this.classList.remove('error');

                if (this.value && idx < otpSlots.length - 1) {
                    otpSlots[idx + 1].focus();
                    otpSlots[idx + 1].select();
                }

                // If all slots filled, clear any previous error alert
                if (getEnteredOtp().length === 4) {
                    clearAlert(otpAlert);
                }
            });

            slot.addEventListener('keydown', function (e) {
                if (e.key === 'Backspace') {
                    if (!this.value && idx > 0) {
                        otpSlots[idx - 1].focus();
                        otpSlots[idx - 1].value = '';
                    } else {
                        this.value = '';
                    }
                } else if (e.key === 'ArrowLeft' && idx > 0) {
                    otpSlots[idx - 1].focus();
                } else if (e.key === 'ArrowRight' && idx < otpSlots.length - 1) {
                    otpSlots[idx + 1].focus();
                }
            });

            slot.addEventListener('paste', function (e) {
                e.preventDefault();
                const pasteData = (e.clipboardData || window.clipboardData).getData('text');
                const digits = pasteData.replace(/\D/g, '');
                if (digits) {
                    for (let i = 0; i < otpSlots.length; i++) {
                        if (digits[i]) {
                            otpSlots[i].value = digits[i];
                            otpSlots[i].classList.remove('error');
                        }
                    }
                    const nextEmpty = otpSlots.find(s => !s.value);
                    if (nextEmpty) {
                        nextEmpty.focus();
                    } else {
                        otpSlots[otpSlots.length - 1].focus();
                    }
                }
            });
        });

        function getEnteredOtp() {
            return otpSlots.map(s => (s.value || '').trim()).join('');
        }

        // -------------------------------------------------------------
        // Step 2: Verification Submit
        // -------------------------------------------------------------
        if (btnVerify) {
            btnVerify.addEventListener('click', async function () {
                clearAlert(otpAlert);
                const code = getEnteredOtp();

                if (code.length < 4) {
                    showAlert(otpAlert, 'Please enter all 4 digits of the verification code.', false);
                    otpSlots.forEach(s => { if (!s.value) s.classList.add('error'); });
                    const firstEmpty = otpSlots.find(s => !s.value);
                    if (firstEmpty) firstEmpty.focus();
                    return;
                }

                setButtonLoading(btnVerify, true, 'Verifying...');

                try {
                    const result = await callApi('/aixodesk/api/verify_otp', { otp: code });
                    if (result.success) {
                        showAlert(otpAlert, result.message || 'Verified successfully! Redirecting...', true);
                        if (btnVerify.querySelector('.o_axd_btn_label')) {
                            btnVerify.querySelector('.o_axd_btn_label').textContent = 'Success! Redirecting...';
                        }
                        clearInterval(resendInterval);
                        setTimeout(function () {
                            window.location.href = result.redirect || '/my';
                        }, 700);
                    } else {
                        showAlert(otpAlert, result.error || 'Verification failed. Please check the code.', false);
                        otpSlots.forEach(s => s.classList.add('error'));
                        if (otpSlots[0]) otpSlots[0].focus();
                        setButtonLoading(btnVerify, false, 'Verify & Continue →');
                    }
                } catch (err) {
                    showAlert(otpAlert, err.message || 'An error occurred during verification. Please try again.', false);
                    setButtonLoading(btnVerify, false, 'Verify & Continue →');
                }
            });
        }

        // -------------------------------------------------------------
        // Step 2: Resend Timer & Resend Button
        // -------------------------------------------------------------
        function startResendTimer(seconds) {
            clearInterval(resendInterval);
            let remaining = seconds;
            if (resendCountdown) resendCountdown.style.display = 'inline';
            if (btnResend) btnResend.style.display = 'none';
            if (resendTimerEl) resendTimerEl.textContent = remaining;

            resendInterval = setInterval(function () {
                remaining -= 1;
                if (remaining <= 0) {
                    clearInterval(resendInterval);
                    if (resendCountdown) resendCountdown.style.display = 'none';
                    if (btnResend) {
                        btnResend.style.display = 'inline-block';
                        btnResend.disabled = false;
                        btnResend.textContent = 'Resend code';
                    }
                } else {
                    if (resendTimerEl) resendTimerEl.textContent = remaining;
                }
            }, 1000);
        }

        if (btnResend) {
            btnResend.addEventListener('click', async function () {
                btnResend.disabled = true;
                btnResend.textContent = 'Sending...';
                clearAlert(otpAlert);

                try {
                    const result = await callApi('/aixodesk/api/resend_otp', {});
                    if (result.success) {
                        showAlert(otpAlert, result.message || 'A new code has been sent!', true);
                        startResendTimer(result.resend_in || 30);
                        otpSlots.forEach(s => { s.value = ''; s.classList.remove('error'); });
                        if (otpSlots[0]) otpSlots[0].focus();
                    } else {
                        showAlert(otpAlert, result.error || 'Unable to resend code right now.', false);
                        btnResend.disabled = false;
                        btnResend.textContent = 'Resend code';
                    }
                } catch (err) {
                    showAlert(otpAlert, err.message || 'Network error while requesting new code.', false);
                    btnResend.disabled = false;
                    btnResend.textContent = 'Resend code';
                }
            });
        }

        // -------------------------------------------------------------
        // Back / Edit Phone Navigation
        // -------------------------------------------------------------
        function navigateBackToSignup() {
            clearAlert(otpAlert);
            clearAlert(signupAlert);
            stepOtp.classList.add('d-none');
            stepSignup.classList.remove('d-none');
            window.history.replaceState({ step: 'signup' }, '', window.location.pathname);
            if (mobileInput) {
                mobileInput.focus();
                mobileInput.select();
            }
        }

        if (btnEditPhone) {
            btnEditPhone.addEventListener('click', navigateBackToSignup);
        }
        if (btnBack) {
            btnBack.addEventListener('click', navigateBackToSignup);
        }

        window.addEventListener('popstate', function () {
            if (window.location.hash !== '#verify') {
                stepOtp.classList.add('d-none');
                stepSignup.classList.remove('d-none');
            } else {
                stepSignup.classList.add('d-none');
                stepOtp.classList.remove('d-none');
            }
        });

        // Ensure initial step matches hash
        if (window.location.hash === '#verify') {
            stepSignup.classList.add('d-none');
            stepOtp.classList.remove('d-none');
            startResendTimer(30);
            if (otpSlots[0]) otpSlots[0].focus();
        } else {
            stepOtp.classList.add('d-none');
            stepSignup.classList.remove('d-none');
        }

        // -------------------------------------------------------------
        // Terms & Privacy Modals
        // -------------------------------------------------------------
        function openModal(modal) {
            if (modal) modal.style.display = 'flex';
        }
        function closeModal(modal) {
            if (modal) modal.style.display = 'none';
        }

        if (linkTerms && modalTerms) {
            linkTerms.addEventListener('click', () => openModal(modalTerms));
        }
        if (linkPrivacy && modalPrivacy) {
            linkPrivacy.addEventListener('click', () => openModal(modalPrivacy));
        }

        document.querySelectorAll('[data-close]').forEach(btn => {
            btn.addEventListener('click', function () {
                const target = this.getAttribute('data-close');
                if (target === 'terms' && modalTerms) closeModal(modalTerms);
                if (target === 'privacy' && modalPrivacy) closeModal(modalPrivacy);
            });
        });

        [modalTerms, modalPrivacy].forEach(m => {
            if (m) {
                m.addEventListener('click', function (e) {
                    if (e.target === m) closeModal(m);
                });
            }
        });

        // -------------------------------------------------------------
        // Button Helper
        // -------------------------------------------------------------
        function setButtonLoading(btn, isLoading, labelText) {
            if (!btn) return;
            const spinner = btn.querySelector('.o_axd_btn_spinner');
            const label = btn.querySelector('.o_axd_btn_label');
            btn.disabled = isLoading;
            if (spinner) spinner.style.display = isLoading ? 'inline-block' : 'none';
            if (label && labelText) label.innerHTML = labelText;
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initAixoDeskSignup);
    } else {
        initAixoDeskSignup();
    }
})();
