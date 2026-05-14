let currentWeather = null;
let loadedConfig = {};
let autoSaveTimer = null;
let weatherCities = [];
let historyConversations = [];
let currentConversation = null;
let selectedConversationKey = '';
let historySidebarOpen = false;

const WEATHER_BASE_URL = 'https://api.map.baidu.com/weather/v1/';
const CONFIG_INPUT_IDS = [
    'age',
    'gender',
    'height',
    'weight',
    'occupation',
    'taste',
    'health',
    'weather_ak',
    'weather_city',
    'primary_type',
    'primary_model',
    'primary_apikey',
    'use_secondary',
    'secondary_type',
    'deepseek_model',
    'deepseek_apikey',
    'ollama_model',
    'ollama_server',
    'primary_llamacpp_server',
    'secondary_llamacpp_server'
];

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
    const favoritesOverlay = document.getElementById('favorites_overlay');
    const closeFavoritesBtn = document.getElementById('close_favorites');

    favoritesBtn.addEventListener('click', () => {
        renderFavorites();
        favoritesOverlay.style.display = 'flex';
    });
    closeFavoritesBtn.addEventListener('click', () => {
        favoritesOverlay.style.display = 'none';
    });
    favoritesOverlay.addEventListener('click', (e) => {
        if (e.target === favoritesOverlay) favoritesOverlay.style.display = 'none';
    });

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

    document.querySelectorAll('.settings-tab').forEach((button) => {
        button.addEventListener('click', () => switchSettingsPanel(button.dataset.panel));
    });

    document.getElementById('fetch_weather').addEventListener('click', fetchWeather);
    document.getElementById('submit_btn').addEventListener('click', submitRequest);
    document.getElementById('refresh_history').addEventListener('click', () => loadHistory(selectedConversationKey));
    document.getElementById('new_chat').addEventListener('click', () => createNewConversation(true));
    document.getElementById('history_list').addEventListener('click', handleHistoryClick);
    document.getElementById('open_history_sidebar').addEventListener('click', openHistorySidebar);
    document.getElementById('close_history_sidebar').addEventListener('click', closeHistorySidebar);
    document.getElementById('history_sidebar_backdrop').addEventListener('click', closeHistorySidebar);
    document.addEventListener('keydown', handleGlobalKeydown);
    userInput.addEventListener('keydown', handleComposerKeydown);
    userInput.addEventListener('input', () => autoResizeTextarea(userInput));

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
    await loadHistory(selectedConversationKey);
});

async function checkFirstRun() {
    const deepseekKey = document.getElementById('deepseek_apikey').value.trim();
    const weatherAk = document.getElementById('weather_ak').value.trim();
    const isFirstRun = !deepseekKey || deepseekKey === 'your_deepseek_api_key_here'
        || !weatherAk || weatherAk === 'your_baidu_api_key_here';

    if (isFirstRun) {
        const overlay = document.getElementById('setup_overlay');
        if (overlay) overlay.style.display = 'flex';
    }
}

function closeSetup() {
    const overlay = document.getElementById('setup_overlay');
    if (overlay) overlay.style.display = 'none';
}

function switchSettingsPanel(panelId) {
    document.querySelectorAll('.settings-tab').forEach((tab) => {
        tab.classList.toggle('active', tab.dataset.panel === panelId);
    });

    document.querySelectorAll('.settings-panel').forEach((panel) => {
        panel.classList.toggle('active', panel.id === panelId);
    });
}

function openHistorySidebar() {
    historySidebarOpen = true;
    syncHistorySidebarState();
}

function closeHistorySidebar() {
    historySidebarOpen = false;
    syncHistorySidebarState();
}

function syncHistorySidebarState() {
    const drawer = document.getElementById('history_sidebar_drawer');
    const backdrop = document.getElementById('history_sidebar_backdrop');
    drawer.classList.toggle('active', historySidebarOpen);
    backdrop.classList.toggle('active', historySidebarOpen);
    drawer.setAttribute('aria-hidden', historySidebarOpen ? 'false' : 'true');
    backdrop.setAttribute('aria-hidden', historySidebarOpen ? 'false' : 'true');
}

function handleGlobalKeydown(event) {
    if (event.key === 'Escape' && historySidebarOpen) {
        closeHistorySidebar();
    }
}

function bindConfigAutoSave() {
    CONFIG_INPUT_IDS.forEach((id) => {
        const element = document.getElementById(id);
        if (!element) {
            return;
        }

        element.addEventListener('change', scheduleConfigSave);
        if ((element.tagName === 'INPUT' || element.tagName === 'TEXTAREA') && element.type !== 'checkbox') {
            element.addEventListener('input', scheduleConfigSave);
        }
    });
}

function updateSecondaryVisibility() {
    const useSecondaryCheckbox = document.getElementById('use_secondary');
    const secondaryType = document.getElementById('secondary_type');
    const secondaryConfig = document.getElementById('secondary_config');
    const deepseekConfig = document.getElementById('deepseek_config');
    const ollamaCloudConfig = document.getElementById('ollama_cloud_config');
    const secondaryLlamacppConfig = document.getElementById('secondary_llamacpp_config');

    secondaryConfig.style.display = useSecondaryCheckbox.checked ? 'block' : 'none';
    deepseekConfig.style.display = secondaryType.value === 'deepseek' ? 'block' : 'none';
    ollamaCloudConfig.style.display = secondaryType.value === 'ollama' ? 'block' : 'none';
    secondaryLlamacppConfig.style.display = secondaryType.value === 'llamacpp' ? 'block' : 'none';
}

