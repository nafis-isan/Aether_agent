<script setup lang="ts">
type User = {
  id: string;
  email: string;
  name: string;
};

type Conversation = {
  id: string;
  title: string;
  updated_at: string;
};

type ChatMessage = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
};

type AuthResponse = {
  access_token: string;
  user: User;
};

type ChatResponse = {
  conversation_id: string;
  reply: string;
  model: string;
  pending_approval_id?: string | null;
};

type ActivityEvent = {
  event_id: string;
  sequence: number;
  type: string;
  run_id: string;
  data: Record<string, unknown>;
};

type Approval = {
  id: string;
  tool_name: string;
  tool_arguments: Record<string, unknown>;
};

type Memory = {
  id: string;
  memory_type: 'preference' | 'fact' | 'context';
  content: string;
};

const runtimeConfig = useRuntimeConfig();
const apiBase = runtimeConfig.public.apiBase;
const wsBase = runtimeConfig.public.wsBase;
const token = useState<string | null>('aether-access-token', () => null);
const user = ref<User | null>(null);
const authMode = ref<'login' | 'register'>('login');
const email = ref('');
const password = ref('');
const name = ref('');
const conversations = ref<Conversation[]>([]);
const messages = ref<ChatMessage[]>([]);
const activeConversationId = ref<string | null>(null);
const draft = ref('');
const modelRole = ref<'general' | 'coding'>('general');
const busy = ref(false);
const errorMessage = ref('');
const backendStatus = ref<'checking' | 'connected' | 'unavailable'>('checking');
const backendHealthError = ref('');
const activityEvents = ref<ActivityEvent[]>([]);
const activityStatus = ref<'disconnected' | 'connecting' | 'connected'>('disconnected');
const eventCursors = ref<Record<string, number>>({});
const approvals = ref<Approval[]>([]);
const memories = ref<Memory[]>([]);
const memoryContent = ref('');
const memoryType = ref<Memory['memory_type']>('preference');
let activitySocket: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let activityGeneration = 0;
let reconnectAttempt = 0;

function getErrorMessage(error: unknown): string {
  if (typeof error === 'object' && error !== null && 'data' in error) {
    const data = error.data;
    if (typeof data === 'object' && data !== null && 'detail' in data && typeof data.detail === 'string') {
      return data.detail;
    }
  }
  return error instanceof Error ? error.message : 'Terjadi kesalahan yang tidak diketahui.';
}

async function checkBackend(): Promise<void> {
  try {
    await $fetch(`${apiBase}/health`);
    backendStatus.value = 'connected';
    backendHealthError.value = '';
  } catch (error) {
    backendStatus.value = 'unavailable';
    backendHealthError.value = getErrorMessage(error);
  }
}

async function authenticate(): Promise<void> {
  errorMessage.value = '';
  busy.value = true;
  try {
    if (authMode.value === 'register') {
      await $fetch<User>(`${apiBase}/auth/register`, {
        method: 'POST',
        body: { email: email.value, password: password.value, name: name.value }
      });
    }
    const result = await $fetch<AuthResponse>(`${apiBase}/auth/login`, {
      method: 'POST',
      body: { email: email.value, password: password.value }
    });
    token.value = result.access_token;
    user.value = result.user;
    password.value = '';
    await Promise.all([loadConversations(), loadApprovals(), loadMemories()]);
  } catch (error) {
    errorMessage.value = getErrorMessage(error);
  } finally {
    busy.value = false;
  }
}

function authHeaders(): Record<string, string> {
  if (!token.value) {
    throw new Error('Silakan login kembali untuk melanjutkan.');
  }
  return { Authorization: `Bearer ${token.value}` };
}

async function loadConversations(): Promise<void> {
  conversations.value = await $fetch<Conversation[]>(`${apiBase}/conversations`, {
    headers: authHeaders()
  });
  if (activeConversationId.value) {
    const selected = conversations.value.find((conversation) => conversation.id === activeConversationId.value);
    if (!selected) {
      activeConversationId.value = null;
      messages.value = [];
    }
  }
}

async function loadApprovals(): Promise<void> {
  if (!token.value) {
    approvals.value = [];
    return;
  }
  approvals.value = await $fetch<Approval[]>(`${apiBase}/approvals`, {
    headers: authHeaders()
  });
}

