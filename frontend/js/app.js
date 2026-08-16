console.log("%c Knowledge Assistant JS MERGED v20260816 LOADED ","background:#101e3b;color:white;padding:6px;border-radius:5px;font-weight:bold");

// Apply the saved theme before first paint so the sign-in screen and the
// application shell never flash the wrong palette.
(function applySavedTheme() {
  const saved = localStorage.getItem("hr_theme")
    || (window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  document.body?.classList.toggle("dark", saved === "dark");
})();

document.addEventListener("DOMContentLoaded", () => {
  const API = "";

  const state = {
    token: localStorage.getItem("hr_access_token") || "",
    user: JSON.parse(localStorage.getItem("hr_user") || "null"),
    threadId: localStorage.getItem("hr_thread_id") || crypto.randomUUID(),
    assistant: null
  };

  const authScreen = document.getElementById("authScreen");
  const appShell = document.getElementById("appShell");

  // Two-letter monogram for avatars, derived from the signed-in user.
  function initialsFor(user) {
    const name = String(user?.full_name || "").trim();
    if (name) {
      const parts = name.split(/\s+/);
      const letters = parts.length > 1
        ? parts[0][0] + parts[parts.length - 1][0]
        : parts[0].slice(0, 2);
      return letters.toUpperCase();
    }
    const email = String(user?.email || "").trim();
    return email ? email.slice(0, 2).toUpperCase() : "··";
  }

  function setAuthenticated(token, user) {
    state.token = token;
    state.user = user;
    localStorage.setItem("hr_access_token", token);
    localStorage.setItem("hr_user", JSON.stringify(user));
    if (authScreen) authScreen.classList.add("hidden");
    if (appShell) appShell.classList.remove("hidden");
    if (document.getElementById("companyName")) document.getElementById("companyName").textContent = user.company_name;
    if (document.getElementById("employeeId")) document.getElementById("employeeId").textContent = user.email;
    if (document.getElementById("accountMenuCompany")) document.getElementById("accountMenuCompany").textContent = user.company_name;
    if (document.getElementById("accountMenuEmail")) document.getElementById("accountMenuEmail").textContent = user.email;
    const userAvatar = document.getElementById("userAvatar");
    if (userAvatar) {
      userAvatar.firstChild
        ? (userAvatar.firstChild.nodeValue = initialsFor(user))
        : userAvatar.prepend(initialsFor(user));
      userAvatar.title = user.full_name || user.email || "";
    }
    const adminNavButton = document.getElementById("adminNavButton");
    if (adminNavButton) adminNavButton.classList.toggle("hidden", user.role !== "company_admin");
  }

  function clearAuthentication() {
    closeAccountMenu();
    state.token = "";
    state.user = null;
    localStorage.removeItem("hr_access_token");
    localStorage.removeItem("hr_user");
    localStorage.removeItem("hr_thread_id");
    if (appShell) appShell.classList.add("hidden");
    if (authScreen) authScreen.classList.remove("hidden");
  }

  async function authFetch(url, options = {}) {
    const headers = new Headers(options.headers || {});
    if (state.token) headers.set("Authorization", `Bearer ${state.token}`);
    const response = await fetch(url, { ...options, headers });
    if (response.status === 401) {
      clearAuthentication();
      throw new Error("Your session has expired. Please sign in again.");
    }
    return response;
  }

  async function loadAssistantConfiguration() {
    const response = await authFetch(`${API}/api/assistants/current`);
    if (!response.ok) throw new Error("Unable to load assistant configuration");
    applyAssistantConfiguration(await response.json());
  }

  function applyAssistantConfiguration(config) {
    state.assistant = config;
    document.title = config.name || "Knowledge Assistant";
    if ($("assistantName")) $("assistantName").textContent = config.name;
    if ($("assistantBrandName")) $("assistantBrandName").textContent = config.name;
    if ($("assistantDescription")) $("assistantDescription").textContent = config.description;
    if ($("assistantBrandDescription")) $("assistantBrandDescription").textContent = config.description;
    const configuredPlaceholder = (config.placeholder || "").trim();
    const usesLegacyPlaceholder = [
      "Ask a question about your knowledge base...",
      "Ask a question about your knowledge base…",
      "Ask a question…",
    ].includes(configuredPlaceholder);
    if (input) {
      input.placeholder = !configuredPlaceholder || usesLegacyPlaceholder
        ? "Ask Nexa anything..."
        : configuredPlaceholder;
    }
    const hasUserMessage = Boolean(chat?.querySelector(".message.user"));
    const existingMessages = chat?.querySelectorAll(".message") || [];
    if (!hasUserMessage && existingMessages.length <= 1 && chat) {
      chat.innerHTML = "";
      if (config.welcome_message) addMessage("assistant", config.welcome_message);
    }
    renderStarterQuestions();
  }

  async function initAuth() {
    if (!state.token) {
      clearAuthentication();
      return false;
    }
    try {
      const response = await authFetch(`${API}/api/auth/me`);
      if (!response.ok) throw new Error("Session invalid");
      const user = await response.json();
      setAuthenticated(state.token, user);
      return true;
    } catch (_) {
      clearAuthentication();
      return false;
    }
  }

  const $ = (id) => document.getElementById(id);
  const loginForm = document.getElementById("loginForm");
  const registerForm = document.getElementById("registerForm");
  const loginView = document.getElementById("loginView");
  const registerView = document.getElementById("registerView");
  const loginError = document.getElementById("loginError");
  const registerError = document.getElementById("registerError");

  document.getElementById("showRegister")?.addEventListener("click", () => {
    loginView?.classList.add("hidden");
    registerView?.classList.remove("hidden");
  });
  document.getElementById("showLogin")?.addEventListener("click", () => {
    registerView?.classList.add("hidden");
    loginView?.classList.remove("hidden");
  });

  loginForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    loginError?.classList.add("hidden");
    const form = new URLSearchParams();
    form.set("username", document.getElementById("loginEmail").value);
    form.set("password", document.getElementById("loginPassword").value);
    try {
      const response = await fetch(`${API}/api/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: form.toString()
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "Login failed");
      setAuthenticated(result.access_token, result.user);
      await loadAssistantConfiguration();
      await loadInitialConversation();
    } catch (error) {
      if (loginError) { loginError.textContent = error.message; loginError.classList.remove("hidden"); }
    }
  });

  registerForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    registerError?.classList.add("hidden");
    try {
      const response = await fetch(`${API}/api/auth/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          company_name: document.getElementById("registerCompany").value,
          full_name: document.getElementById("registerName").value,
          email: document.getElementById("registerEmail").value,
          password: document.getElementById("registerPassword").value
        })
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "Registration failed");
      setAuthenticated(result.access_token, result.user);
      await loadAssistantConfiguration();
      await loadInitialConversation();
    } catch (error) {
      if (registerError) { registerError.textContent = error.message; registerError.classList.remove("hidden"); }
    }
  });

  document.getElementById("logoutButton")?.addEventListener("click", () => {
    closeAccountMenu();
    closeUserModal();
    hideAdminDashboard();
    clearAuthentication();
  });


  const chat = $("chat");
  const input = $("message");
  const working = $("working");
  const fileInput = $("fileInput");
  let pendingSessionDeletion = null;
  let sessionDeleteReturnFocus = null;
  let sessionSearchQuery = "";
  let sessionSearchTimer = null;
  let sessionSearchRequestId = 0;

  if (!chat || !input) {
    console.error("Knowledge Assistant: required chat elements are missing.", {
      chat: !!chat,
      message: !!input
    });
    return;
  }

  if ($("employeeId") && state.user) $("employeeId").textContent = state.user.email;

  const logo = `
    <svg viewBox="0 0 64 64" aria-hidden="true">
      <path d="M19 50V25l6-5 6 5v25M31 50V16l7-5 7 5v34M13 50h38"
            fill="none" stroke="#1769e8" stroke-width="2.7" stroke-linejoin="round"/>
      <path d="M23 31h4M23 37h4M35 23h5M35 29h5M35 35h5"
            stroke="#24a6a3" stroke-width="2.2" stroke-linecap="round"/>
    </svg>`;

  function syncConversationPresentation() {
    const main = document.querySelector("main.main");
    const hasUserMessage = Boolean(chat?.querySelector(".message.user"));
    main?.classList.toggle("has-active-conversation", hasUserMessage);
  }

  function renderAssistantContent(bubble, text) {
    const content = String(text ?? "");
    bubble.classList.add("markdown-body");

    try {
      if (window.NexaMarkdown?.render) {
        bubble.innerHTML = window.NexaMarkdown.render(content);
      } else {
        bubble.textContent = content;
      }
    } catch (error) {
      console.error("Assistant response rendering failed:", error);
      bubble.textContent = content;
    }
  }

  function addMessage(role, text = "", time = "") {
    const row = document.createElement("div");
    row.className = `message ${role}`;

    if (role === "assistant") {
      const icon = document.createElement("div");
      icon.className = "bot-icon";
      icon.innerHTML = logo;
      row.appendChild(icon);
    }

    const bubble = document.createElement("div");
    bubble.className = "bubble";
    if (role === "assistant") renderAssistantContent(bubble, text);
    else bubble.textContent = text;

    if (time) {
      const meta = document.createElement("div");
      meta.className = "message-meta";
      meta.textContent = time;
      bubble.appendChild(meta);
    }

    row.appendChild(bubble);

    if (role === "user") {
      const avatar = document.createElement("div");
      avatar.className = "avatar user-avatar";
      avatar.textContent = initialsFor(state.user);
      avatar.title = state.user?.full_name || state.user?.email || "";
      row.appendChild(avatar);
    }

    chat.appendChild(row);
    chat.scrollTop = chat.scrollHeight;
    syncConversationPresentation();
    renderStarterQuestions();
    return bubble;
  }

  function renderStarterQuestions() {
    const container = $("starterQuestions");
    if (!container) return;
    const questions = Array.isArray(state.assistant?.starter_questions)
      ? state.assistant.starter_questions.filter(Boolean)
      : [];
    const hasUserMessage = Boolean(chat?.querySelector(".message.user"));
    container.innerHTML = "";
    container.classList.toggle("hidden", !questions.length || hasUserMessage);
    if (!questions.length || hasUserMessage) return;
    questions.forEach(question => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "starter-question";
      button.textContent = question;
      button.addEventListener("click", () => {
        input.value = question;
        resizeInput();
        input.focus();
      });
      container.appendChild(button);
    });
  }

  function nowTime() {
    return new Date().toLocaleTimeString([], {
      hour: "numeric",
      minute: "2-digit"
    });
  }

  function setWorking(text, visible = true) {
    if (!working) return;
    working.textContent = text;
    working.classList.toggle("hidden", !visible);
  }

  // =========================================================
  // TEXT-TO-SPEECH
  // Speaks only newly generated assistant responses.
  // =========================================================

  let speechEnabled =
    localStorage.getItem("hr_voice_enabled") !== "false";

  function cleanSpeechText(text) {
    return String(text || "")
      .replace(/```[\s\S]*?```/g, " ")
      .replace(/https?:\/\/\S+/g, " ")
      .replace(/\*\*(.*?)\*\*/g, "$1")
      .replace(/__(.*?)__/g, "$1")
      .replace(/[*_`#>-]/g, " ")
      .replace(/\[(.*?)\]\(.*?\)/g, "$1")
      .replace(/\s+/g, " ")
      .trim();
  }

  function speakResponse(text) {
    if (!speechEnabled) return;

    if (!("speechSynthesis" in window) ||
        !("SpeechSynthesisUtterance" in window)) {
      console.warn("Text-to-speech is not supported by this browser.");
      return;
    }

    const cleanText = cleanSpeechText(text);

    if (!cleanText) return;

    // Stop any previous response from being spoken.
    window.speechSynthesis.cancel();

    const utterance =
      new SpeechSynthesisUtterance(cleanText);

    utterance.lang = "en-US";
    utterance.rate = 1.0;
    utterance.pitch = 1.0;
    utterance.volume = 1.0;

    // Prefer a browser English voice when available.
    const voices =
      window.speechSynthesis.getVoices();

    const preferredVoice =
      voices.find(v =>
        /^en-US$/i.test(v.lang)
      ) ||
      voices.find(v =>
        /^en-/i.test(v.lang)
      ) ||
      voices.find(v =>
        /English/i.test(v.name)
      );

    if (preferredVoice) {
      utterance.voice = preferredVoice;
    }

    utterance.onerror = (event) => {
      console.warn(
        "Text-to-speech error:",
        event.error
      );
    };

    window.speechSynthesis.speak(utterance);
  }

  // Chrome can load voices asynchronously.
  if ("speechSynthesis" in window) {
    window.speechSynthesis.onvoiceschanged = () => {
      window.speechSynthesis.getVoices();
    };
  }

  // Call this from the user's send action so Chrome has a
  // user interaction associated with speech playback.
  function prepareSpeech() {
    if (!speechEnabled) return;

    if ("speechSynthesis" in window) {
      window.speechSynthesis.resume();
    }
  }

  async function sendMessage(text) {
    text = text.trim();
    if (!text) return;

    // The send button / Enter key is a user interaction.
    // Prepare browser speech playback before the async API call.
    prepareSpeech();

    addMessage("user", text, nowTime());
    input.value = "";
    resizeInput();

    // Show animated thinking while the backend is working.
    showThinking("Searching knowledge base...");
    setWorking("", false);

    let bubble = null;
    let answer = "";

    // Create the real assistant bubble only when the first response arrives.
    const ensureAssistantBubble = () => {
      if (!bubble) {
        hideThinking();
        bubble = addMessage("assistant", "");
      }
      return bubble;
    };

    try {
      const response = await authFetch(`${API}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: state.user.id,
          thread_id: state.threadId,
          message: text
        })
      });

      if (!response.ok) {
        const errorText = await response.text();
        hideThinking();
        addMessage(
          "assistant",
          errorText || "Sorry, the request failed.",
          nowTime()
        );
        return;
      }

      // Some backend configurations may return normal JSON instead of SSE.
      if (!response.body) {
        const contentType = response.headers.get("content-type") || "";

        if (contentType.includes("application/json")) {
          const data = await response.json();
          const finalText =
            data.answer ||
            data.text ||
            data.response ||
            data.message ||
            "";

          hideThinking();

          if (finalText) {
            addMessage("assistant", finalText, nowTime());
            speakResponse(finalText);
          } else {
            addMessage("assistant", "I received an empty response from the server.", nowTime());
          }

          return;
        }

        const textResponse = await response.text();
        hideThinking();
        addMessage("assistant", textResponse, nowTime());
        speakResponse(textResponse);
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();

        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // Support both LF and CRLF SSE separators.
        const chunks = buffer.split(/\r?\n\r?\n/);
        buffer = chunks.pop() || "";

        for (const chunk of chunks) {
          const lines = chunk.split(/\r?\n/);

          for (const line of lines) {
            if (!line.startsWith("data:")) continue;

            const payload = line.slice(5).trim();

            if (!payload) continue;

            // Backend may send an SSE terminator.
            if (payload === "[DONE]") {
              continue;
            }

            try {
              const event = JSON.parse(payload);

              if (event.type === "status") {
                if (!bubble) {
                  updateThinkingLabel(event.label || "Thinking...");
                }
                continue;
              }

              if (event.type === "tool") {
                // The backend emitted this only after a real tool operation.
                if (!bubble) {
                  updateThinkingLabel(
                    event.label || activityLabelForTool(event.tool)
                  );
                }
                continue;
              }

              if (event.type === "token") {
                const textPart = event.text || "";

                if (textPart) {
                  answer += textPart;

                  const assistantBubble =
                    ensureAssistantBubble();

                  renderAssistantContent(assistantBubble, answer);

                  chat.scrollTop = chat.scrollHeight;
                }

                continue;
              }

              if (event.type === "done") {
                const finalText =
                  event.text ||
                  event.answer ||
                  answer;

                if (finalText) {
                  answer = finalText;

                  const assistantBubble =
                    ensureAssistantBubble();

                  renderAssistantContent(assistantBubble, answer);
                  chat.scrollTop = chat.scrollHeight;
                }

                continue;
              }

              // Be tolerant of a backend that sends a plain
              // {answer:"..."} event without type.
              if (event.answer || event.text) {
                const textPart =
                  event.answer || event.text || "";

                answer += textPart;

                const assistantBubble =
                  ensureAssistantBubble();

                renderAssistantContent(assistantBubble, answer);

                chat.scrollTop = chat.scrollHeight;
              }

            } catch (err) {
              console.debug("SSE parse:", payload, err);
            }
          }
        }
      }

      // Flush any final buffered SSE event.
      const finalChunk = buffer.trim();

      if (finalChunk.startsWith("data:")) {
        const payload = finalChunk.slice(5).trim();

        if (payload && payload !== "[DONE]") {
          try {
            const event = JSON.parse(payload);

            const finalText =
              event.text ||
              event.answer ||
              answer;

            if (finalText) {
              answer = finalText;

              const assistantBubble =
                ensureAssistantBubble();

              renderAssistantContent(assistantBubble, answer);
            }
          } catch (err) {
            console.debug("Final SSE parse:", err);
          }
        }
      }

      // If the stream ended without a token/done event, don't leave
      // the user stuck on "Thinking".
      if (!answer) {
        hideThinking();
        addMessage(
          "assistant",
          "I received an empty response from the server.",
          nowTime()
        );
      } else {
        hideThinking();

        // Speak only after the complete response is available.
        // This prevents speech from restarting on every token.
        speakResponse(answer);
      }

      await loadSessions();

    } catch (err) {
      console.error("Chat request failed:", err);

      hideThinking();

      if (bubble) {
        renderAssistantContent(
          bubble,
          "Sorry, something went wrong while generating the response."
        );
      } else {
        addMessage(
          "assistant",
          "Sorry, something went wrong while generating the response.",
          nowTime()
        );
      }
    } finally {
      hideThinking();
      setWorking("", false);
    }
  }

  function renderEmptySessions(container, searchQuery = "") {
    if (!container) return;
    const searching = Boolean(searchQuery.trim());
    container.innerHTML = `
      <div class="empty-sessions">
        <span class="empty-sessions-icon">⌁</span>
        <span>${searching ? "No chats found" : "No recent chats yet"}</span>
        <small>${searching ? "Try a different chat title." : "Start a new conversation."}</small>
      </div>
    `;
  }

  function isSessionSearchOpen() {
    return !document.getElementById("sessionSearchPanel")?.classList.contains("hidden");
  }

  function updateSessionSearchControls() {
    const input = document.getElementById("sessionSearchInput");
    const clearButton = document.getElementById("sessionSearchClear");
    clearButton?.classList.toggle("hidden", !input?.value);
  }

  function announceSessionSearch(message) {
    const status = document.getElementById("sessionSearchStatus");
    if (status) status.textContent = message;
  }

  function openSessionSearch() {
    const button = document.getElementById("sessionSearchButton");
    const panel = document.getElementById("sessionSearchPanel");
    const input = document.getElementById("sessionSearchInput");
    if (!panel || !input) return;
    panel.classList.remove("hidden");
    button?.setAttribute("aria-expanded", "true");
    input.focus();
    input.select();
  }

  function closeSessionSearch(returnFocus = true) {
    const button = document.getElementById("sessionSearchButton");
    const panel = document.getElementById("sessionSearchPanel");
    const input = document.getElementById("sessionSearchInput");
    clearTimeout(sessionSearchTimer);
    sessionSearchQuery = "";
    sessionSearchRequestId += 1;
    if (input) input.value = "";
    updateSessionSearchControls();
    announceSessionSearch("");
    panel?.classList.add("hidden");
    button?.setAttribute("aria-expanded", "false");
    loadSessions();
    if (returnFocus) button?.focus();
  }

  function initializeSessionSearch() {
    const button = document.getElementById("sessionSearchButton");
    const input = document.getElementById("sessionSearchInput");
    const clearButton = document.getElementById("sessionSearchClear");
    const closeButton = document.getElementById("sessionSearchClose");
    if (!button || !input) return;

    button.addEventListener("click", () => {
      if (isSessionSearchOpen()) closeSessionSearch();
      else openSessionSearch();
    });

    input.addEventListener("input", () => {
      clearTimeout(sessionSearchTimer);
      updateSessionSearchControls();
      const nextQuery = input.value.trim();
      if (!nextQuery) {
        sessionSearchQuery = "";
        announceSessionSearch("");
        loadSessions();
        return;
      }
      announceSessionSearch("Searching chats");
      sessionSearchTimer = setTimeout(() => {
        sessionSearchQuery = nextQuery;
        loadSessions();
      }, 160);
    });

    input.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        closeSessionSearch();
      } else if (event.key === "ArrowDown") {
        const firstResult = document.querySelector("#sessions .session");
        if (firstResult) {
          event.preventDefault();
          firstResult.focus();
        }
      }
    });

    clearButton?.addEventListener("click", () => {
      clearTimeout(sessionSearchTimer);
      input.value = "";
      sessionSearchQuery = "";
      updateSessionSearchControls();
      announceSessionSearch("");
      loadSessions();
      input.focus();
    });
    closeButton?.addEventListener("click", () => closeSessionSearch());
  }

  function closeSessionMenus(returnFocus = false) {
    document.querySelectorAll(".session-row.menu-open").forEach((row) => {
      const trigger = row.querySelector(".session-menu-trigger");
      const menu = row.querySelector(".session-menu");
      row.classList.remove("menu-open");
      menu?.classList.add("hidden");
      trigger?.setAttribute("aria-expanded", "false");
      if (returnFocus) trigger?.focus();
    });
  }

  function focusSessionMenuTrigger(threadId) {
    const trigger = [...document.querySelectorAll(".session-menu-trigger")]
      .find((item) => item.dataset.threadId === threadId);
    trigger?.focus();
  }

  function setSessionMenuOpen(row, open, focusTarget = null) {
    const trigger = row.querySelector(".session-menu-trigger");
    const menu = row.querySelector(".session-menu");
    if (!trigger || !menu) return;

    closeSessionMenus();
    if (!open) return;

    row.classList.add("menu-open");
    menu.classList.remove("hidden", "opens-up");
    trigger.setAttribute("aria-expanded", "true");

    const recentChats = document.getElementById("sessions");
    if (recentChats && menu.getBoundingClientRect().bottom > recentChats.getBoundingClientRect().bottom) {
      menu.classList.add("opens-up");
    }

    const items = [...menu.querySelectorAll('[role="menuitem"]:not(:disabled)')];
    if (focusTarget === "first") items[0]?.focus();
    if (focusTarget === "last") items.at(-1)?.focus();
  }

  function beginSessionRename(row, session, currentTitle) {
    closeSessionMenus();
    row.classList.add("renaming");

    const form = document.createElement("form");
    form.className = "session-rename-form";

    const renameInput = document.createElement("input");
    renameInput.className = "session-rename-input";
    renameInput.type = "text";
    renameInput.value = currentTitle;
    renameInput.maxLength = 80;
    renameInput.required = true;
    renameInput.setAttribute("aria-label", "Conversation title");

    const actions = document.createElement("span");
    actions.className = "session-rename-actions";

    const saveButton = document.createElement("button");
    saveButton.type = "submit";
    saveButton.textContent = "✓";
    saveButton.setAttribute("aria-label", "Save conversation title");

    const cancelButton = document.createElement("button");
    cancelButton.type = "button";
    cancelButton.textContent = "×";
    cancelButton.setAttribute("aria-label", "Cancel renaming");

    actions.append(saveButton, cancelButton);
    form.append(renameInput, actions);
    row.replaceChildren(form);

    const cancelRename = async () => {
      await loadSessions();
      focusSessionMenuTrigger(session.thread_id);
    };

    cancelButton.addEventListener("click", cancelRename);
    renameInput.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        cancelRename();
      } else if (event.key === "Enter" && !event.isComposing) {
        event.preventDefault();
        form.requestSubmit();
      }
    });

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const title = renameInput.value.trim();
      if (!title) {
        renameInput.setCustomValidity("Enter a conversation title");
        renameInput.reportValidity();
        return;
      }

      renameInput.setCustomValidity("");
      renameInput.disabled = true;
      saveButton.disabled = true;
      cancelButton.disabled = true;
      try {
        const response = await authFetch(`${API}/api/sessions/${encodeURIComponent(session.thread_id)}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title })
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(result.detail || "Unable to rename chat");
        await loadSessions();
        focusSessionMenuTrigger(session.thread_id);
      } catch (error) {
        renameInput.disabled = false;
        saveButton.disabled = false;
        cancelButton.disabled = false;
        renameInput.setCustomValidity(error.message || "Unable to rename chat");
        renameInput.reportValidity();
        renameInput.focus();
      }
    });

    renameInput.focus();
    renameInput.select();
  }

  function closeSessionDeleteModal(returnFocus = true) {
    const modal = document.getElementById("sessionDeleteModal");
    modal?.classList.add("hidden");
    if (modal) modal.inert = true;
    pendingSessionDeletion = null;
    const focusTarget = sessionDeleteReturnFocus;
    sessionDeleteReturnFocus = null;
    if (returnFocus && focusTarget?.isConnected) focusTarget.focus();
  }

  function openSessionDeleteModal(session, trigger) {
    const modal = document.getElementById("sessionDeleteModal");
    const error = document.getElementById("sessionDeleteError");
    if (!modal) return;
    closeSessionMenus();
    pendingSessionDeletion = session;
    sessionDeleteReturnFocus = trigger;
    if (error) {
      error.textContent = "";
      error.classList.add("hidden");
    }
    modal.classList.remove("hidden");
    modal.inert = false;
    requestAnimationFrame(() => document.getElementById("cancelSessionDelete")?.focus());
  }

  function initializeSessionManagement() {
    const modal = document.getElementById("sessionDeleteModal");
    const cancelButton = document.getElementById("cancelSessionDelete");
    const confirmButton = document.getElementById("confirmSessionDelete");
    if (modal) modal.inert = true;

    document.addEventListener("pointerdown", (event) => {
      if (!event.target.closest(".session-actions")) closeSessionMenus();
    });

    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      if (modal && !modal.classList.contains("hidden")) {
        event.preventDefault();
        closeSessionDeleteModal();
        return;
      }
      closeSessionMenus(true);
    });

    modal?.addEventListener("pointerdown", (event) => {
      if (event.target === modal) closeSessionDeleteModal();
    });

    modal?.addEventListener("keydown", (event) => {
      if (event.key !== "Tab") return;
      const items = [cancelButton, confirmButton].filter((item) => item && !item.disabled);
      if (!items.length) return;
      const first = items[0];
      const last = items.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });

    cancelButton?.addEventListener("click", () => closeSessionDeleteModal());
    confirmButton?.addEventListener("click", async () => {
      const session = pendingSessionDeletion;
      if (!session) return;
      const deletingActiveSession = session.thread_id === state.threadId;
      const error = document.getElementById("sessionDeleteError");
      confirmButton.disabled = true;
      if (cancelButton) cancelButton.disabled = true;
      try {
        const response = await authFetch(`${API}/api/sessions/${encodeURIComponent(session.thread_id)}`, {
          method: "DELETE"
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(result.detail || "Unable to delete chat");
        closeSessionDeleteModal(false);
        if (deletingActiveSession) await newChat();
        else await loadSessions();
      } catch (deleteError) {
        if (error) {
          error.textContent = deleteError.message || "Unable to delete chat";
          error.classList.remove("hidden");
        }
      } finally {
        confirmButton.disabled = false;
        if (cancelButton) cancelButton.disabled = false;
      }
    });
  }

  async function loadSessions() {
    const container = document.getElementById("sessions");

    if (!container) {
      console.error("❌ #sessions not found");
      return;
    }

    const requestId = ++sessionSearchRequestId;
    const searchQuery = sessionSearchQuery;
    console.log("✅ Rendering recent chats");

    try {
      const search = searchQuery ? `?q=${encodeURIComponent(searchQuery)}` : "";
      const response = await authFetch(`${API}/api/sessions${search}`);

      if (!response.ok) {
        console.error(
          "Session API failed:",
          response.status
        );
        return [];
      }

      const sessions = await response.json();

      if (requestId !== sessionSearchRequestId) return sessions;

      console.log("Sessions:", sessions);

      container.innerHTML = "";

      if (!sessions || sessions.length === 0) {
        renderEmptySessions(container, searchQuery);
        announceSessionSearch(searchQuery ? "No chats found" : "");
        return [];
      }

      announceSessionSearch(
        searchQuery
          ? `${sessions.length} chat${sessions.length === 1 ? "" : "s"} found`
          : ""
      );

      sessions.forEach((session) => {

        const row = document.createElement("div");
        row.className = "session-row";

        const button =
          document.createElement("button");

        button.type = "button";

        button.className =
          "session" +
          (
            session.thread_id === state.threadId
              ? " active"
              : ""
          );


        /*
         * CHAT SVG
         */
        const icon =
          document.createElement("span");

        icon.className =
          "session-icon";

        icon.innerHTML = `
        <svg
          viewBox="0 0 24 24"
          aria-hidden="true"
        >
          <path
            d="M5 5h14v11H9l-4 4V5z"
          ></path>

          <path
            d="M8 9h8"
          ></path>

          <path
            d="M8 12h5"
          ></path>
        </svg>
      `;


        /*
         * TEXT
         */
        const copy =
          document.createElement("span");

        copy.className =
          "session-copy";


        const title =
          document.createElement("b");

        title.textContent =
          session.title ||
          session.name ||
          "New chat";


        const date =
          document.createElement("span");

        date.textContent =
          formatSessionDate(
            session.updated_at ||
            session.created_at
          );


        copy.appendChild(title);
        copy.appendChild(date);

        button.appendChild(icon);
        button.appendChild(copy);


        /*
         * OPEN CHAT
         */
        button.addEventListener(
          "click",
          async () => {

            console.log(
              "Opening chat:",
              session.thread_id
            );

            state.threadId =
              session.thread_id;

            localStorage.setItem(
              "hr_thread_id",
              state.threadId
            );

            closeSessionMenus();
            await loadHistory();
            await loadSessions();
          }
        );

        button.addEventListener("keydown", (event) => {
          if (!isSessionSearchOpen() || !["ArrowDown", "ArrowUp"].includes(event.key)) return;
          const results = [...container.querySelectorAll(".session")];
          const current = results.indexOf(button);
          if (event.key === "ArrowUp" && current === 0) {
            event.preventDefault();
            document.getElementById("sessionSearchInput")?.focus();
            return;
          }
          const next = event.key === "ArrowDown" ? current + 1 : current - 1;
          if (results[next]) {
            event.preventDefault();
            results[next].focus();
          }
        });


        const actions = document.createElement("div");
        actions.className = "session-actions";

        const menuTrigger = document.createElement("button");
        menuTrigger.type = "button";
        menuTrigger.className = "session-menu-trigger";
        menuTrigger.dataset.threadId = session.thread_id;
        menuTrigger.setAttribute("aria-label", `More actions for ${title.textContent}`);
        menuTrigger.setAttribute("aria-haspopup", "menu");
        menuTrigger.setAttribute("aria-expanded", "false");
        menuTrigger.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="5" cy="12" r="1.4"/><circle cx="12" cy="12" r="1.4"/><circle cx="19" cy="12" r="1.4"/></svg>`;

        const menu = document.createElement("div");
        menu.className = "session-menu hidden";
        menu.setAttribute("role", "menu");
        menu.setAttribute("aria-label", `Actions for ${title.textContent}`);

        const renameButton = document.createElement("button");
        renameButton.type = "button";
        renameButton.setAttribute("role", "menuitem");
        renameButton.textContent = "Rename";

        const deleteButton = document.createElement("button");
        deleteButton.type = "button";
        deleteButton.className = "danger";
        deleteButton.setAttribute("role", "menuitem");
        deleteButton.textContent = "Delete";

        menu.append(renameButton, deleteButton);
        actions.append(menuTrigger, menu);

        menuTrigger.addEventListener("click", () => {
          setSessionMenuOpen(row, !row.classList.contains("menu-open"));
        });
        menuTrigger.addEventListener("keydown", (event) => {
          if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            setSessionMenuOpen(row, true, event.key === "ArrowDown" ? "first" : "last");
          }
        });
        menu.addEventListener("keydown", (event) => {
          const items = [...menu.querySelectorAll('[role="menuitem"]:not(:disabled)')];
          if (event.key === "Escape") {
            event.preventDefault();
            setSessionMenuOpen(row, false);
            menuTrigger.focus();
            return;
          }
          if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key) || !items.length) return;
          event.preventDefault();
          const current = items.indexOf(document.activeElement);
          let next = current;
          if (event.key === "Home") next = 0;
          else if (event.key === "End") next = items.length - 1;
          else if (event.key === "ArrowDown") next = current < 0 ? 0 : (current + 1) % items.length;
          else next = current < 0 ? items.length - 1 : (current - 1 + items.length) % items.length;
          items[next]?.focus();
        });

        renameButton.addEventListener("click", () => beginSessionRename(row, session, title.textContent));
        deleteButton.addEventListener("click", () => openSessionDeleteModal(session, menuTrigger));

        row.append(button, actions);
        container.appendChild(row);
      });

      return sessions;

    } catch (error) {

      if (requestId !== sessionSearchRequestId) return [];

      console.error(
        "❌ Recent chat error:",
        error
      );
      announceSessionSearch(searchQuery ? "Unable to search chats" : "");
      return [];
    }
  }

  async function loadInitialConversation() {
    const sessions = await loadSessions();
    if (sessions.length) {
      const currentExists = sessions.some(session => session.thread_id === state.threadId);
      if (!currentExists) {
        state.threadId = sessions[0].thread_id;
        localStorage.setItem("hr_thread_id", state.threadId);
        await loadSessions();
      }
      await loadHistory();
      return;
    }

    chat.innerHTML = "";
    syncConversationPresentation();
    if (state.assistant?.welcome_message) {
      addMessage("assistant", state.assistant.welcome_message);
    }
    renderStarterQuestions();
  }

  async function loadHistory() {
    chat.innerHTML = "";
    syncConversationPresentation();

    try {
      const response = await authFetch(`${API}/api/sessions/${encodeURIComponent(state.threadId)}/history`);

      if (!response.ok) return;

      const history = await response.json();

      history.forEach((item) => {
        const role =
          item.role === "human" || item.role === "user"
            ? "user"
            : "assistant";

        addMessage(role, item.content || "");
      });
      syncConversationPresentation();
      renderStarterQuestions();
    } catch (err) {
      console.debug("History:", err);
    }
  }

  async function newChat() {
    try {
      const response = await authFetch(`${API}/api/sessions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({})
      });

      if (!response.ok) return;

      const session = await response.json();
      state.threadId = session.thread_id;
      localStorage.setItem("hr_thread_id", state.threadId);

      chat.innerHTML = "";
      syncConversationPresentation();
      if (state.assistant?.welcome_message) addMessage("assistant", state.assistant.welcome_message);
      renderStarterQuestions();
      await loadSessions();
      input.focus();
    } catch (err) {
      console.error("New chat:", err);
    }
  }

  async function uploadFiles() {
    if (!fileInput) return;

    if (!fileInput.files.length) {
      fileInput.click();
      return;
    }

    const form = new FormData();
    [...fileInput.files].forEach((file) => form.append("files", file));

    setWorking("Processing documents...", true);

    try {
      const response = await authFetch(`${API}/api/documents/upload`, {
        method: "POST",
        body: form
      });

      const result = await response.json();

      if (!response.ok) {
        throw new Error(result.detail || "Upload failed");
      }

      setWorking(
        `Knowledge base updated: ${result.documents ?? 0} document(s), ` +
        `${result.pages ?? 0} page(s), ${result.chunks ?? 0} chunks.`,
        true
      );

      fileInput.value = "";
      setTimeout(() => setWorking("", false), 3500);
    } catch (err) {
      setWorking(err.message || "Upload failed", true);
      setTimeout(() => setWorking("", false), 4000);
    }
  }

  function resizeInput() {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 110)}px`;
  }

  function initializeTheme() {
    const themeButton = document.getElementById("themeButton");
    if (!themeButton) return;

    // The saved theme is already applied at load time; sync the control state.
    const syncButton = () => {
      const isDark = document.body.classList.contains("dark");
      themeButton.title = isDark ? "Switch to light mode" : "Switch to dark mode";
      themeButton.setAttribute("aria-pressed", String(isDark));
      const label = themeButton.querySelector(".theme-button-label");
      if (label) label.textContent = isDark ? "Use light theme" : "Use dark theme";
    };

    syncButton();

    themeButton.addEventListener("click", () => {
      const isDark = document.body.classList.toggle("dark");
      localStorage.setItem("hr_theme", isDark ? "dark" : "light");
      syncButton();
    });
  }

  function closeAccountMenu(returnFocus = false) {
    const button = document.getElementById("accountMenuButton");
    const panel = document.getElementById("accountMenuPanel");
    panel?.classList.add("hidden");
    if (panel) {
      panel.inert = true;
      panel.setAttribute("aria-hidden", "true");
    }
    button?.setAttribute("aria-expanded", "false");
    if (returnFocus) button?.focus();
  }

  function openAccountMenu(focusTarget = null) {
    const button = document.getElementById("accountMenuButton");
    const panel = document.getElementById("accountMenuPanel");
    if (!button || !panel) return;

    panel.classList.remove("hidden");
    panel.inert = false;
    panel.setAttribute("aria-hidden", "false");
    button.setAttribute("aria-expanded", "true");

    const items = [...panel.querySelectorAll('[role="menuitem"]:not(:disabled)')];
    if (focusTarget === "first") items[0]?.focus();
    if (focusTarget === "last") items.at(-1)?.focus();
  }

  function initializeAccountMenu() {
    const menu = document.getElementById("accountMenu");
    const button = document.getElementById("accountMenuButton");
    const panel = document.getElementById("accountMenuPanel");
    if (!menu || !button || !panel) return;

    closeAccountMenu();

    button.addEventListener("click", () => {
      const opening = panel.classList.contains("hidden");
      if (opening) openAccountMenu();
      else closeAccountMenu();
    });

    button.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !panel.classList.contains("hidden")) {
        event.preventDefault();
        closeAccountMenu(true);
        return;
      }
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        openAccountMenu(event.key === "ArrowDown" ? "first" : "last");
      }
    });

    document.addEventListener("pointerdown", (event) => {
      if (!menu.contains(event.target)) closeAccountMenu();
    });

    menu.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !panel.classList.contains("hidden")) {
        event.preventDefault();
        closeAccountMenu(true);
      }
    });

    panel.addEventListener("keydown", (event) => {
      if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
      const items = [...panel.querySelectorAll('[role="menuitem"]:not(:disabled)')];
      if (!items.length) return;

      event.preventDefault();
      const current = items.indexOf(document.activeElement);
      let next = current;
      if (event.key === "Home") next = 0;
      else if (event.key === "End") next = items.length - 1;
      else if (event.key === "ArrowDown") next = current < 0 ? 0 : (current + 1) % items.length;
      else if (event.key === "ArrowUp") next = current < 0 ? items.length - 1 : (current - 1 + items.length) % items.length;
      items[next]?.focus();
    });

    menu.addEventListener("focusout", () => {
      setTimeout(() => {
        if (!menu.contains(document.activeElement)) closeAccountMenu();
      }, 0);
    });
  }

  function setThinkingStatus(text) { updateThinkingLabel(text); }

  function activityLabelForTool(toolName) {
    const labels = {
      search_knowledge_base: "Knowledge searched...",
      search_memory: "Saved context checked...",
      manage_memory: "Memory updated...",
      fetch: "Web source fetched..."
    };
    if (labels[toolName]) return labels[toolName];
    if (!toolName) return "Tool completed...";
    const readable = String(toolName).replace(/[_-]+/g, " ").trim();
    return `${readable.charAt(0).toUpperCase()}${readable.slice(1)} completed...`;
  }

  function updateThinkingLabel(text) {
    const label = document.querySelector("#thinkingMessage .thinking-label");
    if (label && text) {
      label.textContent = text;
      label.setAttribute("aria-label", text);
    }
  }

  function hideThinking() {
    const thinking =
        document.getElementById("thinkingMessage");

    if (thinking) {
        thinking.remove();
    }
}

  function showThinking(label = "Thinking...") {
    const chat = document.getElementById("chat");

    if (!chat) {
      return;
    }

    // Don't create it twice; update the truthful current state instead.
    if (document.getElementById("thinkingMessage")) {
      updateThinkingLabel(label);
      return;
    }

    const thinking = document.createElement("div");

    thinking.id = "thinkingMessage";
    thinking.className = "thinking-message";

    thinking.innerHTML = `
        <div class="bot-icon">
            <svg viewBox="0 0 64 64" fill="none">
                <rect
                    x="18"
                    y="8"
                    width="28"
                    height="48"
                    rx="3"
                    stroke="#1769e8"
                    stroke-width="3"
                />

                <rect
                    x="24"
                    y="17"
                    width="16"
                    height="12"
                    rx="2"
                    fill="#eaf2ff"
                    stroke="#1769e8"
                    stroke-width="2"
                />

                <path
                    d="M24 37H40"
                    stroke="#22a6a3"
                    stroke-width="3"
                    stroke-linecap="round"
                />

                <path
                    d="M24 44H35"
                    stroke="#22a6a3"
                    stroke-width="3"
                    stroke-linecap="round"
                />

                <circle
                    cx="36"
                    cy="23"
                    r="2"
                    fill="#1769e8"
                />
            </svg>
        </div>

        <div class="thinking-bubble" role="status" aria-live="polite">
            <span class="thinking-dot"></span>
            <span class="thinking-dot"></span>
            <span class="thinking-dot"></span>
            <span class="thinking-label"></span>
        </div>
    `;

    updateThinkingLabel(label);
    chat.appendChild(thinking);

    // Scroll to bottom
    chat.scrollTop = chat.scrollHeight;
  }

  function formatSessionDate(value) {

    if (!value) {
      return "Today";
    }

    const date =
      new Date(value);

    if (
      Number.isNaN(
        date.getTime()
      )
    ) {
      return "Today";
    }

    const now =
      new Date();


    const sameDay =
      date.getFullYear() ===
      now.getFullYear() &&

      date.getMonth() ===
      now.getMonth() &&

      date.getDate() ===
      now.getDate();


    if (sameDay) {

      return date.toLocaleTimeString(
        [],
        {
          hour: "numeric",
          minute: "2-digit"
        }
      );
    }


    const yesterday =
      new Date(now);

    yesterday.setDate(
      yesterday.getDate() - 1
    );


    const isYesterday =
      date.getFullYear() ===
      yesterday.getFullYear() &&

      date.getMonth() ===
      yesterday.getMonth() &&

      date.getDate() ===
      yesterday.getDate();


    if (isYesterday) {
      return "Yesterday";
    }


    return date.toLocaleDateString(
      [],
      {
        month: "short",
        day: "numeric"
      }
    );
  }

  const chatForm = $("chatForm");
  if (chatForm) {
    chatForm.addEventListener("submit", (event) => {
      event.preventDefault();
      sendMessage(input.value);
    });
  }

  const newChatButton = $("newChat");
  if (newChatButton) {
    newChatButton.addEventListener("click", newChat);
  }

  const uploadButton = $("uploadDocuments");
  if (uploadButton && fileInput) {
    uploadButton.addEventListener("click", () => fileInput.click());
  }

  const attachButton = $("attachButton");
  if (attachButton && fileInput) {
    attachButton.addEventListener("click", () => fileInput.click());
  }

  if (fileInput) {
    fileInput.addEventListener("change", uploadFiles);
  }

  input.addEventListener("input", resizeInput);

  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendMessage(input.value);
    }
  });

  const micButton = $("micButton");
  if (micButton) {
    micButton.addEventListener("click", () => {
      const Recognition =
        window.SpeechRecognition || window.webkitSpeechRecognition;

      if (!Recognition) {
        alert("Voice input is not supported by this browser.");
        return;
      }

      const recognition = new Recognition();
      recognition.lang = "en-US";
      recognition.interimResults = true;

      recognition.onresult = (event) => {
        let transcript = "";

        for (
          let i = event.resultIndex;
          i < event.results.length;
          i++
        ) {
          transcript += event.results[i][0].transcript;
        }

        input.value = transcript;
        resizeInput();
      };

      recognition.start();
    });
  }

  // Authenticate first. Only initialize the application after the
  // backend confirms the user's identity and tenant.
  // The theme control lives in the top bar and must work regardless of
  // authentication state, so wire it up before the identity check.
  initializeTheme();
  initializeAccountMenu();
  initializeSessionManagement();
  initializeSessionSearch();

  initAuth().then((authenticated) => {
    if (!authenticated) return;
    loadAssistantConfiguration()
      .then(loadInitialConversation)
      .catch(console.error);
  });

  // ---------------- Admin dashboard ----------------
  const adminNavButton = $("adminNavButton");
  const assistantNavButton = $("assistantNavButton");
  const adminDashboard = $("adminDashboard");
  const backToAssistant = $("backToAssistant");
  const refreshAdmin = $("refreshAdmin");
  const addUserButton = $("addUserButton");
  const userModal = $("userModal");
  const closeUserModalButton = $("closeUserModal");
  const cancelUserModal = $("cancelUserModal");
  const adminUserForm = $("adminUserForm");
  const adminFileInput = $("adminFileInput");
  const uploadPoliciesButton = $("uploadPoliciesButton");
  const assistantConfigForm = $("assistantConfigForm");
  const adminSectionTabs = [...document.querySelectorAll("[data-admin-section-target]")];
  const adminSectionPanels = [...document.querySelectorAll("[data-admin-panel]")];
  let editableStarterQuestions = [];
  let assistantToolCatalog = [];

