(function () {
    const viewport   = document.getElementById('heroViewport');
    const centerItem = viewport.querySelector('.hero__item--lg');

    function setSizes() {
        const cw = viewport.clientWidth;
        const mobile = cw < 640;
        if (mobile) {
            viewport.querySelectorAll('.hero__item--lg').forEach(el => el.style.width = cw + 'px');
            viewport.querySelectorAll('.hero__item--md').forEach(el => el.style.width = (cw * 0.38) + 'px');
            viewport.querySelectorAll('.hero__item--sm').forEach(el => el.style.width = (cw * 0.38) + 'px');
        } else {
            viewport.querySelectorAll('.hero__item--lg').forEach(el => el.style.width = (cw * 0.34) + 'px');
            viewport.querySelectorAll('.hero__item--md').forEach(el => el.style.width = (cw * 0.22) + 'px');
            viewport.querySelectorAll('.hero__item--sm').forEach(el => el.style.width = (cw * 0.18) + 'px');
        }
    }

    function resetScroll() {
        viewport.scrollLeft = centerItem.offsetLeft
            - (viewport.clientWidth - centerItem.offsetWidth) / 2;
    }

    setSizes();
    resetScroll();
    window.addEventListener('resize', () => { setSizes(); resetScroll(); });

    function step() {
        return viewport.clientWidth * 0.18 + 2;
    }

    document.querySelector('.hero__nav--prev').addEventListener('click', () =>
        viewport.scrollBy({ left: -step(), behavior: 'smooth' })
    );
    document.querySelector('.hero__nav--next').addEventListener('click', () =>
        viewport.scrollBy({ left: step(), behavior: 'smooth' })
    );

    let isDown = false, startX = 0, scrollStart = 0;
    viewport.addEventListener('mousedown', e => {
        isDown = true;
        startX = e.clientX;
        scrollStart = viewport.scrollLeft;
        viewport.style.cursor = 'grabbing';
        e.preventDefault();
    });
    window.addEventListener('mousemove', e => {
        if (!isDown) return;
        viewport.scrollLeft = scrollStart - (e.clientX - startX);
    });
    window.addEventListener('mouseup', () => {
        isDown = false;
        viewport.style.cursor = '';
    });

    document.querySelectorAll('.catalog__filter').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.catalog__filter')
                .forEach(b => b.classList.remove('catalog__filter--active'));
            btn.classList.add('catalog__filter--active');
        });
    });
})();