async function loadMemories(): Promise<void> {
  if (!token.value) {
    memories.value = [];
    return;
  }
  memories.value = await $fetch<Memory[]>(`${apiBase}/memory?active_only=true`, {
    headers: authHeaders()
  });
}

function openActivitySocket(generation: number): void {
  if (!token.value || !activeConversationId.value || generation !== activityGeneration) {
    return;
  }
  activityStatus.value = 'connecting';
  const cursor = encodeURIComponent(JSON.stringify(eventCursors.value));
  const url = `${wsBase.replace(/\/$/, '')}/ws/chat/${activeConversationId.value}?after=${cursor}`;
  const socket = new WebSocket(url, ['aether', `aether.bearer.${token.value}`]);
  activitySocket = socket;

  socket.onopen = () => {
    if (generation !== activityGeneration) {
      socket.close();
      return;
    }
    activityStatus.value = 'connected';
    reconnectAttempt = 0;
  };
  socket.onmessage = (message) => {
    if (generation !== activityGeneration) {
      return;
    }
    try {
      const event = JSON.parse(message.data) as ActivityEvent;
      eventCursors.value = {
        ...eventCursors.value,
        [event.run_id]: Math.max(eventCursors.value[event.run_id] || 0, event.sequence)
      };
      activityEvents.value = [...activityEvents.value, event].slice(-30);
      if (event.type === 'approval.required') {
        void loadApprovals().catch((error: unknown) => {
          errorMessage.value = getErrorMessage(error);
        });
      }
    } catch (error) {
      errorMessage.value = getErrorMessage(error);
    }
  };
  socket.onclose = (event: CloseEvent) => {
    if (generation !== activityGeneration) {
      return;
    }
    activitySocket = null;
    activityStatus.value = 'disconnected';
    if (event.code === 4401) {
      errorMessage.value = 'Sesi aktivitas berakhir. Silakan login kembali.';
      return;
    }
    if (event.code === 4404) {
      errorMessage.value = 'Percakapan tidak ditemukan atau tidak dapat diakses.';
      return;
    }
    const delay = Math.min(1000 * 2 ** reconnectAttempt, 15000);
    reconnectAttempt += 1;
    reconnectTimer = setTimeout(() => openActivitySocket(generation), delay);
  };
}

function disconnectActivity(resetCursor = true): void {
  activityGeneration += 1;
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  if (activitySocket) {
    const socket = activitySocket;
    activitySocket = null;
    socket.close();
  }
  activityStatus.value = 'disconnected';
  if (resetCursor) {
    eventCursors.value = {};
    activityEvents.value = [];
  }
}

function connectActivity(): void {
  disconnectActivity();
  reconnectAttempt = 0;
  if (token.value && activeConversationId.value) {
    openActivitySocket(activityGeneration);
  }
}

async function decideApproval(approval: Approval, approve: boolean): Promise<void> {
  errorMessage.value = '';
  busy.value = true;
  try {
    const result = await $fetch<ChatResponse>(`${apiBase}/approvals/${approval.id}/decision`, {
      method: 'POST',
      headers: authHeaders(),
      body: { approve }
    });
    await Promise.all([loadApprovals(), loadConversations()]);
    activeConversationId.value = result.conversation_id;
    await openConversation(result.conversation_id);
  } catch (error) {
    errorMessage.value = getErrorMessage(error);
  } finally {
    busy.value = false;
  }
}

async function saveMemory(): Promise<void> {
  const content = memoryContent.value.trim();
  if (!content || busy.value) {
    return;
  }
  errorMessage.value = '';
  busy.value = true;
  try {
    await $fetch(`${apiBase}/memory`, {
      method: 'POST',
      headers: authHeaders(),
      body: { memory_type: memoryType.value, content }
    });
    memoryContent.value = '';
    await loadMemories();
  } catch (error) {
    errorMessage.value = getErrorMessage(error);
  } finally {
    busy.value = false;
  }
}

async function deleteMemory(memory: Memory): Promise<void> {
  errorMessage.value = '';
  try {
    await $fetch(`${apiBase}/memory/${memory.id}`, {
      method: 'DELETE',
      headers: authHeaders()
    });
    memories.value = memories.value.filter((item) => item.id !== memory.id);
  } catch (error) {
    errorMessage.value = getErrorMessage(error);
  }
}

