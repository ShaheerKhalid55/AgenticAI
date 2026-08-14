console.log("%c HR Policy Assistant JS v20260813 LOADED ","background:#101e3b;color:white;padding:6px;border-radius:5px;font-weight:bold");
document.addEventListener("DOMContentLoaded", () => {
  const API = "";

  const state = {
    token: localStorage.getItem("hr_access_token") || "",
    user: JSON.parse(localStorage.getItem("hr_user") || "null"),
    threadId: localStorage.getItem("hr_thread_id") || crypto.randomUUID()
  };

  const authScreen = document.getElementById("authScreen");
  const appShell = document.getElementById("appShell");

  function setAuthenticated(token, user) {
    state.token = token;
    state.user = user;
    localStorage.setItem("hr_access_token", token);
    localStorage.setItem("hr_user", JSON.stringify(user));
    if (authScreen) authScreen.classList.add("hidden");
    if (appShell) appShell.classList.remove("hidden");
    if (document.getElementById("companyName")) document.getElementById("companyName").textContent = user.company_name;
    if (document.getElementById("employeeId")) document.getElementById("employeeId").textContent = user.email;
    if (document.getElementById("adminButton")) document.getElementById("adminButton").classList.toggle("hidden", user.role !== "company_admin");
  }

  function clearAuthentication() {
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
      await loadSessions();
      await loadHistory();
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
      await loadSessions();
    } catch (error) {
      if (registerError) { registerError.textContent = error.message; registerError.classList.remove("hidden"); }
    }
  });

  document.getElementById("logoutButton")?.addEventListener("click", () => {
    clearAuthentication();
  });


  const chat = $("chat");
  const input = $("message");
  const working = $("working");
  const fileInput = $("fileInput");

  if (!chat || !input) {
    console.error("HR Policy Assistant: required chat elements are missing.", {
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
    bubble.textContent = text;

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
      avatar.textContent = "SK";
      row.appendChild(avatar);
    }

    chat.appendChild(row);
    chat.scrollTop = chat.scrollHeight;
    return bubble;
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
    showThinking();
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

              if (event.type === "tool") {
                // Keep thinking visible while tools are running.
                if (!bubble) {
                  setWorking(
                    event.label || `Using ${event.tool || "tool"}...`,
                    false
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

                  assistantBubble.textContent = answer;

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

                  assistantBubble.textContent = answer;
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

                assistantBubble.textContent = answer;

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

              assistantBubble.textContent = answer;
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
        bubble.textContent =
          "Sorry, something went wrong while generating the response.";
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

  async function loadSessions() {
    const container = document.getElementById("sessions");

    if (!container) {
      console.error("❌ #sessions not found");
      return;
    }

    console.log("✅ Rendering recent chats");

    try {
      const response = await authFetch(`${API}/api/sessions`);

      if (!response.ok) {
        console.error(
          "Session API failed:",
          response.status
        );
        return;
      }

      const sessions = await response.json();

      console.log("Sessions:", sessions);

      container.innerHTML = "";

      if (!sessions || sessions.length === 0) {
        renderEmptySessions(container);
        return;
      }

      sessions.forEach((session) => {

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

            await loadHistory();
            await loadSessions();
          }
        );


        container.appendChild(button);
      });

    } catch (error) {

      console.error(
        "❌ Recent chat error:",
        error
      );
    }
  }

  async function loadHistory() {
    chat.innerHTML = "";

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

    setWorking("Processing policy documents...", true);

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

    const themeButton =
      document.getElementById(
        "themeButton"
      );

    if (!themeButton) {

      console.error(
        "❌ #themeButton not found"
      );

      return;
    }


    const savedTheme =
      localStorage.getItem(
        "hr_theme"
      );


    if (savedTheme === "dark") {

      document.body.classList.add(
        "dark"
      );

    } else {

      document.body.classList.remove(
        "dark"
      );
    }


    themeButton.addEventListener(
      "click",
      () => {

        const isDark =
          document.body.classList.toggle(
            "dark"
          );


        localStorage.setItem(
          "hr_theme",
          isDark
            ? "dark"
            : "light"
        );


        themeButton.title =
          isDark
            ? "Switch to light mode"
            : "Switch to dark mode";


        console.log(
          "Theme changed:",
          isDark
            ? "dark"
            : "light"
        );
      }
    );
  }

  function hideThinking() {
    const thinking =
        document.getElementById("thinkingMessage");

    if (thinking) {
        thinking.remove();
    }
}

  function showThinking() {
    const chat = document.getElementById("chat");

    if (!chat) {
      return;
    }

    // Don't create it twice
    if (document.getElementById("thinkingMessage")) {
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

        <div class="thinking-bubble">
            <span class="thinking-dot"></span>
            <span class="thinking-dot"></span>
            <span class="thinking-dot"></span>
            <span class="thinking-label">Thinking</span>
        </div>
    `;

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
  initAuth().then((authenticated) => {
    if (!authenticated) return;
    initializeTheme();
    loadSessions();
    loadHistory();
  });

  // ---------------- Admin dashboard ----------------
  const adminButton = $("adminButton");
  const adminDashboard = $("adminDashboard");
  const backToAssistant = $("backToAssistant");
  const refreshAdmin = $("refreshAdmin");
  const addUserButton = $("addUserButton");
  const userModal = $("userModal");
  const closeUserModal = $("closeUserModal");
  const adminUserForm = $("adminUserForm");
  const adminFileInput = $("adminFileInput");
  const uploadPoliciesButton = $("uploadPoliciesButton");

  function showAdminDashboard() {
    if (!state.user || state.user.role !== "company_admin") return;
    adminDashboard?.classList.remove("hidden");
    appShell?.classList.add("hidden");
    loadAdminDashboard();
  }

  function hideAdminDashboard() {
    adminDashboard?.classList.add("hidden");
    appShell?.classList.remove("hidden");
  }

  async function loadAdminDashboard() {
    if (!state.token || state.user?.role !== "company_admin") return;
    const errorBox = $("adminError");
    errorBox?.classList.add("hidden");
    try {
      const [overviewResponse, usersResponse] = await Promise.all([
        authFetch(`${API}/api/admin/overview`),
        authFetch(`${API}/api/admin/users`)
      ]);
      const overview = await overviewResponse.json();
      const users = await usersResponse.json();
      if (!overviewResponse.ok) throw new Error(overview.detail || "Unable to load dashboard");
      if (!usersResponse.ok) throw new Error(users.detail || "Unable to load users");

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
    } catch (error) {
      if (errorBox) { errorBox.textContent = error.message; errorBox.classList.remove("hidden"); }
    }
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
      const action = user.id === state.user.id ? "" : `<button class="table-action" data-user-status="${user.id}">${status === "active" ? "Disable" : "Enable"}</button>`;
      return `<tr>
        <td><strong>${escapeHtml(user.full_name || "—")}</strong></td>
        <td>${escapeHtml(user.email || "—")}</td>
        <td><span class="role-pill">${role}</span></td>
        <td><span class="status-pill ${status}">${status}</span></td>
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
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>'"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));
  }

  adminButton?.addEventListener("click", showAdminDashboard);
  backToAssistant?.addEventListener("click", hideAdminDashboard);
  refreshAdmin?.addEventListener("click", loadAdminDashboard);
  addUserButton?.addEventListener("click", () => userModal?.classList.remove("hidden"));
  closeUserModal?.addEventListener("click", () => userModal?.classList.add("hidden"));
  userModal?.addEventListener("click", event => { if (event.target === userModal) userModal.classList.add("hidden"); });

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
          password: $("adminUserPassword").value,
          role: $("adminUserRole").value
        })
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "Unable to create user");
      adminUserForm.reset();
      userModal?.classList.add("hidden");
      await loadAdminDashboard();
    } catch (err) {
      if (error) { error.textContent = err.message; error.classList.remove("hidden"); }
    }
  });

  uploadPoliciesButton?.addEventListener("click", () => adminFileInput?.click());
  adminFileInput?.addEventListener("change", async () => {
    const files = Array.from(adminFileInput.files || []);
    if (!files.length) return;
    const status = $("uploadStatus");
    status.textContent = "Uploading and indexing…";
    const form = new FormData();
    files.forEach(file => form.append("files", file));
    try {
      const response = await authFetch(`${API}/api/documents/upload`, { method: "POST", body: form });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "Upload failed");
      status.textContent = `Uploaded ${result.documents} PDF(s), ${result.chunks} chunks indexed.`;
      adminFileInput.value = "";
      await loadAdminDashboard();
    } catch (error) {
      status.textContent = error.message;
    }
  });

  if (adminButton && state.user?.role === "company_admin") adminButton.classList.remove("hidden");

});
