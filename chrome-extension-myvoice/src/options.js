import { getBackendUrl, setBackendUrl } from "./lib/config.js";

const backendInput = document.getElementById("backend-url");
const saveBtn = document.getElementById("save-btn");
const openLoginBtn = document.getElementById("open-login-btn");
const statusEl = document.getElementById("status");

function setStatus(text, kind = "") {
  statusEl.textContent = text;
  statusEl.className = `status${kind ? ` ${kind}` : ""}`;
}

async function loadSettings() {
  const backendUrl = await getBackendUrl();
  backendInput.value = backendUrl;
  setStatus("");
}

async function saveSettings() {
  try {
    const value = backendInput.value;
    const saved = await setBackendUrl(value);
    backendInput.value = saved;
    setStatus("Saved.", "ok");
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    setStatus(`Save failed: ${msg}`, "error");
  }
}

async function openLogin() {
  const backendUrl = await setBackendUrl(backendInput.value);
  await chrome.tabs.create({ url: `${backendUrl}/login?next=/ui/posts` });
}

saveBtn.addEventListener("click", saveSettings);
openLoginBtn.addEventListener("click", openLogin);
loadSettings();