async function openConversation(conversationId: string): Promise<void> {
  errorMessage.value = '';
  busy.value = true;
  try {
    messages.value = await $fetch<ChatMessage[]>(
      `${apiBase}/conversations/${conversationId}/messages`,
      { headers: authHeaders() }
    );
    activeConversationId.value = conversationId;
  } catch (error) {
    errorMessage.value = getErrorMessage(error);
  } finally {
    busy.value = false;
  }
}

async function sendMessage(): Promise<void> {
  const message = draft.value.trim();
  if (!message || busy.value) {
    return;
  }
  errorMessage.value = '';
  busy.value = true;
  try {
    const response = await $fetch<ChatResponse>(`${apiBase}/chat`, {
      method: 'POST',
      headers: authHeaders(),
      body: {
        message,
        conversation_id: activeConversationId.value,
        model_role: modelRole.value
      }
    });
    activeConversationId.value = response.conversation_id;
    draft.value = '';
    await Promise.all([
      loadConversations(),
      openConversation(response.conversation_id),
      response.pending_approval_id ? loadApprovals() : Promise.resolve()
    ]);
  } catch (error) {
    errorMessage.value = getErrorMessage(error);
  } finally {
    busy.value = false;
  }
}

function signOut(): void {
  disconnectActivity();
  token.value = null;
  user.value = null;
  conversations.value = [];
  messages.value = [];
  activeConversationId.value = null;
  draft.value = '';
  password.value = '';
  memoryContent.value = '';
  errorMessage.value = '';
  approvals.value = [];
  memories.value = [];
}

watch(activeConversationId, () => {
  activityEvents.value = [];
  eventCursors.value = {};
});
watch([token, activeConversationId], connectActivity);
onMounted(checkBackend);
onBeforeUnmount(() => disconnectActivity());
</script>

