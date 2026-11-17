// landing.js — "See how it works" video modal

(function () {
    var openBtn = document.getElementById('video-open');
    var modal = document.getElementById('video-modal');
    var closeBtn = document.getElementById('video-close');
    var frame = document.getElementById('video-frame');

    if (!openBtn || !modal || !closeBtn || !frame) return;

    function openModal() {
        // Load the video only when opened, so it starts fresh and autoplays.
        frame.src = frame.dataset.src;
        modal.hidden = false;
        document.body.style.overflow = 'hidden';
        closeBtn.focus();
    }

    function closeModal() {
        modal.hidden = true;
        // Unloading the iframe is what actually stops playback.
        frame.src = 'about:blank';
        document.body.style.overflow = '';
        openBtn.focus();
    }

    openBtn.addEventListener('click', openModal);
    closeBtn.addEventListener('click', closeModal);

    // Clicking the dark overlay (outside the dialog) closes the modal.
    modal.addEventListener('click', function (e) {
        if (e.target === modal) closeModal();
    });

    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && !modal.hidden) closeModal();
    });
})();
