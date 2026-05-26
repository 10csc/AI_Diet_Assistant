// ====== 聊天 UI 逻辑 ======

import state from './state.js';
import {
    escapeHtml, renderPlainText, renderInlineText, scrollChatToBottom,
    buildThinkingHtml, autoResizeTextarea, createConversationState,
    isInterruptPayload, buildConversationTitle, buildConversationContext,
    buildReadableError, parsePrimaryDisplay
} from './utils.js';
import { saveConfig, buildPersonalInfoPayload } from './config.js';
import { getRecipeProfile, bindFeedbackButtons } from './favorites.js';
import { loadHistory, renderHistory } from './history.js';

/** 创建新对话 */
export function createNewConversation(shouldRender = true) {
    state.currentConversation = createConversationState({ isDraft: true, title: '新对话' });
    state.selectedConversationKey = state.currentConversation.key;
    if (shouldRender) {
        renderHistory();
        renderCurrentConversation();
    }
}

/** 渲染当前对话到聊天区域 */
export function renderCurrentConversation() {
    const chatMessages = document.getElementById('chat_messages');
    chatMessages.innerHTML = '';

    if (!state.currentConversation || !state.currentConversation.messages.length) {
        appendMessage('assistant', `
            <p>你好，我是你的饮食助手。请告诉我你的想法。</p>
        `);
        return;
    }

    state.currentConversation.messages.forEach((message) => {
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

/** 构建助手回复 HTML */
export function buildAssistantReply(localOutput, cloudOutput, interruptCode = '', interruptImage = '') {
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

/** 构建中断回复（仅展示图片） */
function buildInterruptReply(imageUrl) {
    return `
        <div class="interrupt-only">
            <img src="${escapeHtml(imageUrl)}" alt="speechless" class="interrupt-image">
        </div>
    `;
}

/** 追加消息到聊天区域 */
export function appendMessage(role, html, options = {}) {
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

/** 发送消息请求 */
export async function submitRequest() {
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

    if (!state.currentConversation) {
        createNewConversation(false);
    }

    if (!state.currentConversation.messages.length && state.currentConversation.title === '新对话') {
        state.currentConversation.title = buildConversationTitle(userInput);
    }
    state.currentConversation.isDraft = false;
    state.currentConversation.updatedAt = new Date().toISOString();
    renderHistory();

    const requestData = {
        user_input: userInput,
        personal_info: JSON.stringify(buildPersonalInfoPayload()),
        weather: state.currentWeather ? JSON.stringify(state.currentWeather) : '',
        primary_model_id: primaryModelId,
        secondary_model_id: secondaryModelId,
        primary_api_key: primaryApiKey,
        secondary_api_key: useSecondary ? (document.getElementById('secondary_type').value === 'deepseek' ? document.getElementById('deepseek_apikey').value.trim() : '') : '',
        use_secondary: useSecondary,
        recipe_profile: getRecipeProfile(),
        conversation_id: state.currentConversation.id,
        conversation_title: state.currentConversation.title,
        conversation_context: buildConversationContext(state.currentConversation.messages)
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
            conversation_id: state.currentConversation.id,
            conversation_title: state.currentConversation.title
        };

        state.currentConversation.messages.push(turn);
        state.currentConversation.updatedAt = turn.timestamp;
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
        await loadHistory(state.currentConversation.key);
    } catch (error) {
        loadingMessage.querySelector('.message-body').innerHTML = `<p>${renderPlainText(`请求失败：${buildReadableError(error.message)}`)}</p>`;
        loadingMessage.classList.remove('loading');
    }

    scrollChatToBottom();
}

/** Enter 发送，Shift+Enter 换行 */
export function handleComposerKeydown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        submitRequest();
    }
}
