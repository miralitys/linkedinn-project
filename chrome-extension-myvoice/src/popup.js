import { ApiError, createPost, listPeople, listPosts } from "./lib/api.js";
import { getBackendUrl } from "./lib/config.js";

const scanBtn = document.getElementById("scan-btn");
const reloadPeopleBtn = document.getElementById("reload-people-btn");
const addBtn = document.getElementById("add-btn");
const loginBtn = document.getElementById("login-btn");
const statusEl = document.getElementById("status");
const summaryEl = document.getElementById("scan-summary");
const postsListEl = document.getElementById("new-posts-list");
const openOptionsLink = document.getElementById("open-options-link");

const LOCAL_DEDUPE_KEYS_KEY = "myvoice_popup_dedupe_keys_v1";
const LOCAL_DEDUPE_MAX_KEYS_PER_PERSON = 2500;

let allPeople = [];
let pendingPosts = [];
let scanning = false;
let adding = false;
let hasScanned = false;
let localDedupeKeysByPerson = new Map();
let scanStats = {
  totalContacts: 0,
  scannableContacts: 0,
  checkedContacts: 0,
  contactsWithNew: 0,
  foundPosts: 0,
  skippedNoLinkedIn: 0,
  errors: 0
};

function cleanText(value) {
  return String(value || "").trim();
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function loadLocalDedupeKeys() {
  try {
    const data = await chrome.storage.local.get(LOCAL_DEDUPE_KEYS_KEY);
    const raw = data && data[LOCAL_DEDUPE_KEYS_KEY] ? data[LOCAL_DEDUPE_KEYS_KEY] : null;
    if (!raw || typeof raw !== "object") {
      localDedupeKeysByPerson = new Map();
      return;
    }

    const next = new Map();
    for (const [personIdRaw, keys] of Object.entries(raw)) {
      const personId = Number(personIdRaw);
      if (!Number.isInteger(personId) || personId <= 0) continue;
      if (!Array.isArray(keys) || keys.length === 0) continue;
      const set = new Set(keys.map((k) => cleanText(k)).filter(Boolean));
      if (set.size) next.set(personId, set);
    }
    localDedupeKeysByPerson = next;
  } catch {
    localDedupeKeysByPerson = new Map();
  }
}

function clampKeySet(set, maxSize) {
  if (!(set instanceof Set)) return new Set();
  if (set.size <= maxSize) return set;
  const arr = Array.from(set);
  return new Set(arr.slice(Math.max(0, arr.length - maxSize)));
}

async function persistLocalDedupeKeys() {
  try {
    const obj = {};
    for (const [personId, set] of localDedupeKeysByPerson.entries()) {
      const clamped = clampKeySet(set, LOCAL_DEDUPE_MAX_KEYS_PER_PERSON);
      localDedupeKeysByPerson.set(personId, clamped);
      obj[String(personId)] = Array.from(clamped);
    }
    await chrome.storage.local.set({ [LOCAL_DEDUPE_KEYS_KEY]: obj });
  } catch {
    // ignore storage quota errors
  }
}

function getLocalDedupeKeySet(personId) {
  const id = Number(personId);
  if (!Number.isInteger(id) || id <= 0) return null;
  let set = localDedupeKeysByPerson.get(id);
  if (!set) {
    set = new Set();
    localDedupeKeysByPerson.set(id, set);
  }
  return set;
}

function setStatus(text, kind = "") {
  statusEl.textContent = cleanText(text) || " ";
  statusEl.className = `status${kind ? ` ${kind}` : ""}`;
}

function showLoginButton(show) {
  loginBtn.classList.toggle("hidden", !show);
}

function toIntOrNull(value) {
  if (value == null || value === "") return null;
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  return Math.max(0, Math.round(n));
}

function toNumberOrNull(value) {
  if (value == null || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function formatNumber(value) {
  if (value == null) return null;
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 }).format(n);
}

function formatDate(value) {
  const raw = cleanText(value);
  if (!raw) return "Дата не указана";
  const dt = new Date(raw);
  if (Number.isNaN(dt.getTime())) return "Дата не указана";
  return new Intl.DateTimeFormat("ru-RU", {
    day: "numeric",
    month: "short",
    year: "numeric"
  }).format(dt);
}

function normalizedDay(value) {
  const raw = cleanText(value);
  if (!raw) return "";
  const dt = new Date(raw);
  if (Number.isNaN(dt.getTime())) return "";
  return dt.toISOString().slice(0, 10);
}

function normalizedSnippet(value) {
  return cleanText(value)
    .toLowerCase()
    .replace(/\s+/g, " ")
    .slice(0, 220);
}

function extractActivityId(raw) {
  const text = String(raw || "");
  const patterns = [
    /urn:li:activity:(\d{8,})/i,
    /activity-(\d{8,})/i,
    /ugcPost-(\d{8,})/i,
    /urn:li:ugcPost:(\d{8,})/i,
    // Some LinkedIn surfaces expose share URNs/URLs; backend does not dedupe by "share:",
    // so we convert it into an activity URL using the numeric id.
    /urn:li:share:(\d{8,})/i,
    /share-(\d{8,})/i
  ];
  for (const pattern of patterns) {
    const match = text.match(pattern);
    if (match && match[1]) return match[1];
  }
  return "";
}

function normalizeLinkedInUrl(rawUrl) {
  const raw = cleanText(rawUrl);
  if (!raw) return "";
  const activityId = extractActivityId(raw);
  if (activityId) {
    return `https://www.linkedin.com/feed/update/urn:li:activity:${activityId}/`;
  }
  try {
    const parsed = new URL(raw);
    parsed.search = "";
    parsed.hash = "";
    return parsed.toString().replace(/\/+$/, "");
  } catch {
    return raw;
  }
}

function isLinkedInProfileUrl(rawUrl) {
  const raw = cleanText(rawUrl);
  if (!raw) return false;
  try {
    const parsed = new URL(raw);
    const host = parsed.hostname.toLowerCase();
    if (!(host === "linkedin.com" || host === "www.linkedin.com" || host.endsWith(".linkedin.com"))) {
      return false;
    }
    return parsed.pathname.toLowerCase().includes("/in/");
  } catch {
    return false;
  }
}

function postIdentityKeys(post) {
  const keys = new Set();

  const activityId =
    extractActivityId(post && post.post_url) ||
    extractActivityId(post && post.title) ||
    extractActivityId(post && post.content) ||
    extractActivityId(post && post.text);
  if (activityId) keys.add(`activity:${activityId}`);

  const normalizedUrl = normalizeLinkedInUrl(post && post.post_url);
  if (normalizedUrl) keys.add(`url:${normalizedUrl}`);

  const snippet = normalizedSnippet(post && (post.content || post.text || post.title));
  if (snippet) {
    const day = normalizedDay(post && (post.posted_at || post.posted_at_iso));
    if (day) keys.add(`txt:${day}|${snippet}`);
    // Always add a "no-day" variant: posted_at can be missing, synthetic, or inconsistent.
    keys.add(`txt:|${snippet}`);
  }

  return keys;
}

function hasStableIdentityKey(keys) {
  for (const key of keys || []) {
    if (key.startsWith("activity:") || key.startsWith("url:")) return true;
  }
  return false;
}

function isDuplicateAgainstKeySet(post, keySet) {
  if (!keySet || !(keySet instanceof Set)) return false;
  const keys = postIdentityKeys(post);
  if (!keys.size) return false;

  const snippet = normalizedSnippet(post && (post.content || post.text || post.title));
  const isStrongTextFingerprint = snippet.length >= 80;

  const stableKeys = [];
  const textKeys = [];
  for (const key of keys) {
    if (key.startsWith("activity:") || key.startsWith("url:")) stableKeys.push(key);
    else if (key.startsWith("txt:")) textKeys.push(key);
  }

  for (const key of stableKeys) {
    if (keySet.has(key)) return true;
  }

  // Fallback: dedupe by text fingerprint as well. This is the only reliable
  // option when LinkedIn URL formats/ids differ between scrapes.
  const daySpecificTextKeys = textKeys.filter((key) => key.startsWith("txt:") && !key.startsWith("txt:|"));
  const noDayTextKeys = textKeys.filter((key) => key.startsWith("txt:|"));
  const keysToCheck = isStrongTextFingerprint
    ? [...daySpecificTextKeys, ...noDayTextKeys]
    : daySpecificTextKeys;

  for (const key of keysToCheck) {
    if (keySet.has(key)) return true;
  }
  for (const key of keysToCheck) {
    if (keySet.has(`legacy_${key}`)) return true;
  }
  return false;
}

function postIdentityKey(post) {
  // Canonical key (stable for UI / internal maps). For dedupe, use postIdentityKeys().
  for (const key of postIdentityKeys(post)) return key;
  return "";
}

function addIdentityKeysToSet(set, post) {
  const keys = postIdentityKeys(post);
  if (!keys.size) return;
  for (const key of keys) {
    if (key) set.add(key);
  }
  if (!hasStableIdentityKey(keys)) {
    for (const key of keys) {
      if (key && key.startsWith("txt:")) set.add(`legacy_${key}`);
    }
  }
}

function buildTitle(content, fallbackName = "") {
  const body = cleanText(content);
  if (body) {
    const clipped = body.length > 200 ? `${body.slice(0, 200).trim()}...` : body;
    return clipped.slice(0, 512);
  }
  const name = cleanText(fallbackName);
  return name ? `${name} — LinkedIn post` : "LinkedIn post";
}

function buildCandidateFromLinkedInPost(person, rawPost) {
  if (!person || !rawPost || typeof rawPost !== "object") return null;
  const personId = Number(person.id);
  if (!Number.isInteger(personId) || personId <= 0) return null;

  const content = cleanText(rawPost.content || rawPost.text || rawPost.title);
  const postUrl = normalizeLinkedInUrl(rawPost.post_url);
  if (!content && !postUrl) return null;

  const candidate = {
    key: "",
    person_id: personId,
    person_name: cleanText(person.full_name) || `Contact #${personId}`,
    person_linkedin_url: cleanText(person.linkedin_url),
    post_url: postUrl || null,
    posted_at: cleanText(rawPost.posted_at || rawPost.posted_at_iso) || null,
    content,
    title: cleanText(rawPost.title),
    likes_count: toNumberOrNull(rawPost.likes_count),
    comments_count: toNumberOrNull(rawPost.comments_count),
    reposts_count: toNumberOrNull(rawPost.reposts_count),
    views_count: toNumberOrNull(rawPost.views_count)
  };
  candidate.key = postIdentityKey(candidate);
  return candidate.key ? candidate : null;
}

function refreshSummary() {
  if (!scanStats.totalContacts) {
    summaryEl.textContent = "Контакты еще не загружены.";
    return;
  }

  if (scanning) {
    summaryEl.textContent = `Контактов: ${scanStats.totalContacts} · С LinkedIn: ${scanStats.scannableContacts} · Проверено: ${scanStats.checkedContacts}/${scanStats.scannableContacts} · Найдено новых: ${scanStats.foundPosts}`;
    return;
  }

  if (!hasScanned) {
    summaryEl.textContent = `Контактов: ${scanStats.totalContacts} · С LinkedIn: ${scanStats.scannableContacts}`;
    return;
  }

  summaryEl.textContent = `Контактов: ${scanStats.totalContacts} · С LinkedIn: ${scanStats.scannableContacts} · Проверено: ${scanStats.checkedContacts}/${scanStats.scannableContacts} · Контактов с новыми: ${scanStats.contactsWithNew} · К добавлению: ${pendingPosts.length}`;
}

function createMetricPill(label, value) {
  const text = formatNumber(value);
  if (!text) return null;
  const span = document.createElement("span");
  span.className = "metric-pill";
  span.textContent = `${label}: ${text}`;
  return span;
}

function renderPostsList() {
  postsListEl.replaceChildren();

  if (scanning) {
    const item = document.createElement("div");
    item.className = "posts-empty";
    item.textContent = "Проверяем профили LinkedIn, это может занять до 1-2 минут.";
    postsListEl.appendChild(item);
    return;
  }

  if (!hasScanned) {
    const item = document.createElement("div");
    item.className = "posts-empty";
    item.textContent = "Нажмите «Проверить новые посты», чтобы собрать новые публикации контактов.";
    postsListEl.appendChild(item);
    return;
  }

  if (!pendingPosts.length) {
    const item = document.createElement("div");
    item.className = "posts-empty";
    item.textContent = "Новых постов, которых нет в базе, не найдено.";
    postsListEl.appendChild(item);
    return;
  }

  for (const post of pendingPosts) {
    const card = document.createElement("article");
    card.className = "post-card";

    const header = document.createElement("div");
    header.className = "post-head";

    const person = document.createElement("p");
    person.className = "post-person";
    person.textContent = post.person_name;
    header.appendChild(person);

    const date = document.createElement("p");
    date.className = "post-date";
    date.textContent = formatDate(post.posted_at);
    header.appendChild(date);
    card.appendChild(header);

    const text = document.createElement("p");
    text.className = "post-content";
    const preview = cleanText(post.content);
    text.textContent = preview.length > 220 ? `${preview.slice(0, 220).trim()}...` : preview || "Без текста";
    card.appendChild(text);

    const metrics = document.createElement("div");
    metrics.className = "post-metrics";
    const likes = createMetricPill("Лайки", post.likes_count);
    const comments = createMetricPill("Комментарии", post.comments_count);
    const reposts = createMetricPill("Репосты", post.reposts_count);
    if (likes) metrics.appendChild(likes);
    if (comments) metrics.appendChild(comments);
    if (reposts) metrics.appendChild(reposts);
    if (metrics.childElementCount) {
      card.appendChild(metrics);
    }

    if (post.post_url) {
      const link = document.createElement("a");
      link.className = "post-link";
      link.href = post.post_url;
      link.target = "_blank";
      link.rel = "noreferrer noopener";
      link.textContent = "Открыть пост в LinkedIn";
      card.appendChild(link);
    }

    postsListEl.appendChild(card);
  }
}

function updateButtonsState() {
  scanBtn.disabled = scanning || adding || !allPeople.length;
  reloadPeopleBtn.disabled = scanning || adding;
  addBtn.disabled = scanning || adding || !pendingPosts.length;
  addBtn.textContent = adding
    ? "Добавляю..."
    : pendingPosts.length
      ? `Добавить (${pendingPosts.length})`
      : "Добавить";
}

function refreshUi() {
  refreshSummary();
  renderPostsList();
  updateButtonsState();
}

async function loadExistingPostKeysForPerson(personId) {
  const keys = new Set();
  const batches = [];
  batches.push(await listPosts({ person_id: personId, period: "all", sort: "desc", limit: 500, offset: 0 }));
  batches.push(await listPosts({ person_id: personId, period: "all", sort: "desc", archived: "true", limit: 500, offset: 0 }));
  for (const batch of batches) {
    if (!Array.isArray(batch) || !batch.length) continue;
    for (const post of batch) {
      addIdentityKeysToSet(keys, post);
    }
  }
  const local = getLocalDedupeKeySet(personId);
  if (local) {
    for (const key of local) keys.add(key);
  }
  return keys;
}

async function loadPeople() {
  showLoginButton(false);
  reloadPeopleBtn.disabled = true;
  setStatus("Загружаю контакты...");
  try {
    allPeople = await listPeople();
    scanStats.totalContacts = allPeople.length;
    scanStats.scannableContacts = allPeople.filter((person) => isLinkedInProfileUrl(person.linkedin_url)).length;
    scanStats.skippedNoLinkedIn = scanStats.totalContacts - scanStats.scannableContacts;
    setStatus(`Контактов загружено: ${allPeople.length}.`, "ok");
  } catch (err) {
    allPeople = [];
    scanStats = {
      totalContacts: 0,
      scannableContacts: 0,
      checkedContacts: 0,
      contactsWithNew: 0,
      foundPosts: 0,
      skippedNoLinkedIn: 0,
      errors: 0
    };
    const msg = err instanceof Error ? err.message : String(err || "Unknown error");
    setStatus(`Не удалось загрузить контакты: ${msg}`, "error");
    showLoginButton(err instanceof ApiError && err.status === 401);
  } finally {
    reloadPeopleBtn.disabled = false;
    refreshUi();
  }
}

async function runScan({ auto = false } = {}) {
  if (scanning || adding) return;
  if (!allPeople.length) {
    setStatus("Сначала загрузите контакты.", "error");
    return;
  }

  const scannablePeople = allPeople.filter((person) => isLinkedInProfileUrl(person.linkedin_url));
  scanStats = {
    totalContacts: allPeople.length,
    scannableContacts: scannablePeople.length,
    checkedContacts: 0,
    contactsWithNew: 0,
    foundPosts: 0,
    skippedNoLinkedIn: allPeople.length - scannablePeople.length,
    errors: 0
  };

  pendingPosts = [];
  scanning = true;
  hasScanned = true;
  refreshUi();

  if (!scannablePeople.length) {
    scanning = false;
    setStatus("Нет контактов с валидным LinkedIn URL.", "error");
    refreshUi();
    return;
  }

  let abortedUnauthorized = false;
  const seenCandidateKeysByPerson = new Map();
  const existsProbeCache = new Map();

  for (let i = 0; i < scannablePeople.length; i += 1) {
    const person = scannablePeople[i];
    const personName = cleanText(person.full_name) || `Contact #${person.id}`;
    scanStats.checkedContacts = i + 1;
    setStatus(`[${i + 1}/${scannablePeople.length}] Проверяю ${personName}...`);
    refreshSummary();

    try {
      const existingKeys = await loadExistingPostKeysForPerson(Number(person.id));
      const response = await chrome.runtime.sendMessage({
        type: "MYVOICE_GET_PROFILE_TOP_POSTS",
        profileUrl: cleanText(person.linkedin_url)
      });
      if (!response || !response.ok || !response.data) {
        throw new Error(response && response.error ? response.error : "Не удалось прочитать профиль LinkedIn.");
      }

      const rawPosts = Array.isArray(response.data.new_posts)
        ? response.data.new_posts
        : Array.isArray(response.data.posts)
          ? response.data.posts
          : [];

      let personNewPosts = 0;
      for (const rawPost of rawPosts) {
        const candidate = buildCandidateFromLinkedInPost(person, rawPost);
        if (!candidate) continue;
        let seenKeys = seenCandidateKeysByPerson.get(candidate.person_id);
        if (!seenKeys) {
          seenKeys = new Set();
          seenCandidateKeysByPerson.set(candidate.person_id, seenKeys);
        }

        if (isDuplicateAgainstKeySet(candidate, seenKeys)) continue;
        if (isDuplicateAgainstKeySet(candidate, existingKeys)) continue;

        // Extra dedupe: check backend duplicate detection across ALL saved posts (no history_days window).
        // We do a "probe create" with invalid person_id; backend returns 409 if the post already exists.
        if (candidate.post_url) {
          const cacheKey = candidate.key || candidate.post_url;
          let exists = existsProbeCache.get(cacheKey);
          if (exists === undefined) {
            try {
              exists = await probePostExistsByUrl(candidate.post_url);
              existsProbeCache.set(cacheKey, exists);
            } catch (probeErr) {
              if (probeErr instanceof ApiError && probeErr.status === 401) {
                throw probeErr;
              }
              // If probe fails (non-auth), keep the post to avoid missing new ones.
              exists = null;
              existsProbeCache.set(cacheKey, null);
            }
          }
          if (exists === true) continue;
        }

        addIdentityKeysToSet(seenKeys, candidate);
        pendingPosts.push(candidate);
        personNewPosts += 1;
      }

      if (personNewPosts > 0) {
        scanStats.contactsWithNew += 1;
        scanStats.foundPosts += personNewPosts;
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        abortedUnauthorized = true;
        showLoginButton(true);
        setStatus("Нужен вход в MyVOICE. Нажмите «Войти в MyVOICE».", "error");
        break;
      }
      scanStats.errors += 1;
    }

    refreshUi();
    await sleep(180);
  }

  scanning = false;
  refreshUi();

  if (abortedUnauthorized) return;

  if (!pendingPosts.length) {
    setStatus(
      auto
        ? `Проверка завершена: новых постов нет (${scanStats.checkedContacts}/${scanStats.scannableContacts}).`
        : "Проверка завершена: новых постов нет.",
      "ok"
    );
    return;
  }

  setStatus(
    `Найдено новых постов: ${pendingPosts.length}. Нажмите «Добавить», чтобы сохранить их в систему.`,
    "ok"
  );
}

function buildCreatePayload(post) {
  const content = cleanText(post.content) || null;
  return {
    person_id: Number(post.person_id),
    title: buildTitle(content, post.person_name),
    content,
    post_url: cleanText(post.post_url) || null,
    posted_at: cleanText(post.posted_at) || new Date().toISOString(),
    likes_count: toIntOrNull(post.likes_count),
    comments_count: toIntOrNull(post.comments_count),
    views_count: toIntOrNull(post.views_count)
  };
}

async function probePostExistsByUrl(postUrl) {
  const raw = cleanText(postUrl);
  if (!raw) return null;

  // Backend dedupe only understands activity-/ugcPost- and urn:li:activity:. Older saved
  // posts may be stored as share/ugcPost URLs, so probe a few stable variants by id.
  const activityId = extractActivityId(raw);
  const variants = new Set();
  variants.add(normalizeLinkedInUrl(raw));
  if (activityId) {
    variants.add(`https://www.linkedin.com/feed/update/urn:li:activity:${activityId}/`);
    variants.add(`https://www.linkedin.com/feed/update/urn:li:share:${activityId}/`);
    variants.add(`https://www.linkedin.com/feed/update/urn:li:ugcPost:${activityId}/`);
  }

  try {
    for (const url of variants) {
      if (!url) continue;
      try {
        await createPost({
          person_id: -1,
          title: "probe",
          content: null,
          post_url: url,
          posted_at: new Date().toISOString(),
          likes_count: null,
          comments_count: null,
          views_count: null
        });
        // Should never happen: person_id=-1 is invalid. Treat as exists for safety.
        return true;
      } catch (err) {
        if (err instanceof ApiError) {
          if (err.status === 409) return true; // duplicate => already in system
          if (err.status === 404) continue; // contact not found => try other variants
        }
        throw err;
      }
    }
    return false;
  } catch (err) {
    throw err;
  }
}

async function addAllPendingPosts() {
  if (adding || scanning || !pendingPosts.length) return;

  adding = true;
  showLoginButton(false);
  refreshUi();

  const originalTotal = pendingPosts.length;
  const uniquePersonIds = Array.from(
    new Set(pendingPosts.map((post) => Number(post.person_id)).filter((id) => Number.isInteger(id) && id > 0))
  );

  // Re-check duplicates right before adding to avoid creating duplicates when:
  // - the scan result is stale (posts were added from another device/session),
  // - backend doesn't enforce uniqueness reliably,
  // - or a post has no stable URL/id and is matched by a text fingerprint.
  const existingKeysByPerson = new Map();
  let preSkippedExisting = 0;
  let preSkippedBatchDupes = 0;
  try {
    for (let i = 0; i < uniquePersonIds.length; i += 1) {
      const personId = uniquePersonIds[i];
      setStatus(`[${i + 1}/${uniquePersonIds.length}] Проверяю дубликаты для контакта #${personId}...`);
      existingKeysByPerson.set(personId, await loadExistingPostKeysForPerson(personId));
    }
  } catch (err) {
    adding = false;
    refreshUi();
    if (err instanceof ApiError && err.status === 401) {
      showLoginButton(true);
      setStatus("Нужен вход в MyVOICE. Нажмите «Войти в MyVOICE».", "error");
      return;
    }
    const msg = err instanceof Error ? err.message : String(err || "Unknown error");
    setStatus(`Не удалось проверить дубликаты: ${msg}`, "error");
    return;
  }

  const filtered = [];
  const seenKeysByPerson = new Map();
  for (const post of pendingPosts) {
    const personId = Number(post.person_id);
    const existingKeys = existingKeysByPerson.get(personId);

    let seenKeys = seenKeysByPerson.get(personId);
    if (!seenKeys) {
      seenKeys = new Set();
      seenKeysByPerson.set(personId, seenKeys);
    }

    if (isDuplicateAgainstKeySet(post, seenKeys)) {
      preSkippedBatchDupes += 1;
      continue;
    }

    if (existingKeys && isDuplicateAgainstKeySet(post, existingKeys)) {
      preSkippedExisting += 1;
      continue;
    }

    addIdentityKeysToSet(seenKeys, post);
    filtered.push(post);
  }

  pendingPosts = filtered;
  refreshUi();

  if (!pendingPosts.length) {
    adding = false;
    refreshUi();
    const skipped = preSkippedExisting + preSkippedBatchDupes;
    setStatus(
      skipped
        ? `Все ${originalTotal} постов уже были в базе (пропущено: ${skipped}).`
        : "Нет постов для добавления.",
      "ok"
    );
    return;
  }

  const total = pendingPosts.length;
  let added = 0;
  let skippedDuplicates = 0;
  const failed = [];

  for (let i = 0; i < total; i += 1) {
    const post = pendingPosts[i];
    const payload = buildCreatePayload(post);
    setStatus(`[${i + 1}/${total}] Добавляю пост: ${post.person_name}...`);
    try {
      await createPost(payload);
      added += 1;

      const existingKeys = existingKeysByPerson.get(Number(post.person_id));
      if (existingKeys) addIdentityKeysToSet(existingKeys, payload);
      const localKeys = getLocalDedupeKeySet(Number(post.person_id));
      if (localKeys) addIdentityKeysToSet(localKeys, payload);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        skippedDuplicates += 1;
        const existingKeys = existingKeysByPerson.get(Number(post.person_id));
        if (existingKeys) addIdentityKeysToSet(existingKeys, payload);
        const localKeys = getLocalDedupeKeySet(Number(post.person_id));
        if (localKeys) addIdentityKeysToSet(localKeys, payload);
        continue;
      }
      if (err instanceof ApiError && err.status === 401) {
        showLoginButton(true);
      }
      failed.push(post);
    }
  }

  await persistLocalDedupeKeys();

  pendingPosts = failed;
  adding = false;
  refreshUi();

  if (!failed.length) {
    const skipped = skippedDuplicates + preSkippedExisting + preSkippedBatchDupes;
    setStatus(`Готово. Добавлено: ${added}. Уже были в базе: ${skipped}.`, "ok");
    return;
  }

  setStatus(
    `Частично выполнено. Добавлено: ${added}, уже были в базе: ${skippedDuplicates + preSkippedExisting + preSkippedBatchDupes}, ошибок: ${failed.length}.`,
    failed.length ? "error" : "ok"
  );
}

async function openLogin() {
  const baseUrl = await getBackendUrl();
  await chrome.tabs.create({ url: `${baseUrl}/login?next=/ui/posts` });
}

scanBtn.addEventListener("click", () => {
  runScan();
});

reloadPeopleBtn.addEventListener("click", async () => {
  await loadPeople();
});

addBtn.addEventListener("click", addAllPendingPosts);
loginBtn.addEventListener("click", openLogin);

openOptionsLink.addEventListener("click", (e) => {
  e.preventDefault();
  chrome.runtime.openOptionsPage();
});

(async () => {
  await loadLocalDedupeKeys();
  refreshUi();
  await loadPeople();
})();
