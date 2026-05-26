// ====== 天气相关 ======

import state from './state.js';
import { buildReadableWeatherError } from './utils.js';
import { saveConfig, findSelectedCity, renderWeatherResult, buildWeatherSummary, populateWeatherCityOptions } from './config.js';

/** 加载城市列表 */
export async function loadWeatherCities() {
    try {
        const resp = await fetch('/api/weather/cities');
        const data = await resp.json();
        state.weatherCities = data.items || [];
    } catch (e) {
        console.warn('获取城市列表失败，已降级为空列表', e);
        state.weatherCities = [];
    }
    populateWeatherCityOptions();
}

/** 获取天气数据 */
export async function fetchWeather() {
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
            state.currentWeather = {
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
            renderWeatherResult(buildWeatherSummary(state.currentWeather));
            await saveConfig();
        } else {
            state.currentWeather = null;
            renderWeatherResult(`获取天气失败：${buildReadableWeatherError(data)}`);
        }
    } catch (error) {
        state.currentWeather = null;
        renderWeatherResult(`网络错误：${error.message}`);
    }
}
