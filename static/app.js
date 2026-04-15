const keywordInput = document.getElementById("keyword-input");
const searchBtn = document.getElementById("search-btn");
const searchStatus = document.getElementById("search-status");
const results = document.getElementById("results");
const timeline = document.getElementById("timeline");
const selectedVideo = document.getElementById("selected-video");
const progressLabel = document.getElementById("progress-label");
const progressPercent = document.getElementById("progress-percent");
const progressFill = document.getElementById("progress-fill");
const progressDetail = document.getElementById("progress-detail");
const chatVideoTitle = document.getElementById("chat-video-title");
const chatContainer = document.getElementById("chat-container");
const chatInput = document.getElementById("chat-input");
const sendBtn = document.getElementById("send-btn");
const chatForm = document.getElementById("chat-form");
const loginBtn = document.getElementById("login-btn");
const refreshVideosBtn = document.getElementById("refresh-videos");
const videoHistory = document.getElementById("video-history");

let activeVideoId = "";
let activeVideoTitle = "";

searchBtn.addEventListener("click", searchVideos);
keywordInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") searchVideos();
});
chatForm.addEventListener("submit", sendMessage);
refreshVideosBtn.addEventListener("click", loadVideos);
loginBtn.addEventListener("click", showLoginInfo);

loadVideos();

async function searchVideos() {
    const keyword = keywordInput.value.trim();
    if (!keyword) return;

    searchBtn.disabled = true;
    searchStatus.textContent = "正在搜索 B 站公开视频...";
    results.innerHTML = "";

    try {
        const response = await fetch("/api/search", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({keyword})
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || "搜索失败");

        renderResults(payload.results || []);
        searchStatus.textContent = payload.results?.length ? `找到 ${payload.results.length} 个结果` : "没有找到匹配视频";
    } catch (error) {
        searchStatus.textContent = error.message;
    } finally {
        searchBtn.disabled = false;
    }
}

function renderResults(items) {
    results.innerHTML = "";
    for (const item of items) {
        const card = document.createElement("article");
        card.className = "result-card";
        card.innerHTML = `
            <div class="cover-wrap">${coverMarkup(item)}</div>
            <div class="result-body">
                <h3>${escapeHtml(item.title)}</h3>
                <p>${escapeHtml(item.author || "未知 UP")} · ${escapeHtml(item.duration || "未知时长")}</p>
                <button>读取这个视频</button>
            </div>
        `;
        card.querySelector("button").addEventListener("click", () => processVideo(item));
        results.appendChild(card);
    }
}

async function processVideo(video) {
    selectedVideo.textContent = video.title;
    timeline.innerHTML = "";
    updateProgress(3, "准备创建任务", "正在把视频加入处理队列...");
    addTimeline("queued", "已选择视频，准备创建任务");
    lockChat();

    const response = await fetch("/api/videos/process", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(video)
    });
    const payload = await response.json();
    if (!response.ok) {
        addTimeline("failed", payload.error || "创建任务失败");
        return;
    }
    watchTask(payload.task_id, video);
}

function watchTask(taskId, video) {
    const source = new EventSource(`/api/tasks/${taskId}/events`);
    source.onmessage = (event) => {
        const payload = JSON.parse(event.data);
        updateProgress(payload.progress ?? 0, statusLabel(payload.status), payload.message);
        if (payload.status !== "heartbeat") {
            addTimeline(payload.status, payload.message);
        }
        if (payload.status === "completed") {
            source.close();
            activeVideoId = payload.video_id;
            activeVideoTitle = video.title;
            unlockChat(video.title);
            appendMessage("系统", "已成功读取视频。现在可以基于该视频上下文提问。");
            loadVideos();
        }
        if (payload.status === "failed") {
            source.close();
        }
    };
    source.onerror = () => {
        updateProgress(100, "连接中断", "任务连接中断，请刷新后查看已读取视频");
        addTimeline("failed", "任务连接中断，请刷新后查看已读取视频");
        source.close();
    };
}

function addTimeline(status, message) {
    const item = document.createElement("div");
    item.className = `timeline-item ${status}`;
    item.innerHTML = `<span></span><p>${escapeHtml(message)}</p>`;
    timeline.appendChild(item);
}

function updateProgress(progress, label, detail) {
    const normalized = Math.max(0, Math.min(100, Number(progress) || 0));
    progressFill.style.width = `${normalized}%`;
    progressPercent.textContent = `${Math.round(normalized)}%`;
    progressLabel.textContent = label || "处理中";
    progressDetail.textContent = detail || "任务正在进行...";
    progressFill.classList.toggle("failed", label === "处理失败" || normalized === 100 && /失败|中断/.test(detail || ""));
}

