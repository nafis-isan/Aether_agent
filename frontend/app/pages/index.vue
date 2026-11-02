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
  pending?: boolean;
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
  created_at: string;
  data: Record<string, unknown>;
};

type AgentDefinition = {
  name: string;
  description: string;
};

type AgentActivity = {
  id: string;
  name: string;
  description: string;
  status: 'idle' | 'thinking' | 'working' | 'approval' | 'completed' | 'error';
  isRouted?: boolean;
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
  importance: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

type WorkspaceView = 'chat' | 'memory';

type SpeechRecognitionResultLike = {
  isFinal: boolean;
  0: { transcript: string };
};

type SpeechRecognitionEventLike = {
  resultIndex: number;
  results: ArrayLike<SpeechRecognitionResultLike>;
};

type SpeechRecognitionLike = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onstart: (() => void) | null;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
};

type SpeechRecognitionConstructor = new () => SpeechRecognitionLike;

const runtimeConfig = useRuntimeConfig();
const apiBase = runtimeConfig.public.apiBase;
const wsBase = runtimeConfig.public.wsBase;
const token = useState<string | null>('aether-access-token', () => null);
const user = ref<User | null>(null);
const workspaceView = ref<WorkspaceView>('chat');
const conversationSearch = ref('');
const localAuthMode = ref(false);
const authModeLoaded = ref(false);
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
const agentDefinitions = ref<AgentDefinition[]>([]);
const activityStatus = ref<'disconnected' | 'connecting' | 'connected'>('disconnected');
const eventCursors = ref<Record<string, number>>({});
const approvals = ref<Approval[]>([]);
const memories = ref<Memory[]>([]);
const memoryContent = ref('');
const memoryType = ref<Memory['memory_type']>('preference');
const memoryImportance = ref(3);
const memorySearch = ref('');
const memoryCategoryFilter = ref<Memory['memory_type'] | 'all'>('all');
const showArchivedMemories = ref(false);
const pendingMessage = ref('');
const composerInput = ref<HTMLTextAreaElement | null>(null);
const speechRecognitionAvailable = ref(false);
const speechSynthesisAvailable = ref(false);
const isListening = ref(false);
const speakReplies = ref(true);
const voiceStatus = ref('');
let speechRecognition: SpeechRecognitionLike | null = null;
let voiceTranscript = '';
let voiceDraftPrefix = '';
let activitySocket: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let activityGeneration = 0;
let reconnectAttempt = 0;

const suggestedPrompts = [
  { category: 'Research', prompt: 'Bandingkan sumber dan temukan insight utama.' },
  { category: 'Coding', prompt: 'Tinjau kode ini dan bantu telusuri bug.' },
  { category: 'Produktivitas', prompt: 'Susun prioritas dan rencana kerja hari ini.' },
  { category: 'Umum', prompt: 'Bantu kembangkan ide yang sedang saya pikirkan.' }
];

const visibleMemories = computed(() => memories.value.filter((memory) => {
  const matchesStatus = showArchivedMemories.value || memory.is_active;
  const matchesQuery = memory.content.toLocaleLowerCase().includes(memorySearch.value.trim().toLocaleLowerCase());
  const matchesCategory = memoryCategoryFilter.value === 'all' || memory.memory_type === memoryCategoryFilter.value;
  return matchesStatus && matchesQuery && matchesCategory;
}));

const visibleConversations = computed(() => {
  const query = conversationSearch.value.trim().toLocaleLowerCase();
  return conversations.value.filter((conversation) => conversation.title.toLocaleLowerCase().includes(query));
});
const activeMemoryCount = computed(() => memories.value.filter((memory) => memory.is_active).length);
const archivedMemoryCount = computed(() => memories.value.length - activeMemoryCount.value);
const modelDetails = computed(() => modelRole.value === 'general'
  ? {
      name: 'Nemotron 3 Ultra',
      provider: 'NVIDIA · OpenRouter',
      purpose: 'Percakapan umum dan penalaran'
    }
  : {
      name: 'North Mini Code',
      provider: 'Cohere · OpenRouter',
      purpose: 'Pemrograman dan desain software'
    });
const displayMessages = computed<ChatMessage[]>(() => {
  if (!pendingMessage.value) return messages.value;
  return [
    ...messages.value,
    {
      id: 'pending-user-message',
      role: 'user',
      content: pendingMessage.value,
      created_at: new Date().toISOString(),
      pending: true
    },
    {
      id: 'pending-assistant-message',
      role: 'assistant',
      content: '',
      created_at: new Date().toISOString(),
      pending: true
    }
  ];
});

const currentRunEvents = computed(() => {
  const latestEvent = activityEvents.value.at(-1);
  if (!latestEvent) return [];
  return activityEvents.value
    .filter((event) => event.run_id === latestEvent.run_id)
    .sort((left, right) => left.sequence - right.sequence);
});

const currentRouteEvent = computed(() => currentRunEvents.value
  .filter((event) => event.type === 'agent.status' && event.data.status === 'routed')
  .at(-1));

const routedAgentId = computed(() => {
  const agentId = currentRouteEvent.value?.data.agent;
  return typeof agentId === 'string' ? agentId : null;
});

const currentRunStatus = computed(() => {
  const latestEvent = currentRunEvents.value.at(-1);
  if (!latestEvent) return 'Belum ada aktivitas';
  if (latestEvent.type === 'workflow.failed' || latestEvent.data.status === 'failed') return 'Gagal';
  if (latestEvent.data.status === 'waiting_approval') return 'Menunggu persetujuan';
  if (latestEvent.type === 'workflow.completed') return 'Selesai';
  if (latestEvent.type === 'agent.started' && latestEvent.data.agent === 'aether_core') return 'Core memproses';
  if (latestEvent.type === 'agent.started') return 'Agent bekerja';
  if (latestEvent.data.status === 'routed') return 'Agent dipilih';
  return latestEvent.type.replaceAll('.', ' ');
});

const agentActivities = computed<AgentActivity[]>(() => {
  const displayNames: Record<string, string> = {
    assistant: 'Assistant',
    researcher: 'Researcher',
    developer: 'Developer',
    productivity: 'Productivity Agent',
    document: 'Document Agent'
  };
  const coreEvents = currentRunEvents.value.filter((event) =>
    (event.type === 'agent.started' && event.data.agent === 'aether_core')
    || event.type === 'workflow.completed'
    || event.type === 'workflow.failed'
    || (event.type === 'agent.status' && event.data.status === 'routed')
  );
  const lastCoreEvent = coreEvents.at(-1);
  let coreStatus: AgentActivity['status'] = 'idle';
  if (lastCoreEvent?.type === 'agent.started') coreStatus = 'thinking';
  if (lastCoreEvent?.type === 'agent.status') coreStatus = 'completed';
  if (lastCoreEvent?.type === 'workflow.completed') coreStatus = 'completed';
  if (lastCoreEvent?.type === 'workflow.failed') coreStatus = 'error';

  const activities: AgentActivity[] = [{
    id: 'aether_core',
    name: 'Aether Core',
    description: 'Mengatur alur kerja dan memilih agent.',
    status: coreStatus,
    isRouted: false
  }];
  for (const agent of agentDefinitions.value) {
    const lastEvent = currentRunEvents.value
      .filter((event) => event.data.agent === agent.name)
      .at(-1);
    let agentStatus: AgentActivity['status'] = 'idle';
    if (lastEvent?.type === 'agent.started') agentStatus = 'working';
    if (lastEvent?.type === 'agent.completed') agentStatus = 'completed';
    if (lastEvent?.type === 'agent.status' && lastEvent.data.status === 'waiting_approval') agentStatus = 'approval';
    if (lastEvent?.type === 'workflow.failed' || lastEvent?.data.status === 'failed') agentStatus = 'error';
    activities.push({
      id: agent.name,
      name: displayNames[agent.name] || agent.name,
      description: agent.description,
      status: agentStatus,
      isRouted: routedAgentId.value === agent.name
    });
  }
  return activities;
});

const latestActivity = computed(() => currentRunEvents.value.slice(-4).reverse());

function agentDisplayName(agentId: unknown): string {
  if (typeof agentId !== 'string') return 'Agent';
  if (agentId === 'aether_core') return 'Aether Core';
  return agentActivities.value.find((agent) => agent.id === agentId)?.name || agentId;
}

function activityActor(event: ActivityEvent): string {
  if (event.type.startsWith('workflow.') || event.data.status === 'routed') return 'Aether Core';
  return agentDisplayName(event.data.agent);
}

function activityDescription(event: ActivityEvent): string {
  if (event.type === 'agent.started' && event.data.agent === 'aether_core') return 'Mulai menganalisis permintaan';
  if (event.data.status === 'routed') return `Memilih ${agentDisplayName(event.data.agent)}`;
  if (event.type === 'agent.started') return 'Mulai bekerja';
  if (event.type === 'agent.completed') return 'Menyelesaikan tugas';
  if (event.type === 'agent.status' && event.data.status === 'waiting_approval') return 'Menunggu persetujuan';
  if (event.type === 'approval.required') return 'Persetujuan tindakan diperlukan';
  if (event.type === 'workflow.completed') return 'Alur kerja selesai';
  if (event.type === 'workflow.failed') return 'Alur kerja gagal';
  return event.type.replaceAll('.', ' ');
}

function formatActivityTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat('id-ID', { hour: '2-digit', minute: '2-digit' }).format(date);
}

function formatMemoryDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat('id-ID', { dateStyle: 'medium' }).format(date);
}

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