function updatePrimaryVisibility() {
    const primaryType = document.getElementById('primary_type');
    const primaryDeepseekConfig = document.getElementById('primary_deepseek_config');
    const primaryLlamacppConfig = document.getElementById('primary_llamacpp_config');
    const primaryModelInput = document.getElementById('primary_model');

    primaryDeepseekConfig.style.display = primaryType.value === 'deepseek' ? 'block' : 'none';
    primaryLlamacppConfig.style.display = primaryType.value === 'llamacpp' ? 'block' : 'none';
    primaryModelInput.placeholder = primaryType.value === 'deepseek' ? 'deepseek-chat'
        : primaryType.value === 'llamacpp' ? '由服务端管理' : 'deepseek-r1:7b';
    if (primaryType.value === 'llamacpp') {
        primaryModelInput.value = 'llama.cpp';
    }
}

async function loadWeatherCities() {
    const citySelect = document.getElementById('weather_city');
    citySelect.innerHTML = '<option value="">正在加载城市列表...</option>';

    try {
        const response = await fetch('/api/weather/cities');
        if (!response.ok) {
            throw new Error(`读取城市列表失败: ${response.status}`);
        }

        const result = await response.json();
        weatherCities = Array.isArray(result.items) ? result.items : [];
        populateWeatherCityOptions();
    } catch (error) {
        console.error(error);
        weatherCities = [];
        citySelect.innerHTML = '<option value="">城市列表加载失败</option>';
    }
}

function populateWeatherCityOptions(selectedDistrictId = '') {
    const citySelect = document.getElementById('weather_city');
    citySelect.innerHTML = '<option value="">请选择城市</option>';

    weatherCities.forEach((city) => {
        const option = document.createElement('option');
        option.value = city.district_id;
        option.textContent = city.display_name;
        option.dataset.cityName = city.city_name;
        citySelect.appendChild(option);
    });

    if (selectedDistrictId) {
        citySelect.value = selectedDistrictId;
    }
}

function findSelectedCity() {
    const districtId = document.getElementById('weather_city').value;
    return weatherCities.find((item) => item.district_id === districtId) || null;
}

function findCityFromConfig(weatherApi) {
    if (!weatherApi) {
        return null;
    }

    if (weatherApi.district_id) {
        return weatherCities.find((item) => item.district_id === weatherApi.district_id) || null;
    }

    const fallbackLocation = (weatherApi.city_name || weatherApi.location || '').trim();
    if (!fallbackLocation) {
        return null;
    }

    return weatherCities.find((item) =>
        item.city_name === fallbackLocation ||
        item.display_name.includes(fallbackLocation)
    ) || null;
}

async function loadConfigIntoForm() {
    try {
        const response = await fetch('/api/config');
        if (!response.ok) {
            throw new Error(`读取配置失败: ${response.status}`);
        }

        loadedConfig = await response.json();
        applyConfigToForm(loadedConfig);
    } catch (error) {
        console.error(error);
        loadedConfig = {};
    }
}

function applyConfigToForm(config) {
    const userProfile = config.user_profile || {};
    const weatherApi = config.weather_api || {};
    const models = config.models || {};
    const primary = models.primary || {};
    const secondary = models.secondary || {};
    const savedCity = findCityFromConfig(weatherApi);

    document.getElementById('age').value = userProfile.age || '';
    document.getElementById('gender').value = userProfile.gender || '男';
    document.getElementById('height').value = userProfile.height || '';
    document.getElementById('weight').value = userProfile.weight || '';
    document.getElementById('occupation').value = userProfile.occupation || '';
    document.getElementById('taste').value = userProfile.taste || '';
    document.getElementById('health').value = userProfile.health || '';

    document.getElementById('weather_ak').value = weatherApi.ak || '';
    populateWeatherCityOptions(savedCity ? savedCity.district_id : '');

    const llamacpp = models.llamacpp || {};

    document.getElementById('primary_type').value = primary.type || 'deepseek';
    document.getElementById('primary_model').value = primary.model || 'deepseek-chat';
    document.getElementById('primary_apikey').value = primary.api_key || secondary.api_key || '';
    document.getElementById('primary_llamacpp_server').value = llamacpp.server_url || 'http://127.0.0.1:11435';

    document.getElementById('use_secondary').checked = Boolean(secondary.enabled);
    document.getElementById('secondary_type').value = secondary.type || 'deepseek';
    document.getElementById('deepseek_model').value = secondary.type === 'deepseek' ? (secondary.model || 'deepseek-chat') : 'deepseek-chat';
    document.getElementById('deepseek_apikey').value = secondary.api_key || '';
    document.getElementById('ollama_model').value = secondary.type === 'ollama' ? (secondary.model || '') : '';
    document.getElementById('ollama_server').value = secondary.ollama_server || 'http://localhost:11434';
    document.getElementById('secondary_llamacpp_server').value = llamacpp.server_url || 'http://127.0.0.1:11435';

    if (weatherApi.cached_weather) {
        currentWeather = weatherApi.cached_weather;
        renderWeatherResult(buildWeatherSummary(currentWeather));
    } else {
        renderWeatherResult('等待获取天气...');
    }
}

