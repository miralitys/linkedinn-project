import { createPerson, listPeople } from "./lib/api.js";
import { DEFAULT_BACKEND_URL, PENDING_TAB_ID_KEY, PENDING_URL_KEY } from "./lib/config.js";

const MENU_ID = "myvoice-save-linkedin-post";
const PROFILE_TOP_POSTS_WINDOW_DAYS = 90;
const PROFILE_TOP_POSTS_LIMIT = 10;
const PROFILE_NEW_POSTS_LIMIT = 5;
const TOP_POSTS_CACHE_TTL_MS = 3 * 60 * 1000;
const PROFILE_SCRAPE_MAX_POSTS = 45;
const PROFILE_SCRAPE_MAX_SCROLL_STEPS = 12;
const PROFILE_SCRAPE_SCROLL_DELAY_MS = 700;
const TAB_LOAD_TIMEOUT_MS = 35 * 1000;
const SCRAPE_CANCELLED_CODE = "SCRAPE_CANCELLED";
const BACKEND_URL_KEY = "myvoice_backend_url";
const PEOPLE_CACHE_TTL_MS = 30 * 1000;
const SETUP_AUTHORS_CACHE_TTL_MS = 30 * 1000;
const COMMENT_AGENT_PROMPT_VERSION = "default"; // v1 prompt family
const COMMENT_AGENT_MAX_POST_TEXT_CHARS = 3200;

const topPostsCache = new Map();
const topPostsInflight = new Map();
const topPostsJobs = new Map();
let peopleCacheUpdatedAt = 0;
let peopleCacheData = null;
let peopleCacheInflight = null;
let setupAuthorsCacheUpdatedAt = 0;
let setupAuthorsCacheData = null;
let setupAuthorsCacheInflight = null;

function cleanText(value) {
  return String(value || "").trim();
}

function normalizeBackendUrl(input) {
  const raw = cleanText(input);
  if (!raw) return DEFAULT_BACKEND_URL;
  const withScheme = /^https?:\/\//i.test(raw) ? raw : `http://${raw}`;
  let normalized = withScheme.replace(/\/+$/, "");
  try {
    const parsed = new URL(normalized);
    const host = parsed.hostname.toLowerCase();
    const isLocalHost = host === "localhost" || host === "127.0.0.1" || host === "127.0.0.2";
    if (isLocalHost && parsed.protocol === "https:") {
      parsed.protocol = "http:";
      normalized = parsed.toString().replace(/\/+$/, "");
    }
  } catch {
    // Keep best-effort value for malformed URLs.
  }
  return normalized;
}

async function getBackendBaseUrl() {
  const data = await chrome.storage.sync.get(BACKEND_URL_KEY);
  return normalizeBackendUrl(data[BACKEND_URL_KEY] || DEFAULT_BACKEND_URL);
}

async function parseBackendPayload(response) {
  const contentType = String(response.headers.get("content-type") || "").toLowerCase();
  if (contentType.includes("application/json")) {
    return response.json();
  }
  const text = await response.text();
  return text ? { message: text } : null;
}

function toBackendErrorMessage(status, payload, fallback = "Request failed") {
  if (payload && typeof payload === "object") {
    if (typeof payload.detail === "string" && payload.detail) return payload.detail;
    if (typeof payload.error === "string" && payload.error) return payload.error;
    if (typeof payload.message === "string" && payload.message) return payload.message;
  }
  return `${fallback} (HTTP ${status})`;
}

async function backendRequest(path, init = {}) {
  const baseUrl = await getBackendBaseUrl();
  const headers = { Accept: "application/json", ...(init.headers || {}) };
  const body = init.body;
  const isObjectBody = body && typeof body === "object" && !(body instanceof FormData);
  if (isObjectBody) headers["Content-Type"] = "application/json";

  let response;
  try {
    response = await fetch(`${baseUrl}${path}`, {
      ...init,
      headers,
      body: isObjectBody ? JSON.stringify(body) : body,
      credentials: "include"
    });
  } catch (err) {
    const details = err instanceof Error ? err.message : String(err || "");
    throw new Error(
      details
        ? `Network error. Can't reach backend at ${baseUrl}. ${details}`
        : `Network error. Can't reach backend at ${baseUrl}.`
    );
  }

  const payload = await parseBackendPayload(response);
  if (!response.ok) {
    throw new Error(toBackendErrorMessage(response.status, payload));
  }
  return payload;
}

