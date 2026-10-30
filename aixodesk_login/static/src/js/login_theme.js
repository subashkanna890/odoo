/** @odoo-module ignore **/
/* ==========================================================================
   AixoDesk Login Theme, Carousel & Eye-Toggle Controller
   Plain JavaScript (no external imports/dependencies)
   ========================================================================== */

(function () {
    'use strict';

    function initApp() {
        initTheme();
        initPasswordToggle();
        initCarousel();
    }

    function initTheme() {
        var savedMode = null;
        try {
            var urlParams = new URLSearchParams(window.location.search);
            var queryMode = urlParams.get('mode');
            if (queryMode === 'light' || queryMode === 'dark') {
                savedMode = queryMode;
            } else {
                savedMode = localStorage.getItem('axd-mode');
            }
        } catch (e) {
            console.warn('Parameter or localStorage access issue:', e);
        }

        if (savedMode !== 'dark' && savedMode !== 'light') {
            savedMode = 'light';
        }

        applyMode(savedMode);

        var toggleBtn = document.getElementById('axd_mode_toggle');
        if (toggleBtn) {
            toggleBtn.addEventListener('click', function () {
                var currentMode = document.body.getAttribute('data-axd-mode') || 'light';
                var nextMode = currentMode === 'dark' ? 'light' : 'dark';

                toggleBtn.classList.add('animating');
                setTimeout(function () {
                    toggleBtn.classList.remove('animating');
                }, 350);

                applyMode(nextMode);

                try {
                    localStorage.setItem('axd-mode', nextMode);
                } catch (e) {
                    console.warn('Unable to save mode to localStorage:', e);
                }
            });
        }
    }

    function applyMode(mode) {
        document.documentElement.setAttribute('data-axd-mode', mode);
        document.body.setAttribute('data-axd-mode', mode);
        var loginWrapper = document.querySelector('.o_axd_login');
        if (loginWrapper) {
            loginWrapper.setAttribute('data-axd-mode', mode);
        }
        var toggleBtn = document.getElementById('axd_mode_toggle');
        if (toggleBtn) {
            var label = mode === 'dark' ? 'Switch to bright mode' : 'Switch to dark mode';
            toggleBtn.setAttribute('aria-label', label);
            toggleBtn.setAttribute('title', label);
        }
    }

    /* --- Modern Password Eye Toggle --- */
    function initPasswordToggle() {
        // Remove any default Odoo or duplicate visibility buttons from the DOM
        var dupButtons = document.querySelectorAll('.o_show_password, .input-group > .btn.border');
        for (var i = 0; i < dupButtons.length; i++) {
            dupButtons[i].style.display = 'none';
        }

        var toggleBtn = document.getElementById('axd_eye_toggle');
        var pwdInput = document.getElementById('password');
        if (!toggleBtn || !pwdInput) {
            return;
        }

        var openEye = toggleBtn.querySelector('.o_axd_eye_open');
        var slashEye = toggleBtn.querySelector('.o_axd_eye_slash');

        toggleBtn.addEventListener('click', function (e) {
            e.preventDefault();
            e.stopPropagation();

            var isPassword = pwdInput.getAttribute('type') === 'password';
            if (isPassword) {
                pwdInput.setAttribute('type', 'text');
                toggleBtn.classList.add('active');
                toggleBtn.classList.add('is-visible');
                toggleBtn.setAttribute('title', 'Hide password');
                toggleBtn.setAttribute('aria-label', 'Hide password');
            } else {
                pwdInput.setAttribute('type', 'password');
                toggleBtn.classList.remove('active');
                toggleBtn.classList.remove('is-visible');
                toggleBtn.setAttribute('title', 'Show password');
                toggleBtn.setAttribute('aria-label', 'Show password');
            }
            pwdInput.focus();
        });
    }

    /* --- Carousel with 5-Second Interval & Synced Illustrations --- */
    function initCarousel() {
        var promoCol = document.querySelector('.o_axd_promo_col');
        var slides = document.querySelectorAll('.o_axd_slide');
        var artSlides = document.querySelectorAll('.o_axd_art_slide');
        var dots = document.querySelectorAll('.o_axd_dot');
        if (!slides.length || !dots.length) {
            return;
        }

        var currentIndex = 0;
        var timer = null;
        var prefersReducedMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

        function goToSlide(index) {
            currentIndex = (index + slides.length) % slides.length;

            // 1. Sync Text Slides
            slides.forEach(function (slide, idx) {
                if (idx === currentIndex) {
                    slide.classList.add('active');
                    slide.setAttribute('aria-hidden', 'false');
                } else {
                    slide.classList.remove('active');
                    slide.setAttribute('aria-hidden', 'true');
                }
            });

            // 2. Sync Illustration Deck
            artSlides.forEach(function (art, idx) {
                if (idx === currentIndex) {
                    art.classList.add('active');
                    art.setAttribute('aria-hidden', 'false');
                } else {
                    art.classList.remove('active');
                    art.setAttribute('aria-hidden', 'true');
                }
            });

            // 3. Sync Slide Dots
            dots.forEach(function (dot, idx) {
                if (idx === currentIndex) {
                    dot.classList.add('active');
                    dot.setAttribute('aria-current', 'true');
                    dot.setAttribute('aria-selected', 'true');
                } else {
                    dot.classList.remove('active');
                    dot.removeAttribute('aria-current');
                    dot.setAttribute('aria-selected', 'false');
                }
            });
        }

        dots.forEach(function (dot) {
            dot.addEventListener('click', function () {
                var idx = parseInt(dot.getAttribute('data-slide-index'), 10);
                if (!isNaN(idx)) {
                    goToSlide(idx);
                }
            });
        });

        function startAutoplay() {
            if (prefersReducedMotion) {
                return;
            }
            stopAutoplay();
            // Automatically advances both illustration & slide text every 5 seconds (5000ms)
            timer = setInterval(function () {
                goToSlide(currentIndex + 1);
            }, 5000);
        }

        function stopAutoplay() {
            if (timer) {
                clearInterval(timer);
                timer = null;
            }
        }

        if (promoCol) {
            promoCol.addEventListener('mouseenter', stopAutoplay);
            promoCol.addEventListener('mouseleave', startAutoplay);
        }

        goToSlide(0);
        startAutoplay();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initApp);
    } else {
        initApp();
    }
})();
