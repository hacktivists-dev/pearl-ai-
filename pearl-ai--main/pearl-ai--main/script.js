// Initialize Lucide icons
lucide.createIcons();

let chatHistory = [];
let currentChatId = Date.now().toString();
const chatContainer = document.querySelector('#chat-container > div');
const userInput = document.getElementById('user-input');
const sendBtn = document.getElementById('send-btn');
const recentChatsList = document.getElementById('recent-chats-list');
const newChatBtn = document.getElementById('new-chat-btn');
const clearChatBtn = document.getElementById('clear-chat-btn');
const profileBtn = document.getElementById('profile-btn');
const userNameInput = document.getElementById('user-name-input');
const userAvatar = document.getElementById('user-avatar');
const micBtn = document.getElementById('mic-btn');

let recognition; // Declare recognition globally

async function appendMessage(role, content) {
    const wrapper = document.createElement('div');
    wrapper.className = `flex gap-6 animate-fade-in ${role === 'user' ? 'flex-row-reverse' : ''}`;
    
    const iconHTML = role === 'assistant' 
        ? `<div class="w-8 h-8 rounded-full border border-slate-200 flex items-center justify-center bg-white shrink-0 shadow-sm"><i data-lucide="sparkles" class="w-4 h-4 text-indigo-600"></i></div>`
        : `<div class="w-8 h-8 rounded-full border border-slate-200 flex items-center justify-center bg-white shrink-0 shadow-sm"><i data-lucide="user" class="w-4 h-4 text-slate-600"></i></div>`;

    wrapper.innerHTML = `
        ${iconHTML}
        <div class="space-y-4 ${role === 'user' ? 'message-user p-4 rounded-2xl max-w-[80%]' : 'flex-1 relative group/msg'}">
            <div class="prose prose-slate text-[15px] leading-relaxed text-slate-700">
            </div>
            ${role === 'assistant' ? `
            <button class="copy-btn absolute -top-2 right-0 p-1.5 opacity-0 group-hover/msg:opacity-100 hover:bg-slate-100 rounded-lg transition-all text-slate-400 hover:text-indigo-600" title="Copy response">
                <i data-lucide="copy" class="w-4 h-4"></i>
            </button>` : ''}
        </div>
    `;
    
    chatContainer.appendChild(wrapper);
    lucide.createIcons(); // Refresh icons for new messages

    const proseDiv = wrapper.querySelector('.prose');
    const scrollContainer = document.getElementById('chat-container');

    if (role === 'assistant') {
        let i = 0;
        return new Promise((resolve) => {
            function type() {
                if (i <= content.length) {
                    proseDiv.innerHTML = marked.parse(content.substring(0, i));
                    i += 3; // Typing 3 chars at a time for better flow
                    scrollContainer.scrollTop = scrollContainer.scrollHeight;
                    setTimeout(type, 15);
                } else {
                    proseDiv.innerHTML = marked.parse(content);
                    resolve();
                }
            }
            type();
        });
    } else {
        proseDiv.innerHTML = marked.parse(content);
        wrapper.scrollIntoView({ behavior: 'smooth' });
    }
}

async function sendMessage() {
    const text = userInput.value.trim();
    if (!text || sendBtn.disabled) return;

    sendBtn.disabled = true;
    sendBtn.style.opacity = '0.5';

    appendMessage('user', text);
    userInput.value = '';
    userInput.style.height = 'auto';

    // Add typing indicator
    const typingIndicator = document.createElement('div');
    typingIndicator.className = 'flex gap-6 animate-pulse';
    typingIndicator.id = 'typing-indicator';
    typingIndicator.innerHTML = `
        <div class="w-8 h-8 rounded-full border border-slate-200 flex items-center justify-center bg-white shrink-0 shadow-sm">
            <i data-lucide="sparkles" class="w-4 h-4 text-indigo-600"></i>
        </div>
        <div class="flex items-center">
            <span class="text-sm text-slate-400 italic">PearlAI is typing...</span>
        </div>
    `;
    chatContainer.appendChild(typingIndicator);
    lucide.createIcons();
    typingIndicator.scrollIntoView({ behavior: 'smooth' });

    try {
        const response = await fetch('/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text, history: chatHistory })
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(data.detail || data.message || `Server returned ${response.status}`);
        }
        if (!data.reply) {
            throw new Error('Server returned an empty reply.');
        }
        typingIndicator.remove(); // Remove indicator before starting typewriter effect
        await appendMessage('assistant', data.reply);
        
        chatHistory.push({ role: 'user', content: text }, { role: 'assistant', content: data.reply });
        saveChatSession();
        renderHistory();
    } catch (error) {
        typingIndicator.remove();
        appendMessage('assistant', `Error: ${error.message || 'Could not reach Pearl AI. Please check if the server is running.'}`);
    } finally {
        sendBtn.disabled = false;
        sendBtn.style.opacity = '1';
    }
}