function closeUserModal() {
  userModal?.classList.add("hidden");
  if (userModal) userModal.inert = true;
  adminUserForm?.reset();
  const error = $("userFormError");
  error?.classList.add("hidden");
  if (error) error.textContent = "";
}

function showUserModal() {
  if (!state.user || state.user.role !== "company_admin") return;
  userModal?.classList.remove("hidden");
  if (userModal) userModal.inert = false;
  setTimeout(() => $("adminUserName")?.focus(), 0);
}

  function showAdminSection(section, { focusTab = false } = {}) {
    const nextTab = adminSectionTabs.find(tab => tab.dataset.adminSectionTarget === section);
    const nextPanel = adminSectionPanels.find(panel => panel.dataset.adminPanel === section);
    if (!nextTab || !nextPanel) return;

    adminSectionTabs.forEach(tab => {
      const selected = tab === nextTab;
      tab.classList.toggle("active", selected);
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
    });
    adminSectionPanels.forEach(panel => panel.classList.toggle("hidden", panel !== nextPanel));
    if (focusTab) nextTab.focus();
  }

  function handleAdminSectionKeydown(event) {
    const currentIndex = adminSectionTabs.indexOf(event.currentTarget);
    if (currentIndex < 0) return;
    let nextIndex = null;
    if (["ArrowDown", "ArrowRight"].includes(event.key)) nextIndex = (currentIndex + 1) % adminSectionTabs.length;
    if (["ArrowUp", "ArrowLeft"].includes(event.key)) nextIndex = (currentIndex - 1 + adminSectionTabs.length) % adminSectionTabs.length;
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = adminSectionTabs.length - 1;
    if (nextIndex === null) return;
    event.preventDefault();
    showAdminSection(adminSectionTabs[nextIndex].dataset.adminSectionTarget, { focusTab: true });
  }

  function showAdminDashboard() {
    if (!state.user || state.user.role !== "company_admin") return;
    closeUserModal();
    showAdminSection("overview");
    adminDashboard?.classList.remove("hidden");
    appShell?.classList.add("hidden");
    adminNavButton?.classList.add("active");
    assistantNavButton?.classList.remove("active");
    loadAdminDashboard();
  }

  function hideAdminDashboard() {
    closeUserModal();
    adminDashboard?.classList.add("hidden");
    appShell?.classList.remove("hidden");
    adminNavButton?.classList.remove("active");
    assistantNavButton?.classList.add("active");
  }

  function showAssistant() {
    closeUserModal();
    adminDashboard?.classList.add("hidden");
    appShell?.classList.remove("hidden");
    adminNavButton?.classList.remove("active");
    assistantNavButton?.classList.add("active");
    input?.focus();
  }

  async function loadAdminDashboard() {
    if (!state.token || state.user?.role !== "company_admin") return;
    const errorBox = $("adminError");
    errorBox?.classList.add("hidden");
    try {
      const [overviewResponse, usersResponse, documentsResponse, configResponse, toolsResponse] = await Promise.all([
        authFetch(`${API}/api/admin/overview`),
        authFetch(`${API}/api/admin/users`),
        authFetch(`${API}/api/documents`),
        authFetch(`${API}/api/assistants/current`),
        authFetch(`${API}/api/assistants/default/tools`)
      ]);
      const overview = await overviewResponse.json();
      const users = await usersResponse.json();
      const documents = await documentsResponse.json();
      const config = await configResponse.json();
      const tools = await toolsResponse.json();
      if (!overviewResponse.ok) throw new Error(overview.detail || "Unable to load dashboard");
      if (!usersResponse.ok) throw new Error(users.detail || "Unable to load users");
      if (!documentsResponse.ok) throw new Error(documents.detail || "Unable to load documents");
      if (!configResponse.ok) throw new Error(config.detail || "Unable to load assistant configuration");
      if (!toolsResponse.ok) throw new Error(tools.detail || "Unable to load assistant tools");

      $("statEmployees").textContent = overview.employees ?? 0;
      $("statUsers").textContent = overview.users ?? 0;
      $("statPolicies").textContent = overview.policy_chunks ?? 0;
      $("statConversations").textContent = overview.conversations ?? 0;
      $("workspaceName").textContent = overview.company?.name || state.user.company_name || "—";
      $("workspaceStatus").textContent = overview.company?.status || "active";
      $("workspaceId").textContent = state.user.tenant_id || "—";
      $("workspaceKnowledge").textContent = `${overview.policy_chunks ?? 0} indexed chunks`;
      $("adminCompanySubtitle").textContent = `${overview.company?.name || state.user.company_name || "Company"} workspace`;
      renderUsers(users);
      renderDocuments(documents);
      populateAssistantConfiguration(config, tools);
    } catch (error) {
      if (errorBox) { errorBox.textContent = error.message; errorBox.classList.remove("hidden"); }
    }
  }

  function populateAssistantConfiguration(config, tools) {
    applyAssistantConfiguration(config);
    $("configAssistantName").value = config.name || "";
    $("configAssistantStatus").value = config.status || "active";
    $("configAssistantDescription").value = config.description || "";
    $("configWelcomeMessage").value = config.welcome_message || "";
    $("configPlaceholder").value = config.placeholder || "";
    $("configIcon").value = config.icon || "";
    $("configKnowledgeBase").value = config.knowledge_base_id || "default";
    $("configSystemInstructions").value = config.system_instructions || "";

    const memory = config.memory_settings || {};
    $("configConversationMemory").checked = memory.conversation_memory !== false;
    $("configLongTermMemory").checked = memory.long_term_memory !== false;
    $("configSavePreferences").checked = memory.save_personal_preferences !== false;

    const citations = config.citation_requirements || {};
    $("configCitationsEnabled").checked = citations.enabled !== false;
    $("configCitationsRequired").checked = citations.required !== false;
    $("configCitationDocument").checked = citations.include_document_name !== false;
    $("configCitationPage").checked = citations.include_page !== false;
    $("configCitationChunk").checked = citations.include_chunk !== false;

    editableStarterQuestions = Array.isArray(config.starter_questions)
      ? [...config.starter_questions]
      : [];
    assistantToolCatalog = Array.isArray(tools) ? tools : [];
    renderConfigStarterQuestions();
    renderAssistantTools();
  }

  function renderConfigStarterQuestions() {
    const container = $("configStarterList");
    if (!container) return;
    if (!editableStarterQuestions.length) {
      container.innerHTML = '<p class="config-help">No starter questions configured.</p>';
      return;
    }
    container.innerHTML = editableStarterQuestions.map((question, index) => `
      <div class="config-starter-row">
        <input data-starter-text="${index}" maxlength="300" value="${escapeHtml(question)}" aria-label="Starter question ${index + 1}">
        <button class="admin-secondary" type="button" data-starter-up="${index}" ${index === 0 ? "disabled" : ""} aria-label="Move question up">↑</button>
        <button class="admin-secondary" type="button" data-starter-down="${index}" ${index === editableStarterQuestions.length - 1 ? "disabled" : ""} aria-label="Move question down">↓</button>
        <button class="admin-secondary" type="button" data-starter-remove="${index}" aria-label="Delete question">×</button>
      </div>
    `).join("");
    container.querySelectorAll("[data-starter-text]").forEach(field => {
      field.addEventListener("input", () => { editableStarterQuestions[Number(field.dataset.starterText)] = field.value; });
    });
    container.querySelectorAll("[data-starter-up]").forEach(button => {
      button.addEventListener("click", () => moveStarterQuestion(Number(button.dataset.starterUp), -1));
    });
    container.querySelectorAll("[data-starter-down]").forEach(button => {
      button.addEventListener("click", () => moveStarterQuestion(Number(button.dataset.starterDown), 1));
    });
    container.querySelectorAll("[data-starter-remove]").forEach(button => {
      button.addEventListener("click", () => {
        editableStarterQuestions.splice(Number(button.dataset.starterRemove), 1);
        renderConfigStarterQuestions();
      });
    });
  }

  function moveStarterQuestion(index, direction) {
    const target = index + direction;
    if (target < 0 || target >= editableStarterQuestions.length) return;
    [editableStarterQuestions[index], editableStarterQuestions[target]] = [editableStarterQuestions[target], editableStarterQuestions[index]];
    renderConfigStarterQuestions();
  }

  function renderAssistantTools() {
    const container = $("configTools");
    if (!container) return;
    container.innerHTML = assistantToolCatalog.map(tool => `
      <label class="config-tool">
        <input type="checkbox" data-config-tool="${escapeHtml(tool.id)}" ${tool.enabled ? "checked" : ""} ${tool.available ? "" : "disabled"}>
        <span><b>${escapeHtml(tool.name)}</b><small>${escapeHtml(tool.description)}</small></span>
        <span class="config-tool-status">${escapeHtml(tool.status)}</span>
      </label>
    `).join("");
  }

  function renderUsers(users) {
    const body = $("usersTableBody");
    if (!body) return;
    if (!Array.isArray(users) || !users.length) {
      body.innerHTML = '<tr><td colspan="6" class="empty-table">No users yet.</td></tr>';
      return;
    }
    body.innerHTML = users.map(user => {
      const created = user.created_at ? new Date(user.created_at).toLocaleDateString() : "—";
      const status = user.status || "active";
      const role = user.role === "company_admin" ? "Company admin" : "Employee";
      const invitation = user.invitation || {};
      let detail = "";
      if (status === "invited" && invitation.status) {
        const invitationStatus = String(invitation.status).replaceAll("_", " ");
        const expiry = invitation.expires_at ? ` · expires ${new Date(invitation.expires_at).toLocaleString()}` : "";
        const deliveryError = invitation.delivery_error ? ` · ${invitation.delivery_error}` : "";
        detail = `<small class="invitation-detail ${escapeHtml(invitation.status)}">${escapeHtml(invitationStatus)}${escapeHtml(expiry)}${escapeHtml(deliveryError)}</small>`;
      }
      let action = "";
      if (user.id !== state.user.id && status === "invited") {
        const canRevoke = ["pending_delivery", "sent", "delivery_failed"].includes(invitation.status);
        action = `<div class="user-actions"><button class="table-action" data-resend-invitation="${user.id}">Resend</button>${canRevoke ? `<button class="table-action danger" data-revoke-invitation="${user.id}">Revoke</button>` : ""}</div>`;
      } else if (user.id !== state.user.id && ["active", "inactive"].includes(status)) {
        action = `<button class="table-action" data-user-status="${user.id}">${status === "active" ? "Disable" : "Enable"}</button>`;
      }
      return `<tr>
        <td><strong>${escapeHtml(user.full_name || "—")}</strong></td>
        <td>${escapeHtml(user.email || "—")}</td>
        <td><span class="role-pill">${escapeHtml(role)}</span></td>
        <td><span class="status-pill ${escapeHtml(status)}">${escapeHtml(status)}</span>${detail}</td>
        <td>${created}</td>
        <td>${action}</td>
      </tr>`;
    }).join("");

    body.querySelectorAll("[data-user-status]").forEach(button => {
      button.addEventListener("click", async () => {
        const id = button.dataset.userStatus;
        button.disabled = true;
        try {
          const response = await authFetch(`${API}/api/admin/users/${id}/status`, { method: "PATCH" });
          const result = await response.json();
          if (!response.ok) throw new Error(result.detail || "Unable to update user");
          await loadAdminDashboard();
        } catch (error) {
          const errorBox = $("adminError");
          if (errorBox) { errorBox.textContent = error.message; errorBox.classList.remove("hidden"); }
          button.disabled = false;
        }
      });
    });

    body.querySelectorAll("[data-resend-invitation]").forEach(button => {
      button.addEventListener("click", async () => {
        button.disabled = true;
        try {
          const response = await authFetch(`${API}/api/admin/users/${button.dataset.resendInvitation}/resend-invitation`, { method: "POST" });
          const result = await response.json();
          if (!response.ok) throw new Error(apiErrorMessage(result, "Unable to resend invitation"));
          await loadAdminDashboard();
          if (!result.email_delivered) showAdminMessage(result.invitation?.delivery_error || "Invitation created, but email delivery failed. Correct the email configuration and resend.", true);
          else showAdminMessage("Invitation sent.");
        } catch (error) {
          showAdminMessage(error.message, true);
          button.disabled = false;
        }
      });
    });

    body.querySelectorAll("[data-revoke-invitation]").forEach(button => {
      button.addEventListener("click", async () => {
        if (!window.confirm("Revoke this invitation link? The user will remain invited and can be sent a new invitation later.")) return;
        button.disabled = true;
        try {
          const response = await authFetch(`${API}/api/admin/users/${button.dataset.revokeInvitation}/revoke-invitation`, { method: "POST" });
          const result = await response.json();
          if (!response.ok) throw new Error(apiErrorMessage(result, "Unable to revoke invitation"));
          await loadAdminDashboard();
          showAdminMessage("Invitation revoked.");
        } catch (error) {
          showAdminMessage(error.message, true);
          button.disabled = false;
        }
      });
    });
  }

  function apiErrorMessage(result, fallback) {
    if (typeof result?.detail === "string") return result.detail;
    if (typeof result?.detail?.message === "string") return result.detail.message;
    if (Array.isArray(result?.detail) && result.detail[0]?.msg) return result.detail[0].msg.replace(/^Value error, /, "");
    return fallback;
  }

  function showAdminMessage(message, isError = false) {
    const box = $("adminError");
    if (!box) return;
    box.textContent = message;
    box.classList.remove("hidden");
    box.dataset.kind = isError ? "error" : "success";
  }

  let allPolicyDocuments = [];

  function formatFileSize(bytes) {
    const value = Number(bytes || 0);
    if (!value) return "—";
    if (value < 1024) return `${value} B`;
    if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
    return `${(value / (1024 * 1024)).toFixed(1)} MB`;
  }

  function renderDocuments(documents) {
    allPolicyDocuments = Array.isArray(documents) ? documents : [];
    applyDocumentFilters();
    const active = allPolicyDocuments.filter(d => d.status === "active").length;
    const archived = allPolicyDocuments.filter(d => d.status === "archived").length;
    const indexing = allPolicyDocuments.filter(d => d.status === "indexing" || d.status === "processing").length;
    const failed = allPolicyDocuments.filter(d => d.status === "failed").length;
    const summary = $("documentSummary");
    if (summary) summary.textContent = `${allPolicyDocuments.length} total · ${active} active · ${archived} archived${indexing ? ` · ${indexing} indexing` : ""}${failed ? ` · ${failed} failed` : ""}`;
  }

  function applyDocumentFilters() {
    const body = $("documentsTableBody");
    if (!body) return;
    const search = ($("documentSearch")?.value || "").trim().toLowerCase();
    const status = $("documentStatusFilter")?.value || "all";
    const documents = allPolicyDocuments.filter(doc => {
      const matchesSearch = !search || String(doc.name || "").toLowerCase().includes(search);
      const matchesStatus = status === "all" || doc.status === status;
      return matchesSearch && matchesStatus;
    });

    if (!documents.length) {
      body.innerHTML = '<tr><td colspan="8" class="empty-table">No documents match your filter.</td></tr>';
      return;
    }

    body.innerHTML = documents.map(doc => {
      const uploaded = doc.uploaded_at ? new Date(doc.uploaded_at).toLocaleString([], {dateStyle: "medium", timeStyle: "short"}) : "—";
      const status = doc.status || "active";
      const statusLabel = status === "indexing" || status === "processing" ? "Indexing" : status.charAt(0).toUpperCase() + status.slice(1);
      const tenant = String(doc.tenant_id || "—");
      let actions = "";
      if (status === "active" || status === "processing") {
        actions += `<button class="table-action" data-document-archive="${escapeHtml(doc.id)}">Archive</button>`;
      } else if (status === "archived") {
        actions += `<button class="table-action" data-document-restore="${escapeHtml(doc.id)}">Restore</button>`;
      }
      if(status === "active"){
        actions += `<button class="table-action danger" data-document-delete="${escapeHtml(doc.id)}">Delete</button>`;
      }
      const indexedChunks = Number(doc.indexed_chunks ?? doc.chunks ?? 0);
      const totalChunks = Number(doc.total_chunks ?? doc.chunks ?? 0);
      const progress = Number(doc.progress ?? (totalChunks ? Math.round(indexedChunks * 100 / totalChunks) : 0));
      const chunkLabel = status === "indexing" || status === "processing" || status === "archived"
        ? `${indexedChunks} / ${totalChunks}`
        : `${Number(doc.chunks ?? 0)}`;
      const progressHtml = (status === "indexing" || status === "processing")
        ? `<div class="document-progress"><div class="document-progress-bar" style="width:${Math.max(0, Math.min(100, progress))}%"></div></div><small class="document-progress-label">${progress}%</small>`
        : "";
      return `<tr>
        <td><strong>${escapeHtml(doc.name || "Untitled document")}</strong><small class="document-file-meta">${formatFileSize(doc.size_bytes)}</small></td>
        <td><span class="version-pill">v${escapeHtml(doc.version ?? 1)}</span></td>
        <td>${escapeHtml(uploaded)}</td>
        <td><span class="status-pill ${escapeHtml(status)}">${escapeHtml(statusLabel)}</span>${progressHtml}${status === "failed" && doc.error ? `<small class="document-error">${escapeHtml(doc.error)}</small>` : ""}</td>
        <td>${escapeHtml(doc.pages ?? 0)}</td>
        <td>${escapeHtml(chunkLabel)}</td>
        <td><code title="${escapeHtml(tenant)}">${escapeHtml(tenant.length > 14 ? `${tenant.slice(0, 14)}…` : tenant)}</code></td>
        <td class="document-actions">${actions}</td>
      </tr>`;
    }).join("");

    body.querySelectorAll("[data-document-archive]").forEach(button => {
      button.addEventListener("click", () => changeDocumentStatus(button.dataset.documentArchive, "archive"));
    });
    body.querySelectorAll("[data-document-restore]").forEach(button => {
      button.addEventListener("click", () => changeDocumentStatus(button.dataset.documentRestore, "restore"));
    });
    body.querySelectorAll("[data-document-delete]").forEach(button => {
      button.addEventListener("click", () => deletePolicyDocument(button.dataset.documentDelete));
    });
  }

  async function loadPolicyDocuments() {
    if (!state.token || state.user?.role !== "company_admin") return;
    const response = await authFetch(`${API}/api/documents`);
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Unable to load documents");
    renderDocuments(result);
  }

  async function changeDocumentStatus(documentId, action) {
    const verb = action === "archive" ? "archive" : "restore";
    const message = action === "archive"
      ? "Archive this document version? It will no longer be used as an active knowledge source."
      : "Restore this document version? It will become the active version for this document name.";
    if (!window.confirm(message)) return;
    try {
      document.querySelector(`[data-document-delete="${documentId}"]`)?.setAttribute("hidden", "true");
      const response = await authFetch(`${API}/api/documents/${encodeURIComponent(documentId)}/${verb}`, { method: "PATCH" });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || `Unable to ${verb} policy`);

      // Refresh the document library immediately after the lifecycle change.
      // This updates status, available actions, chunk counts, and the summary
      // without requiring the user to click the manual Refresh button.
      await loadPolicyDocuments();

      // Also refresh dashboard totals (knowledge chunks, etc.) so the rest of
      // the admin screen stays in sync with the document library.
      await loadAdminDashboard();
    } catch (error) {
      const errorBox = $("adminError");
      if (errorBox) { errorBox.textContent = error.message; errorBox.classList.remove("hidden"); }
    }
  }

  async function deletePolicyDocument(documentId) {
    if (!window.confirm("Permanently delete this document version and its indexed vectors? This cannot be undone.")) return;
    try {
      const response = await authFetch(`${API}/api/documents/${encodeURIComponent(documentId)}`, { method: "DELETE" });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "Unable to delete document");
      await loadAdminDashboard();
    } catch (error) {
      const errorBox = $("adminError");
      if (errorBox) { errorBox.textContent = error.message; errorBox.classList.remove("hidden"); }
    }
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>'"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));
  }

  $("configStarterAdd")?.addEventListener("click", () => {
    const field = $("configStarterInput");
    const question = field.value.trim();
    if (!question) return;
    editableStarterQuestions.push(question);
    field.value = "";
    renderConfigStarterQuestions();
  });

  $("configStarterInput")?.addEventListener("keydown", event => {
    if (event.key === "Enter") {
      event.preventDefault();
      $("configStarterAdd")?.click();
    }
  });

  assistantConfigForm?.addEventListener("submit", async event => {
    event.preventDefault();
    const saved = $("assistantConfigSaved");
    const errorBox = $("adminError");
    if (saved) saved.textContent = "Saving…";
    errorBox?.classList.add("hidden");
    const enabledTools = [...document.querySelectorAll("[data-config-tool]:checked")]
      .map(field => field.dataset.configTool);
    const payload = {
      name: $("configAssistantName").value.trim(),
      status: $("configAssistantStatus").value,
      description: $("configAssistantDescription").value.trim(),
      welcome_message: $("configWelcomeMessage").value.trim(),
      placeholder: $("configPlaceholder").value.trim(),
      icon: $("configIcon").value.trim() || null,
      knowledge_base_id: $("configKnowledgeBase").value.trim() || "default",
      system_instructions: $("configSystemInstructions").value.trim(),
      starter_questions: editableStarterQuestions.map(question => question.trim()).filter(Boolean),
      enabled_tools: enabledTools,
      memory_settings: {
        conversation_memory: $("configConversationMemory").checked,
        long_term_memory: $("configLongTermMemory").checked,
        save_personal_preferences: $("configSavePreferences").checked,
      },
      citation_requirements: {
        enabled: $("configCitationsEnabled").checked,
        required: $("configCitationsRequired").checked,
        include_document_name: $("configCitationDocument").checked,
        include_page: $("configCitationPage").checked,
        include_chunk: $("configCitationChunk").checked,
      },
    };
    try {
      const response = await authFetch(`${API}/api/assistants/default`, {
        method: "PATCH",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "Unable to save assistant configuration");
      applyAssistantConfiguration(result);
      const toolsResponse = await authFetch(`${API}/api/assistants/default/tools`);
      const tools = await toolsResponse.json();
      if (!toolsResponse.ok) throw new Error(tools.detail || "Configuration saved, but tools could not be refreshed");
      populateAssistantConfiguration(result, tools);
      if (saved) saved.textContent = "Saved";
      setTimeout(() => { if (saved) saved.textContent = ""; }, 2500);
    } catch (error) {
      if (saved) saved.textContent = "";
      if (errorBox) { errorBox.textContent = error.message; errorBox.classList.remove("hidden"); }
    }
  });

  adminNavButton?.addEventListener("click", showAdminDashboard);
  assistantNavButton?.addEventListener("click", showAssistant);
  backToAssistant?.addEventListener("click", hideAdminDashboard);
  refreshAdmin?.addEventListener("click", loadAdminDashboard);
  adminSectionTabs.forEach(tab => {
    tab.addEventListener("click", () => showAdminSection(tab.dataset.adminSectionTarget));
    tab.addEventListener("keydown", handleAdminSectionKeydown);
  });
  $("refreshDocuments")?.addEventListener("click", loadPolicyDocuments);
  $("documentSearch")?.addEventListener("input", applyDocumentFilters);
  $("documentStatusFilter")?.addEventListener("change", applyDocumentFilters);
  addUserButton?.addEventListener("click", showUserModal);
  closeUserModalButton?.addEventListener("click", closeUserModal);
  cancelUserModal?.addEventListener("click", closeUserModal);
  userModal?.addEventListener("click", event => {
    if (event.target === userModal) closeUserModal();
  });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && userModal && !userModal.classList.contains("hidden")) {
      closeUserModal();
    }
  });

  adminUserForm?.addEventListener("submit", async event => {
    event.preventDefault();
    const error = $("userFormError");
    error?.classList.add("hidden");
    try {
      const response = await authFetch(`${API}/api/admin/users`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          full_name: $("adminUserName").value,
          email: $("adminUserEmail").value,
          role: $("adminUserRole").value
        })
      });
      const result = await response.json();
      if (!response.ok) throw new Error(apiErrorMessage(result, "Unable to invite user"));
      closeUserModal();
      await loadAdminDashboard();
      if (!result.email_delivered) showAdminMessage(result.invitation?.delivery_error || "User is invited, but email delivery failed. Correct the email configuration and resend.", true);
      else showAdminMessage("Invitation sent.");
    } catch (err) {
      if (error) { error.textContent = err.message; error.classList.remove("hidden"); }
    }
  });

  uploadPoliciesButton?.addEventListener("click", () => adminFileInput?.click());
  let documentPollingTimer = null;

  async function pollDocumentIndexing(documentIds) {
    if (documentPollingTimer) {
      clearTimeout(documentPollingTimer);
      documentPollingTimer = null;
    }

    const ids = new Set(documentIds || []);
    if (!ids.size) return;

    try {
      const response = await authFetch(`${API}/api/documents`);
      const documents = await response.json();
      if (!response.ok) throw new Error(documents.detail || "Unable to check indexing progress");

      renderDocuments(documents);
      const tracked = documents.filter(doc => ids.has(doc.id));
      const indexing = tracked.filter(doc => doc.status === "indexing" || doc.status === "processing");
      const failed = tracked.filter(doc => doc.status === "failed");
      const completed = tracked.filter(doc => doc.status === "active");

      const status = $("uploadStatus");
      if (status) {
        if (indexing.length) {
          const total = indexing.reduce((sum, doc) => sum + Number(doc.total_chunks || 0), 0);
          const done = indexing.reduce((sum, doc) => sum + Number(doc.indexed_chunks || 0), 0);
          const percent = total ? Math.round(done * 100 / total) : 0;
          status.textContent = `Indexing… ${done} / ${total} chunks (${percent}%)`;
        } else if (failed.length) {
          status.textContent = `Indexing failed: ${failed.map(doc => doc.name).join(", ")}`;
        } else if (completed.length === ids.size) {
          const chunks = completed.reduce((sum, doc) => sum + Number(doc.chunks || 0), 0);
          status.textContent = `Indexing complete: ${completed.length} document(s), ${chunks} chunks active.`;
        }
      }

      await loadAdminDashboard();

      if (indexing.length) {
        documentPollingTimer = setTimeout(() => pollDocumentIndexing(documentIds), 1200);
      }
    } catch (error) {
      const status = $("uploadStatus");
      if (status) status.textContent = error.message;
      documentPollingTimer = setTimeout(() => pollDocumentIndexing(documentIds), 2500);
    }
  }

  adminFileInput?.addEventListener("change", async () => {
    const files = Array.from(adminFileInput.files || []);
    if (!files.length) return;
    const uploadStatus = $("uploadStatus");
    if (uploadStatus) uploadStatus.textContent = "Uploading…";
    const form = new FormData();
    files.forEach(file => form.append("files", file));
    try {
      const response = await authFetch(`${API}/api/documents/upload`, { method: "POST", body: form });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "Upload failed");
      adminFileInput.value = "";
      const ids = (result.results || []).filter(item => item.id).map(item => item.id);
      if (uploadStatus) uploadStatus.textContent = `Upload accepted. Starting indexing for ${ids.length} document(s)…`;
      await loadAdminDashboard();
      await pollDocumentIndexing(ids);
    } catch (error) {
      if (uploadStatus) uploadStatus.textContent = error.message;
    }
  });


  if (adminNavButton && state.user?.role === "company_admin") adminNavButton.classList.remove("hidden");
  assistantNavButton?.classList.add("active");

});