<template>
  <main class="app-shell">
    <header class="topbar">
      <a class="brand" href="/">AETHER<span>.</span></a>
      <div class="topbar-right">
        <span class="backend-indicator" :class="backendStatus">
          <span class="indicator-dot" />
          {{ backendStatus === 'connected' ? 'Backend tersambung' : backendStatus === 'checking' ? 'Memeriksa backend' : 'Backend tidak tersedia' }}
        </span>
        <span v-if="backendHealthError" class="backend-error" :title="backendHealthError">{{ backendHealthError }}</span>
        <span v-if="user" class="user-label">{{ user.name }}</span>
        <button v-if="user" class="sign-out" type="button" @click="signOut">Keluar</button>
      </div>
    </header>

    <section v-if="!token" class="auth-layout">
      <div class="intro">
        <p class="eyebrow">PERSONAL AI WORKSPACE</p>
        <h1>Ide besar,<br /><span>mulai dari sini.</span></h1>
        <p class="intro-copy">Masuk untuk bercakap dengan Aether. Percakapan disimpan di akunmu dan diproses lewat model OpenRouter di backend.</p>
        <div class="model-chips"><span>Nemotron · General</span><span>North Mini Code · Coding</span></div>
      </div>

      <form class="auth-card" @submit.prevent="authenticate">
        <div class="auth-tabs">
          <button type="button" :class="{ active: authMode === 'login' }" @click="authMode = 'login'; errorMessage = ''">Masuk</button>
          <button type="button" :class="{ active: authMode === 'register' }" @click="authMode = 'register'; errorMessage = ''">Buat akun</button>
        </div>
        <h2>{{ authMode === 'login' ? 'Selamat datang kembali' : 'Mulai bersama Aether' }}</h2>
        <p class="card-copy">{{ authMode === 'login' ? 'Masuk untuk melanjutkan percakapanmu.' : 'Buat akun untuk memulai workspace pribadimu.' }}</p>
        <label v-if="authMode === 'register'" class="field-label">
          Nama
          <input v-model="name" autocomplete="name" maxlength="120" required placeholder="Nama kamu" />
        </label>
        <label class="field-label">
          Email
          <input v-model="email" autocomplete="email" type="email" required placeholder="kamu@email.com" />
        </label>
        <label class="field-label">
          Kata sandi
          <input v-model="password" :autocomplete="authMode === 'login' ? 'current-password' : 'new-password'" type="password" :minlength="authMode === 'register' ? 12 : 1" maxlength="128" required placeholder="Minimal 12 karakter" />
        </label>
        <p v-if="errorMessage" class="error-message" role="alert">{{ errorMessage }}</p>
        <button class="primary-button" type="submit" :disabled="busy">
          {{ busy ? 'Memproses...' : authMode === 'login' ? 'Masuk ke Aether' : 'Buat akun' }}
        </button>
        <p class="privacy-note">Token akses hanya disimpan sementara di memori tab ini.</p>
      </form>
    </section>

    <section v-else class="workspace">
      <aside class="sidebar">
        <button class="new-chat" type="button" :disabled="busy" @click="activeConversationId = null; messages = []; errorMessage = ''">
          <span>＋</span> Percakapan baru
        </button>
        <p class="sidebar-heading">RIWAYAT</p>
        <button
          v-for="conversation in conversations"
          :key="conversation.id"
          class="conversation-item"
          :class="{ selected: activeConversationId === conversation.id }"
          type="button"
          @click="openConversation(conversation.id)"
        >
          <span class="conversation-icon">◌</span>
          <span>{{ conversation.title }}</span>
        </button>
        <p v-if="conversations.length === 0" class="empty-history">Belum ada percakapan.</p>

        <p class="sidebar-heading">PERSETUJUAN</p>
        <article v-for="approval in approvals" :key="approval.id" class="sidebar-card">
          <p>{{ approval.tool_name === 'create_task' ? 'Buat tugas' : approval.tool_name }}</p>
          <span>{{ approval.tool_arguments.title || 'Tindakan memerlukan persetujuanmu.' }}</span>
          <div class="approval-actions">
            <button type="button" :disabled="busy" @click="decideApproval(approval, true)">Setujui</button>
            <button type="button" :disabled="busy" @click="decideApproval(approval, false)">Tolak</button>
          </div>
        </article>
        <p v-if="approvals.length === 0" class="sidebar-empty">Tidak ada tindakan yang menunggu.</p>

        <p class="sidebar-heading">MEMORY SAYA</p>
        <form class="memory-form" @submit.prevent="saveMemory">
          <select v-model="memoryType" aria-label="Jenis memory">
            <option value="preference">Preferensi</option>
            <option value="fact">Fakta</option>
            <option value="context">Konteks</option>
          </select>
          <textarea v-model="memoryContent" maxlength="2000" rows="2" placeholder="Simpan hal yang boleh diingat Aether..." />
          <button type="submit" :disabled="busy || !memoryContent.trim()">Simpan memory</button>
        </form>
        <article v-for="memory in memories" :key="memory.id" class="memory-item">
          <span>{{ memory.content }}</span>
          <button type="button" aria-label="Hapus memory" @click="deleteMemory(memory)">×</button>
        </article>
        <p v-if="memories.length === 0" class="sidebar-empty">Belum ada memory tersimpan.</p>
      </aside>

      <section class="chat-area">
        <div class="chat-heading">
          <div>
            <p class="eyebrow">AETHER ASSISTANT</p>
            <h1>{{ activeConversationId ? 'Percakapan' : 'Apa yang sedang kamu pikirkan?' }}</h1>
          </div>
          <label class="model-select-label">
            MODEL
            <select v-model="modelRole">
              <option value="general">Nemotron · General</option>
              <option value="coding">North Mini Code · Coding</option>
            </select>
          </label>
        </div>

        <section class="activity-panel" aria-live="polite">
          <div class="activity-heading">
            <span>AKTIVITAS AGENT</span>
            <span class="activity-status" :class="activityStatus">{{ activityStatus === 'connected' ? 'Live' : activityStatus === 'connecting' ? 'Menghubungkan' : 'Offline' }}</span>
          </div>
          <p v-if="activityEvents.length === 0" class="activity-empty">
            {{ activeConversationId ? 'Menunggu aktivitas percakapan...' : 'Aktivitas agent tampil setelah percakapan dimulai.' }}
          </p>
          <ul v-else class="activity-list">
            <li v-for="event in activityEvents.slice(-5)" :key="event.event_id">
              <span>{{ event.data.agent || 'Aether' }}</span>
              <span>{{ event.data.status || event.type }}</span>
            </li>
          </ul>
        </section>

        <div v-if="messages.length === 0" class="welcome-state">
          <div class="spark">✳</div>
          <h2>Mulai percakapan</h2>
          <p>Kirim pesan untuk mendapat jawaban dari model yang dipilih.</p>
        </div>
        <div v-else class="messages" aria-live="polite">
          <article v-for="message in messages" :key="message.id" class="message" :class="message.role">
            <div class="message-avatar">{{ message.role === 'assistant' ? 'A' : 'K' }}</div>
            <div class="message-content">
              <p class="message-author">{{ message.role === 'assistant' ? 'Aether' : 'Kamu' }}</p>
              <p class="message-text">{{ message.content }}</p>
            </div>
          </article>
        </div>

        <div class="composer-wrap">
          <p v-if="errorMessage" class="error-message chat-error" role="alert">{{ errorMessage }}</p>
          <form class="composer" @submit.prevent="sendMessage">
            <textarea v-model="draft" :disabled="busy" maxlength="12000" rows="2" placeholder="Tulis pesan untuk Aether..." @keydown.enter.exact.prevent="sendMessage" />
            <div class="composer-footer">
              <span>Jawaban AI dapat keliru. Periksa informasi penting.</span>
              <button class="send-button" type="submit" :disabled="busy || !draft.trim()">
                {{ busy ? 'Berpikir...' : 'Kirim ↑' }}
              </button>
            </div>
          </form>
        </div>
      </section>
    </section>
  </main>
