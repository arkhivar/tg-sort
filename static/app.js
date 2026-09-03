let statusInterval = null;

document.addEventListener("DOMContentLoaded", () => {
    const startBtn = document.getElementById("startBtn");
    const loadTopicsBtn = document.getElementById("loadTopicsBtn");
    const importTopicsBtn = document.getElementById("importTopicsBtn");
    const chatIdInput = document.getElementById("chatId");
    const groupSelect = document.getElementById("groupSelect");
    const refreshGroupsBtn = document.getElementById("refreshGroupsBtn");
    const progressCard = document.getElementById("progressCard");
    const progressFill = document.getElementById("progressFill");
    const progressText = document.getElementById("progressText");
    const currentChat = document.getElementById("currentChat");
    const statusText = document.getElementById("statusText");
    const logContainer = document.getElementById("logContainer");
    const statusDot = document.getElementById("statusDot");
    const statusLabel = document.getElementById("statusLabel");
    const userInfo = document.getElementById("userInfo");
    const userName = document.getElementById("userName");
    const userPhone = document.getElementById("userPhone");
    const setupNotice = document.getElementById("setupNotice");
    const sortCard = document.getElementById("sortCard");
    const customOrderSection = document.getElementById("customOrderSection");
    const standardSortOptions = document.getElementById("standardSortOptions");
    const emojiList = document.getElementById("emojiList");
    const knownTopics = document.getElementById("knownTopics");
    const topicCount = document.getElementById("topicCount");
    const topicRoster = document.getElementById("topicRoster");
    const sortByRadios = document.querySelectorAll('input[name="sortBy"]');

    let fetchedEmojis = [];
    let customEmojiOrder = [];
    let draggedElement = null;

    startBtn.addEventListener("click", startSort);
    loadTopicsBtn.addEventListener("click", loadTopics);
    importTopicsBtn.addEventListener("click", importTopics);
    refreshGroupsBtn.addEventListener("click", () => loadGroups(false));
    groupSelect.addEventListener("change", onGroupSelected);
    chatIdInput.addEventListener("input", () => {
        if (groupSelect.value && groupSelect.value !== chatIdInput.value.trim()) {
            groupSelect.value = "";
        }
    });
    document.getElementById("fetchEmojisBtn").addEventListener("click", fetchEmojis);
    sortByRadios.forEach((radio) => radio.addEventListener("change", updateSortOptions));
    updateSortOptions();
    checkBotStatus();
    loadGroups(false);
    statusInterval = setInterval(updateStatus, 1000);

    async function loadGroups(preserveSelection) {
        try {
            const data = await fetch("/chats").then((response) => response.json());
            const chats = data.chats || [];
            const previous = preserveSelection ? groupSelect.value : "";
            groupSelect.innerHTML = chats.length
                ? "<option value=''>Select a group…</option>"
                : "<option value=''>No groups learned yet</option>";
            chats.forEach((chat) => {
                const option = document.createElement("option");
                option.value = String(chat.chat_id);
                const title = chat.title || `Chat ${chat.chat_id}`;
                option.textContent = `${title} — ${chat.topic_count} topic${chat.topic_count === 1 ? "" : "s"}`;
                groupSelect.appendChild(option);
            });
            if (previous && chats.some((chat) => String(chat.chat_id) === previous)) {
                groupSelect.value = previous;
            }
        } catch (error) {
            console.error("Could not load groups:", error);
        }
    }

    function onGroupSelected() {
        const chatId = groupSelect.value;
        if (!chatId) return;
        chatIdInput.value = chatId;
        resetGroupState();
        loadTopics();
    }

    function resetGroupState() {
        fetchedEmojis = [];
        customEmojiOrder = [];
        emojiList.style.display = "none";
        emojiList.innerHTML = "";
        knownTopics.style.display = "none";
        knownTopics.innerHTML = "";
        topicCount.textContent = "";
    }

    function updateSortOptions() {
        const custom = document.querySelector('input[name="sortBy"]:checked').value === "custom";
        customOrderSection.style.display = custom ? "block" : "none";
        standardSortOptions.style.display = custom ? "none" : "block";
        if (!custom) emojiList.style.display = "none";
    }

    async function checkBotStatus() {
        try {
            const data = await fetch("/auth_status").then((response) => response.json());
            if (!data.configured) {
                statusDot.className = "status-dot offline";
                statusLabel.textContent = "BOT_TOKEN not configured";
                setupNotice.style.display = "block";
                sortCard.classList.add("disabled");
                return;
            }
            if (!data.connected) {
                statusDot.className = "status-dot offline";
                statusLabel.textContent = data.error || "Bot is connecting…";
                sortCard.classList.add("disabled");
                return;
            }
            statusDot.className = "status-dot online";
            statusLabel.textContent = data.poller?.running ? "Connected and listening" : "Connected";
            userInfo.style.display = "block";
            sortCard.classList.remove("disabled");
            const bot = data.bot || {};
            userName.textContent = bot.username ? `@${bot.username}` : (bot.first_name || "Bot");
            userPhone.textContent = "Regular Telegram Bot API";
            document.getElementById("userAvatar").textContent = (bot.first_name || "B")[0].toUpperCase();
        } catch (error) {
            statusDot.className = "status-dot offline";
            statusLabel.textContent = "Unable to check bot status";
        }
    }

    async function loadTopics() {
        const chatId = chatIdInput.value.trim();
        if (!chatId) return alert("Enter a group username or numeric chat ID first.");
        loadTopicsBtn.disabled = true;
        loadTopicsBtn.textContent = "Loading…";
        try {
            const data = await fetch(`/topics?chat_id=${encodeURIComponent(chatId)}`).then((response) => response.json());
            if (data.error) throw new Error(data.error);
            renderKnownTopics(data.topics || []);
            topicCount.textContent = `${(data.topics || []).length} known`;
            loadGroups(true);
        } catch (error) {
            alert(`Could not load topics: ${error.message}`);
        } finally {
            loadTopicsBtn.disabled = false;
            loadTopicsBtn.textContent = "Load known topics";
        }
    }

    function renderKnownTopics(topics) {
        if (!topics.length) {
            knownTopics.innerHTML = "<p class='muted'>No topics learned yet. Import a roster or let the bot observe messages.</p>";
        } else {
            knownTopics.innerHTML = topics.map((topic) =>
                `<div><strong>${escapeHtml(topic.title || "Untitled")}</strong> · ID ${topic.topic_id}` +
                `${topic.emoji_id ? ` · emoji ${topic.emoji_id}` : ""}` +
                `${topic.pinned ? " · pinned" : ""}</div>`
            ).join("");
        }
        knownTopics.style.display = "block";
    }

    async function importTopics() {
        const chatId = chatIdInput.value.trim();
        if (!chatId) return alert("Enter a group username or numeric chat ID first.");
        const lines = topicRoster.value.split("\n").map((line) => line.trim()).filter(Boolean);
        if (!lines.length) return alert("Add at least one topic row.");
        const topics = [];
        for (const line of lines) {
            const parts = line.split("|").map((part) => part.trim());
            if (!/^\d+$/.test(parts[0])) return alert(`Invalid topic ID: ${parts[0]}`);
            topics.push({
                topic_id: parts[0],
                title: parts[1] || "",
                emoji_id: parts[2] || null,
                pinned: ["true", "yes", "1"].includes((parts[3] || "").toLowerCase()),
            });
        }
        importTopicsBtn.disabled = true;
        try {
            const response = await fetch("/import_topics", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({chat_id: chatId, topics}),
            });
            const data = await response.json();
            if (data.error) throw new Error(data.error);
            renderKnownTopics(data.topics || []);
            topicCount.textContent = `${(data.topics || []).length} known`;
            loadGroups(true);
            alert("Topic roster saved.");
        } catch (error) {
            alert(`Could not save roster: ${error.message}`);
        } finally {
            importTopicsBtn.disabled = false;
        }
    }

    async function fetchEmojis() {
        const chatId = chatIdInput.value.trim();
        if (!chatId) return alert("Enter a group username or numeric chat ID first.");
        const button = document.getElementById("fetchEmojisBtn");
        button.disabled = true;
        button.textContent = "Fetching…";
        try {
            const data = await fetch("/fetch_emojis", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({chat_id: chatId}),
            }).then((response) => response.json());
            if (data.error) throw new Error(data.error);
            fetchedEmojis = data.emojis || [];
            displayEmojiList(fetchedEmojis);
        } catch (error) {
            alert(`Could not fetch emoji IDs: ${error.message}`);
        } finally {
            button.disabled = false;
            button.textContent = fetchedEmojis.length ? "↻ Re-fetch emoji IDs" : "1. Fetch emoji IDs";
        }
    }

    function displayEmojiList(emojis) {
        emojiList.innerHTML = "<h3>2. Arrange emoji order</h3><small>Uncheck emojis to exclude their topics.</small>";
        const list = document.createElement("div");
        list.id = "emojiSortableList";
        emojis.forEach((emoji) => {
            const item = document.createElement("label");
            item.className = "emoji-item";
            item.draggable = true;
            item.dataset.emojiId = String(emoji.emoji_id);
            item.innerHTML = `<input type="checkbox" checked class="emoji-checkbox"><strong>${escapeHtml(emoji.emoji_id)}</strong><span>${escapeHtml(emoji.example_title || "Untitled")} (${emoji.count})</span>`;
            item.addEventListener("dragstart", () => {
                draggedElement = item;
                item.style.opacity = "0.45";
            });
            item.addEventListener("dragover", (event) => event.preventDefault());
            item.addEventListener("drop", (event) => {
                event.preventDefault();
                if (!draggedElement || draggedElement === item) return;
                const items = [...list.querySelectorAll(".emoji-item")];
                if (items.indexOf(draggedElement) < items.indexOf(item)) {
                    item.parentNode.insertBefore(draggedElement, item.nextSibling);
                } else {
                    item.parentNode.insertBefore(draggedElement, item);
                }
            });
            item.addEventListener("dragend", () => {
                item.style.opacity = "1";
                draggedElement = null;
            });
            list.appendChild(item);
        });
        emojiList.appendChild(list);
        emojiList.style.display = "block";
    }

    async function startSort() {
        const chatId = chatIdInput.value.trim();
        const sortBy = document.querySelector('input[name="sortBy"]:checked').value;
        const sortOrder = document.getElementById("sortOrder").value;
        if (!chatId) return alert("Enter a group username or numeric chat ID.");
        const body = {
            chat_id: chatId,
            sort_by: sortBy,
            sort_order: sortOrder,
            skip_pinned: document.getElementById("skipPinned").checked,
            custom_message: document.getElementById("customMessage").value.trim() || ".",
        };
        if (sortBy === "custom") {
            customEmojiOrder = [...document.querySelectorAll(".emoji-item")]
                .filter((item) => item.querySelector(".emoji-checkbox").checked)
                .map((item) => item.dataset.emojiId);
            if (!customEmojiOrder.length) return alert("Select at least one emoji.");
            body.custom_emoji_order = customEmojiOrder;
        }
        startBtn.disabled = true;
        startBtn.textContent = "Starting…";
        try {
            const data = await fetch("/start_sort", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify(body),
            }).then((response) => response.json());
            if (data.error) throw new Error(data.error);
            progressCard.style.display = "block";
        } catch (error) {
            alert(`Could not start sort: ${error.message}`);
            startBtn.disabled = false;
            startBtn.textContent = "Start sort";
        }
    }

    async function updateStatus() {
        try {
            const data = await fetch("/status").then((response) => response.json());
            currentChat.textContent = data.current_chat || "-";
            progressFill.style.width = `${data.total ? (data.progress / data.total) * 100 : 0}%`;
            progressText.textContent = `${data.progress} / ${data.total}`;
            if (data.running) {
                statusText.textContent = "Running…";
                statusText.style.color = "#667eea";
            } else if (data.error) {
                statusText.textContent = "Error";
                statusText.style.color = "#c33";
            } else if (data.total > 0 && data.progress >= data.total) {
                statusText.textContent = "Completed";
                statusText.style.color = "#27834b";
            } else {
                statusText.textContent = "Idle";
                statusText.style.color = "#666";
            }
            if (data.logs?.length) {
                logContainer.innerHTML = data.logs.map((log) => `<div class="log-entry">${escapeHtml(log)}</div>`).join("");
                logContainer.scrollTop = logContainer.scrollHeight;
            }
            startBtn.disabled = data.running;
            if (!data.running) startBtn.textContent = "Start sort";
        } catch (error) {
            console.error("Status update error:", error);
        }
    }

    function escapeHtml(value) {
        return String(value).replace(/[&<>"']/g, (char) => ({
            "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
        }[char]));
    }
});