function buildConfigPayload() {
    const primaryType = document.getElementById('primary_type').value;
    const secondaryType = document.getElementById('secondary_type').value;
    const selectedCity = findSelectedCity();

    return {
        ...loadedConfig,
        weather_api: {
            ...(loadedConfig.weather_api || {}),
            ak: document.getElementById('weather_ak').value.trim(),
            district_id: selectedCity ? selectedCity.district_id : '',
            city_name: selectedCity ? selectedCity.city_name : '',
            location: selectedCity ? selectedCity.city_name : '',
            base_url: WEATHER_BASE_URL,
            cached_weather: currentWeather
        },
        models: {
            ...(loadedConfig.models || {}),
            primary: {
                ...(loadedConfig.models?.primary || {}),
                type: primaryType,
                model: document.getElementById('primary_model').value.trim(),
                api_key: primaryType === 'deepseek' ? document.getElementById('primary_apikey').value.trim() : ''
            },
            llamacpp: {
                ...(loadedConfig.models?.llamacpp || {}),
                server_url: document.getElementById('primary_llamacpp_server').value.trim()
            },
            secondary: {
                ...(loadedConfig.models?.secondary || {}),
                enabled: document.getElementById('use_secondary').checked,
                type: secondaryType,
                model: secondaryType === 'deepseek'
                    ? document.getElementById('deepseek_model').value.trim()
                    : document.getElementById('ollama_model').value.trim(),
                api_key: document.getElementById('deepseek_apikey').value.trim(),
                ollama_server: document.getElementById('ollama_server').value.trim()
            }
        },
        user_profile: buildPersonalInfoPayload()
    };
}

function scheduleConfigSave() {
    if (autoSaveTimer) {
        clearTimeout(autoSaveTimer);
    }

    autoSaveTimer = setTimeout(() => {
        saveConfig().catch((error) => {
            console.error('自动保存配置失败:', error);
        });
    }, 300);
}

async function saveConfig() {
    const payload = buildConfigPayload();
    const response = await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload, null, 4)
    });

    if (!response.ok) {
        throw new Error(`保存配置失败: ${response.status}`);
    }

    loadedConfig = payload;
}

async function fetchWeather() {
    await saveConfig();

    const ak = document.getElementById('weather_ak').value.trim();
    const selectedCity = findSelectedCity();

    if (!ak || !selectedCity) {
        alert('请填写 AK 并选择城市');
        return;
    }

    renderWeatherResult('正在获取天气...');

    try {
        const url = `/api/weather?district_id=${encodeURIComponent(selectedCity.district_id)}&ak=${encodeURIComponent(ak)}`;
        const response = await fetch(url);
        const data = await response.json();
        const weatherResult = data?.result || {};
        const weatherNow = data?.result?.now;
        const location = data?.result?.location;
        const forecasts = Array.isArray(weatherResult.forecasts) ? weatherResult.forecasts : [];
        const indexes = Array.isArray(weatherResult.indexes) ? weatherResult.indexes : [];
        const alerts = Array.isArray(weatherResult.alerts) ? weatherResult.alerts : [];

        if (response.ok && data?.status === 0 && weatherNow) {
            currentWeather = {
                district_id: selectedCity.district_id,
                location: {
                    country: location?.country || '',
                    province: location?.province || '',
                    city: location?.city || selectedCity.city_name,
                    name: location?.name || selectedCity.city_name,
                    id: location?.id || selectedCity.district_id
                },
                now: {
                    temperature: weatherNow.temp,
                    feels_like: weatherNow.feels_like,
                    humidity: weatherNow.rh,
                    condition: weatherNow.text,
                    wind_dir: weatherNow.wind_dir,
                    wind_class: weatherNow.wind_class,
                    precipitation_1h: weatherNow.prec_1h,
                    visibility: weatherNow.vis,
                    clouds: weatherNow.clouds,
                    air_quality: {
                        aqi: weatherNow.aqi,
                        pm25: weatherNow.pm25,
                        pm10: weatherNow.pm10,
                        no2: weatherNow.no2,
                        so2: weatherNow.so2,
                        o3: weatherNow.o3,
                        co: weatherNow.co
                    },
                    uptime: weatherNow.uptime
                },
                forecasts,
                indexes,
                alerts
            };
            renderWeatherResult(buildWeatherSummary(currentWeather));
            await saveConfig();
        } else {
            currentWeather = null;
            renderWeatherResult(`获取天气失败：${buildReadableWeatherError(data)}`);
        }
    } catch (error) {
        currentWeather = null;
        renderWeatherResult(`网络错误：${error.message}`);
    }
}

function createConversationState(overrides = {}) {
    const timestamp = new Date().toISOString();
    const id = overrides.id || generateConversationId();
    return {
        key: overrides.key || id,
        id,
        title: overrides.title || '新对话',
        messages: Array.isArray(overrides.messages) ? overrides.messages.slice() : [],
        createdAt: overrides.createdAt || timestamp,
        updatedAt: overrides.updatedAt || timestamp,
        deleteMeta: overrides.deleteMeta || null,
        isDraft: overrides.isDraft !== undefined ? overrides.isDraft : true
    };
}

function createNewConversation(shouldRender = true) {
    currentConversation = createConversationState({ isDraft: true, title: '新对话' });
    selectedConversationKey = currentConversation.key;
    if (shouldRender) {
        renderHistory();
        renderCurrentConversation();
    }
}

// ====== 菜品反馈系统（赞/踩/收藏）======

function getRecipeProfile() {
    try { return JSON.parse(localStorage.getItem('recipe_profile')) || []; }
    catch { return []; }
}

function saveRecipeProfile(profile) {
    localStorage.setItem('recipe_profile', JSON.stringify(profile));
}

function getFavorites() {
    try { return JSON.parse(localStorage.getItem('favorites')) || []; }
    catch { return []; }
}

function saveFavorites(favs) {
    localStorage.setItem('favorites', JSON.stringify(favs));
}

