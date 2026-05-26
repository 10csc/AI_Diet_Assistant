// ====== 工具函数 ======

/** HTML 转义 */
export function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str == null ? '' : String(str);
    return div.innerHTML;
}

/** 纯文本渲染（换行转 <br>） */
export function renderPlainText(text) {
    return escapeHtml(text == null ? '' : String(text)).replace(/\n/g, '<br>');
}

/** 内联文本渲染（仅转义） */
export function renderInlineText(text) {
    return escapeHtml(text == null ? '' : String(text));
}

/** 生成对话唯一 ID */
export function generateConversationId() {
    return `conv_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

/** 判断是否为中断/校验未通过负载 */
export function isInterruptPayload(cloudOutput, interruptCode = '') {
    return interruptCode === 'speechless'
        || (cloudOutput && typeof cloudOutput === 'object' && (
            cloudOutput.mode === 'interrupt' || cloudOutput.interrupt_code === 'speechless'
        ));
}

/** 构建可读性错误消息 */
export function buildReadableError(message) {
    if (!message) {
        return '未知错误';
    }
    if (message.includes('11434') || message.toLowerCase().includes('ollama')) {
        return `${message}。请先确认 Ollama 服务已启动，并且本地已安装所选模型。`;
    }
    return message;
}

/** 构建可读性天气错误消息 */
export function buildReadableWeatherError(data) {
    const message = data?.error || data?.message || data?.msg || '未知错误';
    if (message.includes('APP IP')) {
        return '百度天气 AK 的 IP 校验失败，请在百度地图开放平台检查 AK 的 IP 白名单配置';
    }
    return message;
}

/** 时间格式化：HH:mm */
export function formatClock(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
        return '时间未知';
    }
    return date.toLocaleTimeString('zh-CN', { hour12: false, hour: '2-digit', minute: '2-digit' });
}

/** 日期分组标签：今天/昨天/具体日期 */
export function getDateGroupLabel(value) {
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

/** 解析一级模型输出 */
export function parsePrimaryDisplay(localOutput) {
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

/** 提取单行段落内容 */
function extractSingleLineSection(text, title) {
    const escapedTitle = title.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const regex = new RegExp(`${escapedTitle}：([^\\n]*)`);
    const match = text.match(regex);
    return match ? match[1].trim() : '';
}

/** 提取推荐食材名称列表 */
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

/** 构建对话标题 */
export function buildConversationTitle(text) {
    const normalized = String(text || '').replace(/\s+/g, ' ').trim();
    if (!normalized) {
        return '新对话';
    }
    return normalized.length > 18 ? `${normalized.slice(0, 18)}...` : normalized;
}

/** 构建对话摘要 */
export function buildConversationSummary(conversation) {
    const lastMessage = conversation.messages[conversation.messages.length - 1];
    if (!lastMessage) {
        return conversation.isDraft ? '等待发送第一条消息' : '暂无摘要';
    }
    return formatHistorySummary(lastMessage.cloud_output, lastMessage.local_output, lastMessage.interrupt_code || '');
}

/** 构建对话上下文（最近 6 轮） */
export function buildConversationContext(messages) {
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

/** 构建助手侧上下文文本 */
export function buildAssistantContextText(localOutput, cloudOutput, interruptCode = '') {
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

/** 克隆会话对象（深拷贝 messages、deleteMeta） */
export function cloneConversation(conversation) {
    return {
        ...conversation,
        deleteMeta: conversation.deleteMeta ? { ...conversation.deleteMeta } : null,
        messages: Array.isArray(conversation.messages) ? conversation.messages.map((message) => ({ ...message })) : []
    };
}

/** 自动调整 textarea 高度 */
export function autoResizeTextarea(textarea) {
    textarea.style.height = 'auto';
    textarea.style.height = `${Math.min(textarea.scrollHeight, 180)}px`;
}

/** 滚动聊天区域到底部 */
export function scrollChatToBottom() {
    const chatMessages = document.getElementById('chat_messages');
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

/** 构建思考中 HTML */
export function buildThinkingHtml() {
    return `
        <div class="thinking" aria-label="正在思考">
            <span class="thinking-dot"></span>
            <span class="thinking-dot"></span>
            <span class="thinking-dot"></span>
            <span>正在思考...</span>
        </div>
    `;
}

/** 创建会话状态对象 */
export function createConversationState(overrides = {}) {
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

/** 格式化历史摘要文本 */
export function formatHistorySummary(cloudOutput, localOutput, interruptCode = '') {
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

/** 规范化历史对话记录 */
export function normalizeHistoryConversations(items) {
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
