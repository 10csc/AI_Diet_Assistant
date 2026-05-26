// ====== 历史对话管理 ======

import state from './state.js';
import {
    escapeHtml, formatClock, getDateGroupLabel, formatHistorySummary,
    cloneConversation, normalizeHistoryConversations, buildReadableError,
    buildConversationSummary
} from './utils.js';
import { renderCurrentConversation, createNewConversation } from './chat.js';

/** 打开历史侧边栏 */
export function openHistorySidebar() {
    state.historySidebarOpen = true;
    syncHistorySidebarState();
}

/** 关闭历史侧边栏 */
export function closeHistorySidebar() {
    state.historySidebarOpen = false;
    syncHistorySidebarState();
}

/** 同步侧边栏状态到 DOM */
export function syncHistorySidebarState() {
    const drawer = document.getElementById('history_sidebar_drawer');
    const backdrop = document.getElementById('history_sidebar_backdrop');
    drawer.classList.toggle('active', state.historySidebarOpen);
    backdrop.classList.toggle('active', state.historySidebarOpen);
    drawer.setAttribute('aria-hidden', state.historySidebarOpen ? 'false' : 'true');
    backdrop.setAttribute('aria-hidden', state.historySidebarOpen ? 'false' : 'true');
}

/** 全局键盘事件（Escape 关闭侧边栏） */
export function handleGlobalKeydown(event) {
    if (event.key === 'Escape' && state.historySidebarOpen) {
        closeHistorySidebar();
    }
}

/** 加载历史记录 */
export async function loadHistory(preferredKey = state.selectedConversationKey) {
    const historyList = document.getElementById('history_list');
    historyList.innerHTML = '<div class="history-empty">正在加载历史记录...</div>';

    try {
        const response = await fetch('/api/history?limit=200');
        if (!response.ok) {
            throw new Error(`读取历史记录失败: ${response.status}`);
        }

        const result = await response.json();
        state.historyConversations = normalizeHistoryConversations(Array.isArray(result.items) ? result.items : []);

        const selectedHistory = state.historyConversations.find((item) => item.key === preferredKey);
        if (selectedHistory) {
            state.currentConversation = cloneConversation(selectedHistory);
            state.selectedConversationKey = selectedHistory.key;
        } else if (state.currentConversation?.isDraft) {
            state.selectedConversationKey = state.currentConversation.key;
        } else if (state.historyConversations.length > 0) {
            state.currentConversation = cloneConversation(state.historyConversations[0]);
            state.selectedConversationKey = state.currentConversation.key;
        } else if (!state.currentConversation) {
            createNewConversation(false);
        }

        renderHistory();
        renderCurrentConversation();
    } catch (error) {
        historyList.innerHTML = `<div class="history-empty">加载失败：${escapeHtml(error.message)}</div>`;
    }
}

/** 渲染历史列表 */
export function renderHistory() {
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
                <div class="history-item ${conversation.key === state.selectedConversationKey ? 'active' : ''}" data-key="${escapeHtml(conversation.key)}">
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

/** 获取可渲染的对话列表（含当前草稿） */
export function getRenderableConversations() {
    const conversations = state.historyConversations.slice();
    if (state.currentConversation?.isDraft && !conversations.some((item) => item.key === state.currentConversation.key)) {
        conversations.unshift(cloneConversation(state.currentConversation));
    }
    return conversations;
}

/** 按日期分组对话 */
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

/** 历史列表点击处理 */
export function handleHistoryClick(event) {
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

/** 选择对话 */
export function selectConversation(key) {
    if (!key) {
        return;
    }

    if (state.currentConversation?.key === key && state.currentConversation.isDraft) {
        state.selectedConversationKey = key;
        renderHistory();
        renderCurrentConversation();
        return;
    }

    const selected = state.historyConversations.find((item) => item.key === key);
    if (!selected) {
        return;
    }

    state.currentConversation = cloneConversation(selected);
    state.selectedConversationKey = state.currentConversation.key;
    renderHistory();
    renderCurrentConversation();
}

/** 删除对话 */
export async function deleteConversation(key) {
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

        if (state.currentConversation?.key === key) {
            createNewConversation(false);
        }
        await loadHistory(state.selectedConversationKey);
    } catch (error) {
        alert(`删除失败：${buildReadableError(error.message)}`);
    }
}