function addRecipeFeedback(dishName, dishData, action) {
    const profile = getRecipeProfile();
    // 移除已有同一菜品的旧记录
    const filtered = profile.filter(item => item.dish_name !== dishName);
    filtered.push({
        dish_name: dishName,
        dish_data: dishData,
        action: action,
        timestamp: new Date().toISOString()
    });
    saveRecipeProfile(filtered);
}

function renderFavorites() {
    const list = document.getElementById('favorites_list');
    const favs = getFavorites();
    if (!favs.length) {
        list.innerHTML = '<p class="favorites-empty">暂无收藏</p>';
        return;
    }
    list.innerHTML = favs.map((item, idx) => {
        const dish = item.dish_data?.主菜 || {};
        const sides = Array.isArray(item.dish_data?.配菜) ? item.dish_data.配菜.map(s => s.菜名).filter(Boolean).join('、') : '';
        return `
            <div class="fav-item">
                <div class="fav-item-name">${escapeHtml(dish.菜名 || '未知菜式')}</div>
                <div class="fav-item-meta">${escapeHtml(dish.食材 || '')}${sides ? ' · 配菜：' + escapeHtml(sides) : ''}</div>
                <div class="fav-item-actions">
                    <button class="ghost-btn fav-remove-btn" data-index="${idx}">移除</button>
                </div>
            </div>
        `;
    }).join('');

    list.querySelectorAll('.fav-remove-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const idx = parseInt(btn.dataset.index);
            const favs = getFavorites();
            favs.splice(idx, 1);
            saveFavorites(favs);
            renderFavorites();
        });
    });
}

function bindFeedbackButtons(messageEl) {
    const card = messageEl.querySelector('.feedback-card');
    if (!card) return;

    const dishName = card.dataset.dishName;
    let dishData;
    try { dishData = JSON.parse(card.dataset.dishData); } catch { dishData = {}; }

    // 更新按钮状态
    const profile = getRecipeProfile();
    const existing = profile.find(item => item.dish_name === dishName);
    const favs = getFavorites();
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

    favBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const favs = getFavorites();
        const idx = favs.findIndex(item => item.dish_name === dishName);
        if (idx >= 0) {
            favs.splice(idx, 1);
            favBtn.classList.remove('active');
        } else {
            favs.push({
                dish_name: dishName,
                dish_data: dishData,
                timestamp: new Date().toISOString()
            });
            favBtn.classList.add('active');
        }
        saveFavorites(favs);
    });
}

async function submitRequest() {
    await saveConfig();

    const userInputElement = document.getElementById('user_input');
    const userInput = userInputElement.value.trim();
    if (!userInput) {
        alert('请输入您的需求');
        return;
    }

    const primaryType = document.getElementById('primary_type').value;
    const primaryModel = document.getElementById('primary_model').value.trim();
    const primaryApiKey = document.getElementById('primary_apikey').value.trim();
    const primaryModelId = primaryType === 'deepseek'
        ? `deepseek:${primaryModel}|${primaryApiKey}`
        : primaryType === 'llamacpp'
            ? `llamacpp:${document.getElementById('primary_llamacpp_server').value.trim()}`
            : `ollama:${primaryModel}`;
    const useSecondary = document.getElementById('use_secondary').checked;
    let secondaryModelId = '';

    if (!primaryModel && primaryType !== 'llamacpp') {
        alert('请填写一级模型');
        return;
    }
    if (primaryType === 'deepseek' && !primaryApiKey) {
        alert('请选择 DeepSeek 作为一级模型时填写 API Key');
        return;
    }

    if (useSecondary) {
        const secondaryType = document.getElementById('secondary_type').value;
        if (secondaryType === 'deepseek') {
            const model = document.getElementById('deepseek_model').value.trim();
            const apiKey = document.getElementById('deepseek_apikey').value.trim();
            secondaryModelId = `deepseek:${model}|${apiKey}`;
        } else if (secondaryType === 'llamacpp') {
            const serverUrl = document.getElementById('secondary_llamacpp_server').value.trim();
            secondaryModelId = `llamacpp:${serverUrl}`;
        } else {
            const model = document.getElementById('ollama_model').value.trim();
            const serverAddr = document.getElementById('ollama_server').value.trim();
            secondaryModelId = `ollama:${model}|${serverAddr}`;
        }
    }

    if (!currentConversation) {
        createNewConversation(false);
    }

    if (!currentConversation.messages.length && currentConversation.title === '新对话') {
        currentConversation.title = buildConversationTitle(userInput);
    }
    currentConversation.isDraft = false;
    currentConversation.updatedAt = new Date().toISOString();
    renderHistory();

    const requestData = {
        user_input: userInput,
        personal_info: JSON.stringify(buildPersonalInfoPayload()),
        weather: currentWeather ? JSON.stringify(currentWeather) : '',
        primary_model_id: primaryModelId,
        secondary_model_id: secondaryModelId,
        use_secondary: useSecondary,
        recipe_profile: getRecipeProfile(),
        conversation_id: currentConversation.id,
        conversation_title: currentConversation.title,
        conversation_context: buildConversationContext(currentConversation.messages)
    };

    appendMessage('user', `<p>${renderPlainText(userInput)}</p>`);
    userInputElement.value = '';
    autoResizeTextarea(userInputElement);

    const loadingMessage = appendMessage('assistant', buildThinkingHtml(), { loading: true });

    try {
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(requestData)
        });
        const result = await response.json();

        if (!response.ok) {
            throw new Error(result.error || `请求失败: ${response.status}`);
        }
        if (result.error) {
            throw new Error(result.error);
        }

        const turn = {
            timestamp: new Date().toISOString(),
            user_input: userInput,
            local_output: result.local_output,
            cloud_output: result.cloud_output,
            interrupt_code: result.interrupt_code || '',
            interrupt_image: result.interrupt_image || '',
            conversation_id: currentConversation.id,
            conversation_title: currentConversation.title
        };

        currentConversation.messages.push(turn);
        currentConversation.updatedAt = turn.timestamp;
        const isInterrupt = isInterruptPayload(result.cloud_output, result.interrupt_code || '');
        if (isInterrupt) {
            loadingMessage.classList.add('interrupt-message');
        }
        loadingMessage.querySelector('.message-body').innerHTML = buildAssistantReply(
            result.local_output,
            result.cloud_output,
            result.interrupt_code || '',
            result.interrupt_image || ''
        );
        loadingMessage.classList.remove('loading');
        bindFeedbackButtons(loadingMessage);
        await loadHistory(currentConversation.key);
    } catch (error) {
        loadingMessage.querySelector('.message-body').innerHTML = `<p>${renderPlainText(`请求失败：${buildReadableError(error.message)}`)}</p>`;
        loadingMessage.classList.remove('loading');
    }

    scrollChatToBottom();
}

