(function () {
    const content = document.querySelector('.page-content');
    const header  = document.querySelector('.header');

    window.addEventListener('pageshow', function () {
        content.classList.remove('page-exit');
        header.classList.remove('header--exit');
        requestAnimationFrame(function () {
            content.classList.add('page-visible');
        });
    });

    document.addEventListener('click', function (e) {
        const link = e.target.closest('a[href]');
        if (!link) return;

        const href = link.getAttribute('href');

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
        header.classList.add('header--exit');

        setTimeout(function () {
            window.location.href = href;
        }, 260);
    });
})();
