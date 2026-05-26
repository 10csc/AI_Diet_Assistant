// 全局状态管理
const state = {
    currentWeather: null,
    loadedConfig: {},
    autoSaveTimer: null,
    weatherCities: [],
    historyConversations: [],
    currentConversation: null,
    selectedConversationKey: '',
    historySidebarOpen: false
};

export const WEATHER_BASE_URL = 'https://api.map.baidu.com/weather/v1/';

export default state;