async function loadHistory(preferredKey = selectedConversationKey) {
    const historyList = document.getElementById('history_list');
    historyList.innerHTML = '<div class="history-empty">正在加载历史记录...</div>';

    try {
        const response = await fetch('/api/history?limit=200');
        if (!response.ok) {
            throw new Error(`读取历史记录失败: ${response.status}`);
        }

        const result = await response.json();
        historyConversations = normalizeHistoryConversations(Array.isArray(result.items) ? result.items : []);

        const selectedHistory = historyConversations.find((item) => item.key === preferredKey);
        if (selectedHistory) {
            currentConversation = cloneConversation(selectedHistory);
            selectedConversationKey = selectedHistory.key;
        } else if (currentConversation?.isDraft) {
            selectedConversationKey = currentConversation.key;
        } else if (historyConversations.length > 0) {
            currentConversation = cloneConversation(historyConversations[0]);
            selectedConversationKey = currentConversation.key;
        } else if (!currentConversation) {
            createNewConversation(false);
        }

        renderHistory();
        renderCurrentConversation();
    } catch (error) {
        historyList.innerHTML = `<div class="history-empty">加载失败：${escapeHtml(error.message)}</div>`;
    }
}

function normalizeHistoryConversations(items) {
    const conversationMap = new Map();

    items.forEach((record) => {
        const conversationId = (record.conversation_id || '').trim();
        const key = conversationId || `legacy:${record._log_file || 'unknown'}:${record._line_index ?? 0}`;
        if (!conversationMap.has(key)) {
            conversationMap.set(key, {
                key,
                id: conversationId,
                title: (record.conversation_title || record.user_input || '未命名对话').trim() || '未命名对话',
                messages: [],
                createdAt: record.timestamp || '',
                updatedAt: record.timestamp || '',
                deleteMeta: conversationId
                    ? { conversation_id: conversationId }
                    : { log_file: record._log_file || '', line_index: Number(record._line_index ?? -1) },
                isDraft: false
            });
        }

        const conversation = conversationMap.get(key);
        conversation.messages.push({
            timestamp: record.timestamp || '',
            user_input: record.user_input || '',
            local_output: record.local_output || '',
            cloud_output: record.cloud_output,
            interrupt_code: record.interrupt_code || record.cloud_output?.interrupt_code || '',
            interrupt_image: record.interrupt_image || record.cloud_output?.image_url || '',
            conversation_id: conversationId,
            conversation_title: record.conversation_title || conversation.title
        });

        if (record.timestamp && (!conversation.createdAt || new Date(record.timestamp) < new Date(conversation.createdAt))) {
            conversation.createdAt = record.timestamp;
        }
        if (record.timestamp && (!conversation.updatedAt || new Date(record.timestamp) > new Date(conversation.updatedAt))) {
            conversation.updatedAt = record.timestamp;
        }
        if (record.conversation_title && record.conversation_title.trim()) {
            conversation.title = record.conversation_title.trim();
        }
    });

    return Array.from(conversationMap.values())
        .map((conversation) => ({
            ...conversation,
            messages: conversation.messages.sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp))
        }))
        .sort((a, b) => new Date(b.updatedAt) - new Date(a.updatedAt));
}

function renderHistory() {
    const historyList = document.getElementById('history_list');
    const conversations = getRenderableConversations();
    if (!conversations.length) {
        historyList.innerHTML = '<div class="history-empty">暂无历史记录</div>';
        return;
    }

    const groups = groupConversationsByDate(conversations);
    historyList.innerHTML = groups.map((group) => `
        <div class="history-group">
            <div class="history-group-title">${escapeHtml(group.label)}</div>
            ${group.items.map((conversation) => `
                <div class="history-item ${conversation.key === selectedConversationKey ? 'active' : ''}" data-key="${escapeHtml(conversation.key)}">
                    <button type="button" class="history-main" data-key="${escapeHtml(conversation.key)}">
                        <div class="history-item-time">${escapeHtml(formatClock(conversation.updatedAt))}</div>
                        <div class="history-item-title">${escapeHtml(conversation.title || '未命名对话')}</div>
                        <div class="history-item-subtitle">${escapeHtml(buildConversationSummary(conversation))}</div>
                    </button>
                    <button type="button" class="history-delete" data-action="delete" data-key="${escapeHtml(conversation.key)}" ${conversation.isDraft ? 'disabled' : ''}>删除</button>
                </div>
            `).join('')}
        </div>
    `).join('');
}

