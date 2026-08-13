let recorder = null;
let chunks = [];

document.getElementById("mic").addEventListener("click", async () => {
  const button = document.getElementById("mic");

  if (recorder && recorder.state === "recording") {
    recorder.stop();
    button.textContent = "🎙️";
    return;
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({audio: true});
    recorder = new MediaRecorder(stream);
    chunks = [];

    recorder.ondataavailable = e => chunks.push(e.data);
    recorder.onstop = async () => {
      stream.getTracks().forEach(t => t.stop());

      const blob = new Blob(chunks, {type: "audio/webm"});
      const form = new FormData();
      form.append("file", blob, "question.webm");

      button.textContent = "⏳";
      try {
        const res = await fetch("/api/voice/transcribe", {
          method: "POST",
          body: form
        });
        const data = await res.json();
        if (data.text) {
          document.getElementById("message").value = data.text;
          document.getElementById("message").focus();
        }
      } catch (e) {
        alert("Voice transcription failed.");
      } finally {
        button.textContent = "🎙️";
      }
    };

    recorder.start();
    button.textContent = "⏹️";
  } catch {
    alert("Microphone access was not available.");
  }
});
