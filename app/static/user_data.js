console.log('Happy developing ✨')

const STORAGE_KEY = 'lobotomy_profile';

function saveProfile(data) {
    // TODO: replace with fetch('/api/profile', { method: 'PUT', body: JSON.stringify(data) })
    localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
}

function loadProfile() {
    // TODO: replace with fetch('/api/profile').then(r => r.json())
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        return raw ? JSON.parse(raw) : null;
    } catch {
        return null;
    }
}

// ─── Field config ────────────────────────────────────────────────────────
const FIELDS = [
    { key: 'name',    inputId: 'fieldName',    displayId: 'infoName',    label: 'ФИО',    empty: 'ФИО' },
    { key: 'address', inputId: 'fieldAddress', displayId: 'infoAddress', label: 'Адрес',  empty: 'Адрес' },
    { key: 'city',    inputId: 'fieldCity',    displayId: 'infoCity',    label: 'Город',  empty: 'Город' },
    { key: 'zip',     inputId: 'fieldZip',     displayId: 'infoZip',     label: 'Индекс', empty: 'Индекс' },
    { key: 'email',   inputId: 'fieldEmail',   displayId: 'infoEmail',   label: 'Почта',  empty: 'Почта' },
];

// ─── DOM refs ────────────────────────────────────────────────────────────
const user_data       = document.getElementById('editModal');
const modalClose  = document.getElementById('modalClose');
const modalCancel = document.getElementById('modalCancel');
const form        = document.getElementById('profileForm');
const editBtn     = document.getElementById('openModal');

// ─── Render profile data in the card ─────────────────────────────────────
function renderProfile(data) {
    FIELDS.forEach(({ key, displayId, label, empty }) => {
        const el = document.getElementById(displayId);
        if (!el) return;
        const value = data && data[key] && data[key].trim();
        if (value) {
            el.textContent = `${label}: ${value}`;
            el.classList.remove('profile-info__item--empty');
        } else {
            el.textContent = empty;
            el.classList.add('profile-info__item--empty');
        }
    });
}

// ─── Populate form with stored data ──────────────────────────────────────
function populateForm(data) {
    FIELDS.forEach(({ key, inputId }) => {
        const input = document.getElementById(inputId);
        if (input) input.value = (data && data[key]) || '';
    });
}

// ─── Modal open / close ───────────────────────────────────────────────────
function openModal() {
    const data = loadProfile();
    populateForm(data);
    user_data.hidden = false;
    document.body.style.overflow = 'hidden';
    // Focus first input for a11y
    const first = form.querySelector('input');
    if (first) setTimeout(() => first.focus(), 50);
}

function closeModal() {
    user_data.hidden = true;
    document.body.style.overflow = '';
    editBtn.focus();
}

// ─── Event listeners ──────────────────────────────────────────────────────
editBtn.addEventListener('click', openModal);
modalClose.addEventListener('click', closeModal);
modalCancel.addEventListener('click', closeModal);

// Close on overlay click
user_data.addEventListener('click', (e) => {
    if (e.target === user_data) closeModal();
});

// Close on Escape
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !user_data.hidden) closeModal();
});

// Trap focus inside user_data
user_data.addEventListener('keydown', (e) => {
    if (e.key !== 'Tab') return;
    const focusable = [...user_data.querySelectorAll('button, input, [tabindex]:not([tabindex="-1"])')];
    const first = focusable[0];
    const last  = focusable[focusable.length - 1];
    if (e.shiftKey) {
        if (document.activeElement === first) { e.preventDefault(); last.focus(); }
    } else {
        if (document.activeElement === last)  { e.preventDefault(); first.focus(); }
    }
});

// Save form
form.addEventListener('submit', (e) => {
    e.preventDefault();
    const data = {};
    FIELDS.forEach(({ key, inputId }) => {
        const input = document.getElementById(inputId);
        data[key] = input ? input.value.trim() : '';
    });
    saveProfile(data);
    renderProfile(data);
    closeModal();

    // Brief visual confirmation on the button
    editBtn.textContent = 'Сохранено ✓';
    editBtn.disabled = true;
    setTimeout(() => {
        editBtn.textContent = 'Изменить';
        editBtn.disabled = false;
    }, 1800);
});

// ─── Init on page load ───────────────────────────────────────────────────
(function init() {
    const data = loadProfile();
    renderProfile(data);
})();