// ====== 设置/配置管理 ======

import state, { WEATHER_BASE_URL } from './state.js';

/** 配置表单输入字段 ID 列表 */
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

/** 更新二级模型配置区域的可见性 */
export function updateSecondaryVisibility() {
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

/** 更新一级模型配置区域的可见性 */
export function updatePrimaryVisibility() {
    const primaryType = document.getElementById('primary_type');
    const primaryDeepseekConfig = document.getElementById('primary_deepseek_config');
    const primaryLlamacppConfig = document.getElementById('primary_llamacpp_config');
    const primaryModelInput = document.getElementById('primary_model');

    primaryDeepseekConfig.style.display = primaryType.value === 'deepseek' ? 'block' : 'none';
    primaryLlamacppConfig.style.display = primaryType.value === 'llamacpp' ? 'block' : 'none';
    primaryModelInput.placeholder = primaryType.value === 'deepseek' ? 'deepseek-v4-flash'
        : primaryType.value === 'llamacpp' ? '由服务端管理' : 'deepseek-r1:7b';
    if (primaryType.value === 'llamacpp') {
        primaryModelInput.value = 'llama.cpp';
    }
}

/** 切换设置面板 */
export function switchSettingsPanel(panelId) {
    document.querySelectorAll('.settings-tab').forEach((tab) => {
        tab.classList.toggle('active', tab.dataset.panel === panelId);
    });

    document.querySelectorAll('.settings-panel').forEach((panel) => {
        panel.classList.toggle('active', panel.id === panelId);
    });
}

/** 绑定表单变更自动保存 */
export function bindConfigAutoSave() {
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

/** 调度自动保存 */
export function scheduleConfigSave() {
    if (state.autoSaveTimer) {
        clearTimeout(state.autoSaveTimer);
    }

    state.autoSaveTimer = setTimeout(() => {
        saveConfig().catch((error) => {
            console.error('自动保存配置失败:', error);
        });
    }, 300);
}

/** 从 DOM 读取配置并构建 payload */
export function buildConfigPayload() {
    const primaryType = document.getElementById('primary_type').value;
    const secondaryType = document.getElementById('secondary_type').value;
    const selectedCity = findSelectedCity();

    const weatherAkInput = document.getElementById('weather_ak').value.trim();
    const primaryApiKeyInput = document.getElementById('primary_apikey').value.trim();
    const secondaryApiKeyInput = document.getElementById('deepseek_apikey').value.trim();
    const originalWeatherApi = state.loadedConfig.weather_api || {};
    const originalModels = state.loadedConfig.models || {};
    const originalSecondary = originalModels.secondary || {};

    // 只有用户主动输入时才写入 API Key，否则不传（后端保留旧值）
    const primaryApiKey = primaryType === 'deepseek' ? (primaryApiKeyInput || undefined) : '';
    const secondaryApiKey = secondaryApiKeyInput || undefined;
    const weatherAk = weatherAkInput || undefined;

    return {
        ...state.loadedConfig,
        weather_api: {
            ...originalWeatherApi,
            ak: weatherAk,
            district_id: selectedCity ? selectedCity.district_id : '',
            city_name: selectedCity ? selectedCity.city_name : '',
            location: selectedCity ? selectedCity.city_name : '',
            base_url: WEATHER_BASE_URL,
            cached_weather: state.currentWeather
        },
        models: {
            ...originalModels,
            primary: {
                ...(originalModels.primary || {}),
                type: primaryType,
                model: document.getElementById('primary_model').value.trim(),
                api_key: primaryApiKey
            },
            llamacpp: {
                ...(originalModels.llamacpp || {}),
                server_url: document.getElementById('primary_llamacpp_server').value.trim()
            },
            secondary: {
                ...originalSecondary,
                enabled: document.getElementById('use_secondary').checked,
                type: secondaryType,
                model: secondaryType === 'deepseek'
                    ? document.getElementById('deepseek_model').value.trim()
                    : document.getElementById('ollama_model').value.trim(),
                api_key: secondaryApiKey,
                ollama_server: document.getElementById('ollama_server').value.trim()
            }
        },
        user_profile: buildPersonalInfoPayload()
    };
}

/** 从 API 加载配置到表单 */
export async function loadConfigIntoForm() {
    try {
        const response = await fetch('/api/config');
        if (!response.ok) {
            throw new Error(`读取配置失败: ${response.status}`);
        }

        state.loadedConfig = await response.json();
        applyConfigToForm(state.loadedConfig);
    } catch (error) {
        console.error(error);
        state.loadedConfig = {};
    }
}

/** 将配置对象应用到表单控件 */
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

    // 脱敏后的值（"***"）在表单中显示为空，避免覆盖真实密钥
    const weatherAk = (!weatherApi.ak || weatherApi.ak === '***') ? '' : weatherApi.ak;
    document.getElementById('weather_ak').value = weatherAk;
    populateWeatherCityOptions(savedCity ? savedCity.district_id : '');

    const llamacpp = models.llamacpp || {};

    const primaryApiKey = (!primary.api_key || primary.api_key === '***') ? '' : primary.api_key;
    const secondaryApiKey = (!secondary.api_key || secondary.api_key === '***') ? '' : secondary.api_key;

    document.getElementById('primary_type').value = primary.type || 'deepseek';
    document.getElementById('primary_model').value = primary.model || 'deepseek-v4-flash';
    const primaryKeyField = document.getElementById('primary_apikey');
    primaryKeyField.value = primaryApiKey || '';
    primaryKeyField.placeholder = primaryApiKey ? 'sk-xxx' : (primary.api_key === '***' ? '*** 已配置，留空则保留' : 'sk-xxx');
    document.getElementById('primary_llamacpp_server').value = llamacpp.server_url || 'http://127.0.0.1:11435';

    document.getElementById('use_secondary').checked = Boolean(secondary.enabled);
    document.getElementById('secondary_type').value = secondary.type || 'deepseek';
    document.getElementById('deepseek_model').value = secondary.type === 'deepseek' ? (secondary.model || 'deepseek-v4-flash') : 'deepseek-v4-flash';
    document.getElementById('deepseek_apikey').value = secondaryApiKey;
    document.getElementById('ollama_model').value = secondary.type === 'ollama' ? (secondary.model || '') : '';
    document.getElementById('ollama_server').value = secondary.ollama_server || 'http://localhost:11434';
    document.getElementById('secondary_llamacpp_server').value = llamacpp.server_url || 'http://127.0.0.1:11435';

    if (weatherApi.cached_weather) {
        state.currentWeather = weatherApi.cached_weather;
        renderWeatherResult(buildWeatherSummary(state.currentWeather));
    } else {
        renderWeatherResult('等待获取天气...');
    }
}

/** 保存配置到 API */
export async function saveConfig() {
    const payload = buildConfigPayload();
    const response = await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload, null, 4)
    });

    if (!response.ok) {
        throw new Error(`保存配置失败: ${response.status}`);
    }

    state.loadedConfig = payload;
}