function statusLabel(status) {
    return {
        queued: "等待处理",
        started: "开始处理",
        downloading: "下载音频",
        downloaded: "下载完成",
        transcribing: "语音转文字",
        transcribed: "转写完成",
        indexing: "构建索引",
        completed: "读取完成",
        failed: "处理失败",
        heartbeat: "仍在处理"
    }[status] || "处理中";
}

async function sendMessage(event) {
    event.preventDefault();
    const message = chatInput.value.trim();
    if (!message || !activeVideoId) return;

    chatInput.value = "";
    appendMessage("你", message, true);
    const aiMessage = appendMessage("Qwen", "");
    sendBtn.disabled = true;

    try {
        const response = await fetch("/api/chat", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Accept": "text/event-stream"
            },
            body: JSON.stringify({video_id: activeVideoId, message})
        });
        if (!response.ok) {
            const payload = await response.json();
            throw new Error(payload.error || "问答失败");
        }
        await streamChat(response, aiMessage.querySelector(".message-content"));
    } catch (error) {
        aiMessage.querySelector(".message-content").textContent = error.message;
    } finally {
        sendBtn.disabled = false;
    }
}

async function streamChat(response, target) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
        const {done, value} = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, {stream: true});
        const parts = buffer.split("\n\n");
        buffer = parts.pop() || "";
        for (const part of parts) {
            const line = part.replace(/^data:\s*/, "");
            if (!line) continue;
            const payload = JSON.parse(line);
            if (payload.error) {
                target.textContent += `\n${payload.error}`;
            } else if (payload.response) {
                target.textContent += payload.response;
            }
            chatContainer.scrollTop = chatContainer.scrollHeight;
        }
    }
}

function appendMessage(role, content, isUser = false) {
    const item = document.createElement("div");
    item.className = `chat-message ${isUser ? "user" : "assistant"}`;
    item.innerHTML = `
        <strong>${escapeHtml(role)}</strong>
        <div class="message-content">${escapeHtml(content)}</div>
    `;
    chatContainer.appendChild(item);
    chatContainer.scrollTop = chatContainer.scrollHeight;
    return item;
}

async function loadVideos() {
    const response = await fetch("/api/videos");
    const payload = await response.json();
    videoHistory.innerHTML = "";
    for (const video of payload.videos || []) {
        const button = document.createElement("button");
        button.className = "history-item";
        button.innerHTML = `<strong>${escapeHtml(video.title || video.video_id)}</strong><span>${escapeHtml(video.updated_at || "")}</span>`;
        button.addEventListener("click", () => {
            activeVideoId = video.video_id;
            activeVideoTitle = video.title || video.video_id;
            unlockChat(activeVideoTitle);
            selectedVideo.textContent = activeVideoTitle;
            appendMessage("系统", `已切换到视频：${activeVideoTitle}`);
        });
        videoHistory.appendChild(button);
    }
    if (!videoHistory.children.length) {
        videoHistory.innerHTML = `<p class="empty">还没有已读取视频</p>`;
    }
}

async function showLoginInfo() {
    const response = await fetch("/api/auth/bilibili/status");
    const payload = await response.json();
    window.open(payload.login_url, "_blank", "noopener");
    alert(`公开视频无需登录。\n如需处理受限视频，请将 Netscape cookies 导出到：\n${payload.cookie_path}`);
}

function unlockChat(title) {
    chatInput.disabled = false;
    sendBtn.disabled = false;
    chatVideoTitle.textContent = title;
}

function lockChat() {
    activeVideoId = "";
    chatInput.disabled = true;
    sendBtn.disabled = true;
    chatVideoTitle.textContent = "正在读取视频...";
}

function coverMarkup(item) {
    const cover = item.cover || "";
    if (!cover) {
        return `<div class="cover-placeholder">B站</div>`;
    }
    const proxied = `/api/image-proxy?url=${encodeURIComponent(cover)}`;
    return `<img src="${escapeAttr(proxied)}" alt="" loading="lazy" onerror="this.replaceWith(createCoverPlaceholder())">`;
}

function createCoverPlaceholder() {
    const placeholder = document.createElement("div");
    placeholder.className = "cover-placeholder";
    placeholder.textContent = "B站";
    return placeholder;
}

function escapeHtml(value) {
    return String(value || "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function escapeAttr(value) {
    return escapeHtml(value).replaceAll("`", "&#096;");
}