function normalizeGeneratedVariants(rawComments) {
  const comments = rawComments && typeof rawComments === "object" ? rawComments : {};
  const stripVariantLabel = (value) => {
    let text = cleanText(value);
    if (!text) return "";
    const patterns = [
      /^#{1,6}\s*(short|medium|long)\s*(?:\(\s*\d+\s*words?\s*\))?\s*[:\-–—]*\s*/i,
      /^\[\s*(short|medium|long)\s*\]\s*[:\-–—]*\s*/i,
      /^(short|medium|long)\s*(?:\(\s*\d+\s*words?\s*\))?\s*[:\-–—]\s*/i,
      /^"(short|medium|long)"\s*:\s*/i
    ];
    for (let i = 0; i < 3; i += 1) {
      let changed = false;
      for (const pattern of patterns) {
        const next = text.replace(pattern, "").trim();
        if (next !== text) {
          text = next;
          changed = true;
        }
      }
      if (!changed) break;
    }
    return text;
  };
  return {
    short: stripVariantLabel(comments.short),
    medium: stripVariantLabel(comments.medium),
    long: stripVariantLabel(comments.long)
  };
}

function normalizeSetupAuthor(rawAuthor) {
  if (!rawAuthor || typeof rawAuthor !== "object") return null;
  const fullName = cleanText(rawAuthor.full_name || rawAuthor.name);
  if (!fullName) return null;
  return {
    full_name: fullName,
    role: cleanText(rawAuthor.role),
    history: cleanText(rawAuthor.history),
    linkedin_url: cleanText(rawAuthor.linkedin_url || rawAuthor.linkedin)
  };
}

function normalizeSetupAuthorsList(rawList) {
  const list = Array.isArray(rawList) ? rawList : [];
  const seen = new Set();
  const result = [];
  for (const item of list) {
    const normalized = normalizeSetupAuthor(item);
    if (!normalized) continue;
    const key = `${normalized.full_name.toLowerCase()}|${normalized.linkedin_url.toLowerCase()}`;
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(normalized);
  }
  return result;
}

async function getSetupAuthorsCached({ force = false } = {}) {
  const now = Date.now();
  if (!force && Array.isArray(setupAuthorsCacheData) && now - setupAuthorsCacheUpdatedAt < SETUP_AUTHORS_CACHE_TTL_MS) {
    return setupAuthorsCacheData;
  }
  if (!force && setupAuthorsCacheInflight) {
    return setupAuthorsCacheInflight;
  }

  setupAuthorsCacheInflight = (async () => {
    const draft = await backendRequest("/setup/draft", { method: "GET" });
    const authors = normalizeSetupAuthorsList(draft && (draft.authors || draft.setup_authors));
    setupAuthorsCacheData = authors;
    setupAuthorsCacheUpdatedAt = Date.now();
    return authors;
  })();

  try {
    return await setupAuthorsCacheInflight;
  } finally {
    setupAuthorsCacheInflight = null;
  }
}

