(function () {
    /* -------------------------------------------------------
       PAGE TRANSITIONS
       fade in/out only .page-content — header is untouched
    ------------------------------------------------------- */
    const content = document.querySelector('.page-content');

    window.addEventListener('DOMContentLoaded', function () {
        requestAnimationFrame(function () {
            content.classList.add('page-visible');
        });
    });

    document.addEventListener('click', function (e) {
        const link = e.target.closest('a[href]');
        if (!link) return;

        const href = link.getAttribute('href');

        // Skip: anchors, external links, special protocols, new tabs
        if (
            !href ||
            href.startsWith('#') ||
            href.startsWith('mailto:') ||
            href.startsWith('tel:') ||
            link.target === '_blank' ||
            link.hostname !== window.location.hostname
        ) return;

        e.preventDefault();

        content.classList.remove('page-visible');
        content.classList.add('page-exit');

        // Wait for fade-out to finish, then navigate
        setTimeout(function () {
            window.location.href = href;
        }, 260);
    });
})();