function getRenderableConversations() {
    const conversations = historyConversations.slice();
    if (currentConversation?.isDraft && !conversations.some((item) => item.key === currentConversation.key)) {
        conversations.unshift(cloneConversation(currentConversation));
    }
    return conversations;
}

function groupConversationsByDate(conversations) {
    const groups = [];
    conversations.forEach((conversation) => {
        const label = conversation.isDraft && !conversation.messages.length ? '当前' : getDateGroupLabel(conversation.updatedAt);
        const currentGroup = groups[groups.length - 1];
        if (!currentGroup || currentGroup.label !== label) {
            groups.push({ label, items: [] });
        }
        groups[groups.length - 1].items.push(conversation);
    });
    return groups;
}

function handleHistoryClick(event) {
    const deleteButton = event.target.closest('[data-action="delete"]');
    if (deleteButton) {
        deleteConversation(deleteButton.dataset.key);
        return;
    }

    const mainButton = event.target.closest('.history-main');
    if (!mainButton) {
        return;
    }

    selectConversation(mainButton.dataset.key);
}

function selectConversation(key) {
    if (!key) {
        return;
    }

    if (currentConversation?.key === key && currentConversation.isDraft) {
        selectedConversationKey = key;
        renderHistory();
        renderCurrentConversation();
        return;
    }

    const selected = historyConversations.find((item) => item.key === key);
    if (!selected) {
        return;
    }

    currentConversation = cloneConversation(selected);
    selectedConversationKey = currentConversation.key;
    renderHistory();
    renderCurrentConversation();
}