async function initializeApplication(): Promise<void> {
  await checkBackend();
  if (backendStatus.value !== 'connected') {
    authModeLoaded.value = true;
    return;
  }
  try {
    const mode = await $fetch<{ local_auth: boolean }>(`${apiBase}/auth/mode`);
    localAuthMode.value = mode.local_auth;
    await loadAgents();
    if (mode.local_auth) {
      busy.value = true;
      user.value = await $fetch<User>(`${apiBase}/auth/me`);
      await Promise.all([loadConversations(), loadApprovals(), loadMemories()]);
    }
  } catch (error) {
    errorMessage.value = getErrorMessage(error);
  } finally {
    busy.value = false;
    authModeLoaded.value = true;
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
    await Promise.all([loadAgents(), loadConversations(), loadApprovals(), loadMemories()]);
  } catch (error) {
    errorMessage.value = getErrorMessage(error);
  } finally {
    busy.value = false;
  }
}

async function loadAgents(): Promise<void> {
  agentDefinitions.value = await $fetch<AgentDefinition[]>(`${apiBase}/agents`);
}

function authHeaders(): Record<string, string> {
  if (localAuthMode.value) {
    return {};
  }
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
  if (!token.value && !localAuthMode.value) {
    approvals.value = [];
    return;
  }
  approvals.value = await $fetch<Approval[]>(`${apiBase}/approvals`, {
    headers: authHeaders()
  });
}

async function loadMemories(): Promise<void> {
  if (!token.value && !localAuthMode.value) {
    memories.value = [];
    return;
  }
  memories.value = await $fetch<Memory[]>(`${apiBase}/memory?active_only=false`, {
    headers: authHeaders()
  });
}

function openActivitySocket(generation: number): void {
  if ((!token.value && !localAuthMode.value) || !activeConversationId.value || generation !== activityGeneration) {
    return;
  }
  activityStatus.value = 'connecting';
  const cursor = encodeURIComponent(JSON.stringify(eventCursors.value));
  const url = `${wsBase.replace(/\/$/, '')}/ws/chat/${activeConversationId.value}?after=${cursor}`;
  const protocols = localAuthMode.value
    ? ['aether', 'aether.local']
    : ['aether', `aether.bearer.${token.value}`];
  const socket = new WebSocket(url, protocols);
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
      activityEvents.value = [...activityEvents.value, event]
        .sort((left, right) => left.created_at.localeCompare(right.created_at)
          || (left.run_id === right.run_id ? left.sequence - right.sequence : 0))
        .slice(-30);
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
  if ((token.value || localAuthMode.value) && activeConversationId.value) {
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
      body: { memory_type: memoryType.value, content, importance: memoryImportance.value }
    });
    memoryContent.value = '';
    workspaceView.value = 'memory';
    await loadMemories();
  } catch (error) {
    errorMessage.value = getErrorMessage(error);
  } finally {
    busy.value = false;
  }
}

async function setMemoryActive(memory: Memory, isActive: boolean): Promise<void> {
  errorMessage.value = '';
  try {
    const updated = await $fetch<Memory>(`${apiBase}/memory/${memory.id}`, {
      method: 'PATCH',
      headers: authHeaders(),
      body: { is_active: isActive }
    });
    memories.value = memories.value.map((item) => item.id === updated.id ? updated : item);
  } catch (error) {
    errorMessage.value = getErrorMessage(error);
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
  pendingMessage.value = message;
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
    if (speakReplies.value) {
      speakReply(response.reply);
    }
    pendingMessage.value = '';
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
    pendingMessage.value = '';
    if (!isListening.value && !window.speechSynthesis?.speaking) {
      voiceStatus.value = '';
    }
  }
}

function startVoiceInput(): void {
  if (isListening.value) {
    speechRecognition?.stop();
    voiceStatus.value = 'Menyiapkan transkripsi…';
    return;
  }
  const Recognition = (window as Window & { SpeechRecognition?: SpeechRecognitionConstructor; webkitSpeechRecognition?: SpeechRecognitionConstructor }).SpeechRecognition
    || (window as Window & { webkitSpeechRecognition?: SpeechRecognitionConstructor }).webkitSpeechRecognition;
  if (!Recognition) {
    errorMessage.value = 'Browser ini belum mendukung input suara. Coba Chrome atau Edge versi terbaru.';
    return;
  }
  if (!window.isSecureContext) {
    errorMessage.value = 'Input suara memerlukan koneksi aman (HTTPS) atau localhost.';
    return;
  }

  errorMessage.value = '';
  voiceTranscript = '';
  voiceDraftPrefix = draft.value.trim();
  speechRecognition = new Recognition();
  speechRecognition.lang = 'id-ID';
  speechRecognition.continuous = true;
  speechRecognition.interimResults = true;
  speechRecognition.onstart = () => {
    isListening.value = true;
    voiceStatus.value = 'Mendengarkan… pilih tombol Selesai saat sudah selesai bicara.';
  };
  speechRecognition.onresult = (event) => {
    let finalText = '';
    let interimText = '';
    for (let index = 0; index < event.results.length; index += 1) {
      const result = event.results[index];
      if (result.isFinal) {
        finalText += result[0].transcript;
      } else {
        interimText += result[0].transcript;
      }
    }
    voiceTranscript = finalText.trim();
    const recognizedText = `${finalText}${interimText}`.trim();
    draft.value = [voiceDraftPrefix, recognizedText].filter(Boolean).join(' ');
  };
  speechRecognition.onerror = (event) => {
    const messages: Record<string, string> = {
      'not-allowed': 'Izin mikrofon ditolak. Izinkan akses mikrofon di pengaturan browser.',
      'service-not-allowed': 'Layanan pengenalan suara browser tidak diizinkan.',
      'audio-capture': 'Mikrofon tidak ditemukan atau sedang digunakan aplikasi lain.',
      'no-speech': 'Tidak ada ucapan yang terdeteksi. Tekan mikrofon dan coba lagi.',
      network: 'Layanan pengenalan suara tidak dapat dijangkau. Periksa koneksi internet.',
      aborted: 'Perekaman suara dihentikan.'
    };
    errorMessage.value = messages[event.error] || `Pengenalan suara gagal (${event.error}).`;
  };
  speechRecognition.onend = () => {
    isListening.value = false;
    speechRecognition = null;
    if (voiceTranscript) {
      draft.value = [voiceDraftPrefix, voiceTranscript].filter(Boolean).join(' ');
      voiceStatus.value = 'Mengirim transkripsi…';
      void sendMessage();
      return;
    }
    voiceStatus.value = '';
  };
  try {
    speechRecognition.start();
  } catch (error) {
    speechRecognition = null;
    errorMessage.value = error instanceof Error ? error.message : 'Tidak dapat memulai mikrofon.';
  }
}

function speakReply(text: string): void {
  if (!('speechSynthesis' in window)) {
    voiceStatus.value = 'Pembacaan suara tidak didukung browser ini.';
    return;
  }
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = 'id-ID';
  utterance.onstart = () => {
    voiceStatus.value = 'Aether sedang berbicara…';
  };
  utterance.onend = () => {
    voiceStatus.value = '';
  };
  utterance.onerror = () => {
    voiceStatus.value = 'Balasan suara gagal diputar.';
  };
  window.speechSynthesis.speak(utterance);
}

function toggleSpokenReplies(): void {
  speakReplies.value = !speakReplies.value;
  if (!speakReplies.value && 'speechSynthesis' in window) {
    window.speechSynthesis.cancel();
    voiceStatus.value = '';
  }
}

function initializeVoiceSupport(): void {
  const browserWindow = window as Window & { SpeechRecognition?: SpeechRecognitionConstructor; webkitSpeechRecognition?: SpeechRecognitionConstructor };
  speechRecognitionAvailable.value = Boolean(browserWindow.SpeechRecognition || browserWindow.webkitSpeechRecognition);
  speechSynthesisAvailable.value = 'speechSynthesis' in window;
}

function useSuggestedPrompt(prompt: string): void {
  draft.value = prompt;
  void nextTick(() => composerInput.value?.focus());
}

