document.addEventListener("DOMContentLoaded", async () => {
  const status = document.getElementById("invitationStatus");
  const form = document.getElementById("acceptInvitationForm");
  const errorBox = document.getElementById("invitationError");
  const complete = document.getElementById("invitationComplete");
  const params = new URLSearchParams(window.location.hash.slice(1));
  const token = params.get("token") || "";
  history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);

  function messageFrom(result, fallback) {
    if (typeof result?.detail === "string") return result.detail;
    if (typeof result?.detail?.message === "string") return result.detail.message;
    if (Array.isArray(result?.detail) && result.detail[0]?.msg) return result.detail[0].msg.replace(/^Value error, /, "");
    return fallback;
  }

  if (!token) {
    status.textContent = "This invitation link is invalid or incomplete.";
    return;
  }

  try {
    const response = await fetch("/api/auth/invitations/validate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      body: JSON.stringify({ token })
    });
    const result = await response.json();
    if (!response.ok) throw new Error(messageFrom(result, "Unable to validate this invitation"));
    document.getElementById("workspaceName").textContent = result.workspace_name;
    status.textContent = `Invitation for ${result.recipient_name} (${result.email}).`;
    form.classList.remove("hidden");
  } catch (error) {
    status.textContent = error.message;
    return;
  }

  form.addEventListener("submit", async event => {
    event.preventDefault();
    errorBox.classList.add("hidden");
    const password = document.getElementById("newPassword").value;
    const passwordConfirmation = document.getElementById("confirmPassword").value;
    if (password !== passwordConfirmation) {
      errorBox.textContent = "Passwords do not match";
      errorBox.classList.remove("hidden");
      return;
    }
    const button = document.getElementById("acceptButton");
    button.disabled = true;
    try {
      const response = await fetch("/api/auth/invitations/accept", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        cache: "no-store",
        body: JSON.stringify({
          token,
          password,
          password_confirmation: passwordConfirmation
        })
      });
      const result = await response.json();
      if (!response.ok) throw new Error(messageFrom(result, "Unable to accept this invitation"));
      form.classList.add("hidden");
      status.textContent = `Welcome to ${result.workspace_name}.`;
      complete.classList.remove("hidden");
    } catch (error) {
      errorBox.textContent = error.message;
      errorBox.classList.remove("hidden");
      button.disabled = false;
    }
  });
});
