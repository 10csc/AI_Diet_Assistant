// ====== 主入口 ======

import state from './state.js';
import { loadWeatherCities, fetchWeather } from './weather.js';
import {
    updatePrimaryVisibility, updateSecondaryVisibility, bindConfigAutoSave,
    loadConfigIntoForm, saveConfig, checkFirstRun, closeSetup,
    switchSettingsPanel, scheduleConfigSave
} from './config.js';
import { submitRequest, renderCurrentConversation, createNewConversation, handleComposerKeydown } from './chat.js';
import { loadHistory, openHistorySidebar, closeHistorySidebar, handleHistoryClick, handleGlobalKeydown, syncHistorySidebarState } from './history.js';
import { renderFavorites } from './favorites.js';
import { autoResizeTextarea } from './utils.js';

document.addEventListener('DOMContentLoaded', async () => {
    const primaryType = document.getElementById('primary_type');
    const favoritesBtn = document.getElementById('open_favorites');
    const setupOverlay = document.getElementById('setup_overlay');

    // 配置向导按钮
    document.getElementById('setup_save_btn').addEventListener('click', async () => {
        const apikey = document.getElementById('setup_apikey').value.trim();
        const weatherak = document.getElementById('setup_weatherak').value.trim();
        const modelType = document.getElementById('setup_primary_type').value;
        if (apikey) document.getElementById('deepseek_apikey').value = apikey;
        if (weatherak) document.getElementById('weather_ak').value = weatherak;
        if (apikey) document.getElementById('primary_apikey').value = apikey;
        document.getElementById('primary_type').value = modelType;
        document.getElementById('secondary_type').value = 'deepseek';
        updatePrimaryVisibility();
        updateSecondaryVisibility();
        await saveConfig();
        setupOverlay.style.display = 'none';
    });
    document.getElementById('setup_skip_btn').addEventListener('click', () => {
        setupOverlay.style.display = 'none';
    });

    // 收藏弹出层
    const favoritesOverlay = document.getElementById('favorites_overlay');
    const closeFavoritesBtn = document.getElementById('close_favorites');

    favoritesBtn.addEventListener('click', async () => {
        await renderFavorites();
        favoritesOverlay.style.display = 'flex';
    });
    closeFavoritesBtn.addEventListener('click', () => {
        favoritesOverlay.style.display = 'none';
    });
    favoritesOverlay.addEventListener('click', (e) => {
        if (e.target === favoritesOverlay) favoritesOverlay.style.display = 'none';
    });

    // 模型类型切换
    const useSecondaryCheckbox = document.getElementById('use_secondary');
    const secondaryType = document.getElementById('secondary_type');
    const userInput = document.getElementById('user_input');

    primaryType.addEventListener('change', () => {
        updatePrimaryVisibility();
        scheduleConfigSave();
    });

    useSecondaryCheckbox.addEventListener('change', () => {
        updateSecondaryVisibility();
        scheduleConfigSave();
    });

    secondaryType.addEventListener('change', () => {
        updateSecondaryVisibility();
        scheduleConfigSave();
    });

    // 设置面板切换
    document.querySelectorAll('.settings-tab:not(.nav-tab)').forEach((button) => {
        button.addEventListener('click', () => switchSettingsPanel(button.dataset.panel));
    });

    // 主操作按钮
    document.getElementById('fetch_weather').addEventListener('click', fetchWeather);
    document.getElementById('submit_btn').addEventListener('click', submitRequest);
    document.getElementById('refresh_history').addEventListener('click', () => loadHistory(state.selectedConversationKey));
    document.getElementById('new_chat').addEventListener('click', () => createNewConversation(true));
    document.getElementById('history_list').addEventListener('click', handleHistoryClick);
    document.getElementById('open_history_sidebar').addEventListener('click', openHistorySidebar);
    document.getElementById('close_history_sidebar').addEventListener('click', closeHistorySidebar);
    document.getElementById('history_sidebar_backdrop').addEventListener('click', closeHistorySidebar);

    // 键盘事件
    document.addEventListener('keydown', handleGlobalKeydown);
    userInput.addEventListener('keydown', handleComposerKeydown);
    userInput.addEventListener('input', () => autoResizeTextarea(userInput));

    // 初始化
    bindConfigAutoSave();
    createNewConversation(false);
    await loadWeatherCities();
    await loadConfigIntoForm();
    await checkFirstRun();
    updatePrimaryVisibility();
    updateSecondaryVisibility();
    switchSettingsPanel('weather_panel');
    syncHistorySidebarState();
    autoResizeTextarea(userInput);
    renderCurrentConversation();
    await loadHistory(state.selectedConversationKey);
});