function saveChatSession() {
    const allChats = JSON.parse(localStorage.getItem('pearl_chats') || '{}');
    allChats[currentChatId] = {
        id: currentChatId,
        timestamp: new Date().toISOString(),
        history: chatHistory,
        preview: chatHistory[0]?.content.substring(0, 30) + '...'
    };
    localStorage.setItem('pearl_chats', JSON.stringify(allChats));
}

function renderHistory() {
    const allChats = JSON.parse(localStorage.getItem('pearl_chats') || '{}');
    recentChatsList.innerHTML = '';
    
    const sortedChats = Object.values(allChats).sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
    
    if (sortedChats.length === 0) {
        recentChatsList.innerHTML = '<div class="px-3 py-2 text-xs text-slate-400 italic">No history yet...</div>';
        return;
    }

    sortedChats.forEach(chat => {
        const item = document.createElement('div');
        item.className = `px-3 py-2 text-sm text-slate-600 hover:bg-slate-100 rounded-lg cursor-pointer transition-colors truncate ${chat.id === currentChatId ? 'bg-slate-100 border-l-2 border-indigo-500' : ''}`;
        item.textContent = chat.preview || 'Empty Chat';
        item.onclick = () => loadChat(chat.id);
        recentChatsList.appendChild(item);
    });
}

function loadChat(id) {
    const allChats = JSON.parse(localStorage.getItem('pearl_chats') || '{}');
    const chat = allChats[id];
    if (!chat) return;

    currentChatId = id;
    chatHistory = chat.history;
    
    // Clear UI and reload messages
    chatContainer.innerHTML = '';
    chatHistory.forEach(msg => {
        const wrapper = document.createElement('div');
        wrapper.className = `flex gap-6 animate-fade-in ${msg.role === 'user' ? 'flex-row-reverse' : ''}`;
        wrapper.innerHTML = `
            <div class="w-8 h-8 rounded-full border border-slate-200 flex items-center justify-center bg-white shrink-0 shadow-sm">
                <i data-lucide="${msg.role === 'assistant' ? 'sparkles' : 'user'}" class="w-4 h-4 ${msg.role === 'assistant' ? 'text-indigo-600' : 'text-slate-600'}"></i>
            </div>
            <div class="space-y-4 ${msg.role === 'user' ? 'message-user p-4 rounded-2xl max-w-[80%]' : 'flex-1 relative group/msg'}">
                <div class="prose prose-slate text-[15px] leading-relaxed text-slate-700">${marked.parse(msg.content)}</div>
                ${msg.role === 'assistant' ? `
                <button class="copy-btn absolute -top-2 right-0 p-1.5 opacity-0 group-hover/msg:opacity-100 hover:bg-slate-100 rounded-lg transition-all text-slate-400 hover:text-indigo-600" title="Copy response">
                    <i data-lucide="copy" class="w-4 h-4"></i>
                </button>` : ''}
            </div>`;
        chatContainer.appendChild(wrapper);
    });
    lucide.createIcons();
    renderHistory();
}

newChatBtn.onclick = () => {
    currentChatId = Date.now().toString();
    chatHistory = [];
    chatContainer.innerHTML = '';
    renderHistory();
};

clearChatBtn.onclick = () => {
    if (confirm('Are you sure you want to clear all chat history?')) {
        localStorage.removeItem('pearl_chats');
        newChatBtn.onclick();
    }
};

