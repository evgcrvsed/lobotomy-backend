let collections = [];
let currentProductId = null;

async function init() {
    collections = await fetchCollections();
    renderFilterTabs();
    await renderProducts();
}

async function fetchCollections() {
    const res = await fetch('/api/collections/');
    if (!res.ok) return [];
    return res.json();
}

async function fetchProducts() {
    const res = await fetch('/api/products/');
    if (!res.ok) return [];
    return res.json();
}

// ── Filters ──────────────────────────────────────────────────────────────────

let activeCollectionId = null;

function renderFilterTabs() {
    const container = document.getElementById('filter-tabs');
    container.innerHTML = '';

    addFilterTab(container, 'Все', null);
    for (const col of collections) {
        addFilterTab(container, col.name, col.id);
    }
}

function addFilterTab(container, label, collectionId) {
    const btn = document.createElement('button');
    btn.className = 'admin-filter' + (collectionId === activeCollectionId ? ' admin-filter--active' : '');
    btn.textContent = label;
    btn.addEventListener('click', () => {
        activeCollectionId = collectionId;
        container.querySelectorAll('.admin-filter').forEach(b => b.classList.remove('admin-filter--active'));
        btn.classList.add('admin-filter--active');
        renderProducts();
    });
    container.appendChild(btn);
}

// ── Product list ──────────────────────────────────────────────────────────────

async function renderProducts() {
    const list = document.getElementById('product-list');
    list.innerHTML = '<p class="admin-empty">Загрузка...</p>';

    const products = await fetchProducts();

    const filtered = activeCollectionId !== null
        ? products.filter(p => p.collection_id === activeCollectionId)
        : products;

    list.innerHTML = '';

    if (filtered.length === 0) {
        list.innerHTML = '<p class="admin-empty">Нет изделий</p>';
        return;
    }

    for (const product of filtered) {
        list.appendChild(buildRow(product));
    }
}

function getCollectionName(id) {
    return collections.find(c => c.id === id)?.name ?? '—';
}

function buildRow(product) {
    const firstImg = product.images[0]?.filename ?? null;

    const row = document.createElement('div');
    row.className = 'admin-row';

    row.innerHTML = `
        <div class="admin-row__img">
            ${firstImg
                ? `<img src="/static/images/${firstImg}" alt="${product.name}">`
                : `<div class="admin-row__img-placeholder"></div>`
            }
        </div>
        <div class="admin-row__body">
            <span class="admin-row__name">${product.name}</span>
            <span class="admin-row__collection">${getCollectionName(product.collection_id)}</span>
        </div>
        <div class="admin-row__meta">
            ${[product.material, product.density ? product.density + ' г/м²' : null].filter(Boolean).join(' · ')}
        </div>
        <div class="admin-row__price">${product.price.toLocaleString('ru-RU')} ₽</div>
        <div class="admin-row__actions">
            <button class="btn btn--outline" data-action="edit" data-id="${product.id}">Ред.</button>
            <button class="btn btn--outline admin-btn--danger" data-action="delete" data-id="${product.id}">Уд.</button>
        </div>
    `;

    row.querySelector('[data-action="edit"]').addEventListener('click', () => openEditModal(product.id));
    row.querySelector('[data-action="delete"]').addEventListener('click', () => deleteProduct(product.id, product.name));

    return row;
}

// ── Modal ─────────────────────────────────────────────────────────────────────

function populateCollectionSelect(selectedId) {
    const select = document.getElementById('field-collection');
    select.innerHTML = '';
    for (const col of collections) {
        const opt = document.createElement('option');
        opt.value = col.id;
        opt.textContent = col.name;
        if (col.id === selectedId) opt.selected = true;
        select.appendChild(opt);
    }
}

function openCreateModal() {
    currentProductId = null;
    document.getElementById('modal-title').textContent = 'Добавить изделие';
    document.getElementById('product-form').reset();
    populateCollectionSelect(null);
    document.getElementById('modal-overlay').removeAttribute('hidden');
    document.getElementById('field-name').focus();
}

async function openEditModal(productId) {
    const res = await fetch(`/api/products/${productId}`);
    if (!res.ok) return;
    const product = await res.json();

    currentProductId = productId;
    document.getElementById('modal-title').textContent = 'Редактировать изделие';

    populateCollectionSelect(product.collection_id);
    document.getElementById('field-name').value        = product.name;
    document.getElementById('field-description').value = product.description ?? '';
    document.getElementById('field-material').value    = product.material ?? '';
    document.getElementById('field-density').value     = product.density ?? '';
    document.getElementById('field-price').value       = product.price;
    document.getElementById('field-images').value      = product.images
        .sort((a, b) => a.sort_order - b.sort_order)
        .map(i => i.filename)
        .join('\n');

    document.getElementById('modal-overlay').removeAttribute('hidden');
    document.getElementById('field-name').focus();
}

function closeModal() {
    document.getElementById('modal-overlay').setAttribute('hidden', '');
    currentProductId = null;
}

async function submitForm(e) {
    e.preventDefault();

    const imagesRaw = document.getElementById('field-images').value.trim();
    const images = imagesRaw
        ? imagesRaw.split('\n').map(l => l.trim()).filter(Boolean).map((filename, i) => ({ filename, sort_order: i + 1 }))
        : [];

    const densityVal = document.getElementById('field-density').value;

    const data = {
        collection_id: parseInt(document.getElementById('field-collection').value),
        name:          document.getElementById('field-name').value.trim(),
        description:   document.getElementById('field-description').value.trim() || null,
        material:      document.getElementById('field-material').value.trim() || null,
        density:       densityVal ? parseInt(densityVal) : null,
        price:         parseInt(document.getElementById('field-price').value),
        images,
    };

    const url    = currentProductId ? `/api/products/${currentProductId}` : '/api/products/';
    const method = currentProductId ? 'PUT' : 'POST';

    const submitBtn = document.getElementById('btn-submit');
    submitBtn.disabled = true;
    submitBtn.textContent = 'Сохранение...';

    try {
        const res = await fetch(url, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            alert('Ошибка: ' + (err.detail ?? 'Что-то пошло не так'));
            return;
        }

        closeModal();
        await renderProducts();
    } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Сохранить';
    }
}

async function deleteProduct(productId, name) {
    if (!confirm(`Удалить «${name}»?`)) return;

    const res = await fetch(`/api/products/${productId}`, { method: 'DELETE' });
    if (!res.ok) {
        alert('Не удалось удалить изделие');
        return;
    }
    await renderProducts();
}

// ── Events ────────────────────────────────────────────────────────────────────

document.getElementById('btn-add').addEventListener('click', openCreateModal);
document.getElementById('modal-close').addEventListener('click', closeModal);
document.getElementById('btn-cancel').addEventListener('click', closeModal);
document.getElementById('product-form').addEventListener('submit', submitForm);

document.getElementById('modal-overlay').addEventListener('click', e => {
    if (e.target === e.currentTarget) closeModal();
});

document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeModal();
});

init();
