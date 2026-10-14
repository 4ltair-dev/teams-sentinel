// ==UserScript==
// @name         Teams Sentinel Auto-Plus & Telegram Bridge
// @namespace    https://github.com/4ltair-dev/teams-sentinel
// @version      1.1
// @description  Автоматически ставит «+» и пишет «Здравствуйте» при перекличке в Teams, а также связывает чат с Telegram-ботом Sentinel
// @author       4ltair-dev
// @match        https://teams.microsoft.com/*
// @grant        GM_xmlhttpRequest
// @grant        GM_addStyle
// @connect      127.0.0.1
// @connect      localhost
// @run-at       document-idle
// ==/UserScript==

(function () {
    'use strict';

    const BRIDGE_URL = 'http://127.0.0.1:8765';

    // Настройки авто-плюса
    const PLUS_TIME_WINDOW_MS = 25000; // 25 секунд на сбор 3-4 плюсов
    const PLUS_COOLDOWN_MS = 90000;    // 90 секунд кулдауна
    let autoPlusThreshold = 3;
    let autoPlusEnabled = true;
    let recentPluses = []; // [{ author: string, time: number }]
    let lastSentPlusTime = 0;

    // Настройки авто-приветствия ("Здравствуйте")
    const GREETING_TIME_WINDOW_MS = 35000; // 35 секунд на сбор 3-4 приветствий
    const GREETING_COOLDOWN_MS = 180000;   // 3 минуты кулдауна (чтобы не здороваться дважды)
    let autoGreetingThreshold = 3;
    let autoGreetingEnabled = true;
    let recentGreetings = []; // [{ author: string, time: number }]
    let lastSentGreetingTime = 0;

    let isConnectedToBridge = false;

    console.log('[Teams Sentinel] Userscript v1.1 загружен.');

    // --- Индикатор статуса в интерфейсе Teams ---
    const badge = document.createElement('div');
    badge.id = 'teams-sentinel-badge';
    badge.innerHTML = `
        <div style="display:flex; align-items:center; gap:8px;">
            <span id="ts-dot" style="width:10px; height:10px; border-radius:50%; background:#9e9e9e; display:inline-block;"></span>
            <span style="font-weight:bold;">🛡️ Sentinel:</span>
            <span id="ts-status">Подключение...</span>
        </div>
    `;
    Object.assign(badge.style, {
        position: 'fixed',
        bottom: '15px',
        right: '15px',
        zIndex: '999999',
        background: 'rgba(20, 20, 25, 0.88)',
        backdropFilter: 'blur(8px)',
        color: '#ffffff',
        padding: '8px 14px',
        borderRadius: '20px',
        fontSize: '12px',
        fontFamily: 'Segoe UI, sans-serif',
        boxShadow: '0 4px 14px rgba(0,0,0,0.3)',
        border: '1px solid rgba(255,255,255,0.1)',
        cursor: 'default',
        transition: 'all 0.3s ease'
    });
    document.body.appendChild(badge);

    function updateBadge(connected, text) {
        const dot = document.getElementById('ts-dot');
        const status = document.getElementById('ts-status');
        if (dot && status) {
            dot.style.background = connected ? '#4caf50' : '#f44336';
            status.textContent = text;
        }
    }

    // --- Поиск элементов чата и поля ввода ---
    function findChatInput() {
        return (
            document.querySelector('div[data-tid="ckeditor"] div[role="textbox"]') ||
            document.querySelector('div[role="textbox"][contenteditable="true"]') ||
            document.querySelector('div[contenteditable="true"]') ||
            document.querySelector('textarea[data-tid="chat-input-textbox"]') ||
            document.querySelector('textarea')
        );
    }

    function findSendButton() {
        return (
            document.querySelector('button[data-tid="send-message-button"]') ||
            document.querySelector('button[aria-label="Отправить"]') ||
            document.querySelector('button[aria-label="Send"]') ||
            document.querySelector('button[aria-label="Отправить сообщение"]')
        );
    }

    // --- Отправка сообщения в чат Teams ---
    function sendMessageToChat(messageText) {
        const input = findChatInput();
        if (!input) {
            console.warn('[Teams Sentinel] Поле ввода чата не найдено!');
            return false;
        }

        input.focus();

        // Эмулируем вставку текста
        if (input.tagName.toLowerCase() === 'textarea' || input.tagName.toLowerCase() === 'input') {
            input.value = messageText;
            input.dispatchEvent(new Event('input', { bubbles: true }));
        } else {
            // ContentEditable (CKEditor в Teams)
            document.execCommand('selectAll', false, null);
            document.execCommand('insertText', false, messageText);
            input.dispatchEvent(new Event('input', { bubbles: true }));
        }

        setTimeout(() => {
            const sendBtn = findSendButton();
            if (sendBtn && !sendBtn.disabled) {
                sendBtn.click();
                console.log(`[Teams Sentinel] Сообщение «${messageText}» отправлено по клику кнопки.`);
            } else {
                // Эмуляция нажатия Enter
                const enterEvent = new KeyboardEvent('keydown', {
                    key: 'Enter',
                    code: 'Enter',
                    keyCode: 13,
                    which: 13,
                    bubbles: true,
                    cancelable: true
                });
                input.dispatchEvent(enterEvent);
                console.log(`[Teams Sentinel] Сообщение «${messageText}» отправлено по нажатию Enter.`);
            }
        }, 150);

        return true;
    }

    // --- Проверка типов сообщений ---
    function isPlusMessage(text) {
        if (!text) return false;
        const cleaned = text.trim().toLowerCase();
        return (
            cleaned === '+' ||
            cleaned === '++' ||
            cleaned === '+++' ||
            cleaned === '+1' ||
            cleaned === 'плюс' ||
            cleaned === 'плюсик' ||
            cleaned.startsWith('+ ')
        );
    }

    function isGreetingMessage(text) {
        if (!text) return false;
        const cleaned = text.trim().toLowerCase().replace(/[!.,?]/g, '');
        return (
            cleaned === 'здравствуйте' ||
            cleaned === 'здравствуй' ||
            cleaned === 'добрый день' ||
            cleaned === 'доброе утро' ||
            cleaned === 'добрый вечер' ||
            cleaned === 'привет' ||
            cleaned === 'приветствую' ||
            cleaned.startsWith('здравствуйте') ||
            cleaned.startsWith('добрый день')
        );
    }

    // --- Обработка новых сообщений в чате ---
    function handleIncomingMessage(author, text) {
        const now = Date.now();

        // 1. Проверка на "+"
        if (isPlusMessage(text)) {
            recentPluses = recentPluses.filter(p => (now - p.time) < PLUS_TIME_WINDOW_MS);

            if (!recentPluses.some(p => p.author === author)) {
                recentPluses.push({ author, time: now });
                console.log(`[Teams Sentinel] Плюс от «${author}». Уникальных: ${recentPluses.length}/${autoPlusThreshold}`);
            }

            if (autoPlusEnabled && recentPluses.length >= autoPlusThreshold) {
                if ((now - lastSentPlusTime) > PLUS_COOLDOWN_MS) {
                    lastSentPlusTime = now;
                    const authorList = recentPluses.map(p => p.author);
                    const count = recentPluses.length;
                    recentPluses = [];

                    console.warn(`[Teams Sentinel] 🚀 СРАБОТАЛ АВТО-ПЛЮС! (${count} чел: ${authorList.join(', ')})`);
                    sendMessageToChat('+');

                    reportEventToBridge({
                        type: 'auto_plus',
                        count: count,
                        authors: authorList
                    });
                }
            }
        }

        // 2. Проверка на приветствие ("Здравствуйте")
        if (isGreetingMessage(text)) {
            recentGreetings = recentGreetings.filter(g => (now - g.time) < GREETING_TIME_WINDOW_MS);

            if (!recentGreetings.some(g => g.author === author)) {
                recentGreetings.push({ author, time: now });
                console.log(`[Teams Sentinel] Приветствие от «${author}». Уникальных: ${recentGreetings.length}/${autoGreetingThreshold}`);
            }

            if (autoGreetingEnabled && recentGreetings.length >= autoGreetingThreshold) {
                if ((now - lastSentGreetingTime) > GREETING_COOLDOWN_MS) {
                    lastSentGreetingTime = now;
                    const authorList = recentGreetings.map(g => g.author);
                    const count = recentGreetings.length;
                    recentGreetings = [];

                    console.warn(`[Teams Sentinel] 👋 СРАБОТАЛО АВТО-ПРИВЕТСТВИЕ! (${count} чел: ${authorList.join(', ')})`);
                    sendMessageToChat('Здравствуйте!');

                    reportEventToBridge({
                        type: 'auto_greeting',
                        count: count,
                        authors: authorList
                    });
                }
            }
        }
    }

    // --- MutationObserver для наблюдения за чатом ---
    const chatObserver = new MutationObserver(mutations => {
        for (const m of mutations) {
            for (const node of m.addedNodes) {
                if (node.nodeType === Node.ELEMENT_NODE) {
                    const msgBodies = node.querySelectorAll ? node.querySelectorAll('[data-tid="chat-message-text"], [data-tid="message-body"], div[dir="auto"]') : [];
                    for (const body of msgBodies) {
                        const text = body.textContent || '';
                        if (isPlusMessage(text) || isGreetingMessage(text)) {
                            const msgContainer = body.closest('[data-tid="chat-message"]') || body.closest('div[role="listitem"]') || body.parentElement;
                            let author = 'Студент';
                            if (msgContainer) {
                                const authorEl = msgContainer.querySelector('[data-tid="message-author-name"], span[dir="auto"], h5');
                                if (authorEl && authorEl.textContent.trim()) {
                                    author = authorEl.textContent.trim();
                                }
                            }
                            handleIncomingMessage(author, text);
                        }
                    }
                }
            }
        }
    });

    chatObserver.observe(document.body, { childList: true, subtree: true });

    // --- Взаимодействие с локальным Sentinel WebBridge ---
    async function reportEventToBridge(eventData) {
        try {
            await fetch(`${BRIDGE_URL}/api/chat_event`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(eventData)
            });
        } catch (e) {
            console.error('[Teams Sentinel] Не удалось отправить событие в bridge:', e);
        }
    }

    async function pollBridge() {
        try {
            const chatTitle = document.title || 'Teams Meeting';
            await fetch(`${BRIDGE_URL}/api/heartbeat`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ chat_title: chatTitle })
            });

            // Проверяем исходящие команды из Telegram
            const res = await fetch(`${BRIDGE_URL}/api/outgoing`);
            if (res.ok) {
                const data = await res.json();
                if (data.messages && data.messages.length > 0) {
                    for (const msg of data.messages) {
                        console.log(`[Teams Sentinel] Отправка сообщения из Telegram: «${msg}»`);
                        sendMessageToChat(msg);
                    }
                }
            }

            // Статус настроек
            const statusRes = await fetch(`${BRIDGE_URL}/api/status`);
            if (statusRes.ok) {
                const s = await statusRes.json();
                autoPlusEnabled = s.auto_plus_enabled;
                autoPlusThreshold = s.auto_plus_threshold;
                autoGreetingEnabled = s.auto_greeting_enabled ?? true;
                autoGreetingThreshold = s.auto_greeting_threshold ?? 3;
                isConnectedToBridge = true;
                updateBadge(true, `В сети (+:${autoPlusEnabled ? 'ВКЛ' : 'ВЫКЛ'}, Привет:${autoGreetingEnabled ? 'ВКЛ' : 'ВЫКЛ'})`);
            }
        } catch (e) {
            isConnectedToBridge = false;
            updateBadge(false, 'Бот не запущен');
        }
    }

    // Опрос каждые 800 мс
    setInterval(pollBridge, 800);
    pollBridge();
})();