sendBtn.addEventListener('click', sendMessage);
userInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

userInput.addEventListener('input', function() {
    this.style.height = 'auto';
    this.style.height = (this.scrollHeight) + 'px';
});

// Add event listener for copying messages
chatContainer.addEventListener('click', async (e) => {
    const copyBtn = e.target.closest('.copy-btn');
    if (!copyBtn) return;

    const messageContainer = copyBtn.closest('.group\\/msg');
    const textToCopy = messageContainer.querySelector('.prose').innerText;

    try {
        await navigator.clipboard.writeText(textToCopy);
        const icon = copyBtn.querySelector('i');
        icon.setAttribute('data-lucide', 'check');
        copyBtn.classList.add('text-emerald-500');
        copyBtn.classList.remove('text-slate-400');
        lucide.createIcons();

        setTimeout(() => {
            icon.setAttribute('data-lucide', 'copy');
            copyBtn.classList.remove('text-emerald-500');
            copyBtn.classList.add('text-slate-400');
            lucide.createIcons();
        }, 2000);
    } catch (err) {
        console.error('Failed to copy text: ', err);
    }
});

// Profile Persistence & Interaction
const savedName = localStorage.getItem('pearl_user_name');
if (savedName) {
    userNameInput.value = savedName;
    userAvatar.textContent = savedName.charAt(0).toUpperCase();
}

userNameInput.addEventListener('input', (e) => {
    const name = e.target.value.trim();
    localStorage.setItem('pearl_user_name', name);
    userAvatar.textContent = name ? name.charAt(0).toUpperCase() : 'U';
});

userNameInput.addEventListener('click', (e) => {
    e.stopPropagation();
    userNameInput.focus();
});

profileBtn.addEventListener('click', (e) => {
    // Only trigger if not clicking the input itself
    if (e.target.id !== 'user-name-input') {
        if (confirm('Would you like to logout?')) {
            localStorage.removeItem('pearl_session_active');
            window.location.href = '/login';
        }
    }
});

// Voice Input Feature
if ('SpeechRecognition' in window || 'webkitSpeechRecognition' in window) {
    recognition = new (window.SpeechRecognition || window.webkitSpeechRecognition)();
    recognition.continuous = false; // Listen for a single utterance
    recognition.interimResults = true; // Get interim results
    recognition.lang = 'en-US'; // Set language

    let isListening = false;

    micBtn.addEventListener('click', () => {
        if (isListening) {
            recognition.stop();
        } else {
            recognition.start();
        }
    });

    recognition.onstart = () => {
        isListening = true;
        micBtn.innerHTML = '<i data-lucide="mic-off" class="w-5 h-5 text-red-500"></i>';
        micBtn.title = 'Stop Voice Input';
        lucide.createIcons();
        userInput.placeholder = 'Listening...';
    };

    recognition.onresult = (event) => {
        let interimTranscript = '';
        let finalTranscript = '';

        for (let i = event.resultIndex; i < event.results.length; ++i) {
            if (event.results[i].isFinal) {
                finalTranscript += event.results[i][0].transcript;
            } else {
                interimTranscript += event.results[i][0].transcript;
            }
        }
        userInput.value = finalTranscript || interimTranscript;
        userInput.style.height = 'auto'; // Adjust height
        userInput.style.height = (userInput.scrollHeight) + 'px';
    };

    recognition.onend = () => {
        isListening = false;
        micBtn.innerHTML = '<i data-lucide="mic" class="w-5 h-5"></i>';
        micBtn.title = 'Voice Input';
        lucide.createIcons();
        userInput.placeholder = 'Message PearlAI...';
    };

    recognition.onerror = (event) => {
        console.error('Speech recognition error:', event.error);
        alert('Voice input error: ' + event.error);
        isListening = false;
        micBtn.innerHTML = '<i data-lucide="mic" class="w-5 h-5"></i>';
        micBtn.title = 'Voice Input';
        lucide.createIcons();
        userInput.placeholder = 'Message PearlAI...';
    };
} else {
    micBtn.style.display = 'none'; // Hide mic button if not supported
    console.warn('Web Speech API not supported in this browser.');
}

// Initial Load
renderHistory();