function signOut(): void {
  if (localAuthMode.value) {
    return;
  }
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
watch([token, activeConversationId, localAuthMode], connectActivity);
onMounted(() => {
  initializeVoiceSupport();
  void initializeApplication();
});
onBeforeUnmount(() => {
  disconnectActivity();
  speechRecognition?.stop();
  if ('speechSynthesis' in window) {
    window.speechSynthesis.cancel();
  }
});
</script>

<template>
  <main class="app-shell">
    <header class="topbar">
      <a class="brand" href="/" aria-label="Aether — beranda">
        <img src="/aether-wordmark.png" alt="Aether" />
      </a>
      <div class="topbar-right">
        <span class="backend-indicator" :class="backendStatus">
          <span class="indicator-dot" />
          {{ backendStatus === 'connected' ? 'Backend tersambung' : backendStatus === 'checking' ? 'Memeriksa backend' : 'Backend tidak tersedia' }}
        </span>
        <span v-if="backendHealthError" class="backend-error" :title="backendHealthError">{{ backendHealthError }}</span>
        <span v-if="user" class="user-label">{{ localAuthMode ? 'Mode lokal' : user.name }}</span>
        <button v-if="user && !localAuthMode" class="sign-out" type="button" @click="signOut">Keluar</button>
      </div>
    </header>

    <section v-if="!authModeLoaded" class="startup-state">
      <span class="spark">✳</span>
      <p>{{ backendStatus === 'unavailable' ? 'Backend Aether belum tersambung.' : 'Menghubungkan ke Aether...' }}</p>
      <p v-if="backendHealthError" class="error-message" role="alert">{{ backendHealthError }}</p>
    </section>

    <section v-else-if="!localAuthMode && !token" class="auth-layout">
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
          <span aria-hidden="true">＋</span> Percakapan baru
        </button>
        <nav class="workspace-nav" aria-label="Workspace">
          <button
            type="button"
            :class="{ selected: workspaceView === 'chat' }"
            @click="workspaceView = 'chat'"
          >
            <span aria-hidden="true">◌</span> Chat
          </button>
          <button
            type="button"
            :class="{ selected: workspaceView === 'memory' }"
            @click="workspaceView = 'memory'"
          >
            <span aria-hidden="true">◇</span> Memory
            <span class="nav-count">{{ activeMemoryCount }}</span>
          </button>
        </nav>

        <template v-if="workspaceView === 'chat'">
          <p class="sidebar-heading">RIWAYAT</p>
          <label class="conversation-search">
            <span class="visually-hidden">Cari percakapan</span>
            <input v-model="conversationSearch" type="search" placeholder="Cari percakapan…" />
          </label>
          <button
            v-for="conversation in visibleConversations"
            :key="conversation.id"
            class="conversation-item"
            :class="{ selected: activeConversationId === conversation.id }"
            type="button"
            @click="openConversation(conversation.id)"
          >
            <span class="conversation-icon" aria-hidden="true">◌</span>
            <span>{{ conversation.title }}</span>
          </button>
          <p v-if="conversations.length === 0" class="empty-history">Belum ada percakapan.</p>
          <p v-else-if="visibleConversations.length === 0" class="empty-history">Tidak ada percakapan yang cocok.</p>

          <div class="sidebar-section-heading">
            <p class="sidebar-heading">PERSETUJUAN</p>
            <span v-if="approvals.length" class="nav-count">{{ approvals.length }}</span>
          </div>
          <article v-for="approval in approvals" :key="approval.id" class="sidebar-card">
            <p>{{ approval.tool_name === 'create_task' ? 'Buat tugas' : approval.tool_name }}</p>
            <span>{{ approval.tool_arguments.title || 'Tindakan memerlukan persetujuanmu.' }}</span>
            <div class="approval-actions">
              <button type="button" :disabled="busy" @click="decideApproval(approval, true)">Setujui</button>
              <button type="button" :disabled="busy" @click="decideApproval(approval, false)">Tolak</button>
            </div>
          </article>
          <p v-if="approvals.length === 0" class="sidebar-empty">Tidak ada tindakan yang menunggu.</p>
        </template>
      </aside>

      <section v-if="workspaceView === 'chat'" class="chat-area">
        <div v-if="activeConversationId" class="chat-heading">
          <div>
            <p class="eyebrow">AETHER / CONVERSATION</p>
            <h1>{{ conversations.find((item) => item.id === activeConversationId)?.title || 'Percakapan' }}</h1>
          </div>
        </div>

        <div class="chat-body" :class="{ 'welcome-chat': displayMessages.length === 0 }">
          <section class="conversation-workspace" aria-label="Percakapan dengan Aether">
            <div v-if="displayMessages.length === 0" class="welcome-state">
              <div class="welcome-intro">
                <img class="welcome-mark" src="/aether-monogram.png" alt="" />
                <h2>Selamat datang,<br /><span>aku Aether.</span></h2>
                <p>Apa yang bisa kubantu hari ini?</p>
              </div>
              <div class="prompt-grid" aria-label="Saran percakapan">
                <button
                  v-for="suggestion in suggestedPrompts"
                  :key="suggestion.category"
                  class="prompt-card"
                  type="button"
                  :title="suggestion.prompt"
                  @click="useSuggestedPrompt(suggestion.prompt)"
                >
                  <span class="prompt-icon" aria-hidden="true">{{ { Research: '⌕', Coding: '</>', Produktivitas: '◷', Umum: '✳' }[suggestion.category] }}</span>
                  {{ suggestion.category }}
                </button>
              </div>
            </div>
            <div v-else class="messages" aria-live="polite" :aria-busy="busy">
              <article
                v-for="message in displayMessages"
                :key="message.id"
                class="message"
                :class="[message.role, { pending: message.pending }]"
              >
                <div class="message-avatar">{{ message.role === 'assistant' ? 'A' : 'K' }}</div>
                <div class="message-content">
                  <p class="message-author">{{ message.role === 'assistant' ? 'Aether' : 'Kamu' }}<span v-if="message.pending && message.role === 'assistant'" class="thinking-label">Sedang berpikir</span></p>
                  <p v-if="message.content" class="message-text">{{ message.content }}</p>
                  <p v-else-if="message.pending" class="thinking-placeholder"><span />Agent sedang menyiapkan respons…</p>
                </div>
              </article>
            </div>

            <div class="composer-wrap">
              <p v-if="errorMessage" class="error-message chat-error" role="alert">{{ errorMessage }}</p>
              <form class="composer" @submit.prevent="sendMessage">
                <textarea ref="composerInput" v-model="draft" :disabled="busy" maxlength="12000" rows="2" aria-label="Pesan untuk Aether" placeholder="Tulis pesan untuk Aether..." @keydown.enter.exact.prevent="sendMessage" />
                <div class="composer-footer">
                  <span>{{ busy ? 'Permintaan sedang diproses · Respons tidak di-stream.' : 'Enter untuk mengirim · Shift + Enter untuk baris baru' }}</span>
                  <div class="composer-actions">
                    <label class="inline-model-select">
                      <span class="visually-hidden">Pilih model · {{ modelDetails.provider }}</span>
                      <select v-model="modelRole" :aria-label="`Model ${modelDetails.name}, ${modelDetails.purpose}`">
                        <option value="general">Nemotron · General</option>
                        <option value="coding">North Mini Code · Coding</option>
                      </select>
                    </label>
                    <button
                      class="voice-toggle"
                      type="button"
                      :disabled="!speechSynthesisAvailable"
                      :aria-pressed="speakReplies"
                      :title="speechSynthesisAvailable ? (speakReplies ? 'Matikan balasan suara' : 'Aktifkan balasan suara') : 'Balasan suara tidak didukung browser ini'"
                      @click="toggleSpokenReplies"
                    >
                      {{ speakReplies ? 'Suara aktif' : 'Suara mati' }}
                    </button>
                    <button
                      class="voice-button"
                      :class="{ listening: isListening }"
                      type="button"
                      :disabled="busy || !speechRecognitionAvailable"
                      :aria-label="isListening ? 'Selesai merekam suara' : 'Mulai input suara'"
                      :title="speechRecognitionAvailable ? (isListening ? 'Selesai bicara' : 'Bicara ke Aether') : 'Input suara tidak didukung browser ini'"
                      @click="startVoiceInput"
                    >
                      {{ isListening ? 'Selesai ■' : 'Mikrofon' }}
                    </button>
                    <button class="send-button" type="submit" :disabled="busy || !draft.trim()">
                      {{ busy ? 'Memproses…' : 'Kirim ↑' }}
                    </button>
                  </div>
                </div>
              </form>
              <p v-if="voiceStatus" class="voice-status" role="status" aria-live="polite">{{ voiceStatus }}</p>
              <p class="voice-privacy">
                {{ speechRecognitionAvailable ? 'Mikrofon hanya aktif saat tombol ditekan. Pengenalan ucapan menggunakan layanan browser.' : 'Input suara tidak didukung browser ini. Coba Chrome atau Edge terbaru.' }}
              </p>
            </div>
          </section>

          <aside class="agent-workspace" aria-labelledby="agent-workspace-title">
            <div class="activity-heading">
              <div>
                <p class="eyebrow">SYSTEM / AGENTS</p>
                <h2 id="agent-workspace-title">Execution</h2>
              </div>
              <span class="activity-status" :class="activityStatus">
                <span class="connection-dot" aria-hidden="true" />
                {{ activityStatus === 'connected' ? 'Live' : activityStatus === 'connecting' ? 'Linking' : activeConversationId ? 'Offline' : 'Standby' }}
              </span>
            </div>

            <div class="run-overview">
              <span class="run-kicker">CURRENT RUN</span>
              <strong>{{ currentRunStatus }}</strong>
              <span v-if="currentRunEvents.length">RUN / {{ currentRunEvents[0].run_id.slice(0, 8) }}</span>
              <span v-else>{{ activeConversationId ? 'Menunggu event percakapan.' : 'Belum ada run.' }}</span>
            </div>

            <div class="orchestration-path" aria-label="Alur routing agent">
              <div class="orchestration-node">
                <span class="route-node-label">ORCHESTRATOR</span>
                <div class="orchestration-identity">
                  <span class="agent-indicator" :class="agentActivities[0]?.status" aria-hidden="true" />
                  <strong>Aether Core</strong>
                </div>
                <span class="orchestration-state">{{ agentActivities[0]?.status === 'thinking' ? 'Menganalisis permintaan' : routedAgentId ? 'Routing selesai' : 'Menunggu routing' }}</span>
              </div>

              <div class="orchestration-connector" aria-hidden="true" />

              <div class="orchestration-node worker-node" :class="{ 'route-node-selected': routedAgentId }">
                <span class="route-node-label">ROUTED WORKER</span>
                <div class="orchestration-identity">
                  <span v-if="routedAgentId" class="agent-indicator" :class="agentActivities.find((agent) => agent.id === routedAgentId)?.status" aria-hidden="true" />
                  <strong>{{ routedAgentId ? agentDisplayName(routedAgentId) : 'Belum dipilih' }}</strong>
                </div>
                <span class="orchestration-state">{{ routedAgentId ? 'Dipilih oleh Aether Core' : 'Menunggu event routing' }}</span>
              </div>
            </div>

            <div class="agent-directory">
              <p class="agent-list-label">AVAILABLE WORKERS</p>
              <ul class="agent-list">
                <li
                  v-for="agent in agentActivities.filter((item) => item.id !== 'aether_core')"
                  :key="agent.id"
                  class="agent-row"
                  :class="{ 'selected-agent': agent.isRouted }"
                  :aria-current="agent.isRouted ? 'step' : undefined"
                  :title="agent.description"
                >
                  <span class="agent-indicator" :class="agent.status" aria-hidden="true" />
                  <span class="agent-name">{{ agent.name }}</span>
                  <span class="agent-state" :class="agent.status">
                    {{ { idle: 'Idle', thinking: 'Thinking', working: 'Working', approval: 'Approval', completed: 'Done', error: 'Error' }[agent.status] }}
                  </span>
                </li>
              </ul>
            </div>

            <div v-if="latestActivity.length" class="event-trail" aria-label="Aktivitas terkini">
              <p class="agent-list-label">EVENT LOG</p>
              <ol>
                <li v-for="event in latestActivity" :key="event.event_id">
                  <time :datetime="event.created_at">{{ formatActivityTime(event.created_at) }}</time>
                  <span class="event-actor">{{ activityActor(event) }}</span>
                  <span>{{ activityDescription(event) }}</span>
                </li>
              </ol>
            </div>
          </aside>
        </div>
      </section>

      <section v-else class="memory-workspace" aria-labelledby="memory-title">
        <header class="memory-header">
          <div>
            <p class="eyebrow">PERSONAL CONTEXT</p>
            <h1 id="memory-title">Memory</h1>
            <p>Hal yang kamu simpan dapat membantu Aether memberi jawaban yang lebih relevan.</p>
          </div>
          <div class="memory-counts" aria-label="Ringkasan memory">
            <span><strong>{{ activeMemoryCount }}</strong> aktif</span>
            <span><strong>{{ archivedMemoryCount }}</strong> diarsipkan</span>
          </div>
        </header>
        <div class="memory-layout">
          <form class="memory-editor" @submit.prevent="saveMemory">
            <div>
              <p class="eyebrow">TAMBAHKAN MEMORY</p>
              <h2>Simpan konteks penting</h2>
              <p>Memory hanya disimpan atas tindakanmu dan dapat dinonaktifkan kapan saja.</p>
            </div>
            <label class="memory-field">
              Kategori
              <select v-model="memoryType">
                <option value="preference">Preferensi</option>
                <option value="fact">Fakta</option>
                <option value="context">Konteks</option>
              </select>
            </label>
            <label class="memory-field">
              Isi
              <textarea v-model="memoryContent" maxlength="2000" rows="5" required placeholder="Contoh: Saya lebih suka penjelasan ringkas dengan contoh praktis." />
            </label>
            <label class="memory-field">
              Kepentingan
              <select v-model.number="memoryImportance">
                <option :value="1">Rendah</option>
                <option :value="2">Agak rendah</option>
                <option :value="3">Normal</option>
                <option :value="4">Penting</option>
                <option :value="5">Sangat penting</option>
              </select>
            </label>
            <button class="primary-button memory-save" type="submit" :disabled="busy || !memoryContent.trim()">
              {{ busy ? 'Menyimpan…' : 'Simpan memory' }}
            </button>
          </form>

          <div class="memory-library">
            <div class="memory-library-heading">
              <div>
                <p class="eyebrow">MEMORY TERSIMPAN</p>
                <h2>{{ showArchivedMemories ? 'Semua status' : 'Memory aktif' }}</h2>
              </div>
              <label class="archive-toggle">
                <input v-model="showArchivedMemories" type="checkbox" />
                Tampilkan arsip
              </label>
            </div>
            <div class="memory-filters">
              <label class="memory-search">
                <span class="visually-hidden">Cari memory</span>
                <input v-model="memorySearch" type="search" placeholder="Cari isi memory…" />
              </label>
              <label class="memory-category-filter">
                <span class="visually-hidden">Filter kategori memory</span>
                <select v-model="memoryCategoryFilter">
                  <option value="all">Semua kategori</option>
                  <option value="preference">Preferensi</option>
                  <option value="fact">Fakta</option>
                  <option value="context">Konteks</option>
                </select>
              </label>
            </div>
            <p v-if="errorMessage" class="error-message memory-error" role="alert">{{ errorMessage }}</p>
            <p v-if="memories.length === 0" class="memory-empty">Belum ada memory. Simpan konteks pertama yang ingin Aether ingat.</p>
            <p v-else-if="visibleMemories.length === 0" class="memory-empty">Tidak ada memory yang cocok dengan filter ini.</p>
            <ul v-else class="memory-list">
              <li v-for="memory in visibleMemories" :key="memory.id" class="memory-card">
                <div class="memory-card-meta">
                  <span class="memory-category">{{ { preference: 'Preferensi', fact: 'Fakta', context: 'Konteks' }[memory.memory_type] }}</span>
                  <span class="memory-status" :class="{ archived: !memory.is_active }">{{ memory.is_active ? 'Aktif' : 'Diarsipkan' }}</span>
                </div>
                <p>{{ memory.content }}</p>
                <div class="memory-card-footer">
                  <span>Kepentingan {{ memory.importance }}/5</span>
                  <time v-if="memory.updated_at && formatMemoryDate(memory.updated_at)" :datetime="memory.updated_at">
                    Diperbarui {{ formatMemoryDate(memory.updated_at) }}
                  </time>
                  <div>
                    <button
                      type="button"
                      :disabled="busy"
                      @click="setMemoryActive(memory, !memory.is_active)"
                    >
                      {{ memory.is_active ? 'Arsipkan' : 'Aktifkan' }}
                    </button>
                    <button type="button" class="delete-memory" :disabled="busy" @click="deleteMemory(memory)">Hapus</button>
                  </div>
                </div>
              </li>
            </ul>
          </div>
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
:focus-visible { outline: 2px solid #72dfbf; outline-offset: 2px; }

.app-shell { min-height: 100vh; background: #080b10; }
.topbar { height: 72px; display: flex; align-items: center; justify-content: space-between; padding: 0 5vw; border-bottom: 1px solid #ffffff0f; }
.brand { display: inline-flex; align-items: center; width: 108px; height: 30px; text-decoration: none; }
.brand img { display: block; width: 100%; height: 100%; object-fit: contain; }
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
.startup-state { min-height: calc(100vh - 72px); display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; color: #9aa5b5; font-size: 12px; text-align: center; }
.startup-state p { margin: 0; }
.startup-state .error-message { max-width: min(520px, 85vw); }

.workspace { min-height: calc(100vh - 72px); display: grid; grid-template-columns: 238px minmax(0, 1fr); }
.sidebar { max-height: calc(100vh - 72px); overflow-y: auto; padding: 24px 14px; border-right: 1px solid #ffffff10; background: #0b0f16a8; }
.new-chat { width: 100%; padding: 11px 12px; border: 1px solid #ffffff20; border-radius: 8px; background: #121923; color: #e9eff5; text-align: left; font-size: 12px; transition: background 140ms ease, border-color 140ms ease; }
.new-chat:hover { border-color: #72dfbf66; background: #17212b; }
.new-chat span { margin-right: 8px; color: #72dfbf; font-size: 17px; vertical-align: -1px; }
.workspace-nav { display: grid; gap: 4px; margin: 18px 0 24px; padding-bottom: 15px; border-bottom: 1px solid #ffffff10; }
.workspace-nav button { display: flex; align-items: center; gap: 10px; padding: 10px; border: 0; border-radius: 7px; background: transparent; color: #9da9b7; text-align: left; font-size: 11px; }
.workspace-nav button:hover, .workspace-nav button.selected { background: #17212d; color: #e5ecf2; }
.workspace-nav button > span:first-child { width: 16px; color: #72dfbf; text-align: center; font-size: 15px; }
.nav-count { margin-left: auto; color: #72dfbf; font-size: 10px; font-variant-numeric: tabular-nums; }
.sidebar-section-heading { display: flex; align-items: center; justify-content: space-between; }
.sidebar-heading { margin: 20px 9px 10px; color: #687586; font-size: 9px; font-weight: 700; letter-spacing: 0.18em; }
.conversation-search { display: block; margin: 0 0 8px; }
.conversation-search input { width: 100%; padding: 8px 9px; border: 1px solid #ffffff14; border-radius: 6px; outline: none; background: #090d13; color: #dce4ec; font-size: 10px; }
.conversation-search input:focus { border-color: #72dfbf88; }
.conversation-item { width: 100%; display: flex; align-items: center; gap: 9px; overflow: hidden; margin: 3px 0; padding: 10px 9px; border: 0; border-radius: 8px; background: transparent; color: #9da9b7; text-align: left; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; }
.conversation-item.selected, .conversation-item:hover { background: #17212d; color: #e5ecf2; }
.conversation-icon { color: #6bd9b9; }
.empty-history { padding: 0 9px; color: #687586; font-size: 11px; }
.sidebar-empty { margin: 0; padding: 0 9px; color: #687586; font-size: 10px; line-height: 1.5; }
.sidebar-card { margin: 8px 0; padding: 10px; border: 1px solid #ffffff14; border-radius: 9px; background: #111722; }
.sidebar-card p { margin: 0 0 5px; color: #e2e8ef; font-size: 11px; font-weight: 600; }
.sidebar-card > span { display: block; color: #929eac; font-size: 10px; line-height: 1.5; overflow-wrap: anywhere; }
.approval-actions { display: flex; gap: 7px; margin-top: 9px; }
.approval-actions button { padding: 7px 9px; border: 1px solid #ffffff1c; border-radius: 6px; background: #18222e; color: #dce5ec; font-size: 9px; }
.approval-actions button:first-child { border-color: #72dfbf55; color: #72dfbf; }
.chat-area { min-width: 0; height: calc(100vh - 72px); display: flex; flex-direction: column; padding: 27px clamp(20px, 4vw, 58px) 20px; }
.chat-heading { display: flex; align-items: center; justify-content: space-between; gap: 20px; }
.chat-heading .eyebrow { margin: 0 0 9px; }
.chat-heading h1 { margin: 0; font-size: clamp(20px, 2.4vw, 29px); letter-spacing: -0.04em; }
.model-select-label { display: grid; gap: 6px; color: #6f7b8b; font-size: 8px; letter-spacing: 0.14em; }
.model-select-label select { min-width: 185px; padding: 9px 10px; border: 1px solid #ffffff20; border-radius: 8px; background: #111722; color: #dfe7ef; font-size: 10px; letter-spacing: normal; }
.model-purpose { max-width: 230px; color: #8a96a4; font-size: 9px; letter-spacing: normal; line-height: 1.4; }
.agent-workspace { width: min(980px, 100%); margin: 20px auto 0; padding: 15px 17px 13px; border: 1px solid #ffffff12; border-radius: 10px; background: #0d131c; }
.activity-heading { display: flex; align-items: center; justify-content: space-between; gap: 14px; }
.activity-heading .eyebrow { margin: 0 0 5px; font-size: 8px; }
.activity-heading h2 { margin: 0; color: #e3e9ef; font-size: 13px; font-weight: 600; letter-spacing: -0.01em; }
.activity-status { display: inline-flex; align-items: center; gap: 7px; color: #84909e; font-size: 9px; }
.activity-status.connected { color: #72dfbf; }
.activity-status.connecting { color: #d3a64e; }
.connection-dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.run-overview { display: grid; grid-template-columns: minmax(140px, 0.7fr) minmax(0, 1.6fr); align-items: stretch; gap: 12px; margin-top: 13px; padding: 11px; border: 1px solid #ffffff0d; border-radius: 7px; background: #0a0f16; }
.run-overview-copy { display: grid; align-content: center; justify-items: start; gap: 5px; min-width: 0; }
.run-kicker, .route-node-label { color: #738090; font-size: 8px; font-weight: 700; letter-spacing: 0.13em; }
.run-overview-copy strong { color: #e2e8ef; font-size: 12px; font-weight: 600; }
.run-overview-copy > span:last-child { overflow: hidden; max-width: 100%; color: #778393; font-size: 8px; text-overflow: ellipsis; white-space: nowrap; }
.route-track { display: grid; grid-template-columns: minmax(0, 1fr) 24px minmax(0, 1fr); align-items: center; gap: 7px; }
.route-node { min-width: 0; display: grid; gap: 4px; padding: 9px 10px; border: 1px solid #ffffff10; border-radius: 6px; background: #101721; }
.route-node strong { overflow: hidden; color: #dce4ec; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.route-node > span:last-child { overflow: hidden; color: #788493; font-size: 8px; text-overflow: ellipsis; white-space: nowrap; }
.route-node-selected { border-color: #72dfbf4d; background: #102019; }
.route-node-selected .route-node-label { color: #72dfbf; }
.route-arrow { color: #657384; text-align: center; font-size: 14px; }
.agent-list-label { margin: 13px 0 0; color: #657282; font-size: 8px; font-weight: 700; letter-spacing: 0.12em; }
.agent-list { display: grid; grid-template-columns: repeat(auto-fit, minmax(165px, 1fr)); gap: 7px; margin: 13px 0 0; padding: 0; list-style: none; }
.agent-row { min-width: 0; display: grid; grid-template-columns: 8px minmax(0, 1fr) auto; align-items: center; gap: 9px; padding: 9px 10px; border: 1px solid #ffffff0d; border-radius: 7px; background: #111822; }
.agent-row.core-agent { grid-column: 1 / -1; }
.agent-row.selected-agent { border-color: #72dfbf4d; background: #101b19; }
.agent-indicator { width: 7px; height: 7px; border-radius: 50%; background: #596573; }
.agent-indicator.thinking, .agent-indicator.approval { background: #d3a64e; }
.agent-indicator.working { background: #72dfbf; }
.agent-indicator.completed { background: #6a9c8b; }
.agent-indicator.error { background: #ec6c72; }
.agent-copy { min-width: 0; display: grid; gap: 3px; }
.agent-name { overflow: hidden; color: #dce4ec; font-size: 10px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.agent-description { overflow: hidden; color: #778393; font-size: 8px; text-overflow: ellipsis; white-space: nowrap; }
.agent-state { color: #808d9b; font-size: 8px; white-space: nowrap; }
.agent-state.thinking, .agent-state.approval { color: #d3a64e; }
.agent-state.working { color: #72dfbf; }
.agent-state.completed { color: #8ab9a8; }
.agent-state.error { color: #ec6c72; }
.event-trail { display: grid; grid-template-columns: 125px minmax(0, 1fr); align-items: start; gap: 10px; margin-top: 11px; padding-top: 10px; border-top: 1px solid #ffffff0d; }
.event-trail > p { margin: 2px 0 0; color: #657282; font-size: 8px; font-weight: 700; letter-spacing: 0.12em; }
.event-trail ul { display: grid; gap: 5px; margin: 0; padding: 0; list-style: none; }
.event-trail li { display: grid; grid-template-columns: 44px minmax(88px, 0.45fr) minmax(0, 1fr); align-items: center; gap: 8px; min-width: 0; color: #a9b5c1; font-size: 8px; }
.event-trail time { color: #687586; font-variant-numeric: tabular-nums; }
.event-actor { overflow: hidden; color: #b7c2ce; text-overflow: ellipsis; white-space: nowrap; }
.event-trail li span:last-child { color: #7e8b99; }
.welcome-state { flex: 1; width: min(980px, 100%); display: flex; flex-direction: column; justify-content: center; gap: 22px; margin: 0 auto; padding: 24px 0; }
.welcome-intro .eyebrow { margin: 0 0 11px; }
.welcome-intro h2 { margin: 0; color: #edf2f6; font-size: clamp(25px, 3.2vw, 37px); font-weight: 550; line-height: 1.16; letter-spacing: -0.045em; }
.welcome-intro h2 span { color: #88a99f; }
.welcome-intro > p:last-child { margin: 11px 0 0; color: #8e9aa8; font-size: 12px; }
.prompt-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px; }
.prompt-card { position: relative; min-height: 83px; display: grid; align-content: start; gap: 8px; padding: 13px 38px 13px 14px; border: 1px solid #ffffff13; border-radius: 8px; background: #101721; color: #dfe6ec; text-align: left; }
.prompt-card:hover { border-color: #72dfbf66; background: #141d27; }
.prompt-card > span:first-child { color: #72dfbf; font-size: 8px; font-weight: 700; letter-spacing: 0.11em; text-transform: uppercase; }
.prompt-card strong { max-width: 440px; color: #c3ccd5; font-size: 10px; font-weight: 450; line-height: 1.5; }
.prompt-card .prompt-arrow { position: absolute; top: 12px; right: 13px; color: #748291; font-size: 13px; }
.messages { flex: 1; overflow-y: auto; width: min(850px, 100%); margin: 25px auto 18px; padding: 0 7px; }
.message { display: flex; gap: 13px; margin: 0 0 24px; }
.message-avatar { flex: 0 0 28px; height: 28px; display: grid; place-items: center; border: 1px solid #ffffff20; border-radius: 9px; background: #151e29; color: #c6d2de; font-size: 10px; }
.message.assistant .message-avatar { border-color: #4cd7ae55; background: #10251f; color: #72dfbf; }
.message-content { min-width: 0; }
.message-author { display: flex; align-items: center; gap: 9px; margin: 0 0 7px; color: #9aa6b5; font-size: 10px; }
.message-text { margin: 0; color: #e2e8ef; font-size: 13px; line-height: 1.8; white-space: pre-wrap; overflow-wrap: anywhere; }
.message.pending .message-text { color: #cbd4dd; }
.thinking-label { color: #7f8e9b; font-size: 9px; }
.thinking-placeholder { display: inline-flex; align-items: center; gap: 8px; margin: 0; color: #9ca9b5; font-size: 11px; }
.thinking-placeholder span { width: 7px; height: 7px; border: 1px solid #72dfbf; border-radius: 50%; background: #72dfbf55; }
.composer-wrap { width: min(850px, 100%); margin: auto auto 0; }
.composer { padding: 12px 13px 9px; border: 1px solid #ffffff20; border-radius: 9px; background: #111722; transition: border-color 140ms ease; }
.composer textarea { width: 100%; resize: vertical; min-height: 48px; max-height: 180px; border: 0; outline: none; background: transparent; color: #e9eff5; font-size: 12px; line-height: 1.6; }
.composer textarea::placeholder { color: #667383; }
.composer-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; color: #7c8997; font-size: 9px; }
.composer-actions { display: flex; flex: 0 0 auto; align-items: center; gap: 7px; }
.voice-toggle, .voice-button { padding: 8px 9px; border: 1px solid #ffffff20; border-radius: 4px; background: transparent; color: #aab5c0; font-size: 9px; white-space: nowrap; }
.voice-toggle[aria-pressed="true"] { border-color: #72dfbf55; color: #72dfbf; }
.voice-button:hover:not(:disabled), .voice-toggle:hover:not(:disabled) { border-color: #72dfbf88; color: #dce5ec; }
.voice-button.listening { border-color: #72dfbf88; background: #10251f; color: #72dfbf; }
.voice-privacy, .voice-status { margin: 7px 2px 0; color: #687586; font-size: 8px; line-height: 1.5; }
.voice-status { color: #9aa5b2; }
.send-button { padding: 8px 12px; border: 0; border-radius: 6px; background: #72dfbf; color: #07110e; font-size: 10px; font-weight: 700; }
.chat-error { margin: 0 0 10px; }
.memory-workspace { width: min(1200px, 100%); min-width: 0; height: calc(100vh - 72px); overflow-y: auto; margin: 0 auto; padding: 38px clamp(20px, 5vw, 64px); }
.memory-header { display: flex; align-items: flex-end; justify-content: space-between; gap: 25px; padding-bottom: 24px; border-bottom: 1px solid #ffffff12; }
.memory-header .eyebrow { margin: 0 0 8px; }
.memory-header h1 { margin: 0; color: #edf2f6; font-size: 28px; letter-spacing: -0.04em; }
.memory-header > div:first-child > p:last-child { max-width: 470px; margin: 9px 0 0; color: #8e9aa8; font-size: 11px; line-height: 1.65; }
.memory-counts { display: flex; gap: 8px; }
.memory-counts span { padding: 8px 10px; border: 1px solid #ffffff12; border-radius: 6px; color: #909cab; font-size: 9px; white-space: nowrap; }
.memory-counts strong { color: #dce4ec; font-size: 11px; }
.memory-layout { display: grid; grid-template-columns: minmax(220px, 0.72fr) minmax(0, 1.5fr); align-items: start; gap: 22px; padding-top: 23px; }
.memory-editor { display: grid; gap: 14px; padding: 17px; border: 1px solid #ffffff12; border-radius: 9px; background: #0d131c; }
.memory-editor .eyebrow, .memory-library-heading .eyebrow { margin: 0 0 7px; font-size: 8px; }
.memory-editor h2, .memory-library-heading h2 { margin: 0; color: #e3e9ef; font-size: 14px; font-weight: 600; }
.memory-editor > div > p:last-child { margin: 7px 0 0; color: #85919e; font-size: 10px; line-height: 1.55; }
.memory-field { display: grid; gap: 7px; color: #aeb8c3; font-size: 10px; }
.memory-field select, .memory-field textarea, .memory-search input { width: 100%; padding: 10px 11px; border: 1px solid #ffffff18; border-radius: 6px; outline: none; background: #090d13; color: #e2e8ef; font: inherit; font-size: 10px; }
.memory-field textarea { resize: vertical; line-height: 1.6; }
.memory-field select:focus, .memory-field textarea:focus, .memory-search input:focus { border-color: #72dfbf88; }
.memory-save { margin: 0; cursor: pointer; }
.memory-library { min-width: 0; }
.memory-library-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.archive-toggle { display: inline-flex; align-items: center; gap: 7px; color: #9aa5b2; font-size: 9px; cursor: pointer; }
.archive-toggle input { accent-color: #72dfbf; }
.memory-filters { display: grid; grid-template-columns: minmax(0, 1fr) minmax(130px, 0.38fr); gap: 8px; margin: 13px 0; }
.memory-search { display: block; }
.memory-search input { background: #0d131c; }
.memory-category-filter select { width: 100%; height: 100%; padding: 10px 11px; border: 1px solid #ffffff18; border-radius: 6px; background: #0d131c; color: #e2e8ef; font: inherit; font-size: 10px; }
.memory-category-filter select:focus { outline: 2px solid #72dfbf88; outline-offset: 1px; }
.memory-list { display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }
.memory-card { padding: 13px 14px 11px; border: 1px solid #ffffff12; border-radius: 8px; background: #0d131c; }
.memory-card-meta, .memory-card-footer, .memory-card-footer > div { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.memory-category { color: #72dfbf; font-size: 8px; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase; }
.memory-status { padding: 4px 7px; border-radius: 999px; background: #173027; color: #82d9b7; font-size: 8px; }
.memory-status.archived { background: #252b33; color: #a2acb7; }
.memory-card > p { margin: 11px 0 13px; color: #d5dde5; font-size: 11px; line-height: 1.7; white-space: pre-wrap; overflow-wrap: anywhere; }
.memory-card-footer { padding-top: 9px; border-top: 1px solid #ffffff0d; color: #788594; font-size: 8px; }
.memory-card-footer button { padding: 5px 7px; border: 1px solid #ffffff18; border-radius: 5px; background: transparent; color: #aab5c0; font-size: 8px; }
.memory-card-footer button:hover { border-color: #72dfbf66; color: #72dfbf; }
.memory-card-footer .delete-memory:hover { border-color: #ec6c7288; color: #ff9a9f; }
.memory-empty { padding: 24px; border: 1px dashed #ffffff1d; border-radius: 8px; color: #8995a2; font-size: 10px; line-height: 1.6; text-align: center; }
.memory-error { margin: 8px 0; }
.visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; clip-path: inset(50%); }

@media (max-width: 760px) {
  .auth-layout { grid-template-columns: 1fr; gap: 30px; padding: 35px 0; }
  .intro h1 { font-size: 45px; }
  .intro-copy { font-size: 12px; }
  .workspace { grid-template-columns: 1fr; }
  .sidebar { max-height: 36vh; padding: 10px 14px; border-right: 0; border-bottom: 1px solid #ffffff10; }
  .sidebar-heading { margin: 14px 3px 8px; }
  .workspace-nav { grid-template-columns: repeat(2, minmax(0, 1fr)); margin: 8px 0 12px; padding-bottom: 9px; }
  .empty-history { display: none; }
  .new-chat { width: 100%; }
  .conversation-item { width: 100%; }
  .chat-area { height: calc(100vh - 36vh - 72px); min-height: 440px; padding: 18px 16px 16px; }
  .chat-heading { order: 0; align-items: flex-start; }
  .chat-heading h1 { max-width: 210px; font-size: 18px; }
  .model-select-label select { min-width: 125px; max-width: 145px; }
  .model-purpose { max-width: 145px; }
  .agent-workspace { order: 3; margin-top: 14px; padding: 12px; }
  .welcome-state, .messages { order: 1; }
  .composer-wrap { order: 2; }
  .run-overview { grid-template-columns: 1fr; }
  .run-overview-copy { grid-template-columns: auto 1fr; align-items: baseline; column-gap: 8px; }
  .run-overview-copy > span:last-child { grid-column: 1 / -1; }
  .agent-list { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .agent-row.core-agent { grid-column: 1 / -1; }
  .agent-row { grid-template-columns: 7px minmax(0, 1fr); gap: 7px; padding: 8px; }
  .agent-state { grid-column: 2; }
  .agent-description { white-space: normal; }
  .event-trail { grid-template-columns: 1fr; gap: 7px; }
  .welcome-state { justify-content: flex-start; gap: 18px; padding: 24px 0; }
  .prompt-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .prompt-card { min-height: 65px; }
  .composer-footer { align-items: flex-end; }
  .composer-footer > span { max-width: 35%; line-height: 1.5; }
  .composer-actions { flex-wrap: wrap; justify-content: flex-end; gap: 4px; }
  .voice-toggle, .voice-button, .send-button { padding: 7px 6px; font-size: 8px; }
  .memory-workspace { height: auto; min-height: calc(100vh - 36vh - 72px); overflow: visible; padding: 24px 16px; }
  .memory-header { align-items: flex-start; flex-direction: column; padding-bottom: 18px; }
  .memory-header h1 { font-size: 24px; }
  .memory-layout { grid-template-columns: 1fr; gap: 20px; padding-top: 18px; }
  .memory-filters { grid-template-columns: 1fr; }
}

@media (max-width: 420px) {
  .topbar { height: 62px; padding: 0 16px; }
  .topbar-right { gap: 9px; font-size: 10px; }
  .backend-error { display: none; }
  .workspace-nav button { padding: 9px 7px; }
  .chat-area { height: calc(100vh - 36vh - 62px); padding: 15px 12px 12px; }
  .chat-heading { gap: 8px; }
  .chat-heading h1 { max-width: 160px; font-size: 16px; }
  .model-select-label select { min-width: 115px; max-width: 125px; padding: 8px 6px; font-size: 9px; }
  .model-purpose { max-width: 125px; font-size: 8px; }
  .welcome-state { gap: 12px; padding: 14px 0; }
  .prompt-card { min-height: 60px; gap: 5px; padding: 10px 26px 10px 11px; }
  .prompt-card strong { font-size: 9px; line-height: 1.4; }
  .agent-list { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .agent-row { grid-template-columns: 7px minmax(0, 1fr); }
  .agent-row.core-agent { grid-column: 1 / -1; }
  .agent-state { grid-column: 2; }
  .agent-description { display: none; }
  .agent-row { padding: 7px; }
  .agent-list { gap: 5px; margin-top: 9px; }
  .agent-workspace { padding: 10px; }
  .run-overview { gap: 8px; margin-top: 9px; padding: 8px; }
  .route-node { gap: 3px; padding: 7px; }
  .agent-list-label { margin-top: 10px; }
  .memory-counts { width: 100%; }
  .memory-counts span { flex: 1; text-align: center; }
  .route-track { grid-template-columns: minmax(0, 1fr) 16px minmax(0, 1fr); gap: 4px; }
  .route-node { padding: 8px 7px; }
  .route-node strong { font-size: 9px; }
  .event-trail { grid-template-columns: 1fr; }
}

/* Operational workspace treatment: flat surfaces, explicit hierarchy, and compact labels. */
.app-shell { background: #08090d; }
.topbar { padding-right: clamp(16px, 3vw, 42px); padding-left: clamp(16px, 3vw, 42px); border-bottom-color: #ffffff12; }
.workspace { grid-template-columns: 224px minmax(0, 1fr); }
.sidebar { background: #0a0c11; }
.chat-area { padding: 24px clamp(20px, 3vw, 42px) 18px; }
.chat-heading { flex: 0 0 auto; padding-bottom: 17px; border-bottom: 1px solid #ffffff12; }
.chat-heading .eyebrow, .model-select-label, .run-kicker, .route-node-label, .agent-list-label, .event-trail > p {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
.chat-heading .eyebrow { color: #788493; font-size: 9px; letter-spacing: 0.12em; }
.chat-heading h1 { font-size: clamp(18px, 2vw, 24px); font-weight: 560; letter-spacing: -0.035em; }
.model-select-label { gap: 5px; font-size: 8px; }
.model-select-label select { border-color: #ffffff1c; border-radius: 4px; background: #0d1117; }
.chat-body { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1fr) minmax(255px, 300px); }
.conversation-workspace { min-width: 0; min-height: 0; display: flex; flex-direction: column; padding: 0 clamp(20px, 3vw, 42px) 0 0; }
.agent-workspace { width: auto; min-height: 0; overflow-y: auto; margin: 0; padding: 19px 0 8px 20px; border: 0; border-left: 1px solid #ffffff12; border-radius: 0; background: transparent; }
.activity-heading { padding-bottom: 14px; border-bottom: 1px solid #ffffff12; }
.activity-heading .eyebrow { color: #788493; font-size: 8px; }
.activity-heading h2 { color: #edf2f6; font-size: 16px; font-weight: 540; letter-spacing: -0.025em; }
.activity-status { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 8px; }
.run-overview { display: grid; gap: 5px; margin-top: 16px; padding: 0 0 14px; border: 0; border-bottom: 1px solid #ffffff12; border-radius: 0; background: transparent; }
.run-kicker, .route-node-label { font-size: 8px; letter-spacing: 0.11em; }
.run-overview > strong { color: #e8edf2; font-size: 13px; font-weight: 550; }
.run-overview > span:last-child, .orchestration-state { color: #788493; font-size: 9px; line-height: 1.5; }
.orchestration-path { display: grid; grid-template-columns: 1fr; gap: 0; margin-top: 16px; }
.orchestration-node { min-width: 0; display: grid; gap: 7px; padding: 0 0 12px; }
.orchestration-identity { display: flex; align-items: center; gap: 9px; min-height: 18px; }
.orchestration-identity strong { overflow: hidden; color: #e4e9ef; font-size: 12px; font-weight: 550; text-overflow: ellipsis; white-space: nowrap; }
.orchestration-connector { width: 1px; height: 19px; margin: 0 0 12px 3px; background: #72dfbf55; }
.worker-node { padding: 0 0 15px; }
.worker-node.route-node-selected .route-node-label { color: #72dfbf; }
.worker-node.route-node-selected .orchestration-identity strong { color: #b7e9d8; }
.agent-indicator { flex: 0 0 7px; width: 7px; height: 7px; border-radius: 1px; }
.agent-directory { padding-top: 2px; border-top: 1px solid #ffffff12; }
.agent-list-label { margin: 14px 0 8px; color: #687586; font-size: 8px; letter-spacing: 0.1em; }
.agent-list { display: block; margin: 0; }
.agent-row { min-height: 34px; grid-template-columns: 7px minmax(0, 1fr) auto; gap: 9px; padding: 7px 4px; border: 0; border-bottom: 1px solid #ffffff0b; border-radius: 0; background: transparent; }
.agent-row.selected-agent { border-color: #ffffff0b; border-left: 2px solid #72dfbf; background: #0d1414; }
.agent-name { font-size: 10px; font-weight: 500; }
.agent-state { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 8px; }
.event-trail { display: block; margin-top: 16px; padding-top: 1px; border-top: 0; }
.event-trail ol { display: grid; gap: 0; margin: 0; padding: 0 0 0 9px; border-left: 1px solid #ffffff17; list-style: none; }
.event-trail li { display: grid; grid-template-columns: 38px minmax(0, 1fr); gap: 4px 7px; padding: 0 0 12px; color: #9aa5b2; font-size: 9px; line-height: 1.45; }
.event-trail time { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 8px; }
.event-actor { color: #c3ccd5; }
.event-trail li > span:last-child { grid-column: 2; overflow-wrap: anywhere; color: #798593; }
.welcome-state { width: 100%; max-width: 740px; gap: 27px; margin: auto; padding: 32px 0; }
.welcome-intro .eyebrow { margin-bottom: 15px; color: #788493; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 9px; letter-spacing: 0.12em; }
.welcome-intro h2 { max-width: 650px; font-size: clamp(30px, 4vw, 46px); font-weight: 520; line-height: 1.12; letter-spacing: -0.05em; }
.welcome-intro h2 span { color: #a4b9b2; }
.welcome-intro > p:last-child { max-width: 480px; margin-top: 14px; color: #9aa5b2; font-size: 12px; line-height: 1.7; }
.prompt-grid { display: block; border-top: 1px solid #ffffff15; }
.prompt-card { width: 100%; min-height: 0; display: grid; grid-template-columns: 92px minmax(0, 1fr) 16px; align-items: center; gap: 12px; padding: 12px 4px 12px 0; border: 0; border-bottom: 1px solid #ffffff12; border-radius: 0; background: transparent; }
.prompt-card:hover { border-color: #ffffff28; background: transparent; }
.prompt-card > span:first-child { color: #72dfbf; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 8px; letter-spacing: 0.08em; }
.prompt-card strong { max-width: none; color: #cbd3dc; font-size: 10px; font-weight: 450; line-height: 1.5; }
.prompt-card .prompt-arrow { position: static; color: #687586; text-align: right; }
.prompt-card:hover strong, .prompt-card:hover .prompt-arrow { color: #72dfbf; }
.messages { width: 100%; max-width: 780px; padding: 22px 4px 0; }
.message { gap: 12px; margin-bottom: 25px; }
.message-avatar { flex-basis: 24px; height: 24px; border-radius: 4px; background: #10141b; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.message.assistant .message-avatar { border-color: #ffffff1b; background: #101714; }
.message-author { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 9px; }
.message-text { font-size: 13px; line-height: 1.8; }
.composer-wrap { width: 100%; max-width: 780px; padding: 12px 0 0; }
.composer { padding: 11px 12px 9px; border-radius: 5px; background: #0d1117; }
.composer textarea { font-size: 12px; }
.send-button { border-radius: 3px; }
.memory-editor, .memory-card { border-radius: 4px; background: #0b0f14; }
.memory-counts span { border-radius: 3px; }
.memory-status { border-radius: 2px; }
.memory-card-footer button { border-radius: 3px; }
.sidebar-card { border-radius: 4px; background: #0c1016; }
.new-chat, .conversation-item, .workspace-nav button { border-radius: 4px; }

@media (max-width: 900px) {
  .workspace { grid-template-columns: 205px minmax(0, 1fr); }
  .chat-body { grid-template-columns: minmax(0, 1fr) 250px; }
  .conversation-workspace { padding-right: 17px; }
  .agent-workspace { padding-left: 16px; }
}

@media (max-width: 760px) {
  .workspace { grid-template-columns: 1fr; }
  .chat-area { height: calc(100vh - 36vh - 72px); min-height: 480px; padding: 16px; }
  .chat-heading { align-items: center; padding-bottom: 12px; }
  .chat-body { display: flex; flex-direction: column; overflow-y: auto; }
  .conversation-workspace { flex: 1 0 auto; min-height: 0; padding: 0; }
  .welcome-state { flex: 1; gap: 12px; padding: 19px 0 14px; }
  .welcome-intro .eyebrow { margin-bottom: 9px; }
  .welcome-intro h2 { font-size: clamp(26px, 7vw, 34px); }
  .welcome-intro > p:last-child { margin-top: 9px; font-size: 11px; }
  .prompt-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 12px; }
  .prompt-card { grid-template-columns: minmax(0, 1fr) 14px; grid-template-rows: auto auto; gap: 4px; padding: 9px 2px 9px 0; }
  .prompt-card > span:first-child { grid-column: 1 / -1; }
  .prompt-card strong { grid-column: 1; font-size: 9px; }
  .prompt-card .prompt-arrow { grid-column: 2; grid-row: 2; }
  .messages { min-height: 220px; margin: 0 auto 10px; }
  .composer-wrap { margin-top: auto; padding-bottom: 14px; }
  .agent-workspace { flex: 0 0 auto; order: 1; max-height: 34vh; overflow-y: auto; margin-top: 0; padding: 15px 0 4px; border-top: 1px solid #ffffff12; border-left: 0; }
  .activity-heading { padding-bottom: 10px; }
  .run-overview { grid-template-columns: auto 1fr; align-items: baseline; column-gap: 8px; margin-top: 12px; padding-bottom: 10px; }
  .run-overview > span:last-child { grid-column: 1 / -1; }
  .orchestration-path { grid-template-columns: minmax(0, 1fr) 18px minmax(0, 1fr); align-items: center; gap: 7px; margin-top: 12px; }
  .orchestration-node { padding-bottom: 0; }
  .orchestration-connector { width: 100%; height: 1px; margin: 0; }
  .worker-node { padding-bottom: 0; }
  .agent-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: 12px; }
  .agent-row { grid-template-columns: 7px minmax(0, 1fr) auto; }
  .event-trail { display: block; }
  .event-trail ol { grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: 12px; }
  .memory-workspace { height: auto; min-height: calc(100vh - 36vh - 72px); overflow: visible; }
}

@media (max-width: 420px) {
  .chat-area { height: calc(100vh - 36vh - 62px); padding: 13px 12px; }
  .chat-heading { gap: 8px; }
  .chat-heading h1 { max-width: none; font-size: 16px; }
  .model-select-label select { min-width: 115px; max-width: 125px; padding: 8px 6px; font-size: 9px; }
  .model-purpose { max-width: 125px; font-size: 8px; }
  .conversation-workspace { flex-basis: 350px; min-height: 350px; }
  .welcome-state { gap: 13px; padding-top: 18px; }
  .welcome-intro h2 { font-size: 27px; }
  .welcome-intro > p:last-child { font-size: 11px; }
  .prompt-card { grid-template-columns: minmax(0, 1fr) 12px; grid-template-rows: auto auto; gap: 4px; padding: 9px 2px 9px 0; }
  .prompt-card strong { font-size: 9px; }
  .composer-footer > span { max-width: 68%; line-height: 1.5; }
  .agent-list { gap: 0 9px; }
  .agent-row { min-height: 32px; padding: 6px 2px; }
  .event-trail ol { grid-template-columns: 1fr; }
  .memory-counts { width: 100%; }
  .memory-counts span { flex: 1; text-align: center; }
}

/* Conversation landing page follows the supplied compact assistant-workspace reference. */
.topbar { height: 56px; padding: 0 24px; background: #191919; }
.workspace { min-height: calc(100vh - 56px); grid-template-columns: 252px minmax(0, 1fr); background: #191919; }
.sidebar { max-height: calc(100vh - 56px); padding: 17px 10px 22px; background: #1d1d1d; }
.new-chat { padding: 10px 12px; border: 0; border-radius: 7px; background: #373737; color: #f0f0f0; font-size: 12px; }
.new-chat:hover { background: #414141; }
.workspace-nav { gap: 3px; margin: 12px 0 20px; padding-bottom: 15px; }
.workspace-nav button { min-height: 34px; padding: 8px 10px; border-radius: 6px; color: #c3c3c3; }
.workspace-nav button:hover, .workspace-nav button.selected { background: #303030; color: #f4f4f4; }
.workspace-nav button > span:first-child { color: #c8c8c8; }
.sidebar-heading { margin: 18px 7px 9px; color: #c5c5c5; letter-spacing: 0.02em; }
.conversation-search input { padding: 9px 10px; border-color: #ffffff10; border-radius: 6px; background: #252525; }
.conversation-item { min-height: 34px; margin: 2px 0; border-radius: 5px; color: #c7c7c7; }
.conversation-item.selected, .conversation-item:hover { background: #2b2b2b; color: #fff; }
.empty-history, .sidebar-empty { color: #858585; }
.chat-area { height: calc(100vh - 56px); padding: 0 clamp(20px, 5vw, 72px) 28px; background: #191919; }
.chat-heading { min-height: 64px; align-items: center; padding-bottom: 12px; border-bottom-color: #ffffff0b; }
.chat-heading .eyebrow { margin-bottom: 4px; }
.chat-heading h1 { font-size: 18px; }
.chat-body.welcome-chat { grid-template-columns: minmax(0, 1fr); }
.chat-body.welcome-chat .agent-workspace { display: none; }
.chat-body.welcome-chat .conversation-workspace { display: grid; grid-template-rows: auto auto; align-content: center; gap: 25px; padding: 0; }
.welcome-state { width: min(660px, 100%); max-width: 660px; align-items: center; justify-content: center; gap: 25px; padding: 30px 0 20px; text-align: center; }
.welcome-intro { display: flex; flex-direction: column; align-items: center; }
.welcome-mark { width: 42px; height: 42px; margin-bottom: 8px; object-fit: contain; }
.welcome-intro h2 { font-family: Georgia, "Times New Roman", serif; font-size: clamp(32px, 4vw, 43px); font-weight: 400; line-height: 1.15; letter-spacing: -0.035em; }
.welcome-intro h2 span { color: #e2e2e2; }
.welcome-intro > p:last-child { margin-top: 9px; color: #9c9c9c; font-size: 12px; }
.prompt-grid { display: flex; flex-wrap: wrap; justify-content: center; gap: 8px; border: 0; }
.prompt-card { width: auto; min-height: 0; display: inline-flex; align-items: center; gap: 6px; padding: 8px 10px; border: 0; border-radius: 7px; background: #343434; color: #e2e2e2; font-size: 10px; }
.prompt-card:hover { border: 0; background: #414141; color: #fff; }
.prompt-icon { color: #cbd9d4; font-size: 12px; font-weight: 600; }
.chat-body.welcome-chat .composer-wrap { margin: 0 auto; padding: 0; }
.composer { padding: 14px 15px 11px; border: 1px solid #ffffff0c; border-radius: 14px; background: #303030; }
.composer:focus-within { border-color: #72dfbf66; }
.composer textarea { min-height: 55px; font-size: 13px; }
.composer textarea::placeholder { color: #999; }
.composer-footer { min-height: 32px; color: #999; }
.composer-actions { gap: 6px; }
.inline-model-select select { max-width: 164px; padding: 7px 8px; border: 0; border-radius: 6px; background: #3b3b3b; color: #e4e4e4; font-size: 9px; }
.voice-toggle, .voice-button { border-color: transparent; background: #3b3b3b; color: #d3d3d3; }
.voice-toggle[aria-pressed="true"] { border-color: transparent; color: #9ce5cd; }
.voice-button.listening { background: #183229; }
.send-button { padding: 8px 11px; }
.voice-privacy { margin-top: 6px; color: #747474; text-align: center; }
.voice-status { text-align: center; }

@media (max-width: 760px) {
  .topbar { height: 56px; padding: 0 16px; }
  .workspace { min-height: calc(100vh - 56px); grid-template-columns: 1fr; }
  .sidebar { max-height: 36vh; padding: 10px 12px; }
  .chat-area { height: calc(100vh - 36vh - 56px); min-height: 440px; padding: 0 16px 16px; }
  .chat-body.welcome-chat { display: flex; flex: 1; min-height: 0; overflow: visible; }
  .chat-body.welcome-chat .conversation-workspace { display: grid; flex: 1; min-height: 0; align-content: center; gap: 18px; }
  .chat-body.welcome-chat .welcome-state { flex: 0 0 auto; justify-content: center; gap: 18px; padding: 12px 0; }
  .chat-body.welcome-chat .composer-wrap { flex: 0 0 auto; width: 100%; margin: 0; padding: 0 0 12px; }
  .chat-body.welcome-chat .composer-footer { align-items: flex-end; }
  .chat-body.welcome-chat .composer-footer > span { max-width: 32%; font-size: 8px; }
  .chat-body.welcome-chat .composer-actions { flex-wrap: wrap; justify-content: flex-end; gap: 4px; }
  .chat-body.welcome-chat .inline-model-select select { max-width: 120px; padding: 7px 5px; font-size: 8px; }
  .chat-body.welcome-chat .voice-toggle,
  .chat-body.welcome-chat .voice-button,
  .chat-body.welcome-chat .send-button { padding: 7px 6px; font-size: 8px; }
}

@media (max-width: 420px) {
  .workspace { min-height: calc(100vh - 62px); grid-template-columns: 1fr; }
  .sidebar { max-height: 36vh; }
  .chat-area { height: calc(100vh - 36vh - 62px); min-height: 410px; padding: 0 12px 12px; }
  .chat-body.welcome-chat .welcome-state { gap: 14px; }
  .welcome-mark { width: 36px; height: 36px; }
  .welcome-intro h2 { font-size: 32px; }
  .prompt-grid { gap: 6px; }
  .prompt-card { padding: 7px 8px; }
  .chat-body.welcome-chat .composer { padding: 11px 10px 9px; }
  .chat-body.welcome-chat .composer textarea { min-height: 46px; }
}

@media (max-width: 360px) {
  body { min-width: 0; }
  .topbar { padding-right: 12px; padding-left: 12px; }
  .topbar-right { gap: 8px; font-size: 9px; }
  .user-label { display: none; }
  .chat-body.welcome-chat .composer-footer > span { display: none; }
  .chat-body.welcome-chat .composer-actions { width: 100%; justify-content: space-between; }
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { scroll-behavior: auto !important; transition-duration: 0.01ms !important; animation-duration: 0.01ms !important; animation-iteration-count: 1 !important; }
}
</style>