</template>

<style>
:root {
  color-scheme: dark;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background: #080b10;
  color: #e7eaf0;
  font-synthesis: none;
  text-rendering: optimizeLegibility;
}

* { box-sizing: border-box; }
body { margin: 0; min-width: 320px; min-height: 100vh; }
button, input, textarea, select { font: inherit; }
button { cursor: pointer; }
button:disabled { cursor: not-allowed; opacity: 0.62; }

.app-shell { min-height: 100vh; background: radial-gradient(ellipse at 42% 0%, #131c2d 0, #080b10 53%); }
.topbar { height: 72px; display: flex; align-items: center; justify-content: space-between; padding: 0 5vw; border-bottom: 1px solid #ffffff0f; }
.brand { color: #f1f5f9; font-size: 15px; font-weight: 800; letter-spacing: 0.16em; text-decoration: none; }
.brand span { color: #6de0c1; }
.topbar-right { display: flex; align-items: center; gap: 20px; color: #9aa5b5; font-size: 12px; }
.backend-indicator { display: inline-flex; align-items: center; gap: 8px; }
.indicator-dot { width: 7px; height: 7px; border-radius: 50%; background: #d3a64e; }
.backend-indicator.connected .indicator-dot { background: #5bd6a4; }
.backend-indicator.unavailable .indicator-dot { background: #ec6c72; }
.backend-error { max-width: 260px; overflow: hidden; color: #ff9a9f; text-overflow: ellipsis; white-space: nowrap; }
.user-label { color: #dce3ed; }
.sign-out { padding: 7px 12px; border: 1px solid #ffffff20; border-radius: 8px; background: transparent; color: #dce3ed; }
.auth-layout { width: min(1120px, 90vw); min-height: calc(100vh - 72px); margin: auto; display: grid; grid-template-columns: 1.1fr 0.8fr; align-items: center; gap: 12%; padding: 55px 0; }
.eyebrow { color: #71dabe; font-size: 10px; font-weight: 700; letter-spacing: 0.19em; }
.intro h1 { margin: 22px 0; font-size: clamp(42px, 5.5vw, 72px); line-height: 1.06; letter-spacing: -0.055em; }
.intro h1 span { color: #87a2bd; }
.intro-copy, .card-copy { color: #9aa5b5; font-size: 14px; line-height: 1.8; }
.intro-copy { max-width: 440px; }
.model-chips { display: flex; flex-wrap: wrap; gap: 9px; margin-top: 30px; }
.model-chips span { padding: 9px 12px; border: 1px solid #ffffff14; border-radius: 999px; color: #bac6d3; font-size: 11px; }
.auth-card { padding: 30px; border: 1px solid #ffffff18; border-radius: 18px; background: #111722d9; box-shadow: 0 25px 80px #0005; }
.auth-tabs { display: grid; grid-template-columns: 1fr 1fr; gap: 5px; padding: 4px; border-radius: 10px; background: #090d13; }
.auth-tabs button { padding: 10px; border: 0; border-radius: 7px; background: transparent; color: #8d99a9; font-size: 12px; }
.auth-tabs button.active { background: #1c2633; color: #eef4fa; }
.auth-card h2 { margin: 26px 0 4px; font-size: 20px; letter-spacing: -0.03em; }
.card-copy { margin: 0 0 23px; font-size: 12px; }
.field-label { display: grid; gap: 8px; margin-top: 15px; color: #b6c0cd; font-size: 11px; }
.field-label input { width: 100%; padding: 12px 13px; border: 1px solid #ffffff18; border-radius: 9px; outline: none; background: #090d13; color: #f2f5f8; font-size: 13px; }
.field-label input:focus, .composer:focus-within { border-color: #65cfb0aa; }
.primary-button { width: 100%; margin-top: 23px; padding: 13px; border: 0; border-radius: 9px; background: #72dfbf; color: #07110e; font-weight: 700; font-size: 12px; }
.privacy-note { margin: 14px 0 0; color: #687485; text-align: center; font-size: 10px; }
.error-message { color: #ff9a9f; font-size: 12px; line-height: 1.5; }

.workspace { min-height: calc(100vh - 72px); display: grid; grid-template-columns: 250px minmax(0, 1fr); }
.sidebar { max-height: calc(100vh - 72px); overflow-y: auto; padding: 24px 14px; border-right: 1px solid #ffffff10; background: #0b0f16a8; }
.new-chat { width: 100%; padding: 11px 12px; border: 1px solid #ffffff20; border-radius: 9px; background: #121923; color: #e9eff5; text-align: left; font-size: 12px; }
.new-chat span { margin-right: 8px; color: #72dfbf; font-size: 17px; vertical-align: -1px; }
.sidebar-heading { margin: 28px 9px 12px; color: #687586; font-size: 9px; font-weight: 700; letter-spacing: 0.18em; }
.conversation-item { width: 100%; display: flex; align-items: center; gap: 9px; overflow: hidden; margin: 3px 0; padding: 10px 9px; border: 0; border-radius: 8px; background: transparent; color: #9da9b7; text-align: left; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; }
.conversation-item.selected, .conversation-item:hover { background: #17212d; color: #e5ecf2; }
.conversation-icon { color: #6bd9b9; }
.empty-history { padding: 0 9px; color: #687586; font-size: 11px; }
.sidebar-empty { margin: 0; padding: 0 9px; color: #687586; font-size: 10px; line-height: 1.5; }
.sidebar-card { margin: 8px 0; padding: 10px; border: 1px solid #ffffff14; border-radius: 9px; background: #111722; }
.sidebar-card p { margin: 0 0 5px; color: #e2e8ef; font-size: 11px; font-weight: 600; }
.sidebar-card > span { display: block; color: #929eac; font-size: 10px; line-height: 1.5; overflow-wrap: anywhere; }
.approval-actions { display: flex; gap: 7px; margin-top: 9px; }
.approval-actions button, .memory-form button { padding: 7px 9px; border: 1px solid #ffffff1c; border-radius: 7px; background: #18222e; color: #dce5ec; font-size: 9px; }
.approval-actions button:first-child, .memory-form button { border-color: #72dfbf55; color: #72dfbf; }
.memory-form { display: grid; gap: 7px; margin: 8px 0 10px; }
.memory-form select, .memory-form textarea { width: 100%; padding: 8px; border: 1px solid #ffffff18; border-radius: 7px; outline: none; background: #090d13; color: #dce5ec; font-size: 10px; }
.memory-form textarea { resize: vertical; line-height: 1.5; }
.memory-item { display: flex; align-items: flex-start; justify-content: space-between; gap: 6px; margin: 5px 0; padding: 8px; border-radius: 7px; background: #111722; color: #9da9b7; font-size: 10px; line-height: 1.5; }
.memory-item span { overflow-wrap: anywhere; }
.memory-item button { flex: 0 0 20px; border: 0; background: transparent; color: #9da9b7; font-size: 15px; }
.chat-area { min-width: 0; height: calc(100vh - 72px); display: flex; flex-direction: column; padding: 35px clamp(20px, 6vw, 90px) 25px; }
.chat-heading { display: flex; align-items: center; justify-content: space-between; gap: 20px; }
.chat-heading .eyebrow { margin: 0 0 9px; }
.chat-heading h1 { margin: 0; font-size: clamp(20px, 2.4vw, 29px); letter-spacing: -0.04em; }
.model-select-label { display: grid; gap: 6px; color: #6f7b8b; font-size: 8px; letter-spacing: 0.14em; }
.model-select-label select { min-width: 185px; padding: 9px 10px; border: 1px solid #ffffff20; border-radius: 8px; background: #111722; color: #dfe7ef; font-size: 10px; letter-spacing: normal; }
.activity-panel { width: min(850px, 100%); margin: 18px auto 0; padding: 10px 12px; border: 1px solid #ffffff10; border-radius: 9px; background: #0d131caa; }
.activity-heading { display: flex; align-items: center; justify-content: space-between; color: #738092; font-size: 8px; font-weight: 700; letter-spacing: 0.15em; }
.activity-status { letter-spacing: normal; text-transform: uppercase; }
.activity-status.connected { color: #72dfbf; }
.activity-status.connecting { color: #d3a64e; }
.activity-status.disconnected { color: #8792a0; }
.activity-empty { margin: 8px 0 0; color: #748092; font-size: 10px; }
.activity-list { display: grid; gap: 5px; margin: 8px 0 0; padding: 0; list-style: none; }
.activity-list li { display: flex; justify-content: space-between; gap: 12px; color: #aab4c0; font-size: 9px; }
.activity-list li span:last-child { color: #7e8a99; text-align: right; }
.welcome-state { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; padding-bottom: 30px; text-align: center; }
.spark { color: #72dfbf; font-size: 35px; }
.welcome-state h2 { margin: 15px 0 7px; font-size: 19px; }
.welcome-state p { margin: 0; color: #8591a0; font-size: 12px; }
.messages { flex: 1; overflow-y: auto; width: min(850px, 100%); margin: 35px auto 20px; padding: 0 7px; }
.message { display: flex; gap: 13px; margin: 0 0 27px; }
.message-avatar { flex: 0 0 28px; height: 28px; display: grid; place-items: center; border: 1px solid #ffffff20; border-radius: 9px; background: #151e29; color: #c6d2de; font-size: 10px; }
.message.assistant .message-avatar { border-color: #4cd7ae55; background: #10251f; color: #72dfbf; }
.message-content { min-width: 0; }
.message-author { margin: 0 0 7px; color: #9aa6b5; font-size: 10px; }
.message-text { margin: 0; color: #e2e8ef; font-size: 13px; line-height: 1.75; white-space: pre-wrap; overflow-wrap: anywhere; }
.composer-wrap { width: min(850px, 100%); margin: auto auto 0; }
.composer { padding: 13px 14px 10px; border: 1px solid #ffffff20; border-radius: 13px; background: #111722; }
.composer textarea { width: 100%; resize: vertical; min-height: 48px; max-height: 180px; border: 0; outline: none; background: transparent; color: #e9eff5; font-size: 12px; line-height: 1.6; }
.composer textarea::placeholder { color: #667383; }
.composer-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; color: #687586; font-size: 9px; }
.send-button { padding: 8px 12px; border: 0; border-radius: 7px; background: #72dfbf; color: #07110e; font-size: 10px; font-weight: 700; }
.chat-error { margin: 0 0 10px; }

@media (max-width: 760px) {
  .auth-layout { grid-template-columns: 1fr; gap: 30px; padding: 35px 0; }
  .intro h1 { font-size: 45px; }
  .intro-copy { font-size: 12px; }
  .workspace { grid-template-columns: 1fr; }
  .sidebar { max-height: 36vh; padding: 10px 14px; border-right: 0; border-bottom: 1px solid #ffffff10; }
  .sidebar-heading { margin: 14px 3px 8px; }
  .empty-history { display: none; }
  .new-chat { width: 100%; }
  .conversation-item { width: 100%; }
  .chat-area { height: calc(100vh - 36vh - 72px); min-height: 400px; padding: 18px 16px 16px; }
  .chat-heading { align-items: flex-start; }
  .chat-heading h1 { max-width: 210px; font-size: 19px; }
  .model-select-label select { min-width: 140px; max-width: 150px; }
  .activity-panel { margin-top: 14px; }
}
</style>