/** 构建个人信息 payload */
export function buildPersonalInfoPayload() {
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

/** 检测首次运行并显示设置向导 */
export function checkFirstRun() {
    const deepseekKey = document.getElementById('deepseek_apikey').value.trim();
    const weatherAk = document.getElementById('weather_ak').value.trim();
    const isFirstRun = !deepseekKey || deepseekKey === 'your_deepseek_api_key_here'
        || !weatherAk || weatherAk === 'your_baidu_api_key_here';

    if (isFirstRun) {
        const overlay = document.getElementById('setup_overlay');
        if (overlay) overlay.style.display = 'flex';
    }
}

/** 关闭设置向导 */
export function closeSetup() {
    const overlay = document.getElementById('setup_overlay');
    if (overlay) overlay.style.display = 'none';
}

/** 填充城市下拉选项 */
export function populateWeatherCityOptions(selectedDistrictId = '') {
    const citySelect = document.getElementById('weather_city');
    citySelect.innerHTML = '<option value="">请选择城市</option>';

    state.weatherCities.forEach((city) => {
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

/** 根据下拉框选中值查找城市 */
export function findSelectedCity() {
    const districtId = document.getElementById('weather_city').value;
    return state.weatherCities.find((item) => item.district_id === districtId) || null;
}

/** 从配置的天气信息中查找对应城市 */
export function findCityFromConfig(weatherApi) {
    if (!weatherApi) {
        return null;
    }

    if (weatherApi.district_id) {
        return state.weatherCities.find((item) => item.district_id === weatherApi.district_id) || null;
    }

    const fallbackLocation = (weatherApi.city_name || weatherApi.location || '').trim();
    if (!fallbackLocation) {
        return null;
    }

    return state.weatherCities.find((item) =>
        item.city_name === fallbackLocation ||
        item.display_name.includes(fallbackLocation)
    ) || null;
}

/** 渲染天气结果文本 */
export function renderWeatherResult(text) {
    document.getElementById('weather_result').textContent = text;
}

/** 构建天气摘要文本 */
export function buildWeatherSummary(weather) {
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
