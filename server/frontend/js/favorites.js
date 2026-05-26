// ====== 收藏/反馈管理 ======

import { escapeHtml } from './utils.js';

const FAVORITES_URL = '/api/favorites';
const FAVORITES_ADD_URL = '/api/favorites/add';
const FAVORITES_REMOVE_URL = '/api/favorites/remove';
const FEEDBACK_URL = '/api/feedback';

/** 本地存储后备 */
function getLocalFavorites() {
    try { return JSON.parse(localStorage.getItem('favorites')) || []; }
    catch { return []; }
}

function saveLocalFavorites(favs) {
    localStorage.setItem('favorites', JSON.stringify(favs));
}

function getLocalRecipeProfile() {
    try { return JSON.parse(localStorage.getItem('recipe_profile')) || []; }
    catch { return []; }
}

function saveLocalRecipeProfile(profile) {
    localStorage.setItem('recipe_profile', JSON.stringify(profile));
}

/** 获取收藏列表（API → localStorage 降级） */
export async function getFavorites() {
    try {
        const resp = await fetch(FAVORITES_URL);
        if (resp.ok) {
            const data = await resp.json();
            if (Array.isArray(data)) return data;
        }
    } catch { /* 降级到 localStorage */ }
    return getLocalFavorites();
}

/** 获取菜品反馈画像 */
export function getRecipeProfile() {
    return getLocalRecipeProfile();
}

/** 添加菜品反馈（API + localStorage） */
export async function addRecipeFeedback(dishName, dishData, action) {
    const profile = getLocalRecipeProfile();
    const filtered = profile.filter(item => item.dish_name !== dishName);
    const entry = { dish_name: dishName, dish_data: dishData, action, timestamp: new Date().toISOString() };
    filtered.push(entry);
    saveLocalRecipeProfile(filtered);

    // 同步到服务端
    try {
        await fetch(FEEDBACK_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(entry),
        });
    } catch { /* 静默降级 */ }
}

/** 添加收藏（API + localStorage） */
async function addFavoriteToServer(entry) {
    try {
        await fetch(FAVORITES_ADD_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(entry),
        });
    } catch { /* 静默降级 */ }
}

/** 移除收藏（API + localStorage） */
async function removeFavoriteFromServer(dishName) {
    try {
        await fetch(FAVORITES_REMOVE_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ dish_name: dishName }),
        });
    } catch { /* 静默降级 */ }
}

/** 渲染收藏列表 UI */
export async function renderFavorites() {
    const list = document.getElementById('favorites_list');
    const favs = await getFavorites();
    if (!favs.length) {
        list.innerHTML = '<p class="favorites-empty">暂无收藏</p>';
        return;
    }
    list.innerHTML = favs.map((item, idx) => {
        const dish = item.dish_data?.主菜 || {};
        const sides = Array.isArray(item.dish_data?.配菜)
            ? item.dish_data.配菜.map(s => s.菜名).filter(Boolean).join('、')
            : '';
        return `
            <div class="fav-item">
                <div class="fav-item-name">${escapeHtml(dish.菜名 || '未知菜式')}</div>
                <div class="fav-item-meta">${escapeHtml(dish.食材 || '')}${sides ? ' · 配菜：' + escapeHtml(sides) : ''}</div>
                <div class="fav-item-actions">
                    <button class="ghost-btn fav-remove-btn" data-dish-name="${escapeHtml(item.dish_name || '')}">移除</button>
                </div>
            </div>
        `;
    }).join('');

    list.querySelectorAll('.fav-remove-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            const dishName = btn.dataset.dishName;
            const localFavs = getLocalFavorites().filter(f => f.dish_name !== dishName);
            saveLocalFavorites(localFavs);
            await removeFavoriteFromServer(dishName);
            await renderFavorites();
        });
    });
}

/** 绑定消息卡片中的反馈按钮事件 */
export function bindFeedbackButtons(messageEl) {
    const card = messageEl.querySelector('.feedback-card');
    if (!card) return;

    const dishName = card.dataset.dishName;
    let dishData;
    try { dishData = JSON.parse(card.dataset.dishData); } catch { dishData = {}; }

    const profile = getLocalRecipeProfile();
    const existing = profile.find(item => item.dish_name === dishName);
    const favs = getLocalFavorites();
    const isFavorited = favs.some(item => item.dish_name === dishName);

    const likeBtn = card.querySelector('.like-btn');
    const dislikeBtn = card.querySelector('.dislike-btn');
    const favBtn = card.querySelector('.fav-btn');

    if (existing) {
        if (existing.action === 'like') likeBtn.classList.add('active');
        else if (existing.action === 'dislike') dislikeBtn.classList.add('active');
    }
    if (isFavorited) favBtn.classList.add('active');

    likeBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        addRecipeFeedback(dishName, dishData, 'like');
        likeBtn.classList.add('active');
        dislikeBtn.classList.remove('active');
    });

    dislikeBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        addRecipeFeedback(dishName, dishData, 'dislike');
        dislikeBtn.classList.add('active');
        likeBtn.classList.remove('active');
    });

    favBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const favs = getLocalFavorites();
        const idx = favs.findIndex(item => item.dish_name === dishName);
        if (idx >= 0) {
            favs.splice(idx, 1);
            favBtn.classList.remove('active');
            saveLocalFavorites(favs);
            await removeFavoriteFromServer(dishName);
        } else {
            const entry = { dish_name: dishName, dish_data: dishData, timestamp: new Date().toISOString() };
            favs.push(entry);
            favBtn.classList.add('active');
            saveLocalFavorites(favs);
            await addFavoriteToServer(entry);
        }
    });
}
