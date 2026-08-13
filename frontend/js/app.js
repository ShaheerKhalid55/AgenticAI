console.log("%c HR Policy Assistant JS v20260813 LOADED ","background:#101e3b;color:white;padding:6px;border-radius:5px;font-weight:bold");
document.addEventListener("DOMContentLoaded", () => {
  const API = "";

  const state = {
    userId: localStorage.getItem("hr_user_id") || `employee-${crypto.randomUUID().slice(0, 8)}`,
    threadId: localStorage.getItem("hr_thread_id") || crypto.randomUUID()
  };

  localStorage.setItem("hr_user_id", state.userId);
  localStorage.setItem("hr_thread_id", state.threadId);

  const $ = (id) => document.getElementById(id);

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

  if ($("employeeId")) $("employeeId").textContent = state.userId;

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
      const response = await fetch(`${API}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: state.userId,
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
      const response = await fetch(
        `${API}/api/sessions?user_id=${encodeURIComponent(state.userId)}`
      );

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
      const response = await fetch(
        `${API}/api/sessions/${encodeURIComponent(state.threadId)}/history`
      );

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
      const response = await fetch(`${API}/api/sessions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: state.userId })
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
      const response = await fetch(`${API}/api/documents/upload`, {
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

  // Initialize immediately because we are already inside
  // the page's DOMContentLoaded handler.
  initializeTheme();
  loadSessions();
  loadHistory();
});
