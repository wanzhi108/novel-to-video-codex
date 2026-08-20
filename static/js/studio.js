// ── Novel2Vid Studio v9 ──
// v9.10: 前端 API 基址 → 同源兜底 + localhost 回退, 支持局域网/远程访问
const API = (() => {
  if (window.location.hostname && window.location.port) return window.location.origin;
  return "http://localhost:8190";
})();

// ========== State ==========
const state = {
  mode: "balanced",
  style: "cinematic",
  model: "animagine-xl-4.0",
  generating: false,
  jobId: null,
  ws: null,
  sceneCount: 0,
  scenesDone: 0,
  startTime: null,
  quality: {
    use_ipadapter: true, use_hires_fix: true, use_multi_shot: true,
    use_ken_burns: false, use_dual_frame: false, video_mode: "local",
    smart_dubbing: true, use_manga_fx: false,
    use_color_grading: true, use_fade_transition: true,
    use_pulid: false, tts_enabled: true,
  },
  history: [],
};

// Load history
try { state.history = JSON.parse(localStorage.getItem("nv2v_history") || "[]"); } catch(_) {}

// ========== Toast ==========
function toast(msg, type) {
  const c = document.getElementById("toastContainer");
  const el = document.createElement("div");
  el.className = `toast toast-${type||"info"}`;
  el.textContent = msg;
  c.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

// ========== API ==========
async function apiGet(path) {
  const r = await fetch(API + path);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

async function apiPost(path, data) {
  const r = await fetch(API + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

async function checkHealth() {
  try {
    const d = await apiGet("/api/health");
    toast("服务器连接成功", "success");
    return true;
  } catch(e) {
    toast("服务器未连接，请启动后端", "error");
    return false;
  }
}

async function checkComfyUI() {
  try {
    const d = await apiGet("/api/comfyui-check");
    // v9.10: 防御空响应 / ComfyUI 未启动时 API 仍返回 200 但 data 为空
    if (!d || !d.data) {
      document.getElementById("vramDisp").textContent = "离线";
      return false;
    }
    const vramFree = d.data.devices?.[0]?.vram_free;
    document.getElementById("vramDisp").textContent = vramFree
      ? `${(vramFree/1024).toFixed(1)}GB free` : "检测中";
    return d.status === "ok";
  } catch { return false; }
}

// ========== Modes ==========
const presets = {
  draft:   { use_ipadapter:false, use_hires_fix:false, use_multi_shot:false, use_ken_burns:true, video_mode:"local", smart_dubbing:false, use_manga_fx:false, use_color_grading:false, use_fade_transition:false },
  balanced:{ use_ipadapter:true, use_hires_fix:true, use_multi_shot:true, use_ken_burns:false, video_mode:"local", smart_dubbing:true, use_manga_fx:false, use_color_grading:true, use_fade_transition:true },
  quality: { use_ipadapter:true, use_hires_fix:true, use_multi_shot:true, use_ken_burns:false, video_mode:"local", smart_dubbing:true, use_manga_fx:false, use_color_grading:true, use_fade_transition:true },
};

function setMode(mode) {
  state.mode = mode;
  Object.assign(state.quality, presets[mode]);
  document.querySelectorAll(".mode-btn").forEach(b => b.classList.toggle("active", b.dataset.mode === mode));
  refreshOpts();
}

function setStyle(style) {
  state.style = style;
  document.getElementById("styleSelect").value = style;
  const hints = { cinematic:"电影级写实 | 红果短剧首选", realistic:"照片级真实 | 配合RealVisXL", anime:"动漫/漫剧风 | 配合animagine", ink:"水墨古风 | 需下载模型" };
  document.getElementById("styleHint").textContent = hints[style] || "";
}

// ========== UI Refresh ==========
function refreshOpts() {
  const q = state.quality;
  document.querySelectorAll("[data-opt]").forEach(el => {
    const k = el.dataset.opt;
    if (el.type === "checkbox") el.checked = !!q[k];
    else if (el.type === "radio") el.checked = String(q[k]) === el.value;
  });
  // Update steps badge
  const ipa = q.use_ipadapter ? "ON" : "OFF";
  document.getElementById("s1Badge").textContent = ipa === "ON" ? "IP-Adapter" : "无";
  document.getElementById("s1Badge").className = "badge " + (ipa === "ON" ? "badge-success" : "badge-warning");
  // Char count
  const txt = document.getElementById("novelInput").value;
  document.getElementById("charCount").textContent = txt.length + "字";
}

// ========== Quick Presets ==========
function quickPreset(name) {
  if (name === "optimal") {
    state.mode = "balanced";
    Object.assign(state.quality, {
      use_ipadapter: true, use_hires_fix: true, use_multi_shot: true,
      use_ken_burns: false, use_dual_frame: false, video_mode: "local",
      smart_dubbing: true, use_manga_fx: false,
      use_color_grading: true, use_fade_transition: true,
    });
    refreshOpts();
  }
  if (name === "fast") {
    state.mode = "draft";
    Object.assign(state.quality, presets.draft);
    refreshOpts();
  }
}

// ========== Drag & Drop ==========
function setupDragDrop() {
  const ta = document.getElementById("novelInput");
  ta.addEventListener("dragover", e => { e.preventDefault(); ta.classList.add("drag-over"); });
  ta.addEventListener("dragleave", () => ta.classList.remove("drag-over"));
  ta.addEventListener("drop", e => {
    e.preventDefault();
    ta.classList.remove("drag-over");
    const file = e.dataTransfer.files[0];
    if (file && file.name.endsWith(".txt")) {
      const reader = new FileReader();
      reader.onload = ev => { ta.value = ev.target.result; refreshOpts(); };
      reader.readAsText(file);
      toast(`已加载: ${file.name}`, "success");
    } else { toast("请拖入 .txt 文件", "error"); }
  });
}

// ========== Generate ==========
async function startGenerate() {
  if (state.generating) return;
  const text = document.getElementById("novelInput").value.trim();
  const apikey = document.getElementById("apiKey").value.trim();
  if (text.length < 10) { toast("小说文本至少10字", "error"); return; }

  // Confirm
  const eta = Math.ceil(text.length / 5);
  if (!confirm(`预估 ${eta} 个场景，首次需~40min。\n\n风格: ${state.style}\n模型: ${state.model}\nIP-Adapter: ${state.quality.use_ipadapter?"ON":"OFF"}\n多镜头: ${state.quality.use_multi_shot?"ON":"OFF"}\n\n确定生成？`)) return;

  state.generating = true;
  state.startTime = Date.now();
  document.getElementById("genBtn").disabled = true;
  document.getElementById("genBtn").textContent = "生成中...";
  document.getElementById("progressPanel").classList.remove("hidden");
  document.getElementById("progressFill").style.width = "0%";
  document.getElementById("progressText").textContent = "提交中...";
  document.getElementById("sceneList").innerHTML = "";

  try {
    const payload = {
      novel_text: text,
      novel_title: "Novel2Vid生成",
      style: state.style,
      img_checkpoint: state.model,
      vid_checkpoint: "ltx-2.3-22b-dev-fp8.safetensors",
      deepseek_key: apikey || undefined,
      ...state.quality,
    };
    const data = await apiPost("/api/generate", payload);
    state.jobId = data.job_id;
    state.scenesDone = 0;
    connectWS(data.job_id);
    toast("任务已提交", "success");
  } catch(e) {
    toast("提交失败: " + e.message, "error");
    state.generating = false;
    document.getElementById("genBtn").disabled = false;
    document.getElementById("genBtn").textContent = "生成";
  }
}

function cancelGeneration() {
  if (!state.jobId) return;
  if (state.ws) state.ws.close();
  state.generating = false;
  state.jobId = null;
  document.getElementById("genBtn").disabled = false;
  document.getElementById("genBtn").textContent = "生成";
  toast("已取消", "warning");
}

// ========== WebSocket ==========
// v9.10: retryCount 提升到模块级，避免 connectWS 每次调用重置为 0
let _wsRetryCount = 0;

function connectWS(jobId) {
  if (state.ws) state.ws.close();
  // v9.10: WS URL 跟随 API 基址动态构造，不再硬编码 localhost
  const wsBase = API.replace(/^http/, "ws");
  const ws = new WebSocket(`${wsBase}/ws/progress/${jobId}`);
  state.ws = ws;

  ws.onopen = () => {
    _wsRetryCount = 0;
    document.getElementById("progressText").textContent = "管道启动中...";
  };

  ws.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data);
      handleWSMessage(msg);
    } catch(e) {}
  };

  ws.onerror = () => {};
  ws.onclose = () => {
    if (state.generating && _wsRetryCount < 5) {
      _wsRetryCount++;
      setTimeout(() => connectWS(jobId), 3000 * _wsRetryCount);
    }
  };
}

function handleWSMessage(msg) {
  const type = msg.type || "";
  if (type === "scene_status") {
    handleSceneStatus(msg);
  } else if (type === "storyboard_done") {
    state.sceneCount = msg.scenes || 0;
    document.getElementById("progressText").textContent = `分镜完成: ${state.sceneCount} 个场景`;
    buildSceneList(state.sceneCount);
  } else if (type === "job_complete") {
    onJobComplete(msg);
  } else if (type === "error") {
    toast(msg.message || "生成错误", "error");
  }
}

function handleSceneStatus(msg) {
  const sid = msg.scene_id;
  document.getElementById("progressText").textContent = `场景 ${sid}: ${msg.status}`;
  if (msg.status === "done") {
    state.scenesDone++;
    updateSceneCard(sid, "done");
  } else if (msg.status === "error") {
    updateSceneCard(sid, "error");
  } else {
    updateSceneCard(sid, "running");
  }
  updateProgress();
}

function buildSceneList(n) {
  const list = document.getElementById("sceneList");
  list.innerHTML = Array.from({length: n}, (_, i) => {
    const pos = ["wide","mid","close"][i%3]||"shot";
    return `<div class="scene-card" data-sid="${i+1}" id="scard${i+1}">
      <div class="thumb" style="width:36px;height:36px;display:flex;align-items:center;justify-content:center;font-size:12px">${i+1}</div>
      <div class="info"><div class="scene-name">场景${i+1} · ${pos}</div><div class="scene-chars">排队中</div></div>
      <span class="scene-status" style="color:var(--text-muted)">⏳</span>
    </div>`;
  }).join("");
}

function updateSceneCard(sid, status) {
  const card = document.getElementById(`scard${sid}`);
  if (!card) return;
  const icons = { done: "✅", error: "❌", running: "🔄" };
  const colors = { done: "var(--success)", error: "var(--error)", running: "var(--primary-light)" };
  card.querySelector(".scene-status").textContent = icons[status] || "⏳";
  card.querySelector(".scene-status").style.color = colors[status] || "";
}

function updateProgress() {
  if (!state.sceneCount) return;
  const pct = Math.round((state.scenesDone / state.sceneCount) * 100);
  document.getElementById("progressFill").style.width = pct + "%";
  const elapsed = (Date.now() - state.startTime) / 1000 / 60;
  const eta = state.scenesDone > 0 ? (elapsed / state.scenesDone) * (state.sceneCount - state.scenesDone) : 0;
  document.getElementById("etaDisp").textContent = eta > 0 ? `~${Math.ceil(eta)}min` : "--";
  document.getElementById("etaElapsed").textContent = `${elapsed.toFixed(1)}min`;
}

function onJobComplete(msg) {
  state.generating = false;
  document.getElementById("genBtn").disabled = false;
  document.getElementById("genBtn").textContent = "生成";
  document.getElementById("progressText").textContent = "✅ 全部完成!";
  document.getElementById("progressFill").style.width = "100%";

  // Show video
  if (msg.merged_video) {
    const v = document.getElementById("playerVideo");
    // v9.10: 处理绝对路径 / 相对路径两种情况, 避免 /output//output/ 双重拼接
    const videoPath = msg.merged_video.startsWith("/") || msg.merged_video.startsWith("http")
      ? msg.merged_video
      : "/output/" + msg.merged_video;
    v.src = videoPath;
    v.parentElement.classList.remove("hidden");
    v.play();
  }

  // Save to history
  const entry = {
    id: state.jobId,
    title: "Novel2Vid生成",
    time: new Date().toLocaleString(),
    scenes: state.sceneCount,
    style: state.style,
  };
  state.history.unshift(entry);
  if (state.history.length > 5) state.history.length = 5;
  localStorage.setItem("nv2v_history", JSON.stringify(state.history));
  renderHistory();

  toast("视频生成完成!", "success");
}

// ========== History ==========
function renderHistory() {
  const el = document.getElementById("historyList");
  if (!el) return;
  el.innerHTML = state.history.map(h => `
    <div class="history-item" onclick="toast('Job: ${h.id}')">
      <div class="hist-title">${h.title}</div>
      <div class="hist-meta">${h.time} · ${h.scenes}场景 · ${h.style}</div>
    </div>
  `).join("") || '<div style="color:var(--text-muted);font-size:12px;text-align:center;padding:20px">暂无历史记录</div>';
}

// ========== Init ==========
document.addEventListener("DOMContentLoaded", () => {
  setupDragDrop();
  refreshOpts();
  renderHistory();
  checkHealth();
  setInterval(checkComfyUI, 30000);
  checkComfyUI();

  // Keyboard shortcut
  document.addEventListener("keydown", e => {
    if (e.ctrlKey && e.key === "Enter") { e.preventDefault(); startGenerate(); }
  });

  // Option binding
  document.querySelectorAll("[data-opt]").forEach(el => {
    el.addEventListener("change", () => {
      const k = el.dataset.opt;
      if (el.type === "checkbox") state.quality[k] = el.checked;
      else if (el.type === "radio") state.quality[k] = el.value;
      refreshOpts();
    });
  });

  // Text input
  document.getElementById("novelInput").addEventListener("input", refreshOpts);
});