async function generateCommentVariantsForPost(postText, selectedAuthor = null) {
  const fullText = cleanText(postText);
  const text = fullText.length > COMMENT_AGENT_MAX_POST_TEXT_CHARS
    ? `${fullText.slice(0, COMMENT_AGENT_MAX_POST_TEXT_CHARS).trim()}...`
    : fullText;
  if (!text) {
    throw new Error("Post text is empty.");
  }
  const author = normalizeSetupAuthor(selectedAuthor);
  const payload = {
    post_text: text,
    goal: "network",
    prompt_version: COMMENT_AGENT_PROMPT_VERSION
  };
  if (author) {
    payload.author = author;
  }

  const response = await backendRequest("/agents/comment_agent/run", {
    method: "POST",
    body: {
      payload
    }
  });

  const comments = normalizeGeneratedVariants(response && response.result && response.result.comments);
  if (!comments.short && !comments.medium && !comments.long) {
    throw new Error("No comment variants were returned.");
  }
  return {
    variants: comments,
    draftId: response && response.draft_id != null ? response.draft_id : null
  };
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function isLinkedInHost(hostname) {
  const host = String(hostname || "").toLowerCase();
  return host === "linkedin.com" || host === "www.linkedin.com" || host.endsWith(".linkedin.com");
}

function isLinkedInUrl(url) {
  const s = String(url || "").toLowerCase();
  if (!s.startsWith("http")) return false;
  if (!s.includes("linkedin.com")) return false;
  return s.includes("/feed/update/") || s.includes("/posts/") || s.includes("activity-");
}

function buildDisplayNameFromSlug(slug) {
  const normalized = decodeURIComponent(cleanText(slug))
    .replace(/[-_]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (!normalized) return "";
  const words = normalized.split(" ").filter(Boolean).slice(0, 6);
  return words
    .map((word) => `${word.slice(0, 1).toUpperCase()}${word.slice(1)}`)
    .join(" ");
}

function isGenericActivityLabel(value) {
  const text = cleanText(value).toLowerCase();
  if (!text) return true;
  return text === "activity" || text === "recent activity" || text.includes("recent activity on linkedin");
}

function splitPersonName(fullName) {
  const normalized = cleanText(fullName).replace(/\s+/g, " ").trim();
  if (!normalized) return { firstName: "", lastName: "" };
  const words = normalized.split(" ").filter(Boolean);
  if (words.length === 1) return { firstName: words[0], lastName: "" };
  return {
    firstName: words[0],
    lastName: words.slice(1).join(" ")
  };
}

function normalizePersonName(value) {
  return cleanText(value)
    .toLowerCase()
    .replace(/[^a-z0-9а-яё\s-]/gi, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function parseLinkedInEntity(url) {
  const raw = cleanText(url);
  if (!raw) return null;
  try {
    const parsed = new URL(raw);
    if (!isLinkedInHost(parsed.hostname)) return null;
    const parts = parsed.pathname
      .split("/")
      .map((part) => cleanText(part).toLowerCase())
      .filter(Boolean);
    if (parts.length < 2) return null;
    const scope = parts[0];
    if (!["in", "company", "school"].includes(scope)) return null;
    return {
      scope,
      slug: parts[1],
      key: `${scope}/${parts[1]}`,
      url: `${parsed.origin}/${scope}/${parts[1]}/`
    };
  } catch {
    return null;
  }
}

function buildPersonPayload(rawPerson) {
  const fullName = cleanText(rawPerson && rawPerson.full_name);
  const firstName = cleanText(rawPerson && rawPerson.first_name);
  const lastName = cleanText(rawPerson && rawPerson.last_name);
  const combinedName = cleanText(fullName || `${firstName} ${lastName}`);
  const nameParts = splitPersonName(combinedName);
  const profile = parseLinkedInEntity(cleanText(rawPerson && rawPerson.linkedin_url));
  return {
    full_name: combinedName,
    first_name: firstName || nameParts.firstName,
    last_name: lastName || nameParts.lastName,
    linkedin_url: profile ? profile.url : cleanText(rawPerson && rawPerson.linkedin_url)
  };
}

function findExistingPersonByPayload(people, payload) {
  const list = Array.isArray(people) ? people : [];
  if (!list.length) return null;

  const targetEntity = parseLinkedInEntity(payload && payload.linkedin_url);
  if (targetEntity) {
    const byLinkedin = list.find((person) => {
      const personEntity = parseLinkedInEntity(person && person.linkedin_url);
      return personEntity && personEntity.key === targetEntity.key;
    });
    if (byLinkedin) return byLinkedin;
  }

  const targetName = normalizePersonName(payload && payload.full_name);
  if (!targetName) return null;
  return list.find((person) => normalizePersonName(person && person.full_name) === targetName) || null;
}

async function getPeopleCached({ force = false } = {}) {
  const now = Date.now();
  if (!force && Array.isArray(peopleCacheData) && now - peopleCacheUpdatedAt < PEOPLE_CACHE_TTL_MS) {
    return peopleCacheData;
  }
  if (!force && peopleCacheInflight) {
    return peopleCacheInflight;
  }

  peopleCacheInflight = (async () => {
    const people = await listPeople();
    peopleCacheData = Array.isArray(people) ? people : [];
    peopleCacheUpdatedAt = Date.now();
    return peopleCacheData;
  })();

  try {
    return await peopleCacheInflight;
  } finally {
    peopleCacheInflight = null;
  }
}

async function checkPersonInSystem(rawPerson) {
  const payload = buildPersonPayload(rawPerson);
  if (!payload.full_name && !payload.linkedin_url) {
    return { exists: false, person: null, payload };
  }
  const people = await getPeopleCached();
  const existing = findExistingPersonByPayload(people, payload);
  return { exists: Boolean(existing), person: existing || null, payload };
}

async function addPersonToSystem(rawPerson) {
  const payload = buildPersonPayload(rawPerson);
  if (!payload.full_name) {
    throw new Error("Profile full name is required.");
  }

  const people = await getPeopleCached();
  const existing = findExistingPersonByPayload(people, payload);
  if (existing) {
    return { added: false, person: existing, payload };
  }

  const created = await createPerson({
    full_name: payload.full_name,
    linkedin_url: payload.linkedin_url || null
  });

  peopleCacheUpdatedAt = 0;
  peopleCacheData = null;
  return { added: true, person: created || null, payload };
}

function parseLinkedInProfile(url) {
  const raw = cleanText(url);
  if (!raw) return null;
  try {
    const parsed = new URL(raw);
    if (!isLinkedInHost(parsed.hostname)) return null;
    const parts = parsed.pathname
      .split("/")
      .map((part) => cleanText(part).toLowerCase())
      .filter(Boolean);
    if (parts.length < 2 || parts[0] !== "in") return null;
    const slug = parts[1];
    return {
      slug,
      profileKey: `in/${slug}`,
      profileUrl: `${parsed.origin}/in/${slug}/`,
      recentActivityUrl: `${parsed.origin}/in/${slug}/recent-activity/all/`,
      displayName: buildDisplayNameFromSlug(slug)
    };
  } catch {
    return null;
  }
}

function cancelledError() {
  const err = new Error(SCRAPE_CANCELLED_CODE);
  err.code = SCRAPE_CANCELLED_CODE;
  return err;
}

function isCancelledError(err) {
  if (!err) return false;
  const code = cleanText(err.code);
  const message = cleanText(err.message);
  return code === SCRAPE_CANCELLED_CODE || message === SCRAPE_CANCELLED_CODE;
}

function toNumber(value, fallback = 0) {
  if (value == null || value === "") return fallback;
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function postDateMs(post) {
  const raw = cleanText(post && (post.posted_at_iso || post.posted_at));
  if (!raw) return Number.NaN;
  const dt = new Date(raw);
  return dt.getTime();
}

function scorePost(post) {
  const reactions = toNumber(post.reactions_count != null ? post.reactions_count : post.likes_count, 0);
  const comments = toNumber(post.comments_count, 0);
  const reposts = toNumber(post.reposts_count, 0);
  const views = toNumber(post.views_count, 0);
  return reactions + comments * 3 + reposts * 2 + views * 0.02;
}

function extractActivityId(raw) {
  const text = String(raw || "");
  const patterns = [
    /urn:li:activity:(\d{8,})/i,
    /activity-(\d{8,})/i,
    /ugcPost-(\d{8,})/i,
    /urn:li:ugcPost:(\d{8,})/i,
    /urn:li:share:(\d{8,})/i,
    /share-(\d{8,})/i
  ];
  for (const pattern of patterns) {
    const match = text.match(pattern);
    if (match && match[1]) return match[1];
  }
  return "";
}

function normalizeUrlForKey(rawUrl) {
  const raw = cleanText(rawUrl);
  if (!raw) return "";
  try {
    const parsed = new URL(raw);
    parsed.search = "";
    parsed.hash = "";
    return parsed.toString().replace(/\/+$/, "");
  } catch {
    return raw;
  }
}

function normalizedDay(raw) {
  const dt = new Date(cleanText(raw));
  if (Number.isNaN(dt.getTime())) return "";
  return dt.toISOString().slice(0, 10);
}

function normalizedSnippet(raw) {
  return cleanText(raw)
    .toLowerCase()
    .replace(/\s+/g, " ")
    .slice(0, 200);
}

function postIdentityKey(post) {
  const activityId =
    extractActivityId(post && post.post_url) ||
    extractActivityId(post && post.title) ||
    extractActivityId(post && post.content) ||
    extractActivityId(post && post.text);
  if (activityId) return `activity:${activityId}`;

  const normalizedUrl = normalizeUrlForKey(post && post.post_url);
  if (normalizedUrl) return `url:${normalizedUrl}`;

  const day = normalizedDay(post && (post.posted_at_iso || post.posted_at));
  const snippet = normalizedSnippet(post && (post.text || post.content || post.title));
  return `txt:${day}|${snippet}`;
}

function dedupePosts(posts) {
  const byKey = new Map();
  for (const post of posts) {
    const key = postIdentityKey(post);
    if (!key) continue;
    const existing = byKey.get(key);
    if (!existing) {
      byKey.set(key, post);
      continue;
    }

    const existingScore = scorePost(existing);
    const candidateScore = scorePost(post);
    const existingDate = postDateMs(existing);
    const candidateDate = postDateMs(post);
    const shouldReplace =
      candidateScore > existingScore ||
      (candidateScore === existingScore && candidateDate > existingDate);
    if (shouldReplace) byKey.set(key, post);
  }
  return Array.from(byKey.values());
}

function resolvePostUrl(post) {
  const activityId =
    extractActivityId(post && post.post_url) ||
    extractActivityId(post && post.title) ||
    extractActivityId(post && post.content) ||
    extractActivityId(post && post.text) ||
    extractActivityId(post ? JSON.stringify(post) : "");
  if (activityId) return `https://www.linkedin.com/feed/update/urn:li:activity:${activityId}/`;

  const direct = cleanText(post && post.post_url);
  const normalized = normalizeUrlForKey(direct);
  return normalized || null;
}

function mapPostForUi(post, score) {
  return {
    title: cleanText(post.title),
    content: cleanText(post.text || post.content),
    post_url: resolvePostUrl(post),
    posted_at: cleanText(post.posted_at_iso || post.posted_at) || null,
    likes_count: toNumber(post.reactions_count != null ? post.reactions_count : post.likes_count, null),
    comments_count: toNumber(post.comments_count, null),
    reposts_count: toNumber(post.reposts_count, null),
    views_count: toNumber(post.views_count, null),
    score: Math.round(score * 100) / 100
  };
}

function pickTopPosts(posts, { days, topN }) {
  const uniquePosts = dedupePosts(Array.isArray(posts) ? posts : []);
  const cutoffMs = Date.now() - days * 24 * 60 * 60 * 1000;
  const rankedInWindow = [];
  const rankedFallback = [];
  for (const post of uniquePosts) {
    const postedAtMs = postDateMs(post);
    const score = scorePost(post);
    if (Number.isFinite(postedAtMs)) {
      rankedFallback.push({ post, score, postedAtMs });
      if (postedAtMs >= cutoffMs) {
        rankedInWindow.push({ post, score, postedAtMs });
      }
    } else {
      rankedFallback.push({ post, score, postedAtMs: 0 });
    }
  }

  const sorter = (a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    return b.postedAtMs - a.postedAtMs;
  };

  if (rankedInWindow.length > 0) {
    rankedInWindow.sort(sorter);
    return rankedInWindow.slice(0, topN).map((item) => mapPostForUi(item.post, item.score));
  }

  rankedFallback.sort(sorter);
  return rankedFallback.slice(0, topN).map((item) => mapPostForUi(item.post, item.score));
}

function pickLatestPosts(posts, { topN }) {
  const uniquePosts = dedupePosts(Array.isArray(posts) ? posts : []);
  const dated = [];
  const undated = [];
  for (const post of uniquePosts) {
    const postedAtMs = postDateMs(post);
    const score = scorePost(post);
    const item = { post, score, postedAtMs: Number.isFinite(postedAtMs) ? postedAtMs : 0 };
    if (Number.isFinite(postedAtMs)) {
      dated.push(item);
    } else {
      undated.push(item);
    }
  }

  dated.sort((a, b) => {
    if (b.postedAtMs !== a.postedAtMs) return b.postedAtMs - a.postedAtMs;
    return b.score - a.score;
  });

  undated.sort((a, b) => b.score - a.score);

  return dated.concat(undated).slice(0, topN).map((item) => mapPostForUi(item.post, item.score));
}

async function waitForTabComplete(tabId, timeoutMs = TAB_LOAD_TIMEOUT_MS) {
  return new Promise((resolve, reject) => {
    let settled = false;
    let timeoutId = null;

    const cleanup = () => {
      if (timeoutId) clearTimeout(timeoutId);
      chrome.tabs.onUpdated.removeListener(onUpdated);
      chrome.tabs.onRemoved.removeListener(onRemoved);
    };

    const done = () => {
      if (settled) return;
      settled = true;
      cleanup();
      resolve();
    };

    const fail = (error) => {
      if (settled) return;
      settled = true;
      cleanup();
      reject(error);
    };

    const onUpdated = (updatedTabId, changeInfo) => {
      if (updatedTabId !== tabId) return;
      if (changeInfo.status === "complete") done();
    };

    const onRemoved = (removedTabId) => {
      if (removedTabId === tabId) fail(new Error("LinkedIn tab was closed before loading."));
    };

    timeoutId = setTimeout(() => {
      fail(new Error("Timed out while loading LinkedIn profile activity page."));
    }, timeoutMs);

    chrome.tabs.onUpdated.addListener(onUpdated);
    chrome.tabs.onRemoved.addListener(onRemoved);

    chrome.tabs.get(tabId)
      .then((tab) => {
        if (tab && tab.status === "complete") done();
      })
      .catch((err) => fail(err instanceof Error ? err : new Error(String(err || "Unknown tab error"))));
  });
}

async function safeCloseTab(tabId) {
  if (!Number.isInteger(tabId) || tabId <= 0) return;
  try {
    await chrome.tabs.remove(tabId);
  } catch {
    // Ignore: tab can be already closed.
  }
}

async function requestPostsFromTab(tabId, payload) {
  const attempts = 3;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return await chrome.tabs.sendMessage(tabId, payload);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err || "");
      const canRetry = attempt < attempts && message.includes("Receiving end does not exist");
      if (!canRetry) throw err;
      await chrome.tabs.reload(tabId);
      await waitForTabComplete(tabId);
      await sleep(1200);
    }
  }
  return null;
}

async function scrapeProfilePosts(profile, job = null) {
  if (job && job.cancelled) throw cancelledError();
  const tab = await chrome.tabs.create({ url: profile.recentActivityUrl, active: false });
  const tabId = Number(tab && tab.id);
  if (!Number.isInteger(tabId) || tabId <= 0) {
    throw new Error("Failed to open a hidden LinkedIn tab.");
  }
  if (job) job.tabId = tabId;

  try {
    if (job && job.cancelled) throw cancelledError();
    await waitForTabComplete(tabId);
    if (job && job.cancelled) throw cancelledError();
    await sleep(1400);
    if (job && job.cancelled) throw cancelledError();

    const response = await requestPostsFromTab(tabId, {
      type: "MYVOICE_EXTRACT_PROFILE_POSTS",
      expectedProfileKey: profile.profileKey,
      expectedSlug: profile.slug,
      maxPosts: PROFILE_SCRAPE_MAX_POSTS,
      maxScrollSteps: PROFILE_SCRAPE_MAX_SCROLL_STEPS,
      scrollDelayMs: PROFILE_SCRAPE_SCROLL_DELAY_MS
    });

    if (!response || !response.ok || !response.data) {
      const msg = response && response.error ? response.error : "Failed to parse profile posts from LinkedIn.";
      throw new Error(msg);
    }
    if (job && job.cancelled) throw cancelledError();
    return response.data;
  } finally {
    if (job) job.tabId = null;
    await safeCloseTab(tabId);
  }
}

async function getProfileTopPosts(profileUrl) {
  const profile = parseLinkedInProfile(profileUrl);
  if (!profile) {
    return { person: null, posts: [], reason: "not_profile_page" };
  }

  const now = Date.now();
  const cached = topPostsCache.get(profile.profileKey);
  if (cached && now - cached.updatedAt < TOP_POSTS_CACHE_TTL_MS) {
    return cached.payload;
  }

  if (topPostsInflight.has(profile.profileKey)) {
    return topPostsInflight.get(profile.profileKey);
  }

  const run = (async () => {
    const job = { cancelled: false, tabId: null };
    topPostsJobs.set(profile.profileKey, job);
    try {
      const extracted = await scrapeProfilePosts(profile, job);
      const parsedPosts = Array.isArray(extracted.posts) ? extracted.posts : [];
      const top = pickTopPosts(parsedPosts, {
        days: PROFILE_TOP_POSTS_WINDOW_DAYS,
        topN: PROFILE_TOP_POSTS_LIMIT
      });
      const latest = pickLatestPosts(parsedPosts, {
        topN: PROFILE_NEW_POSTS_LIMIT
      });
      const payload = {
        personName: isGenericActivityLabel(extracted.profile_name)
          ? (profile.displayName || profile.slug)
          : cleanText(extracted.profile_name),
        personAvatar: cleanText(extracted.profile_avatar_url),
      };
      const nameParts = splitPersonName(payload.personName);
      const responsePayload = {
        person: {
          full_name: payload.personName,
          first_name: nameParts.firstName,
          last_name: nameParts.lastName,
          nickname: profile.slug,
          avatar_url: payload.personAvatar || null,
          linkedin_url: profile.profileUrl
        },
        posts: top,
        best_posts: top,
        new_posts: latest,
        reason: top.length ? null : "no_posts_in_period",
        source: "linkedin_recent_activity"
      };
      topPostsCache.set(profile.profileKey, {
        updatedAt: Date.now(),
        payload: responsePayload
      });
      return responsePayload;
    } catch (err) {
      if (isCancelledError(err)) {
        if (cached && cached.payload) return cached.payload;
        return {
          person: null,
          posts: [],
          best_posts: [],
          new_posts: [],
          reason: "cancelled",
          source: "linkedin_recent_activity"
        };
      }
      throw err;
    } finally {
      topPostsJobs.delete(profile.profileKey);
    }
  })();

  topPostsInflight.set(profile.profileKey, run);
  try {
    return await run;
  } finally {
    topPostsInflight.delete(profile.profileKey);
  }
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({
      id: MENU_ID,
      title: "Save to MyVOICE's",
      contexts: ["page", "link"],
      documentUrlPatterns: ["https://www.linkedin.com/*"]
    });
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== MENU_ID) return;
  const candidate = info.linkUrl || info.pageUrl || "";
  if (!isLinkedInUrl(candidate)) return;
  const sourceTabId = Number(tab && tab.id);
  await chrome.storage.local.set({
    [PENDING_URL_KEY]: candidate,
    [PENDING_TAB_ID_KEY]: Number.isInteger(sourceTabId) ? sourceTabId : null
  });
  await chrome.tabs.create({ url: chrome.runtime.getURL("src/popup.html") });
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || !message.type) return;

  if (message.type === "MYVOICE_CHECK_PROFILE_PERSON") {
    checkPersonInSystem(message.person)
      .then((result) => {
        sendResponse({
          ok: true,
          exists: Boolean(result && result.exists),
          person: result ? result.person || null : null,
          payload: result ? result.payload || null : null
        });
      })
      .catch((err) => {
        const msg = err instanceof Error ? err.message : String(err || "Unknown error");
        sendResponse({ ok: false, error: msg });
      });
    return true;
  }

  if (message.type === "MYVOICE_ADD_PROFILE_PERSON") {
    addPersonToSystem(message.person)
      .then((result) => {
        sendResponse({
          ok: true,
          added: Boolean(result && result.added),
          person: result ? result.person || null : null,
          payload: result ? result.payload || null : null
        });
      })
      .catch((err) => {
        const msg = err instanceof Error ? err.message : String(err || "Unknown error");
        sendResponse({ ok: false, error: msg });
      });
    return true;
  }

  if (message.type === "MYVOICE_OPEN_LINKEDIN_POST") {
    const url = cleanText(message.url);
    const newTab = Boolean(message.newTab);
    if (!isLinkedInUrl(url)) {
      sendResponse({ ok: false, error: "Invalid LinkedIn post URL." });
      return;
    }

    if (newTab) {
      chrome.tabs.create({ url, active: true })
        .then(() => sendResponse({ ok: true }))
        .catch((err) => {
          const msg = err instanceof Error ? err.message : String(err || "Unknown error");
          sendResponse({ ok: false, error: msg });
        });
      return true;
    }

    const senderTabId = Number(sender && sender.tab && sender.tab.id);
    const updatePromise = Number.isInteger(senderTabId) && senderTabId > 0
      ? chrome.tabs.update(senderTabId, { url }).then(() => ({ ok: true }))
      : chrome.tabs.create({ url, active: true }).then(() => ({ ok: true }));

    updatePromise
      .then((result) => sendResponse(result))
      .catch((err) => {
        const msg = err instanceof Error ? err.message : String(err || "Unknown error");
        sendResponse({ ok: false, error: msg });
      });
    return true;
  }

  if (message.type === "MYVOICE_CANCEL_PROFILE_TOP_POSTS") {
    const profile = parseLinkedInProfile(cleanText(message.profileUrl));
    if (profile) {
      const job = topPostsJobs.get(profile.profileKey);
      if (job) {
        job.cancelled = true;
        if (Number.isInteger(job.tabId) && job.tabId > 0) {
          safeCloseTab(job.tabId).catch(() => {
            // ignore tab close race
          });
        }
      }
    }
    sendResponse({ ok: true });
    return;
  }

  if (message.type === "MYVOICE_GET_PROFILE_TOP_POSTS") {
    const profileUrl = cleanText(message.profileUrl);
    getProfileTopPosts(profileUrl)
      .then((payload) => {
        sendResponse({ ok: true, data: payload });
      })
      .catch((err) => {
        const msg = err instanceof Error ? err.message : String(err || "Unknown error");
        sendResponse({ ok: false, error: msg });
      });
    return true;
  }

  if (message.type === "MYVOICE_GET_SETUP_AUTHORS") {
    getSetupAuthorsCached({ force: Boolean(message.force) })
      .then((authors) => {
        sendResponse({ ok: true, authors });
      })
      .catch((err) => {
        const msg = err instanceof Error ? err.message : String(err || "Unknown error");
        sendResponse({ ok: false, error: msg });
      });
    return true;
  }

  if (message.type === "MYVOICE_GENERATE_COMMENT_VARIANTS") {
    const postText = cleanText(message.postText);
    const selectedAuthor = message.author && typeof message.author === "object" ? message.author : null;
    generateCommentVariantsForPost(postText, selectedAuthor)
      .then((payload) => {
        sendResponse({ ok: true, ...payload });
      })
      .catch((err) => {
        const msg = err instanceof Error ? err.message : String(err || "Unknown error");
        sendResponse({ ok: false, error: msg });
      });
    return true;
  }
});