async function deleteConversation(key) {
    const targetConversation = getRenderableConversations().find((item) => item.key === key);
    if (!targetConversation) {
        return;
    }

    if (targetConversation.isDraft) {
        createNewConversation(true);
        return;
    }

    const confirmed = window.confirm(`确认永久删除「${targetConversation.title || '未命名对话'}」吗？删除后无法恢复。`);
    if (!confirmed) {
        return;
    }

    const payload = targetConversation.id
        ? { conversation_id: targetConversation.id }
        : {
            log_file: targetConversation.deleteMeta?.log_file || '',
            line_index: targetConversation.deleteMeta?.line_index ?? -1
        };

    try {
        const response = await fetch('/api/history/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const result = await response.json();
        if (!response.ok || result.error) {
            throw new Error(result.error || `删除失败: ${response.status}`);
        }

        if (currentConversation?.key === key) {
            createNewConversation(false);
        }
        await loadHistory(selectedConversationKey);
    } catch (error) {
        alert(`删除失败：${buildReadableError(error.message)}`);
    }
}

function renderCurrentConversation() {
    const chatMessages = document.getElementById('chat_messages');
    chatMessages.innerHTML = '';

    if (!currentConversation || !currentConversation.messages.length) {
        appendMessage('assistant', `
            <p>你好，我是你的饮食助手。</p>
            <p>左侧可以先做快捷设置；点击“历史对话”按钮后，会展开独立历史面板查看和管理会话，不会挤占设置区域。</p>
        `);
        return;
    }

    currentConversation.messages.forEach((message) => {
        appendMessage('user', `<p>${renderPlainText(message.user_input || '')}</p>`);
        appendMessage(
            'assistant',
            buildAssistantReply(
                message.local_output,
                message.cloud_output,
                message.interrupt_code || '',
                message.interrupt_image || ''
            ),
            { interruptOnly: isInterruptPayload(message.cloud_output, message.interrupt_code || '') }
        );
    });
}

function cloneConversation(conversation) {
    return {
        ...conversation,
        deleteMeta: conversation.deleteMeta ? { ...conversation.deleteMeta } : null,
        messages: Array.isArray(conversation.messages) ? conversation.messages.map((message) => ({ ...message })) : []
    };
}

function buildConversationTitle(text) {
    const normalized = String(text || '').replace(/\s+/g, ' ').trim();
    if (!normalized) {
        return '新对话';
    }
    return normalized.length > 18 ? `${normalized.slice(0, 18)}...` : normalized;
}

function buildConversationSummary(conversation) {
    const lastMessage = conversation.messages[conversation.messages.length - 1];
    if (!lastMessage) {
        return conversation.isDraft ? '等待发送第一条消息' : '暂无摘要';
    }
    return formatHistorySummary(lastMessage.cloud_output, lastMessage.local_output, lastMessage.interrupt_code || '');
}

function buildConversationContext(messages) {
    return messages.slice(-6).map((message, index) => {
        const assistantText = buildAssistantContextText(
            message.local_output,
            message.cloud_output,
            message.interrupt_code || ''
        );
        return [
            `第${index + 1}轮用户：${message.user_input || ''}`,
            `第${index + 1}轮助手：${assistantText}`
        ].join('\n');
    }).join('\n\n');
}

function isInterruptPayload(cloudOutput, interruptCode = '') {
    return interruptCode === 'speechless'
        || (cloudOutput && typeof cloudOutput === 'object' && (
            cloudOutput.mode === 'interrupt' || cloudOutput.interrupt_code === 'speechless'
        ));
}

function buildAssistantContextText(localOutput, cloudOutput, interruptCode = '') {
    if (isInterruptPayload(cloudOutput, interruptCode)) {
        return '输入校验未通过，本轮未进入模型推理';
    }
    const sections = [];
    const primaryView = parsePrimaryDisplay(localOutput);
    if (typeof cloudOutput === 'string' && cloudOutput.trim()) {
        sections.push(`菜单回复：${cloudOutput.trim()}`);
    } else if (cloudOutput && typeof cloudOutput === 'object' && cloudOutput.mode !== 'only_local') {
        const mainDish = cloudOutput.主菜 || {};
        const sideDishNames = Array.isArray(cloudOutput.配菜)
            ? cloudOutput.配菜.map((item) => item?.菜名).filter(Boolean)
            : [];
        sections.push([
            mainDish.菜名,
            mainDish.食材,
            sideDishNames.length ? `配菜：${sideDishNames.join('、')}` : '',
            mainDish.推荐理由
        ].filter(Boolean).join('；'));
    }

    if (primaryView.optimizedPrompt) {
        sections.push(`优化提示词：${primaryView.optimizedPrompt}`);
    }

    if (primaryView.foodNames.length > 0) {
        sections.push(`食材推荐：${primaryView.foodNames.join('、')}`);
    }

    return sections.filter(Boolean).join('\n') || '无';
}

function buildPersonalInfoPayload() {
    return {
        age: document.getElementById('age').value.trim(),
        gender: document.getElementById('gender').value,
        height: document.getElementById('height').value.trim(),
        weight: document.getElementById('weight').value.trim(),
        occupation: document.getElementById('occupation').value.trim(),
        taste: document.getElementById('taste').value.trim(),
        health: document.getElementById('health').value.trim()
    };
}

function buildAssistantReply(localOutput, cloudOutput, interruptCode = '', interruptImage = '') {
    if (isInterruptPayload(cloudOutput, interruptCode)) {
        const imageUrl = interruptImage || cloudOutput?.image_url || '/image/speechless.webp';
        return buildInterruptReply(imageUrl);
    }

    const cards = [];
    const primaryView = parsePrimaryDisplay(localOutput);

    if (cloudOutput && typeof cloudOutput === 'object' && cloudOutput.mode !== 'only_local') {
        const mainDish = cloudOutput.主菜 || {};
        const sideDishes = Array.isArray(cloudOutput.配菜) ? cloudOutput.配菜.slice(0, 2) : [];
        const dishName = mainDish.菜名 || '';
        const dishData = escapeHtml(JSON.stringify({主菜: mainDish, 配菜: sideDishes}));
        cards.push(`
            <div class="reply-card feedback-card" data-dish-name="${escapeHtml(dishName)}" data-dish-data='${dishData}'>
                <h3>本次菜单建议</h3>
                <div class="reply-list">
                    <div class="reply-list-item"><strong>主菜：</strong>${escapeHtml(mainDish.菜名 || '-')}</div>
                    <div class="reply-list-item"><strong>主菜食材：</strong>${escapeHtml(mainDish.食材 || '-')}</div>
                    <div class="reply-list-item"><strong>主菜做法：</strong>${escapeHtml(mainDish.烹饪方式 || '-')}</div>
                    <div class="reply-list-item"><strong>主菜营养价值：</strong>${escapeHtml(mainDish.营养价值 || '-')}</div>
                    <div class="reply-list-item"><strong>主菜推荐理由：</strong>${escapeHtml(mainDish.推荐理由 || '-')}</div>
                    <div class="reply-list-item"><strong>配菜：</strong>${sideDishes.length ? sideDishes.map((item) => `${escapeHtml(item.菜名 || '-') }（${escapeHtml(item.食材 || '-')}）`).join('、') : '暂无配菜'}</div>
                </div>
                <div class="feedback-actions">
                    <button class="feedback-btn like-btn" title="赞"><span>👍</span> 赞</button>
                    <button class="feedback-btn dislike-btn" title="踩"><span>👎</span> 踩</button>
                    <button class="feedback-btn fav-btn" title="收藏"><span>⭐</span> 收藏</button>
                </div>
            </div>
        `);
    } else if (typeof cloudOutput === 'string' && cloudOutput.trim()) {
        cards.push(`
            <div class="reply-card">
                <h3>模型回复</h3>
                <p>${renderPlainText(cloudOutput)}</p>
            </div>
        `);
    } else {
        cards.push(`
            <div class="reply-card">
                <h3>二级模型状态</h3>
                <p>当前未启用二级模型，因此这次只返回了提示词优化结果，没有继续生成完整菜单。</p>
            </div>
        `);
    }

    cards.push(`
        <div class="reply-card">
            <h3>一级模型结果</h3>
            <div class="reply-list">
                <div class="reply-list-item"><strong>优化提示词：</strong>${renderInlineText(primaryView.optimizedPrompt || '暂无优化提示词')}</div>
                <div class="reply-list-item"><strong>食材推荐结果：</strong>${escapeHtml(primaryView.foodNames.length ? primaryView.foodNames.join('、') : '暂无食材推荐')}</div>
            </div>
        </div>
    `);

    return `
        <p>我已经根据你的输入整理好分析结果，下面是这次的回复。</p>
        ${cards.join('')}
    `;
}

function buildInterruptReply(imageUrl) {
    return `
        <div class="interrupt-only">
            <img src="${escapeHtml(imageUrl)}" alt="speechless" class="interrupt-image">
        </div>
    `;
}

function appendMessage(role, html, options = {}) {
    const chatMessages = document.getElementById('chat_messages');
    const message = document.createElement('div');
    message.className = `message ${role}${options.loading ? ' loading' : ''}`;
    if (options.interruptOnly) {
        message.classList.add('interrupt-message');
    }
    message.innerHTML = `
        <div class="message-bubble">
            <div class="message-role">${role === 'user' ? '你' : '饮食助手'}</div>
            <div class="message-body">${html}</div>
        </div>
    `;
    chatMessages.appendChild(message);
    scrollChatToBottom();
    return message;
}

function scrollChatToBottom() {
    const chatMessages = document.getElementById('chat_messages');
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function buildThinkingHtml() {
    return `
        <div class="thinking" aria-label="正在思考">
            <span class="thinking-dot"></span>
            <span class="thinking-dot"></span>
            <span class="thinking-dot"></span>
            <span>正在思考...</span>
        </div>
    `;
}

function renderWeatherResult(text) {
    document.getElementById('weather_result').textContent = text;
}

function buildWeatherSummary(weather) {
    if (!weather || !weather.now) {
        return '暂无天气数据';
    }

    const city = weather.location?.city || weather.location?.name || '未知城市';
    const now = weather.now || {};
    const forecast = Array.isArray(weather.forecasts) && weather.forecasts.length > 0
        ? weather.forecasts[0]
        : null;

    return [
        `城市：${city}`,
        `天气：${now.condition || '-'}，${now.temperature ?? '-'}°C，湿度 ${now.humidity ?? '-'}%`,
        `风力：${now.wind_dir || '-'} ${now.wind_class || ''}`.trim(),
        `空气质量：AQI ${now.air_quality?.aqi ?? '-'}`,
        forecast ? `明日趋势：${forecast.text_day || '-'}，${forecast.low ?? '-'}~${forecast.high ?? '-'}°C` : ''
    ].filter(Boolean).join('\n');
}

function formatHistorySummary(cloudOutput, localOutput, interruptCode = '') {
    const primaryView = parsePrimaryDisplay(localOutput);
    if (typeof cloudOutput === 'string' && cloudOutput.trim()) {
        return cloudOutput.trim();
    }
    if (cloudOutput && typeof cloudOutput === 'object') {
        if (isInterruptPayload(cloudOutput, interruptCode || cloudOutput.interrupt_code || '')) {
            return '输入校验未通过';
        }
        if (cloudOutput.mode === 'only_local') {
            return primaryView.foodNames.length > 0
                ? `食材推荐：${primaryView.foodNames.slice(0, 3).join('、')}`
                : '仅做了提示词优化';
        }
        const mainDish = cloudOutput.主菜 || {};
        return [
            mainDish.菜名,
            mainDish.推荐理由
        ].filter(Boolean).join(' | ') || primaryView.optimizedPrompt || '无摘要';
    }
    if (interruptCode === 'speechless') {
        return '输入校验未通过';
    }
    return primaryView.optimizedPrompt || '无摘要';
}

function parsePrimaryDisplay(localOutput) {
    const text = String(localOutput || '').trim();
    if (!text) {
        return { optimizedPrompt: '', foodNames: [] };
    }

    const optimizedPrompt = extractSingleLineSection(text, '优化提示词');
    const foodNames = extractRecommendedFoodNames(text);

    return {
        optimizedPrompt,
        foodNames
    };
}

function extractSingleLineSection(text, title) {
    const escapedTitle = title.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const regex = new RegExp(`${escapedTitle}：([^\\n]*)`);
    const match = text.match(regex);
    return match ? match[1].trim() : '';
}

function extractRecommendedFoodNames(text) {
    const names = [];
    const seen = new Set();
    const pushName = (value) => {
        const name = String(value || '').trim();
        if (!name || seen.has(name)) {
            return;
        }
        seen.add(name);
        names.push(name);
    };

    const bulletRegex = /^-\s*([^|\n]+?)\s*\|/gm;
    let bulletMatch = bulletRegex.exec(text);
    while (bulletMatch) {
        pushName(bulletMatch[1]);
        bulletMatch = bulletRegex.exec(text);
    }

    if (names.length === 0) {
        const inlineRegex = /食材=([^；\n]+)/g;
        let inlineMatch = inlineRegex.exec(text);
        while (inlineMatch) {
            pushName(inlineMatch[1]);
            inlineMatch = inlineRegex.exec(text);
        }
    }

    return names.slice(0, 8);
}

function getDateGroupLabel(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
        return '更早';
    }

    const now = new Date();
    const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const yesterdayStart = new Date(todayStart);
    yesterdayStart.setDate(yesterdayStart.getDate() - 1);
    const targetStart = new Date(date.getFullYear(), date.getMonth(), date.getDate());

    if (targetStart.getTime() === todayStart.getTime()) {
        return '今天';
    }
    if (targetStart.getTime() === yesterdayStart.getTime()) {
        return '昨天';
    }
    return date.toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric' });
}

function formatClock(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
        return '时间未知';
    }
    return date.toLocaleTimeString('zh-CN', { hour12: false, hour: '2-digit', minute: '2-digit' });
}

function handleComposerKeydown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        submitRequest();
    }
}

function autoResizeTextarea(textarea) {
    textarea.style.height = 'auto';
    textarea.style.height = `${Math.min(textarea.scrollHeight, 180)}px`;
}

function renderPlainText(text) {
    return escapeHtml(text == null ? '' : String(text)).replace(/\n/g, '<br>');
}

function renderInlineText(text) {
    return escapeHtml(text == null ? '' : String(text));
}

function buildReadableError(message) {
    if (!message) {
        return '未知错误';
    }
    if (message.includes('11434') || message.toLowerCase().includes('ollama')) {
        return `${message}。请先确认 Ollama 服务已启动，并且本地已安装所选模型。`;
    }
    return message;
}

function buildReadableWeatherError(data) {
    const message = data?.error || data?.message || data?.msg || '未知错误';
    if (message.includes('APP IP')) {
        return '百度天气 AK 的 IP 校验失败，请在百度地图开放平台检查 AK 的 IP 白名单配置';
    }
    return message;
}

function generateConversationId() {
    return `conv_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str == null ? '' : String(str);
    return div.innerHTML;
}
