function cleanText(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function parseNumberToken(raw) {
  const text = cleanText(raw);
  if (!text) return null;
  const match = text.match(/(\d[\d\s.,]*)(?:\s*([kкmм]))?/i);
  if (!match || !match[1]) return null;

  let body = String(match[1] || "")
    .replace(/\u00a0/g, " ")
    .replace(/\s+/g, "")
    .trim();
  if (!body) return null;

  const commaCount = (body.match(/,/g) || []).length;
  const dotCount = (body.match(/\./g) || []).length;
  if (commaCount && dotCount) {
    const lastComma = body.lastIndexOf(",");
    const lastDot = body.lastIndexOf(".");
    const decimalSep = lastComma > lastDot ? "," : ".";
    const thousandsSep = decimalSep === "," ? "." : ",";
    body = body.replace(new RegExp(`\\${thousandsSep}`, "g"), "");
    if (decimalSep === ",") body = body.replace(",", ".");
  } else if (commaCount > 0) {
    if (commaCount > 1) {
      body = body.replace(/,/g, "");
    } else {
      const idx = body.indexOf(",");
      const digitsAfter = body.length - idx - 1;
      body = digitsAfter === 3 ? body.replace(",", "") : body.replace(",", ".");
    }
  } else if (dotCount > 1) {
    const last = body.lastIndexOf(".");
    const digitsAfter = body.length - last - 1;
    if (digitsAfter === 3) {
      body = body.replace(/\./g, "");
    } else {
      body = `${body.slice(0, last).replace(/\./g, "")}.${body.slice(last + 1)}`;
    }
  }

  const n = Number(body);
  if (!Number.isFinite(n)) return null;
  const suffix = String(match[2] || "").toLowerCase();
  if (suffix === "k" || suffix === "к") return Math.round(n * 1000);
  if (suffix === "m" || suffix === "м") return Math.round(n * 1000000);
  return Math.round(n);
}

function isLikelyHttpUrl(url) {
  const raw = String(url || "").trim();
  return /^https?:\/\//i.test(raw);
}

function normalizeImageUrl(rawUrl) {
  const raw = String(rawUrl || "").trim();
  if (!raw) return "";
  if (raw.startsWith("data:")) return "";
  try {
    const parsed = new URL(raw, window.location.origin);
    return isLikelyHttpUrl(parsed.toString()) ? parsed.toString() : "";
  } catch {
    return "";
  }
}

function readImgUrl(img) {
  if (!img) return "";
  const src = normalizeImageUrl(img.getAttribute("src"));
  if (src) return src;
  const delayed = normalizeImageUrl(img.getAttribute("data-delayed-url"));
  if (delayed) return delayed;
  const srcset = cleanText(img.getAttribute("srcset"));
  if (srcset) {
    const first = cleanText(srcset.split(",")[0]).split(" ")[0];
    const fromSrcset = normalizeImageUrl(first);
    if (fromSrcset) return fromSrcset;
  }
  return "";
}

function extractMetric(text, patterns) {
  const haystack = cleanText(text);
  for (const pattern of patterns) {
    const match = haystack.match(pattern);
    if (!match || !match[1]) continue;
    const parsed = parseNumberToken(match[1]);
    if (parsed != null) return parsed;
  }
  return null;
}

function extractPostId(url) {
  const s = String(url || "");
  const m = s.match(/(?:activity-|ugcPost-|share-)(\d+)/i);
  return m ? m[1] : "";
}

function pickArticle(url) {
  const postId = extractPostId(url);
  const all = Array.from(document.querySelectorAll("article, [role='article']"));
  if (all.length === 0) return null;
  if (!postId) return all[0];

  const match = all.find((article) =>
    Array.from(article.querySelectorAll("a[href]")).some((a) => String(a.href || "").includes(postId))
  );
  return match || all[0];
}

function extractAuthor(article) {
  const selectors = [
    "a[href*='/in/']",
    "a[href*='/company/']",
    "a[href*='/school/']"
  ];
  for (const selector of selectors) {
    const links = Array.from(article.querySelectorAll(selector));
    for (const link of links) {
      const text = cleanText(link.textContent);
      if (!text || text.length > 120) continue;
      if (/(follow|connect|подпис|контакт|message|сообщение)/i.test(text)) continue;
      return { name: text, url: String(link.href || "").trim() || null };
    }
  }
  return { name: null, url: null };
}

function extractAuthorAvatar(article, authorName = "") {
  const preferredSelectors = [
    "img.update-components-actor__avatar-image",
    "img.feed-shared-actor__avatar-image",
    "img[data-anonymize='headshot-photo']",
    "img.pv-top-card-profile-picture__image",
    "img[class*='avatar']",
    "img[class*='headshot']",
    "img[class*='profile-photo']"
  ];
  for (const selector of preferredSelectors) {
    const img = article.querySelector(selector);
    const imgUrl = readImgUrl(img);
    if (imgUrl) return imgUrl;
  }

  const authorLower = cleanText(authorName).toLowerCase();
  const images = Array.from(article.querySelectorAll("img"));
  for (const img of images) {
    const alt = cleanText(img.getAttribute("alt")).toLowerCase();
    const cls = cleanText(img.getAttribute("class")).toLowerCase();
    if (alt.includes("emoji") || alt.includes("icon")) continue;
    if (
      cls.includes("avatar") ||
      cls.includes("headshot") ||
      cls.includes("profile") ||
      (authorLower && alt.includes(authorLower))
    ) {
      const imgUrl = readImgUrl(img);
      if (imgUrl) return imgUrl;
    }
  }
  return null;
}

function extractPostText(article) {
  const selectors = [
    ".update-components-text",
    ".feed-shared-inline-show-more-text",
    "[data-test-id='main-feed-activity-card__commentary']",
    ".feed-shared-update-v2__description"
  ];
  const candidates = [];
  for (const selector of selectors) {
    const nodes = Array.from(article.querySelectorAll(selector));
    for (const node of nodes) {
      const text = cleanText(node.textContent);
      if (text) candidates.push(text);
    }
  }
  if (!candidates.length) return null;
  candidates.sort((a, b) => b.length - a.length);
  return candidates[0] || null;
}

function extractPublishedRaw(article) {
  const timeEl = article.querySelector("time");
  if (timeEl) {
    const datetimeAttr = cleanText(timeEl.getAttribute("datetime"));
    if (datetimeAttr) return datetimeAttr;
    const timeText = cleanText(timeEl.textContent);
    if (timeText) return timeText;
  }
  const candidates = Array.from(article.querySelectorAll("a, span"));
  for (const node of candidates) {
    const text = cleanText(node.textContent);
    if (!text) continue;
    // Covers strings like "posted this • 10h", "1d", "2 weeks ago", "3 мес."
    if (/(\d+)\s*(m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days|w|wk|wks|week|weeks|mo|mos|month|months|y|yr|yrs|year|years|мин|минута|минут|ч|час|часа|часов|дн|д|день|дня|дней|нед|неделя|недели|недель|мес|месяц|месяца|месяцев|г|год|года|лет)\b/i.test(text)) {
      return text;
    }
  }
  return null;
}

function parsePublishedIso(raw) {
  const value = cleanText(raw);
  if (!value) return null;

  const direct = new Date(value);
  if (!Number.isNaN(direct.getTime())) return direct.toISOString();

  const m = value.match(/(\d+)\s*(m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days|w|wk|wks|week|weeks|mo|mos|month|months|y|yr|yrs|year|years|мин|минута|минут|ч|час|часа|часов|дн|д|день|дня|дней|нед|неделя|недели|недель|мес|месяц|месяца|месяцев|г|год|года|лет)\b/i);
  if (!m) return null;
  const n = Number(m[1]);
  if (!Number.isFinite(n) || n <= 0) return null;
  const unit = m[2].toLowerCase();
  const now = Date.now();
  const offsets = {
    m: 60 * 1000,
    min: 60 * 1000,
    mins: 60 * 1000,
    minute: 60 * 1000,
    minutes: 60 * 1000,
    "мин": 60 * 1000,
    "минута": 60 * 1000,
    "минут": 60 * 1000,
    h: 60 * 60 * 1000,
    hr: 60 * 60 * 1000,
    hrs: 60 * 60 * 1000,
    hour: 60 * 60 * 1000,
    hours: 60 * 60 * 1000,
    "ч": 60 * 60 * 1000,
    "час": 60 * 60 * 1000,
    "часа": 60 * 60 * 1000,
    "часов": 60 * 60 * 1000,
    d: 24 * 60 * 60 * 1000,
    day: 24 * 60 * 60 * 1000,
    days: 24 * 60 * 60 * 1000,
    "дн": 24 * 60 * 60 * 1000,
    "д": 24 * 60 * 60 * 1000,
    "день": 24 * 60 * 60 * 1000,
    "дня": 24 * 60 * 60 * 1000,
    "дней": 24 * 60 * 60 * 1000,
    w: 7 * 24 * 60 * 60 * 1000,
    wk: 7 * 24 * 60 * 60 * 1000,
    wks: 7 * 24 * 60 * 60 * 1000,
    week: 7 * 24 * 60 * 60 * 1000,
    weeks: 7 * 24 * 60 * 60 * 1000,
    "нед": 7 * 24 * 60 * 60 * 1000,
    "неделя": 7 * 24 * 60 * 60 * 1000,
    "недели": 7 * 24 * 60 * 60 * 1000,
    "недель": 7 * 24 * 60 * 60 * 1000,
    mo: 30 * 24 * 60 * 60 * 1000,
    mos: 30 * 24 * 60 * 60 * 1000,
    month: 30 * 24 * 60 * 60 * 1000,
    months: 30 * 24 * 60 * 60 * 1000,
    "мес": 30 * 24 * 60 * 60 * 1000,
    "месяц": 30 * 24 * 60 * 60 * 1000,
    "месяца": 30 * 24 * 60 * 60 * 1000,
    "месяцев": 30 * 24 * 60 * 60 * 1000,
    y: 365 * 24 * 60 * 60 * 1000,
    yr: 365 * 24 * 60 * 60 * 1000,
    yrs: 365 * 24 * 60 * 60 * 1000,
    year: 365 * 24 * 60 * 60 * 1000,
    years: 365 * 24 * 60 * 60 * 1000,
    "г": 365 * 24 * 60 * 60 * 1000,
    "год": 365 * 24 * 60 * 60 * 1000,
    "года": 365 * 24 * 60 * 60 * 1000,
    "лет": 365 * 24 * 60 * 60 * 1000
  };
  const step = offsets[unit];
  if (!step) return null;
  return new Date(now - n * step).toISOString();
}

function extractFromCurrentPage(targetUrl) {
  const url = String(targetUrl || window.location.href || "").trim();
  const article = pickArticle(url);
  if (!article) {
    return { ok: false, error: "No post card found on this page." };
  }

  const author = extractAuthor(article);
  const text = extractPostText(article);
  if (!author.name && !text) {
    return { ok: false, error: "Failed to extract post content from this page." };
  }

  const articleText = cleanText(article.innerText);
  const publishedAtRaw = extractPublishedRaw(article);
  return {
    ok: true,
    data: {
      author_name: author.name,
      author_profile_url: author.url,
      text: text || null,
      post_url: url || window.location.href,
      published_at_raw: publishedAtRaw,
      posted_at_iso: parsePublishedIso(publishedAtRaw),
      reactions_count: extractMetric(articleText, [
        /(\d[\d.,\s]*[KkMmКкМм]?)\s*(?:reactions?|реакц(?:ия|ии|ий|ий))/i,
        /(\d[\d.,\s]*[KkMmКкМм]?)\s*(?:likes?|лайк(?:ов|а|и)?)/i
      ]),
      comments_count: extractMetric(articleText, [
        /(\d[\d.,\s]*[KkMmКкМм]?)\s*(?:comments?|комментар(?:ий|ия|иев))/i
      ]),
      views_count: extractMetric(articleText, [
        /(\d[\d.,\s]*[KkMmКкМм]?)\s*(?:views?|просмотр(?:ов|а)?)/i
      ])
    }
  };
}

function parseLinkedInProfileKeyFromUrl(url) {
  const raw = String(url || "").trim();
  if (!raw) return "";
  try {
    const parsed = new URL(raw);
    if (!isLinkedInHost(parsed.hostname)) return "";
    const parts = parsed.pathname
      .split("/")
      .map((part) => cleanText(part).toLowerCase())
      .filter(Boolean);
    if (parts.length < 2 || parts[0] !== "in") return "";
    return `in/${parts[1]}`;
  } catch {
    return "";
  }
}

function normalizeLinkedInPostUrl(url) {
  const raw = String(url || "").trim();
  if (!raw) return "";
  try {
    const parsed = new URL(raw, window.location.origin);
    if (!isLinkedInHost(parsed.hostname)) return "";
    const path = String(parsed.pathname || "").toLowerCase();
    if (!(path.includes("/posts/") || path.includes("/feed/update/") || path.includes("activity-"))) return "";
    parsed.search = "";
    parsed.hash = "";
    return parsed.toString().replace(/\/+$/, "");
  } catch {
    return "";
  }
}

function extractActivityIdFromText(raw) {
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

function extractPostUrlFromArticle(article) {
  const anchors = Array.from(article.querySelectorAll("a[href]"));
  const candidates = anchors
    .map((a) => normalizeLinkedInPostUrl(a.href))
    .filter(Boolean);
  for (const href of candidates) {
    const activityId = extractActivityIdFromText(href);
    if (activityId) {
      return `https://www.linkedin.com/feed/update/urn:li:activity:${activityId}/`;
    }
  }

  // Fallback: build stable URL from activity id found in the card markup.
  const attrCandidates = [
    article.getAttribute("data-urn"),
    article.getAttribute("data-id"),
    article.getAttribute("data-activity-urn"),
    article.getAttribute("id")
  ];
  for (const source of attrCandidates) {
    const activityId = extractActivityIdFromText(source);
    if (activityId) {
      return `https://www.linkedin.com/feed/update/urn:li:activity:${activityId}/`;
    }
  }

  const htmlActivityId = extractActivityIdFromText(article.outerHTML);
  if (htmlActivityId) {
    return `https://www.linkedin.com/feed/update/urn:li:activity:${htmlActivityId}/`;
  }

  return candidates.length ? candidates[0] : null;
}

function extractMetricFromSelectors(article, selectors) {
  for (const selector of selectors) {
    const node = article.querySelector(selector);
    if (!node) continue;
    const parsed = parseNumberToken(node.textContent);
    if (parsed != null) return parsed;
  }
  return null;
}

function extractPostFromArticle(article) {
  const author = extractAuthor(article);
  const authorAvatarUrl = extractAuthorAvatar(article, author.name || "");
  const articleText = cleanText(article.innerText);
  const publishedAtRaw = extractPublishedRaw(article);
  const postUrl = extractPostUrlFromArticle(article);
  const reactionsCount =
    extractMetricFromSelectors(article, [
      ".social-details-social-counts__reactions-count",
      "[class*='social-details-social-counts__reactions-count']"
    ]) ||
    extractMetric(articleText, [
      /(\d[\d.,\s]*[KkMmКкМм]?)\s*(?:reactions?|реакц(?:ия|ии|ий|ий))/i,
      /(\d[\d.,\s]*[KkMmКкМм]?)\s*(?:likes?|лайк(?:ов|а|и)?)/i
    ]);
  const commentsCount =
    extractMetricFromSelectors(article, [
      ".social-details-social-counts__comments",
      "[class*='social-details-social-counts__comments']"
    ]) ||
    extractMetric(articleText, [
      /(\d[\d.,\s]*[KkMmКкМм]?)\s*(?:comments?|комментар(?:ий|ия|иев))/i
    ]);
  const repostsCount = extractMetric(articleText, [
    /(\d[\d.,\s]*[KkMmКкМм]?)\s*(?:reposts?|репост(?:ов|а|ы)?)/i
  ]);
  const viewsCount = extractMetric(articleText, [
    /(\d[\d.,\s]*[KkMmКкМм]?)\s*(?:views?|просмотр(?:ов|а)?|impressions?)/i
  ]);
  const postText = extractPostText(article) || articleText || null;
  if (!postText && !postUrl) return null;

  return {
    author_name: author.name || null,
    author_profile_url: author.url || null,
    author_profile_key: parseLinkedInProfileKeyFromUrl(author.url),
    author_avatar_url: authorAvatarUrl,
    text: postText,
    post_url: postUrl,
    published_at_raw: publishedAtRaw,
    posted_at_iso: parsePublishedIso(publishedAtRaw),
    reactions_count: reactionsCount,
    comments_count: commentsCount,
    reposts_count: repostsCount,
    views_count: viewsCount
  };
}

function postBelongsToProfile(post, expectedProfileKey, expectedSlug) {
  if (!post) return false;
  if (expectedProfileKey && post.author_profile_key === expectedProfileKey) return true;
  if (expectedSlug && post.post_url) {
    const match = String(post.post_url).toLowerCase().match(/\/posts\/([a-z0-9-]+)(?:_|-activity-|\/|$)/i);
    if (match && cleanText(match[1]).toLowerCase() === expectedSlug) return true;
    if (String(post.post_url).toLowerCase().includes(`/in/${expectedSlug}/`)) return true;
  }
  return false;
}

function postDedupeKey(post) {
  const activityId =
    extractActivityIdFromText(post && post.post_url) ||
    extractActivityIdFromText(post && post.title) ||
    extractActivityIdFromText(post && post.text);
  if (activityId) return `activity:${activityId}`;

  if (post && post.post_url) {
    const normalizedUrl = normalizeLinkedInPostUrl(post.post_url);
    if (normalizedUrl) return `url:${normalizedUrl}`;
  }

  const snippet = cleanText(post && post.text).toLowerCase().replace(/\s+/g, " ").slice(0, 200);
  const day = cleanText(post && post.posted_at_iso).slice(0, 10);
  return `txt:${day}|${snippet}`;
}

function extractProfileNameFromDocument() {
  const h1 = document.querySelector("h1");
  const h1Text = cleanText(h1 && h1.textContent);
  if (h1Text && h1Text.length <= 140) return h1Text;

  const title = cleanText(document.title);
  if (!title) return "";
  const head = title.split("|")[0] || "";
  return cleanText(head);
}

function isLikelyProfileAvatarUrl(url) {
  const raw = String(url || "").toLowerCase();
  if (!raw) return false;
  if (raw.includes("company-logo")) return false;
  if (raw.includes("ghost_company")) return false;
  if (raw.includes("logo")) return false;
  return (
    raw.includes("profile-displayphoto") ||
    raw.includes("profile-framedphoto") ||
    raw.includes("headshot") ||
    raw.includes("dms/image")
  );
}

function pickAvatarFromImages(images, expectedName = "") {
  const name = cleanText(expectedName).toLowerCase();
  const scored = [];
  for (const img of images || []) {
    const url = readImgUrl(img);
    if (!url) continue;
    const alt = cleanText(img.getAttribute("alt")).toLowerCase();
    const cls = cleanText(img.getAttribute("class")).toLowerCase();
    let score = 0;

    if (isLikelyProfileAvatarUrl(url)) score += 10;
    if (cls.includes("profile") || cls.includes("headshot")) score += 8;
    if (cls.includes("avatar")) score += 5;
    if (name && alt.includes(name)) score += 14;
    if (alt.includes("profile photo")) score += 6;
    if (alt.includes("company")) score -= 10;
    if (alt.includes("logo")) score -= 12;

    const w = Number(img.getAttribute("width")) || 0;
    const h = Number(img.getAttribute("height")) || 0;
    if (w >= 80 || h >= 80) score += 4;
    if (w > 0 && h > 0 && (w < 40 || h < 40)) score -= 3;

    scored.push({ url, score });
  }
  scored.sort((a, b) => b.score - a.score);
  return scored.length ? scored[0].url : "";
}

function extractProfileAvatarFromDocument(expectedName = "") {
  const strongSelectors = [
    "img.pv-top-card-profile-picture__image--show",
    "img.pv-top-card-profile-picture__image",
    "img[data-anonymize='headshot-photo']",
    "img.profile-photo-edit__preview"
  ];
  for (const selector of strongSelectors) {
    const node = document.querySelector(selector);
    const url = readImgUrl(node);
    if (url && isLikelyProfileAvatarUrl(url)) return url;
  }

  const h1 = document.querySelector("main h1, h1");
  if (h1) {
    const section = h1.closest("section") || h1.closest("main") || h1.parentElement;
    const sectionImages = section ? Array.from(section.querySelectorAll("img")) : [];
    const picked = pickAvatarFromImages(sectionImages, expectedName || cleanText(h1.textContent));
    if (picked) return picked;
  }

  const fallback = pickAvatarFromImages(Array.from(document.querySelectorAll("main img")), expectedName);
  return fallback || "";
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function extractProfilePostsFromCurrentPage(options = {}) {
  const expectedProfileKey = cleanText(options.expectedProfileKey).toLowerCase();
  const expectedSlug = cleanText(options.expectedSlug).toLowerCase();
  const maxPosts = Math.min(120, Math.max(10, Number(options.maxPosts) || 40));
  const maxScrollSteps = Math.min(18, Math.max(3, Number(options.maxScrollSteps) || 10));
  const scrollDelayMs = Math.min(2000, Math.max(250, Number(options.scrollDelayMs) || 700));

  const byKey = new Map();
  let stableScrollSteps = 0;

  for (let step = 0; step < maxScrollSteps; step += 1) {
    const beforeCount = byKey.size;
    const articles = Array.from(document.querySelectorAll("article, [role='article']"));
    for (const article of articles) {
      const post = extractPostFromArticle(article);
      if (!post) continue;
      const key = postDedupeKey(post);
      if (!key) continue;
      if (!byKey.has(key)) byKey.set(key, post);
    }

    if (byKey.size >= maxPosts) break;

    const prevHeight = document.body ? document.body.scrollHeight : 0;
    window.scrollTo({ top: prevHeight + 1200, behavior: "auto" });
    await sleep(scrollDelayMs);
    const nextHeight = document.body ? document.body.scrollHeight : 0;
    const grew = nextHeight > prevHeight + 8;
    if (!grew && byKey.size === beforeCount) {
      stableScrollSteps += 1;
      if (stableScrollSteps >= 2) break;
    } else {
      stableScrollSteps = 0;
    }
  }

  const allPosts = Array.from(byKey.values());
  const matchingPosts = allPosts.filter((post) => postBelongsToProfile(post, expectedProfileKey, expectedSlug));
  const posts = matchingPosts.length >= 3 ? matchingPosts : allPosts;
  const profileAvatar =
    posts.find((post) => cleanText(post.author_avatar_url)) ||
    allPosts.find((post) => cleanText(post.author_avatar_url)) ||
    null;

  posts.sort((a, b) => {
    const at = new Date(a.posted_at_iso || 0).getTime();
    const bt = new Date(b.posted_at_iso || 0).getTime();
    return bt - at;
  });

  return {
    ok: true,
    data: {
      profile_name: extractProfileNameFromDocument() || null,
      profile_avatar_url: profileAvatar ? cleanText(profileAvatar.author_avatar_url) : null,
      posts: posts.slice(0, maxPosts)
    }
  };
}

const PROFILE_PANEL_ID = "myvoice-top-posts-panel";
const PROFILE_PANEL_STYLE_ID = "myvoice-top-posts-style";
const PROFILE_PANEL_LAUNCHER_ID = "myvoice-top-posts-launcher";
const PROFILE_PANEL_COLLAPSED_KEY = "myvoice_top_posts_collapsed";
const PROFILE_PANEL_REFRESH_DELAY_MS = 350;
const PROFILE_PANEL_TAB_BEST = "best";
const PROFILE_PANEL_TAB_NEW = "new";
const PROFILE_PANEL_PERSON_CACHE_TTL_MS = 60 * 1000;
const COMMENT_ASSIST_STYLE_ID = "myvoice-comment-assist-style";
const COMMENT_ASSIST_ROOT_ID = "myvoice-comment-assist";
const COMMENT_ASSIST_REFRESH_DELAY_MS = 260;
const COMMENT_ASSIST_STICKY_WINDOW_MS = 6500;
const MYVOICE_LOGO_PATH = "icons/icon48.png";
const COMMENT_ASSIST_AUTHOR_PREF_KEY = "myvoice_comment_assist_author_key";
const COMMENT_ASSIST_AUTHOR_SELECT_ID = "myvoice-comment-assist-author-select";
const COMMENT_ASSIST_GENERATION_STATUS_STEPS = [
  "Подготавливаю контекст поста...",
  "Проверяю структуру и тон...",
  "Собираю prompt для генерации...",
  "Отправляю запрос в MyVOICE...",
  "Жду ответ модели...",
  "Разбираю черновые варианты...",
  "Проверяю читаемость и длину...",
  "Собираю short / medium / long...",
  "Финализирую варианты..."
];

let profilePanelRefreshTimer = null;
let profilePanelLastUrl = "";
let profilePanelRequestId = 0;
let profilePanelCollapsed = false;
let profilePanelActiveTab = PROFILE_PANEL_TAB_BEST;
let profilePanelCurrentData = null;
let profilePanelCardOpenHandlersBound = false;
let profilePanelPersonLookupRequestId = 0;
let commentAssistRefreshTimer = null;
let commentAssistRequestId = 0;
let commentAssistAuthorsRequestId = 0;
let commentAssistStatusTicker = null;
let commentAssistTriggersBound = false;
let commentAssistTargetArticle = null;
let commentAssistTargetCommentBox = null;
let commentAssistTargetActivityId = "";
let commentAssistTargetUpdatedAt = 0;
let commentAssistStickyUntil = 0;
let commentAssistTransientObserver = null;
let commentAssistTransientObserverTimer = null;
let commentAssistTransientObserverDebounce = null;
let commentAssistState = {
  postKey: "",
  generating: false,
  generationStartedAt: 0,
  variants: null,
  activeVariant: "",
  authors: [],
  authorsLoaded: false,
  authorsLoading: false,
  authorsError: "",
  selectedAuthorKey: readPreferredCommentAuthorKey(),
  statusText: "",
  statusKind: "",
  statusDetails: ""
};
const profilePanelPersonPresenceCache = new Map();

function readCollapsedPreference() {
  try {
    return window.localStorage.getItem(PROFILE_PANEL_COLLAPSED_KEY) === "1";
  } catch {
    return false;
  }
}

function writeCollapsedPreference(value) {
  try {
    window.localStorage.setItem(PROFILE_PANEL_COLLAPSED_KEY, value ? "1" : "0");
  } catch {
    // ignore storage errors
  }
}

function isLinkedInHost(hostname) {
  const host = String(hostname || "").toLowerCase();
  return host === "linkedin.com" || host === "www.linkedin.com" || host.endsWith(".linkedin.com");
}

function parseLinkedInProfile(url) {
  const raw = String(url || "").trim();
  if (!raw) return null;
  try {
    const parsed = new URL(raw);
    if (!isLinkedInHost(parsed.hostname)) return null;
    const parts = parsed.pathname
      .split("/")
      .map((part) => cleanText(part).toLowerCase())
      .filter(Boolean);
    if (parts.length < 2) return null;
    if (parts[0] !== "in") return null;
    if (parts[2] === "recent-activity") return null;
    return {
      profileKey: `${parts[0]}/${parts[1]}`,
      profileSlug: parts[1],
      profileUrl: `${parsed.origin}/in/${parts[1]}/`
    };
  } catch {
    return null;
  }
}

function splitPersonName(fullName) {
  const normalized = cleanText(fullName).replace(/\s+/g, " ").trim();
  if (!normalized) return { firstName: "", lastName: "" };
  const parts = normalized.split(" ").filter(Boolean);
  if (parts.length === 1) return { firstName: parts[0], lastName: "" };
  return {
    firstName: parts[0],
    lastName: parts.slice(1).join(" ")
  };
}

function upsertPanelStyles() {
  if (document.getElementById(PROFILE_PANEL_STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = PROFILE_PANEL_STYLE_ID;
  style.textContent = `
    #${PROFILE_PANEL_ID} {
      position: fixed;
      right: 0;
      top: 56px;
      width: min(360px, 92vw);
      max-height: calc(100vh - 64px);
      background: #ffffff;
      border-left: 1px solid #d0d7de;
      border-top: 1px solid #d0d7de;
      border-bottom: 1px solid #d0d7de;
      border-top-left-radius: 14px;
      border-bottom-left-radius: 14px;
      box-shadow: 0 10px 28px rgba(15, 23, 42, 0.18);
      z-index: 2147483646;
      display: flex;
      flex-direction: column;
      color: #1f2328;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
    }

    #${PROFILE_PANEL_ID} .myvoice-top-posts__header {
      position: sticky;
      top: 0;
      z-index: 1;
      padding: 16px 14px 12px;
      border-bottom: 1px solid #e5e7eb;
      background: linear-gradient(180deg, #ffffff 0%, #fafcff 100%);
    }

    #${PROFILE_PANEL_ID} .myvoice-top-posts__header-top {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      margin-bottom: 12px;
    }

    #${PROFILE_PANEL_ID} .myvoice-top-posts__brand {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 0;
      color: #1d4ed8;
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0.01em;
      margin-bottom: 0;
    }

    #${PROFILE_PANEL_ID} .myvoice-top-posts__brand-logo {
      width: 36px;
      height: 36px;
      border-radius: 11px;
      overflow: hidden;
      display: grid;
      place-items: center;
    }

    #${PROFILE_PANEL_ID} .myvoice-top-posts__logo-image {
      display: block;
      width: 100%;
      height: 100%;
      object-fit: cover;
    }

    #${PROFILE_PANEL_ID} .myvoice-top-posts__logo-fallback,
    #${COMMENT_ASSIST_ROOT_ID} .myvoice-top-posts__logo-fallback,
    #${PROFILE_PANEL_LAUNCHER_ID} .myvoice-top-posts__logo-fallback {
      width: 100%;
      height: 100%;
      border-radius: inherit;
      display: grid;
      place-items: center;
      background: linear-gradient(145deg, #6f78ff 0%, #4e5cf7 100%);
      color: #ffffff;
      font-size: 18px;
      font-weight: 800;
      line-height: 1;
      user-select: none;
    }

    #${PROFILE_PANEL_ID} .myvoice-top-posts__brand-text {
      line-height: 1;
      white-space: nowrap;
    }

    #${PROFILE_PANEL_ID} .myvoice-top-posts__close {
      width: 30px;
      height: 30px;
      border-radius: 9px;
      border: 1px solid #dbe3ee;
      background: #ffffff;
      color: #475569;
      cursor: pointer;
      font-size: 18px;
      line-height: 1;
      display: grid;
      place-items: center;
      padding: 0;
      transition: background-color 0.12s ease, border-color 0.12s ease, color 0.12s ease;
    }

    #${PROFILE_PANEL_ID} .myvoice-top-posts__close:hover {
      background: #f8fafc;
      border-color: #cbd5e1;
      color: #0f172a;
    }

    #${PROFILE_PANEL_ID} .myvoice-top-posts__title {
      margin: 16px 0 0;
      font-size: 17px;
      font-weight: 700;
      line-height: 1.2;
      letter-spacing: -0.01em;
    }

    #${PROFILE_PANEL_ID} .myvoice-top-posts__tabs {
      margin-top: 10px;
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }

    #${PROFILE_PANEL_ID} .myvoice-top-posts__tab {
      height: 30px;
      border: 1px solid #dbe3ee;
      border-radius: 999px;
      background: #ffffff;
      color: #475569;
      font-size: 12px;
      font-weight: 600;
      line-height: 1;
      padding: 0 12px;
      cursor: pointer;
      transition: background-color 0.12s ease, border-color 0.12s ease, color 0.12s ease;
    }

    #${PROFILE_PANEL_ID} .myvoice-top-posts__tab:hover {
      background: #f8fafc;
      border-color: #cbd5e1;
      color: #0f172a;
    }

    #${PROFILE_PANEL_ID} .myvoice-top-posts__tab.active {
      background: #eaf2ff;
      border-color: #bfdbfe;
      color: #1d4ed8;
    }

    #${PROFILE_PANEL_ID} .myvoice-top-posts__tab:focus-visible {
      outline: 2px solid #93c5fd;
      outline-offset: 2px;
    }

    #${PROFILE_PANEL_ID} .myvoice-top-posts__person {
      display: grid;
      grid-template-columns: 52px minmax(0, 1fr);
      gap: 10px;
      align-items: center;
      margin-top: 10px;
      padding: 8px;
      border-radius: 12px;
      border: 1px solid #dbeafe;
      background: linear-gradient(180deg, #f8fbff 0%, #eef5ff 100%);
    }

    #${PROFILE_PANEL_ID} .myvoice-top-posts__person-meta {
      min-width: 0;
      display: grid;
      gap: 4px;
    }

    #${PROFILE_PANEL_ID} .myvoice-top-posts__person-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      min-width: 0;
    }

    #${PROFILE_PANEL_ID} .myvoice-top-posts__avatar {
      width: 52px;
      height: 52px;
      border-radius: 50%;
      border: 2px solid #ffffff;
      object-fit: cover;
      display: block;
      background: #e2e8f0;
      box-shadow: 0 2px 8px rgba(15, 23, 42, 0.12);
    }

    #${PROFILE_PANEL_ID} .myvoice-top-posts__avatar-fallback {
      width: 52px;
      height: 52px;
      border-radius: 50%;
      display: grid;
      place-items: center;
      border: 2px solid #ffffff;
      background: linear-gradient(135deg, #1d4ed8 0%, #3b82f6 100%);
      color: #ffffff;
      font-size: 18px;
      font-weight: 700;
      box-shadow: 0 2px 8px rgba(15, 23, 42, 0.12);
    }

    #${PROFILE_PANEL_ID} .myvoice-top-posts__person-name {
      margin: 0;
      color: #0f172a;
      font-size: 15px;
      font-weight: 700;
      line-height: 1.2;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    #${PROFILE_PANEL_ID} .myvoice-top-posts__person-add {
      height: 28px;
      border-radius: 999px;
      border: 1px solid #bfdbfe;
      background: #ffffff;
      color: #1d4ed8;
      font-size: 12px;
      font-weight: 700;
      line-height: 1;
      padding: 0 10px;
      white-space: nowrap;
      cursor: pointer;
      transition: background-color 0.12s ease, border-color 0.12s ease, color 0.12s ease;
    }

    #${PROFILE_PANEL_ID} .myvoice-top-posts__person-add:hover:not(:disabled) {
      background: #eff6ff;
      border-color: #93c5fd;
      color: #1e40af;
    }

    #${PROFILE_PANEL_ID} .myvoice-top-posts__person-add:disabled {
      cursor: default;
      opacity: 0.65;
    }

    #${PROFILE_PANEL_ID} .myvoice-top-posts__person-add[hidden] {
      display: none !important;
    }

    #${PROFILE_PANEL_ID} .myvoice-top-posts__body {
      overflow: auto;
      padding: 10px;
      display: grid;
      gap: 10px;
      align-content: start;
    }

    #${PROFILE_PANEL_ID} .myvoice-top-posts__status {
      border: 1px solid #e5e7eb;
      border-radius: 10px;
      background: #f8fafc;
      padding: 12px;
      font-size: 13px;
      line-height: 1.45;
      color: #374151;
    }

    #${PROFILE_PANEL_ID} .myvoice-top-posts__status.error {
      border-color: #fecaca;
      background: #fff1f2;
      color: #9f1239;
    }

    #${PROFILE_PANEL_ID} .myvoice-top-posts__status-text {
      margin: 0;
    }

    #${PROFILE_PANEL_ID} .myvoice-top-posts__action {
      margin-top: 10px;
      height: 34px;
      border: 1px solid #fecaca;
      border-radius: 999px;
      background: #ffffff;
      color: #9f1239;
      font-size: 13px;
      font-weight: 600;
      padding: 0 12px;
      cursor: pointer;
    }

    #${PROFILE_PANEL_ID} .myvoice-top-posts__action:hover {
      background: #ffe4e6;
    }

    #${PROFILE_PANEL_ID} .myvoice-top-posts__card {
      display: block;
      text-decoration: none;
      color: inherit;
      border: 1px solid #e5e7eb;
      border-radius: 12px;
      background: #ffffff;
      padding: 11px;
      transition: border-color 0.14s ease, box-shadow 0.14s ease, transform 0.14s ease;
    }

    #${PROFILE_PANEL_ID} .myvoice-top-posts__card:hover {
      border-color: #9dc0ff;
      box-shadow: 0 8px 20px rgba(59, 130, 246, 0.16);
      transform: translateY(-1px);
    }

    #${PROFILE_PANEL_ID} .myvoice-top-posts__meta {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      margin: 0 0 8px;
      color: #6b7280;
      font-size: 12px;
      line-height: 1.3;
    }

    #${PROFILE_PANEL_ID} .myvoice-top-posts__text {
      margin: 0;
      font-size: 14px;
      line-height: 1.45;
      color: #111827;
      white-space: pre-wrap;
      word-break: break-word;
    }

    #${PROFILE_PANEL_ID} .myvoice-top-posts__metrics {
      margin-top: 10px;
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }

    #${PROFILE_PANEL_ID} .myvoice-top-posts__footer {
      margin-top: 10px;
      display: grid;
      gap: 8px;
    }

    #${PROFILE_PANEL_ID} .myvoice-top-posts__footer .myvoice-top-posts__metrics {
      margin-top: 0;
      justify-content: flex-start;
    }

    #${PROFILE_PANEL_ID} .myvoice-top-posts__read-more {
      display: inline-flex;
      align-items: center;
      justify-self: start;
      border: 1px solid #bfdbfe;
      border-radius: 999px;
      background: #f8fbff;
      color: #1d4ed8;
      font-size: 12px;
      font-weight: 600;
      line-height: 1.2;
      cursor: pointer;
      padding: 4px 10px;
      user-select: none;
      transition: background-color 0.12s ease, border-color 0.12s ease, color 0.12s ease;
    }

    #${PROFILE_PANEL_ID} .myvoice-top-posts__read-more:hover {
      background: #edf4ff;
      border-color: #93c5fd;
      color: #1e40af;
    }

    #${PROFILE_PANEL_ID} .myvoice-top-posts__read-more:focus-visible {
      outline: 2px solid #93c5fd;
      outline-offset: 2px;
      border-radius: 4px;
    }

    #${PROFILE_PANEL_ID} .myvoice-top-posts__metric {
      font-size: 12px;
      border: 1px solid #bfdbfe;
      color: #1e3a8a;
      background: #eff6ff;
      border-radius: 999px;
      padding: 3px 8px;
      white-space: nowrap;
    }

    #${PROFILE_PANEL_LAUNCHER_ID} {
      position: fixed;
      right: 10px;
      top: 240px;
      width: 46px;
      height: 46px;
      border-radius: 12px;
      border: none;
      background: transparent;
      box-shadow: none;
      display: grid;
      place-items: center;
      padding: 0;
      overflow: hidden;
      cursor: pointer;
      z-index: 2147483646;
      user-select: none;
      transition: transform 0.12s ease, box-shadow 0.12s ease;
    }

    #${PROFILE_PANEL_LAUNCHER_ID} .myvoice-top-posts__logo-image {
      width: 100%;
      height: 100%;
      object-fit: cover;
      border-radius: 12px;
    }

    #${PROFILE_PANEL_LAUNCHER_ID}:hover {
      transform: translateY(-1px);
      box-shadow: 0 12px 24px rgba(78, 92, 247, 0.28);
    }

    @media (max-width: 1320px) {
      #${PROFILE_PANEL_ID} {
        top: 62px;
        width: min(330px, 95vw);
      }
    }
  `;
  document.documentElement.appendChild(style);
}

function getRuntimeUrlSafe(path) {
  try {
    if (!chrome || !chrome.runtime || !chrome.runtime.id || typeof chrome.runtime.getURL !== "function") {
      return "";
    }
    return chrome.runtime.getURL(path);
  } catch {
    return "";
  }
}

function createMyvoiceLogoFallback() {
  const fallback = document.createElement("span");
  fallback.className = "myvoice-top-posts__logo-fallback";
  fallback.setAttribute("aria-hidden", "true");
  fallback.textContent = "V";
  return fallback;
}

function createMyvoiceLogoImage() {
  const src = getRuntimeUrlSafe(MYVOICE_LOGO_PATH);
  if (!src) return createMyvoiceLogoFallback();

  const img = document.createElement("img");
  img.className = "myvoice-top-posts__logo-image";
  img.src = src;
  img.alt = "MyVOICE's";
  img.decoding = "async";
  img.onerror = () => {
    if (!img.parentElement) return;
    img.replaceWith(createMyvoiceLogoFallback());
  };
  return img;
}

function getOrCreatePanel() {
  let panel = document.getElementById(PROFILE_PANEL_ID);
  if (panel) return panel;

  panel = document.createElement("aside");
  panel.id = PROFILE_PANEL_ID;

  const header = document.createElement("div");
  header.className = "myvoice-top-posts__header";

  const headerTop = document.createElement("div");
  headerTop.className = "myvoice-top-posts__header-top";

  const brand = document.createElement("div");
  brand.className = "myvoice-top-posts__brand";
  const brandLogo = document.createElement("span");
  brandLogo.className = "myvoice-top-posts__brand-logo";
  brandLogo.appendChild(createMyvoiceLogoImage());
  brand.appendChild(brandLogo);
  const brandText = document.createElement("span");
  brandText.className = "myvoice-top-posts__brand-text";
  brandText.textContent = "MyVOICE's";
  brand.appendChild(brandText);
  headerTop.appendChild(brand);

  const closeBtn = document.createElement("button");
  closeBtn.type = "button";
  closeBtn.className = "myvoice-top-posts__close";
  closeBtn.title = "Close";
  closeBtn.setAttribute("aria-label", "Close");
  closeBtn.textContent = "×";
  closeBtn.addEventListener("click", () => {
    setPanelCollapsed(true);
  });
  headerTop.appendChild(closeBtn);
  header.appendChild(headerTop);

  const title = document.createElement("p");
  title.className = "myvoice-top-posts__title";
  title.textContent = "Best Posts";
  header.appendChild(title);

  const tabs = document.createElement("div");
  tabs.className = "myvoice-top-posts__tabs";
  tabs.setAttribute("role", "tablist");
  tabs.setAttribute("aria-label", "Post types");

  const bestTab = document.createElement("button");
  bestTab.type = "button";
  bestTab.className = "myvoice-top-posts__tab";
  bestTab.setAttribute("role", "tab");
  bestTab.setAttribute("data-tab", PROFILE_PANEL_TAB_BEST);
  bestTab.textContent = "Best Posts";
  bestTab.addEventListener("click", () => {
    setProfilePanelTab(PROFILE_PANEL_TAB_BEST);
  });

  const newTab = document.createElement("button");
  newTab.type = "button";
  newTab.className = "myvoice-top-posts__tab";
  newTab.setAttribute("role", "tab");
  newTab.setAttribute("data-tab", PROFILE_PANEL_TAB_NEW);
  newTab.textContent = "New Posts";
  newTab.addEventListener("click", () => {
    setProfilePanelTab(PROFILE_PANEL_TAB_NEW);
  });

  tabs.appendChild(bestTab);
  tabs.appendChild(newTab);
  header.appendChild(tabs);

  const person = document.createElement("div");
  person.className = "myvoice-top-posts__person";

  const avatarFallback = document.createElement("div");
  avatarFallback.className = "myvoice-top-posts__avatar-fallback";
  avatarFallback.textContent = "MV";
  person.appendChild(avatarFallback);

  const personMeta = document.createElement("div");
  personMeta.className = "myvoice-top-posts__person-meta";

  const personHead = document.createElement("div");
  personHead.className = "myvoice-top-posts__person-head";

  const personName = document.createElement("p");
  personName.className = "myvoice-top-posts__person-name";
  personName.textContent = "LinkedIn Author";
  personHead.appendChild(personName);

  const addBtn = document.createElement("button");
  addBtn.type = "button";
  addBtn.className = "myvoice-top-posts__person-add";
  addBtn.hidden = true;
  addBtn.textContent = "+Add";
  personHead.appendChild(addBtn);

  personMeta.appendChild(personHead);

  person.appendChild(personMeta);
  header.appendChild(person);

  const body = document.createElement("div");
  body.className = "myvoice-top-posts__body";

  panel.appendChild(header);
  panel.appendChild(body);
  document.body.appendChild(panel);
  applyProfilePanelTabs(panel);

  return panel;
}

function getOrCreateLauncher() {
  let launcher = document.getElementById(PROFILE_PANEL_LAUNCHER_ID);
  if (launcher) return launcher;

  launcher = document.createElement("button");
  launcher.id = PROFILE_PANEL_LAUNCHER_ID;
  launcher.type = "button";
  launcher.title = "Open MyVOICE's";
  launcher.setAttribute("aria-label", "Open MyVOICE's panel");
  launcher.appendChild(createMyvoiceLogoImage());
  launcher.addEventListener("click", () => {
    setPanelCollapsed(false);
    scheduleProfilePanelRefresh(0);
  });
  document.body.appendChild(launcher);
  return launcher;
}

function removeLauncher() {
  const launcher = document.getElementById(PROFILE_PANEL_LAUNCHER_ID);
  if (launcher) launcher.remove();
}

function setPanelCollapsed(value) {
  profilePanelCollapsed = Boolean(value);
  if (profilePanelCollapsed) {
    profilePanelRequestId += 1;
    profilePanelPersonLookupRequestId += 1;
    const profile = parseLinkedInProfile(window.location.href);
    if (profile) {
      sendRuntimeMessageSafe({
        type: "MYVOICE_CANCEL_PROFILE_TOP_POSTS",
        profileUrl: profile.profileUrl
      }).catch(() => {
        // ignore background unavailability
      });
    }
  }
  writeCollapsedPreference(profilePanelCollapsed);

  const panel = document.getElementById(PROFILE_PANEL_ID);
  if (panel) {
    panel.style.display = profilePanelCollapsed ? "none" : "flex";
  }

  if (profilePanelCollapsed) {
    upsertPanelStyles();
    const launcher = getOrCreateLauncher();
    launcher.style.display = "grid";
  } else {
    const launcher = document.getElementById(PROFILE_PANEL_LAUNCHER_ID);
    if (launcher) launcher.style.display = "none";
  }
}

function removePanel() {
  profilePanelPersonLookupRequestId += 1;
  const panel = document.getElementById(PROFILE_PANEL_ID);
  if (panel) panel.remove();
}

function setProfilePanelTab(tab) {
  const nextTab = tab === PROFILE_PANEL_TAB_NEW ? PROFILE_PANEL_TAB_NEW : PROFILE_PANEL_TAB_BEST;
  profilePanelActiveTab = nextTab;
  const panel = document.getElementById(PROFILE_PANEL_ID);
  if (!panel) return;
  applyProfilePanelTabs(panel);
  if (profilePanelCurrentData) renderProfilePanelBody(panel, profilePanelCurrentData);
  const body = panel.querySelector(".myvoice-top-posts__body");
  if (body) {
    body.scrollTop = 0;
    if (typeof body.scrollTo === "function") {
      body.scrollTo({ top: 0, left: 0, behavior: "auto" });
    }
  }
}

function compactNumber(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "0";
  if (Math.abs(n) >= 1000000) return `${(n / 1000000).toFixed(1).replace(/\.0$/, "")}M`;
  if (Math.abs(n) >= 1000) return `${(n / 1000).toFixed(1).replace(/\.0$/, "")}K`;
  return String(Math.round(n));
}

function formatPostedAt(value) {
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return "Unknown date";
  return dt.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric"
  });
}

function initialsFromName(value) {
  const words = cleanText(value).split(" ").filter(Boolean);
  if (!words.length) return "MV";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return `${words[0].slice(0, 1)}${words[1].slice(0, 1)}`.toUpperCase();
}

function buildPersonPayloadForSystem(personData, fullName) {
  const profileFromPerson = parseLinkedInProfile(cleanText(personData && personData.linkedin_url));
  const profileFromPage = parseLinkedInProfile(window.location.href);
  const effectiveProfile = profileFromPerson || profileFromPage || null;
  const payloadFullName = cleanText(fullName) || cleanText(personData && personData.full_name);
  const nameParts = splitPersonName(payloadFullName);
  return {
    full_name: payloadFullName,
    first_name: cleanText(personData && personData.first_name) || nameParts.firstName,
    last_name: cleanText(personData && personData.last_name) || nameParts.lastName,
    linkedin_url: effectiveProfile ? effectiveProfile.profileUrl : cleanText(personData && personData.linkedin_url)
  };
}

function personLookupKeyFromPayload(payload) {
  const profile = parseLinkedInProfile(cleanText(payload && payload.linkedin_url));
  if (profile && profile.profileKey) return profile.profileKey;
  const normalizedName = normalizeTextForMatch(payload && payload.full_name);
  if (normalizedName) return `name:${normalizedName}`;
  return "";
}

function getPersonPresenceFromCache(cacheKey) {
  const cached = profilePanelPersonPresenceCache.get(cacheKey);
  if (!cached) return null;
  if (Date.now() - cached.checkedAt > PROFILE_PANEL_PERSON_CACHE_TTL_MS) {
    profilePanelPersonPresenceCache.delete(cacheKey);
    return null;
  }
  return cached;
}

function setPersonPresenceCache(cacheKey, exists) {
  if (!cacheKey) return;
  profilePanelPersonPresenceCache.set(cacheKey, {
    exists: Boolean(exists),
    checkedAt: Date.now()
  });
}

function setPersonAddButtonState(button, state, errorMessage = "") {
  if (!button) return;

  button.title = "";
  if (state === "hidden") {
    button.hidden = true;
    button.disabled = true;
    button.textContent = "+Add";
    return;
  }

  button.hidden = false;
  if (state === "checking") {
    button.disabled = true;
    button.textContent = "Checking...";
    return;
  }
  if (state === "adding") {
    button.disabled = true;
    button.textContent = "Adding...";
    return;
  }
  button.disabled = false;
  button.textContent = "+Add";
  if (state === "error" && errorMessage) {
    button.title = errorMessage;
  }
}

function bindPersonAddButton(panel, payload) {
  const addBtn = panel.querySelector(".myvoice-top-posts__person-add");
  if (!addBtn) return;

  const personPayload = payload || {};
  const cacheKey = personLookupKeyFromPayload(personPayload);
  addBtn.dataset.personLookupKey = cacheKey;
  addBtn.onclick = null;

  if (!personPayload.full_name) {
    setPersonAddButtonState(addBtn, "hidden");
    return;
  }

  const applyAddAction = () => {
    addBtn.onclick = async (event) => {
      event.preventDefault();
      event.stopPropagation();
      setPersonAddButtonState(addBtn, "adding");
      try {
        const response = await sendRuntimeMessageSafe({
          type: "MYVOICE_ADD_PROFILE_PERSON",
          person: personPayload
        });
        if (!response || !response.ok) {
          const msg = response && response.error ? response.error : "Failed to add contact.";
          setPersonAddButtonState(addBtn, "error", msg);
          return;
        }
        setPersonPresenceCache(cacheKey, true);
        setPersonAddButtonState(addBtn, "hidden");
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err || "Failed to add contact.");
        setPersonAddButtonState(addBtn, "error", msg);
      }
    };
  };

  const cached = getPersonPresenceFromCache(cacheKey);
  if (cached) {
    if (cached.exists) {
      setPersonAddButtonState(addBtn, "hidden");
      return;
    }
    setPersonAddButtonState(addBtn, "ready");
    applyAddAction();
    return;
  }

  setPersonAddButtonState(addBtn, "checking");
  const requestId = ++profilePanelPersonLookupRequestId;
  sendRuntimeMessageSafe({
    type: "MYVOICE_CHECK_PROFILE_PERSON",
    person: personPayload
  }).then((response) => {
    if (requestId !== profilePanelPersonLookupRequestId) return;
    if (!document.body.contains(panel)) return;
    if (addBtn.dataset.personLookupKey !== cacheKey) return;

    if (!response || !response.ok) {
      const msg = response && response.error ? response.error : "Failed to check contact.";
      setPersonAddButtonState(addBtn, "error", msg);
      return;
    }

    const exists = Boolean(response.exists);
    setPersonPresenceCache(cacheKey, exists);
    if (exists) {
      setPersonAddButtonState(addBtn, "hidden");
      return;
    }
    setPersonAddButtonState(addBtn, "ready");
    applyAddAction();
  }).catch((err) => {
    if (requestId !== profilePanelPersonLookupRequestId) return;
    if (!document.body.contains(panel)) return;
    if (addBtn.dataset.personLookupKey !== cacheKey) return;
    const msg = err instanceof Error ? err.message : String(err || "Failed to check contact.");
    setPersonAddButtonState(addBtn, "error", msg);
  });
}

function renderPersonHeader(panel, personData) {
  const personNameEl = panel.querySelector(".myvoice-top-posts__person-name");
  const personRoot = panel.querySelector(".myvoice-top-posts__person");
  if (!personNameEl || !personRoot) return;

  const profilePageName = cleanText(extractProfileNameFromDocument());
  const fallbackName = cleanText(personData && personData.full_name) || "LinkedIn Author";
  const fullName = profilePageName || fallbackName;
  const pageAvatar = cleanText(extractProfileAvatarFromDocument(fullName));
  const avatarUrl = pageAvatar || cleanText(personData && personData.avatar_url);

  personNameEl.textContent = fullName;

  const existingAvatar = personRoot.querySelector(".myvoice-top-posts__avatar");
  const existingFallback = personRoot.querySelector(".myvoice-top-posts__avatar-fallback");

  if (avatarUrl) {
    let avatar = existingAvatar;
    if (!avatar) {
      avatar = document.createElement("img");
      avatar.className = "myvoice-top-posts__avatar";
      avatar.alt = fullName;
      avatar.loading = "lazy";
      personRoot.insertBefore(avatar, personRoot.firstChild);
    }
    avatar.src = avatarUrl;
    avatar.alt = fullName;
    avatar.onerror = () => {
      avatar.remove();
      let fallback = personRoot.querySelector(".myvoice-top-posts__avatar-fallback");
      if (!fallback) {
        fallback = document.createElement("div");
        fallback.className = "myvoice-top-posts__avatar-fallback";
        personRoot.insertBefore(fallback, personRoot.firstChild);
      }
      fallback.textContent = initialsFromName(fullName);
    };
    if (existingFallback) existingFallback.remove();
  } else {
    if (existingAvatar) existingAvatar.remove();
    let fallback = existingFallback;
    if (!fallback) {
      fallback = document.createElement("div");
      fallback.className = "myvoice-top-posts__avatar-fallback";
      personRoot.insertBefore(fallback, personRoot.firstChild);
    }
    fallback.textContent = initialsFromName(fullName);
  }

  const payload = buildPersonPayloadForSystem(personData, fullName);
  bindPersonAddButton(panel, payload);
}

function statusNode(text, { error = false } = {}) {
  const node = document.createElement("div");
  node.className = `myvoice-top-posts__status${error ? " error" : ""}`;
  node.textContent = text;
  return node;
}

function sendRuntimeMessageSafe(payload) {
  try {
    const maybePromise = chrome.runtime.sendMessage(payload);
    if (maybePromise && typeof maybePromise.then === "function") {
      return maybePromise;
    }
    return Promise.resolve(maybePromise);
  } catch (err) {
    return Promise.reject(err);
  }
}

function toAbsoluteLinkedInUrl(rawUrl) {
  const raw = cleanText(rawUrl);
  if (!raw) return "";
  try {
    return new URL(raw, window.location.origin).toString();
  } catch {
    return raw;
  }
}

function normalizeTextForMatch(value) {
  return cleanText(value).toLowerCase().replace(/\s+/g, " ");
}

function resolvePostUrlFromVisiblePage(post) {
  const sourceText = cleanText(post && (post.content || post.title || post.text));
  if (!sourceText) return "";

  const sourceNormalized = normalizeTextForMatch(sourceText).slice(0, 180);
  if (!sourceNormalized) return "";
  const tokens = sourceNormalized.split(" ").filter((token) => token.length >= 5).slice(0, 14);
  if (!tokens.length) return "";

  const articles = Array.from(document.querySelectorAll("article, [role='article']"));
  let bestScore = 0;
  let bestUrl = "";
  for (const article of articles) {
    const articleText = normalizeTextForMatch(extractPostText(article) || article.innerText).slice(0, 6000);
    if (!articleText) continue;

    let score = articleText.includes(sourceNormalized) ? 1000 : 0;
    for (const token of tokens) {
      if (articleText.includes(token)) score += 1;
    }
    if (score < 5) continue;

    const url = cleanText(extractPostUrlFromArticle(article));
    if (!url) continue;
    if (score > bestScore) {
      bestScore = score;
      bestUrl = url;
    }
  }

  return bestUrl;
}

function resolvePostUrlForCard(post) {
  const direct = toAbsoluteLinkedInUrl(post && post.post_url);
  if (direct) return direct;

  const fromVisiblePage = toAbsoluteLinkedInUrl(resolvePostUrlFromVisiblePage(post));
  if (fromVisiblePage) return fromVisiblePage;

  const activityId = extractActivityIdFromText(post && (post.post_url || post.content || post.title || post.text));
  if (activityId) return `https://www.linkedin.com/feed/update/urn:li:activity:${activityId}/`;
  return "";
}

function openPostUrl(href, { newTab = false } = {}) {
  const url = toAbsoluteLinkedInUrl(href);
  if (!url) return;
  const openFallback = () => {
    if (newTab) {
      window.open(url, "_blank", "noopener,noreferrer");
    } else {
      window.location.assign(url);
    }
  };

  sendRuntimeMessageSafe({
    type: "MYVOICE_OPEN_LINKEDIN_POST",
    url,
    newTab: Boolean(newTab)
  }).then((response) => {
    if (response && response.ok) return;
    openFallback();
  }).catch(() => {
    // Fallback if background is temporarily unavailable.
    openFallback();
  });
}

function bindProfilePanelCardOpenHandlers() {
  if (profilePanelCardOpenHandlersBound) return;
  profilePanelCardOpenHandlersBound = true;

  const findCardFromEvent = (event) => {
    const target = event && event.target;
    if (!(target instanceof Element)) return null;
    if (target.closest(".myvoice-top-posts__read-more")) return null;
    return target.closest(`#${PROFILE_PANEL_ID} .myvoice-top-posts__card[data-post-url]`);
  };

  const handleClickLikeEvent = (event, { forceNewTab = false } = {}) => {
    const card = findCardFromEvent(event);
    if (!card) return;

    const url = cleanText(card.getAttribute("data-post-url"));
    if (!url) return;

    const openInNewTab = forceNewTab || event.button === 1 || event.metaKey || event.ctrlKey || event.shiftKey;
    event.preventDefault();
    event.stopPropagation();
    if (typeof event.stopImmediatePropagation === "function") {
      event.stopImmediatePropagation();
    }
    openPostUrl(url, { newTab: openInNewTab });
  };

  window.addEventListener("click", (event) => {
    if (event.button !== 0) return;
    handleClickLikeEvent(event);
  }, true);

  window.addEventListener("auxclick", (event) => {
    if (event.button !== 1) return;
    handleClickLikeEvent(event, { forceNewTab: true });
  }, true);
}

function getPanelPostsByTab(data) {
  const bestPosts = Array.isArray(data && data.best_posts)
    ? data.best_posts
    : Array.isArray(data && data.posts)
      ? data.posts
      : [];
  const newPosts = Array.isArray(data && data.new_posts) ? data.new_posts : [];
  return { bestPosts, newPosts };
}

function applyProfilePanelTabs(panel) {
  const tabNodes = Array.from(panel.querySelectorAll(".myvoice-top-posts__tab"));
  for (const tab of tabNodes) {
    const tabValue = cleanText(tab.getAttribute("data-tab"));
    const isActive = tabValue === profilePanelActiveTab;
    tab.classList.toggle("active", isActive);
    tab.setAttribute("aria-selected", isActive ? "true" : "false");
  }
}

function renderProfilePanelBody(panel, data) {
  const body = panel.querySelector(".myvoice-top-posts__body");
  const title = panel.querySelector(".myvoice-top-posts__title");
  if (!body || !title) return;

  const isNewTab = profilePanelActiveTab === PROFILE_PANEL_TAB_NEW;
  title.textContent = isNewTab ? "New Posts" : "Best Posts";
  applyProfilePanelTabs(panel);

  if (!data || !data.person) {
    body.replaceChildren(statusNode("Could not read posts from this LinkedIn profile."));
    return;
  }

  const { bestPosts, newPosts } = getPanelPostsByTab(data);
  const activePosts = isNewTab ? newPosts : bestPosts;
  if (!activePosts.length) {
    body.replaceChildren(
      statusNode(isNewTab ? "No recent posts found for this profile." : "No posts found for this profile.")
    );
    return;
  }

  body.replaceChildren(...activePosts.map((post) => buildPostCard(post, { showScore: !isNewTab })));
}

function buildPostCard(post, options = {}) {
  const showScore = options.showScore !== false;
  const href = resolvePostUrlForCard(post);
  const card = document.createElement(href ? "a" : "div");
  card.className = "myvoice-top-posts__card";
  if (href) {
    card.href = href;
    card.target = "_self";
    card.setAttribute("data-post-url", href);
  } else {
    card.style.cursor = "default";
  }

  const meta = document.createElement("div");
  meta.className = "myvoice-top-posts__meta";

  const leftMeta = document.createElement("span");
  leftMeta.textContent = formatPostedAt(post.posted_at);
  meta.appendChild(leftMeta);

  if (showScore) {
    const scoreMeta = document.createElement("span");
    scoreMeta.textContent = `Score ${compactNumber(post.score)}`;
    meta.appendChild(scoreMeta);
  }

  const text = document.createElement("p");
  text.className = "myvoice-top-posts__text";
  const source = cleanText(post.content) || cleanText(post.title) || "No post text";
  const hasLongText = source.length > 260;
  const previewText = hasLongText ? `${source.slice(0, 257)}...` : source;
  let expanded = false;
  text.textContent = previewText;

  const metrics = document.createElement("div");
  metrics.className = "myvoice-top-posts__metrics";

  const metricsMap = [
    ["Likes", post.likes_count],
    ["Comments", post.comments_count],
    ["Reposts", post.reposts_count]
  ];
  for (const [label, value] of metricsMap) {
    if (value == null) continue;
    const badge = document.createElement("span");
    badge.className = "myvoice-top-posts__metric";
    badge.textContent = `${label}: ${compactNumber(value)}`;
    metrics.appendChild(badge);
  }

  card.appendChild(meta);
  card.appendChild(text);
  if (hasLongText || metrics.childNodes.length) {
    const footer = document.createElement("div");
    footer.className = "myvoice-top-posts__footer";

    if (hasLongText) {
      const toggle = document.createElement("span");
      toggle.className = "myvoice-top-posts__read-more";
      toggle.setAttribute("role", "button");
      toggle.setAttribute("aria-expanded", "false");
      toggle.tabIndex = 0;
      toggle.textContent = "Read more";

      const toggleExpanded = () => {
        expanded = !expanded;
        text.textContent = expanded ? source : previewText;
        toggle.setAttribute("aria-expanded", expanded ? "true" : "false");
        toggle.textContent = expanded ? "Show less" : "Read more";
      };

      const onToggleClick = (event) => {
        event.preventDefault();
        event.stopPropagation();
        toggleExpanded();
      };

      const onToggleKeydown = (event) => {
        if (event.key !== "Enter" && event.key !== " " && event.key !== "Spacebar") return;
        event.preventDefault();
        event.stopPropagation();
        toggleExpanded();
      };

      toggle.addEventListener("click", onToggleClick);
      toggle.addEventListener("keydown", onToggleKeydown);
      footer.appendChild(toggle);
    }

    if (metrics.childNodes.length) footer.appendChild(metrics);
    card.appendChild(footer);
  }
  return card;
}

function renderProfilePanelLoading() {
  profilePanelCurrentData = null;
  upsertPanelStyles();
  const panel = getOrCreatePanel();
  const body = panel.querySelector(".myvoice-top-posts__body");
  const title = panel.querySelector(".myvoice-top-posts__title");
  if (!body) return;
  if (title) title.textContent = profilePanelActiveTab === PROFILE_PANEL_TAB_NEW ? "New Posts" : "Best Posts";
  applyProfilePanelTabs(panel);
  body.replaceChildren(statusNode("Loading posts..."));
}

function renderProfilePanelError(text) {
  profilePanelCurrentData = null;
  upsertPanelStyles();
  const panel = getOrCreatePanel();
  const body = panel.querySelector(".myvoice-top-posts__body");
  applyProfilePanelTabs(panel);
  if (!body) return;
  body.replaceChildren(statusNode(text, { error: true }));
}

function isExtensionContextInvalidatedMessage(message) {
  const text = String(message || "");
  return /extension context invalidated/i.test(text) || /context invalidated/i.test(text);
}

function renderProfilePanelExtensionReloadHint() {
  profilePanelCurrentData = null;
  upsertPanelStyles();
  const panel = getOrCreatePanel();
  const body = panel.querySelector(".myvoice-top-posts__body");
  applyProfilePanelTabs(panel);
  if (!body) return;

  const box = document.createElement("div");
  box.className = "myvoice-top-posts__status error";

  const text = document.createElement("p");
  text.className = "myvoice-top-posts__status-text";
  text.textContent = "Extension was reloaded. Refresh this LinkedIn tab to reconnect MyVOICE's.";

  const action = document.createElement("button");
  action.type = "button";
  action.className = "myvoice-top-posts__action";
  action.textContent = "Reload page";
  action.addEventListener("click", () => {
    window.location.reload();
  });

  box.appendChild(text);
  box.appendChild(action);
  body.replaceChildren(box);
}

function renderProfilePanelResult(data) {
  profilePanelCurrentData = data || null;
  upsertPanelStyles();
  const panel = getOrCreatePanel();
  renderPersonHeader(panel, data && data.person);
  renderProfilePanelBody(panel, data);
}

async function refreshProfileTopPostsPanel() {
  const profile = parseLinkedInProfile(window.location.href);
  if (!profile) {
    profilePanelCurrentData = null;
    removePanel();
    removeLauncher();
    return;
  }

  if (profilePanelCollapsed) {
    const panel = document.getElementById(PROFILE_PANEL_ID);
    if (panel) panel.style.display = "none";
    upsertPanelStyles();
    const launcher = getOrCreateLauncher();
    launcher.style.display = "grid";
    return;
  }

  const launcher = document.getElementById(PROFILE_PANEL_LAUNCHER_ID);
  if (launcher) launcher.style.display = "none";
  const panel = getOrCreatePanel();
  panel.style.display = "flex";

  const requestId = ++profilePanelRequestId;
  renderProfilePanelLoading();
  let response;
  try {
    response = await sendRuntimeMessageSafe({
      type: "MYVOICE_GET_PROFILE_TOP_POSTS",
      profileUrl: profile.profileUrl,
      profileKey: profile.profileKey,
      profileSlug: profile.profileSlug
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err || "Unknown error");
    if (requestId === profilePanelRequestId) {
      if (isExtensionContextInvalidatedMessage(msg)) {
        renderProfilePanelExtensionReloadHint();
        return;
      }
      renderProfilePanelError(`Failed to load posts: ${msg}`);
    }
    return;
  }

  if (requestId !== profilePanelRequestId) return;
  if (!response || !response.ok) {
    const msg = response && response.error ? response.error : "Unexpected background response.";
    if (isExtensionContextInvalidatedMessage(msg)) {
      renderProfilePanelExtensionReloadHint();
      return;
    }
    renderProfilePanelError(`Failed to load posts: ${msg}`);
    return;
  }
  renderProfilePanelResult(response.data);
}

function scheduleProfilePanelRefresh(delay = PROFILE_PANEL_REFRESH_DELAY_MS) {
  if (profilePanelRefreshTimer) window.clearTimeout(profilePanelRefreshTimer);
  profilePanelRefreshTimer = window.setTimeout(() => {
    profilePanelRefreshTimer = null;
    refreshProfileTopPostsPanel();
  }, delay);
}

function isLinkedInPostPage(url = window.location.href) {
  const normalized = normalizeLinkedInPostUrl(url);
  return Boolean(normalized);
}

function isElementVisible(el) {
  if (!(el instanceof Element)) return false;
  if (!el.isConnected) return false;
  const style = window.getComputedStyle(el);
  if (!style || style.display === "none" || style.visibility === "hidden") return false;
  const rect = el.getBoundingClientRect();
  if (!rect || rect.width <= 0 || rect.height <= 0) return false;
  return true;
}

function resetCommentAssistState(nextPostKey = "") {
  if (commentAssistStatusTicker) {
    window.clearInterval(commentAssistStatusTicker);
    commentAssistStatusTicker = null;
  }
  const preservedAuthors = Array.isArray(commentAssistState.authors) ? commentAssistState.authors : [];
  const preservedAuthorKey = cleanText(commentAssistState.selectedAuthorKey) || readPreferredCommentAuthorKey();
  commentAssistRequestId += 1;
  commentAssistState = {
    postKey: nextPostKey,
    generating: false,
    generationStartedAt: 0,
    variants: null,
    activeVariant: "",
    authors: preservedAuthors,
    authorsLoaded: Boolean(commentAssistState.authorsLoaded),
    authorsLoading: Boolean(commentAssistState.authorsLoading),
    authorsError: cleanText(commentAssistState.authorsError),
    selectedAuthorKey: preservedAuthorKey,
    statusText: "",
    statusKind: "",
    statusDetails: ""
  };
}

function stopCommentAssistStatusTicker() {
  if (!commentAssistStatusTicker) return;
  window.clearInterval(commentAssistStatusTicker);
  commentAssistStatusTicker = null;
}

function buildCommentAssistGenerationStatusText(elapsedMs, steps = COMMENT_ASSIST_GENERATION_STATUS_STEPS) {
  const queue = Array.isArray(steps) ? steps.map(cleanText).filter(Boolean) : [];
  if (!queue.length) return "";

  const total = queue.length;
  const stepDurationMs = 2200;
  const seconds = Math.max(1, Math.floor(elapsedMs / 1000));
  let stepIndex = Math.floor(elapsedMs / stepDurationMs);
  if (stepIndex >= total) stepIndex = total - 1;

  let text = `[${stepIndex + 1}/${total}] ${queue[stepIndex]}`;
  if (seconds >= 8) text = `${text} (${seconds}s)`;

  if (seconds >= 25 && stepIndex === total - 1) {
    const longWaitHints = [
      "Сервер сейчас занят, продолжаю ждать...",
      "Ответ ещё в обработке на backend...",
      "Почти готово, финализирую результат..."
    ];
    const hintIndex = Math.floor((seconds - 25) / 5) % longWaitHints.length;
    text = `[${total}/${total}] ${longWaitHints[hintIndex]} (${seconds}s)`;
  }

  return text;
}

function startCommentAssistStatusTicker(requestId, steps = COMMENT_ASSIST_GENERATION_STATUS_STEPS) {
  stopCommentAssistStatusTicker();
  const startedAt = Date.now();

  const tick = () => {
    if (requestId !== commentAssistRequestId || !commentAssistState.generating) {
      stopCommentAssistStatusTicker();
      return;
    }
    const elapsedMs = Math.max(0, Date.now() - startedAt);
    const text = buildCommentAssistGenerationStatusText(elapsedMs, steps);
    if (!text || text === commentAssistState.statusText) return;
    setCommentAssistStatus(text);
    scheduleCommentAssistRefresh(0);
  };

  tick();
  commentAssistStatusTicker = window.setInterval(tick, 1000);
}

function extractLinkedInActivityIdFromElement(el) {
  if (!(el instanceof Element)) return "";
  const sources = [
    el.getAttribute("data-urn"),
    el.getAttribute("data-activity-urn"),
    el.getAttribute("data-entity-urn"),
    el.getAttribute("data-id"),
    el.getAttribute("id")
  ];
  for (const source of sources) {
    const activityId = extractActivityIdFromText(source);
    if (activityId) return activityId;
  }
  const classId = extractActivityIdFromText(cleanText(el.className));
  if (classId) return classId;
  return "";
}

function bumpCommentAssistStickyWindow() {
  commentAssistStickyUntil = Math.max(commentAssistStickyUntil, Date.now() + COMMENT_ASSIST_STICKY_WINDOW_MS);
}

function stopCommentAssistTransientObserver() {
  if (commentAssistTransientObserver) {
    commentAssistTransientObserver.disconnect();
    commentAssistTransientObserver = null;
  }
  if (commentAssistTransientObserverTimer) {
    window.clearTimeout(commentAssistTransientObserverTimer);
    commentAssistTransientObserverTimer = null;
  }
  if (commentAssistTransientObserverDebounce) {
    window.clearTimeout(commentAssistTransientObserverDebounce);
    commentAssistTransientObserverDebounce = null;
  }
}

function startCommentAssistTransientObserver() {
  bumpCommentAssistStickyWindow();
  stopCommentAssistTransientObserver();
  const body = document.body || document.documentElement;
  if (!body) return;

  commentAssistTransientObserver = new MutationObserver(() => {
    if (Date.now() > commentAssistStickyUntil) return;
    if (commentAssistTransientObserverDebounce) return;
    commentAssistTransientObserverDebounce = window.setTimeout(() => {
      commentAssistTransientObserverDebounce = null;
      scheduleCommentAssistRefresh(50);
    }, 70);
  });
  commentAssistTransientObserver.observe(body, { childList: true, subtree: true });
  commentAssistTransientObserverTimer = window.setTimeout(() => {
    stopCommentAssistTransientObserver();
  }, COMMENT_ASSIST_STICKY_WINDOW_MS + 1000);
}

function scoreLinkedInPostContainerCandidate(el) {
  if (!(el instanceof HTMLElement)) return -Infinity;
  const tag = cleanText(el.tagName).toLowerCase();
  const role = cleanText(el.getAttribute("role")).toLowerCase();
  const cls = cleanText(el.className).toLowerCase();
  const activityId = extractLinkedInActivityIdFromElement(el);

  const hasArticleMarker = tag === "article" || role === "article";
  const hasFeedMarker = cls.includes("feed-shared-update") || cls.includes("update-components");
  const hasPostLink = Boolean(el.querySelector(
    "a[href*='/feed/update/urn:li:activity:'], a[href*='/posts/'], a[href*='activity-'], a[href*='ugcPost-'], a[href*='share-']"
  ));
  if (!(hasArticleMarker || hasFeedMarker || hasPostLink || activityId)) return -Infinity;

  let score = 0;
  if (tag === "article") score += 60;
  if (role === "article") score += 55;
  if (cls.includes("feed-shared-update-v2")) score += 50;
  if (cls.includes("feed-shared-update")) score += 35;
  if (cls.includes("update-components")) score += 12;
  if (activityId) score += 90;
  if (hasPostLink) score += 18;

  // Tiny wrappers are usually noise (icons, buttons). Prefer containers that
  // actually represent a full post card.
  const textLen = cleanText(el.textContent).length;
  if (textLen > 80) score += 8;
  if (textLen > 300) score += 6;
  if (textLen < 20) score -= 20;

  return score;
}

function findLinkedInPostContainerFromNode(node) {
  if (!(node instanceof Element)) return null;
  // Fast path: prefer closest ancestor that has a direct activity id marker.
  let direct = node;
  for (let hops = 0; hops < 24 && direct; hops += 1) {
    if (direct instanceof HTMLElement) {
      const directId = extractLinkedInActivityIdFromElement(direct);
      if (directId) {
        const cls = cleanText(direct.className).toLowerCase();
        const tag = cleanText(direct.tagName).toLowerCase();
        const role = cleanText(direct.getAttribute("role")).toLowerCase();
        const textLen = cleanText(direct.textContent).length;
        const looksLikePostContainer =
          tag === "article" ||
          role === "article" ||
          cls.includes("feed-shared-update") ||
          cls.includes("update-components") ||
          textLen > 80;
        if (looksLikePostContainer) return direct;
      }

      const tag = cleanText(direct.tagName).toLowerCase();
      const role = cleanText(direct.getAttribute("role")).toLowerCase();
      if (tag === "article" || role === "article") return direct;
    }
    direct = direct.parentElement;
  }

  let el = node;
  let best = null;
  let bestScore = -Infinity;

  for (let hops = 0; hops < 28 && el; hops += 1) {
    if (el instanceof HTMLElement) {
      const score = scoreLinkedInPostContainerCandidate(el);
      const adjusted = score - hops * 3; // prefer closer matches
      if (adjusted > bestScore) {
        best = el;
        bestScore = adjusted;
      }
      // Strong signal early exit: activity id on a reasonably close container.
      if (score >= 130 && hops <= 8) return el;
    }
    el = el.parentElement;
  }

  if (best) return best;

  // As a last resort, try common containers even if they don't score well.
  const fallback = node.closest("article, [role='article'], .feed-shared-update-v2");
  return fallback instanceof HTMLElement ? fallback : null;
}

function deriveActivityIdForContainer(container) {
  if (!(container instanceof Element)) return "";
  return extractLinkedInActivityIdFromElement(container) || extractActivityIdFromText(container.outerHTML);
}

function findLinkedInPostContainerForActivityId(activityId) {
  const id = cleanText(activityId);
  if (!id) return null;

  const selectors = [
    `[data-activity-urn*='urn:li:activity:${id}']`,
    `[data-urn*='urn:li:activity:${id}']`,
    `[data-entity-urn*='urn:li:activity:${id}']`,
    `a[href*='urn:li:activity:${id}']`,
    `a[href*='activity-${id}']`,
    `a[href*='ugcPost-${id}']`,
    `a[href*='share-${id}']`
  ];

  const seen = new Set();
  const containers = [];
  for (const selector of selectors) {
    const nodes = Array.from(document.querySelectorAll(selector)).slice(0, 40);
    for (const node of nodes) {
      const container = findLinkedInPostContainerFromNode(node);
      if (!(container instanceof HTMLElement)) continue;
      if (seen.has(container)) continue;
      seen.add(container);
      containers.push(container);
    }
  }
  if (!containers.length) return null;

  let best = null;
  let bestScore = -Infinity;
  for (const container of containers) {
    const score = scoreLinkedInPostContainerCandidate(container);
    const rect = container.getBoundingClientRect();
    const inViewport = rect.bottom >= 0 && rect.top <= window.innerHeight;
    const adjusted = score + (inViewport ? 12 : 0);
    if (adjusted > bestScore) {
      best = container;
      bestScore = adjusted;
    }
  }
  return best;
}

function commentAssistPostKeyFromEditor(editor) {
  if (!(editor instanceof Element)) return "";

  const container = findLinkedInPostContainerFromNode(editor);
  if (container) {
    const postUrl = cleanText(extractPostUrlFromArticle(container));
    const normalizedUrl = normalizeLinkedInPostUrl(postUrl);
    if (normalizedUrl) return normalizedUrl;

    const activityId =
      extractActivityIdFromText(postUrl) ||
      extractLinkedInActivityIdFromElement(container) ||
      extractActivityIdFromText(container.outerHTML);
    if (activityId) return `urn:li:activity:${activityId}`;

    const text = cleanText(extractPostText(container));
    if (text) return `txt:${text.toLowerCase().slice(0, 180)}`;
  }

  const pageKey = normalizeLinkedInPostUrl(window.location.href);
  if (pageKey) return pageKey;
  return "";
}

function ensureCommentAssistStateForEditor(editor) {
  const key = commentAssistPostKeyFromEditor(editor);
  if (!key) return;
  if (commentAssistState.postKey !== key) {
    resetCommentAssistState(key);
  }
}

function setCommentAssistTargetFromNode(node) {
  if (!(node instanceof Element)) return false;
  const box = node.closest(".comments-comment-box, [class*='comments-comment-box']");
  if (box instanceof HTMLElement) {
    commentAssistTargetCommentBox = box;
    const idFromBox = deriveActivityIdForContainer(box);
    if (idFromBox) commentAssistTargetActivityId = idFromBox;
  }
  const container = findLinkedInPostContainerFromNode(node);
  if (container) {
    commentAssistTargetArticle = container;
    const id = deriveActivityIdForContainer(container);
    if (id) commentAssistTargetActivityId = id;
  } else if (commentAssistTargetCommentBox) {
    // If we can't map the comment box to a post container, still keep the box as anchor.
    commentAssistTargetArticle = null;
  } else {
    return false;
  }
  commentAssistTargetUpdatedAt = Date.now();
  return true;
}

function isCommentActionButton(node) {
  if (!(node instanceof Element)) return false;
  const btn = node.closest("button, a, [role='button']");
  if (!btn) return false;
  const control = cleanText(btn.getAttribute("data-control-name")).toLowerCase();
  if (control === "comment") return true;
  const label = cleanText(btn.getAttribute("aria-label") || btn.textContent).toLowerCase();
  if (!label) return false;
  if (label === "comment") return true;
  if (label.includes("comment")) return true;
  if (label.includes("коммент")) return true;
  if (label.includes("ответ")) return true;
  return false;
}

function bindCommentAssistFeedTriggers() {
  if (commentAssistTriggersBound) return;
  commentAssistTriggersBound = true;

  document.addEventListener("click", (event) => {
    const target = event && event.target;
    if (!(target instanceof Element)) return;
    const profilePanel = document.getElementById(PROFILE_PANEL_ID);
    if (profilePanel && profilePanel.contains(target)) return;

    if (isCommentActionButton(target)) {
      // Prefer mapping the click to a specific post container and its comment box.
      const btn = target.closest("button, a, [role='button']") || target;
      const container = findLinkedInPostContainerFromNode(btn);
      if (container) {
        commentAssistTargetArticle = container;
        commentAssistTargetCommentBox =
          container.querySelector(".comments-comment-box, [class*='comments-comment-box']") || null;
        commentAssistTargetActivityId = deriveActivityIdForContainer(container);
        commentAssistTargetUpdatedAt = Date.now();
      } else {
        setCommentAssistTargetFromNode(btn);
      }
      scheduleCommentAssistRefresh(40);
      scheduleCommentAssistRefresh(220);
      scheduleCommentAssistRefresh(900);
      return;
    }

    // If user clicks into an existing comment composer directly.
    if (target.closest(".comments-comment-box, [class*='comments-comment-box']")) {
      setCommentAssistTargetFromNode(target);
      scheduleCommentAssistRefresh(0);
    }
  }, true);

  document.addEventListener("focusin", (event) => {
    const target = event && event.target;
    if (!(target instanceof Element)) return;
    const profilePanel = document.getElementById(PROFILE_PANEL_ID);
    if (profilePanel && profilePanel.contains(target)) return;
    setCommentAssistTargetFromNode(target);
    scheduleCommentAssistRefresh(0);
  }, true);
}

function scoreCommentEditorCandidate(editor) {
  if (!(editor instanceof HTMLElement)) return -1000;

  const attrs = [
    editor.getAttribute("aria-label"),
    editor.getAttribute("data-placeholder"),
    editor.getAttribute("aria-placeholder"),
    editor.getAttribute("placeholder")
  ].map(cleanText).filter(Boolean).join(" ").toLowerCase();

  const className = cleanText(editor.className).toLowerCase();
  const wrapper = editor.closest("form, [class*='comment'], [data-test-id*='comment']");
  const wrapperClass = cleanText(wrapper && wrapper.className).toLowerCase();
  const wrapperId = cleanText(wrapper && wrapper.id).toLowerCase();

  // Some LinkedIn editors are "visually" sized by a wrapper, while the inner
  // contenteditable node can have a 0-height rect when empty. Treat those as
  // visible if the wrapper itself is visible.
  if (!isElementVisible(editor)) {
    const visibleWrapper = wrapper instanceof Element ? wrapper : editor.parentElement;
    if (!isElementVisible(visibleWrapper)) return -1000;
  }

  let score = 0;
  if (attrs.includes("add a comment")) score += 140;
  if (attrs.includes("добав") && attrs.includes("коммент")) score += 140;
  if (attrs.includes("comment")) score += 70;
  if (attrs.includes("коммент")) score += 70;
  if (className.includes("comment")) score += 50;
  if (wrapperClass.includes("comment") || wrapperId.includes("comment")) score += 40;
  if (wrapper && wrapper.tagName.toLowerCase() === "form") score += 18;
  if (editor.closest(".msg-overlay-bubble-header, .msg-overlay-list-bubble, [aria-label*='Messaging']")) {
    score -= 400;
  }
  if (attrs.includes("message") || attrs.includes("сообщ")) score -= 180;

  const rect = editor.getBoundingClientRect();
  if (rect.top >= 0 && rect.top <= window.innerHeight) score += 12;
  if (rect.top > window.innerHeight) score -= 18;
  return score;
}

function findLinkedInCommentEditor(scopeRoot = document) {
  const root = scopeRoot && typeof scopeRoot.querySelectorAll === "function" ? scopeRoot : document;
  const selectors = [
    // LinkedIn sometimes uses contenteditable="plaintext-only" (and may omit explicit "true").
    "[contenteditable]:not([contenteditable='false'])[role='textbox']",
    "[contenteditable]:not([contenteditable='false'])[data-placeholder]",
    "[contenteditable]:not([contenteditable='false'])[aria-label]",
    "[role='textbox'][aria-label]",
    "[role='textbox'][data-placeholder]",
    "div.comments-comment-box-comment__text-editor[contenteditable]:not([contenteditable='false'])",
    "textarea[aria-label]",
    "textarea[placeholder]"
  ];
  const candidates = [];
  const seen = new Set();
  for (const selector of selectors) {
    const nodes = Array.from(root.querySelectorAll(selector));
    for (const node of nodes) {
      if (!(node instanceof HTMLElement)) continue;
      if (seen.has(node)) continue;
      seen.add(node);

      // Filter out nodes that aren't actually editable.
      const ceAttr = cleanText(node.getAttribute("contenteditable")).toLowerCase();
      if (ceAttr === "false") continue;
      candidates.push(node);
    }
  }
  if (!candidates.length) return null;

  let best = null;
  let bestScore = -Infinity;
  for (const candidate of candidates) {
    const score = scoreCommentEditorCandidate(candidate);
    if (score > bestScore) {
      best = candidate;
      bestScore = score;
    }
  }
  return bestScore >= 30 ? best : null;
}

function findCommentComposerAnchor(editor) {
  if (!editor) return null;
  return (
    editor.closest("form.comments-comment-box__form") ||
    editor.closest("form") ||
    editor.closest(".comments-comment-box") ||
    editor.closest("[class*='comments-comment-box']") ||
    editor.parentElement
  );
}

function resolveCommentAssistMount(editor) {
  if (!editor) return null;
  const baseTarget =
    editor.closest(".comments-comment-box") ||
    editor.closest("[class*='comments-comment-box']") ||
    findCommentComposerAnchor(editor);
  if (!baseTarget || !baseTarget.parentElement) return null;

  let target = baseTarget;
  for (let i = 0; i < 5; i += 1) {
    const parent = target.parentElement;
    if (!parent || parent === document.body || parent === document.documentElement) break;

    const style = window.getComputedStyle(parent);
    const display = cleanText(style.display).toLowerCase();
    const direction = cleanText(style.flexDirection).toLowerCase();
    const isFlexRow = display.includes("flex") && direction !== "column";
    const isGrid = display.includes("grid");
    if (!(isFlexRow || isGrid)) break;

    target = parent;
  }

  return target.parentElement ? { parent: target.parentElement, before: target } : null;
}

function resolveCommentAssistFallbackMountForFeed(container) {
  if (!(container instanceof HTMLElement)) return null;

  // Prefer mounting right before the comment box wrapper if it exists.
  const commentBox = container.querySelector(".comments-comment-box, [class*='comments-comment-box']");
  if (commentBox && commentBox.parentElement) {
    return { parent: commentBox.parentElement, before: commentBox };
  }

  // Next best: mount after the social action bar (Like / Comment / Repost / Send).
  const actionBar =
    container.querySelector(".feed-shared-social-actions") ||
    container.querySelector("[class*='feed-shared-social-actions']") ||
    container.querySelector("[data-test-id*='social-actions']") ||
    container.querySelector("[data-test-id*='socialAction']") ||
    container.querySelector("[data-control-name='social-actions']") ||
    container.querySelector("[class*='social-actions']");
  if (actionBar && actionBar.parentElement) {
    return { parent: actionBar.parentElement, before: actionBar.nextSibling };
  }

  // Last resort: append to the post container.
  return { parent: container, before: null };
}

function findVisibleLinkedInCommentBox(scopeRoot = document) {
  const root = scopeRoot && typeof scopeRoot.querySelectorAll === "function" ? scopeRoot : document;
  const boxes = Array.from(root.querySelectorAll(".comments-comment-box, [class*='comments-comment-box']"));
  if (!boxes.length) return null;

  const active = document.activeElement instanceof Element ? document.activeElement : null;
  let best = null;
  let bestScore = -Infinity;

  for (const box of boxes) {
    if (!(box instanceof HTMLElement)) continue;
    if (!isElementVisible(box)) continue;

    const rect = box.getBoundingClientRect();
    const inViewport = rect.bottom >= 0 && rect.top <= window.innerHeight;
    const hasEditor =
      Boolean(box.querySelector("[contenteditable]:not([contenteditable='false'])")) ||
      Boolean(box.querySelector("textarea"));

    let score = 0;
    if (active && box.contains(active)) score += 200;
    if (hasEditor) score += 24;
    if (inViewport) score += 18;
    // Prefer boxes closer to the top of viewport.
    score += Math.max(-50, 12 - Math.abs(rect.top) / 60);

    if (score > bestScore) {
      best = box;
      bestScore = score;
    }
  }

  return best;
}

function removeCommentAssistRoot() {
  const root = document.getElementById(COMMENT_ASSIST_ROOT_ID);
  if (root) root.remove();
}

function isCommentAssistInteractionActive(root = document.getElementById(COMMENT_ASSIST_ROOT_ID)) {
  if (!(root instanceof HTMLElement)) return false;
  const active = document.activeElement;
  if (!(active instanceof Element)) return false;
  if (!root.contains(active)) return false;

  const tag = cleanText(active.tagName).toLowerCase();
  if (tag === "select" || tag === "option") return true;
  if (active.id === COMMENT_ASSIST_AUTHOR_SELECT_ID) return true;
  return Boolean(active.closest(`#${COMMENT_ASSIST_AUTHOR_SELECT_ID}`));
}

function upsertCommentAssistStyles() {
  if (document.getElementById(COMMENT_ASSIST_STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = COMMENT_ASSIST_STYLE_ID;
  style.textContent = `
	    #${COMMENT_ASSIST_ROOT_ID} {
	      display: block;
	      width: 100%;
	      max-width: 100%;
	      box-sizing: border-box;
	      margin: 0 0 12px;
	      color: #0f172a;
	    }

    #${COMMENT_ASSIST_ROOT_ID} .myvoice-comment-assist__card {
      border: 1px solid #d6e2f6;
      border-radius: 18px;
      background: linear-gradient(180deg, #ffffff 0%, #f8fbff 100%);
      box-shadow: 0 10px 26px rgba(15, 23, 42, 0.08);
      padding: 14px 14px 12px;
      display: grid;
      gap: 12px;
      position: relative;
      overflow: hidden;
    }

    #${COMMENT_ASSIST_ROOT_ID} .myvoice-comment-assist__card::before {
      content: "";
      position: absolute;
      left: 0;
      top: 0;
      right: 0;
      height: 3px;
      background: linear-gradient(90deg, #6f78ff 0%, #4e5cf7 55%, #6d8dff 100%);
      opacity: 0.92;
    }

    #${COMMENT_ASSIST_ROOT_ID} .myvoice-comment-assist__top {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }

    #${COMMENT_ASSIST_ROOT_ID} .myvoice-comment-assist__brand {
      display: inline-flex;
      align-items: center;
      gap: 11px;
      min-width: 0;
    }

    #${COMMENT_ASSIST_ROOT_ID} .myvoice-comment-assist__logo {
      width: 38px;
      height: 38px;
      border-radius: 12px;
      overflow: hidden;
      display: grid;
      place-items: center;
      flex: 0 0 auto;
      box-shadow: 0 8px 18px rgba(78, 92, 247, 0.22);
    }

    #${COMMENT_ASSIST_ROOT_ID} .myvoice-comment-assist__logo .myvoice-top-posts__logo-image {
      width: 100%;
      height: 100%;
      object-fit: cover;
    }

    #${COMMENT_ASSIST_ROOT_ID} .myvoice-comment-assist__brand-meta {
      min-width: 0;
      display: grid;
      gap: 1px;
    }

    #${COMMENT_ASSIST_ROOT_ID} .myvoice-comment-assist__title {
      margin: 0;
      font-size: 15px;
      line-height: 1.2;
      font-weight: 800;
      letter-spacing: 0.01em;
      color: #1e40af;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    #${COMMENT_ASSIST_ROOT_ID} .myvoice-comment-assist__subtitle {
      margin: 0;
      font-size: 12px;
      line-height: 1.3;
      color: #5f7498;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    #${COMMENT_ASSIST_ROOT_ID} .myvoice-comment-assist__btn {
      height: 40px;
      border: none;
      border-radius: 999px;
      padding: 0 18px;
      min-width: 186px;
      font-size: 13px;
      font-weight: 700;
      color: #ffffff;
      background: linear-gradient(145deg, #6f78ff 0%, #4e5cf7 100%);
      cursor: pointer;
      transition: transform 0.12s ease, box-shadow 0.12s ease, opacity 0.12s ease;
      box-shadow: 0 10px 20px rgba(78, 92, 247, 0.28);
      letter-spacing: 0.01em;
    }

    #${COMMENT_ASSIST_ROOT_ID} .myvoice-comment-assist__btn:hover:not(:disabled) {
      transform: translateY(-1px);
      box-shadow: 0 10px 18px rgba(78, 92, 247, 0.3);
    }

    #${COMMENT_ASSIST_ROOT_ID} .myvoice-comment-assist__btn:disabled {
      cursor: default;
      opacity: 0.7;
      transform: none;
      box-shadow: none;
    }

    #${COMMENT_ASSIST_ROOT_ID} .myvoice-comment-assist__author {
      display: grid;
      gap: 8px;
      background: linear-gradient(180deg, #f8fbff 0%, #f1f6ff 100%);
      border: 1px solid #d8e4fb;
      border-radius: 14px;
      padding: 10px;
    }

    #${COMMENT_ASSIST_ROOT_ID} .myvoice-comment-assist__author-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
    }

    #${COMMENT_ASSIST_ROOT_ID} .myvoice-comment-assist__author-label {
      margin: 0;
      font-size: 12px;
      line-height: 1.2;
      font-weight: 700;
      letter-spacing: 0.02em;
      color: #4f6488;
    }

    #${COMMENT_ASSIST_ROOT_ID} .myvoice-comment-assist__author-refresh {
      height: 28px;
      border: 1px solid #bfd4ff;
      border-radius: 999px;
      background: #ffffff;
      color: #1d4ed8;
      font-size: 11px;
      line-height: 1;
      font-weight: 700;
      padding: 0 10px;
      cursor: pointer;
      transition: border-color 0.12s ease, background-color 0.12s ease, color 0.12s ease;
    }

    #${COMMENT_ASSIST_ROOT_ID} .myvoice-comment-assist__author-refresh:hover:not(:disabled) {
      border-color: #8db3ff;
      background: #eef4ff;
      color: #1e40af;
    }

    #${COMMENT_ASSIST_ROOT_ID} .myvoice-comment-assist__author-refresh:disabled {
      opacity: 0.55;
      cursor: default;
      text-decoration: none;
    }

    #${COMMENT_ASSIST_ROOT_ID} .myvoice-comment-assist__author-select {
      width: 100%;
      height: 44px;
      border-radius: 12px;
      border: 1px solid #bfd2f3;
      background: #ffffff;
      color: #0f172a;
      font-size: 15px;
      font-weight: 650;
      padding: 0 12px;
      outline: none;
      box-sizing: border-box;
      appearance: auto;
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.9);
    }

    #${COMMENT_ASSIST_ROOT_ID} .myvoice-comment-assist__author-select:focus {
      border-color: #8fb3ff;
      box-shadow: 0 0 0 4px rgba(79, 125, 255, 0.18);
    }

    #${COMMENT_ASSIST_ROOT_ID} .myvoice-comment-assist__author-select:disabled {
      background: #f8fafc;
      color: #64748b;
      cursor: default;
    }

    #${COMMENT_ASSIST_ROOT_ID} .myvoice-comment-assist__author-hint {
      margin: 0;
      font-size: 12px;
      line-height: 1.35;
      color: #627591;
      word-break: break-word;
    }

    #${COMMENT_ASSIST_ROOT_ID} .myvoice-comment-assist__author-hint.error {
      color: #b42318;
    }

    #${COMMENT_ASSIST_ROOT_ID} .myvoice-comment-assist__variants {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
    }

    #${COMMENT_ASSIST_ROOT_ID} .myvoice-comment-assist__variant {
      height: 34px;
      border-radius: 11px;
      border: 1px solid #ccdaff;
      background: #ffffff;
      color: #334155;
      font-size: 12px;
      font-weight: 700;
      padding: 0 10px;
      cursor: pointer;
      transition: border-color 0.12s ease, background-color 0.12s ease, color 0.12s ease;
      text-align: center;
    }

    #${COMMENT_ASSIST_ROOT_ID} .myvoice-comment-assist__variant:hover {
      border-color: #a5bfff;
      background: #f3f7ff;
    }

    #${COMMENT_ASSIST_ROOT_ID} .myvoice-comment-assist__variant:disabled {
      cursor: default;
      opacity: 0.5;
      background: #f8fafc;
      border-color: #dbe3ee;
      color: #64748b;
    }

    #${COMMENT_ASSIST_ROOT_ID} .myvoice-comment-assist__variant.active {
      border-color: #6f78ff;
      background: #eaf0ff;
      color: #1d4ed8;
    }

    #${COMMENT_ASSIST_ROOT_ID} .myvoice-comment-assist__status {
      margin-top: 2px;
      font-size: 12px;
      line-height: 1.3;
      color: #50627d;
      min-height: 22px;
      word-break: break-word;
      background: #f5f8fd;
      border: 1px solid #e0e9f7;
      border-radius: 10px;
      padding: 8px 10px;
    }

    #${COMMENT_ASSIST_ROOT_ID} .myvoice-comment-assist__status.error {
      color: #b42318;
      background: #fff2f0;
      border: 1px solid #ffd3cc;
      border-radius: 8px;
      padding: 6px 8px;
    }

    #${COMMENT_ASSIST_ROOT_ID} .myvoice-comment-assist__status.ok {
      color: #166534;
      background: #effcf5;
      border: 1px solid #b7ebd0;
      border-radius: 8px;
      padding: 6px 8px;
    }

    @media (max-width: 760px) {
      #${COMMENT_ASSIST_ROOT_ID} .myvoice-comment-assist__top {
        flex-direction: column;
        align-items: stretch;
      }

      #${COMMENT_ASSIST_ROOT_ID} .myvoice-comment-assist__btn {
        width: 100%;
        min-width: 0;
      }
    }
  `;
  document.documentElement.appendChild(style);
}

function getAvailableCommentVariants(variants) {
  if (!variants || typeof variants !== "object") return [];
  return ["short", "medium", "long"]
    .filter((key) => cleanText(variants[key]))
    .map((key) => ({ key, text: String(variants[key] || "") }));
}

function stripCommentVariantLabel(rawText) {
  let text = cleanText(rawText);
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
}

function getDefaultCommentVariantKey(variants) {
  if (cleanText(variants && variants.medium)) return "medium";
  if (cleanText(variants && variants.short)) return "short";
  if (cleanText(variants && variants.long)) return "long";
  return "";
}

function commentVariantLabel(key) {
  if (key === "short") return "Короткий";
  if (key === "medium") return "Средний";
  if (key === "long") return "Длинный";
  return key;
}

function readPreferredCommentAuthorKey() {
  try {
    return cleanText(window.localStorage.getItem(COMMENT_ASSIST_AUTHOR_PREF_KEY));
  } catch {
    return "";
  }
}

function writePreferredCommentAuthorKey(value) {
  const key = cleanText(value);
  try {
    if (key) {
      window.localStorage.setItem(COMMENT_ASSIST_AUTHOR_PREF_KEY, key);
    } else {
      window.localStorage.removeItem(COMMENT_ASSIST_AUTHOR_PREF_KEY);
    }
  } catch {
    // ignore storage errors
  }
}

function buildCommentAssistAuthorKey(author, fallbackIndex = 0) {
  const linkedin = cleanText(author && author.linkedin_url).toLowerCase();
  if (linkedin) return `ln:${linkedin}`;
  const fullName = cleanText(author && author.full_name).toLowerCase();
  const role = cleanText(author && author.role).toLowerCase();
  if (fullName || role) return `nm:${fullName}|${role}`;
  return `idx:${fallbackIndex}`;
}

function normalizeCommentAssistAuthor(rawAuthor, fallbackIndex = 0) {
  if (!rawAuthor || typeof rawAuthor !== "object") return null;
  const fullName = cleanText(rawAuthor.full_name || rawAuthor.name);
  if (!fullName) return null;
  return {
    key: buildCommentAssistAuthorKey(rawAuthor, fallbackIndex),
    full_name: fullName,
    role: cleanText(rawAuthor.role),
    history: cleanText(rawAuthor.history),
    linkedin_url: cleanText(rawAuthor.linkedin_url || rawAuthor.linkedin)
  };
}

function normalizeCommentAssistAuthors(rawAuthors) {
  const list = Array.isArray(rawAuthors) ? rawAuthors : [];
  const seen = new Set();
  const authors = [];
  for (let index = 0; index < list.length; index += 1) {
    const normalized = normalizeCommentAssistAuthor(list[index], index);
    if (!normalized) continue;
    if (seen.has(normalized.key)) continue;
    seen.add(normalized.key);
    authors.push(normalized);
  }
  return authors;
}

function getSelectedCommentAssistAuthor() {
  const authors = Array.isArray(commentAssistState.authors) ? commentAssistState.authors : [];
  if (!authors.length) return null;
  const stateKey = cleanText(commentAssistState.selectedAuthorKey);
  const storedKey = readPreferredCommentAuthorKey();
  const normalizedStored = storedKey.toLowerCase();
  return (
    authors.find((author) => author.key === stateKey) ||
    authors.find((author) => author.key === storedKey) ||
    authors.find((author) => author.full_name.toLowerCase() === normalizedStored) ||
    authors[0]
  );
}

function setCommentAssistAuthors(rawAuthors) {
  commentAssistState.authors = normalizeCommentAssistAuthors(rawAuthors);
  commentAssistState.authorsLoaded = true;
  commentAssistState.authorsLoading = false;
  commentAssistState.authorsError = "";
  const selected = getSelectedCommentAssistAuthor();
  commentAssistState.selectedAuthorKey = selected ? selected.key : "";
  writePreferredCommentAuthorKey(commentAssistState.selectedAuthorKey);
}

async function ensureCommentAssistAuthorsLoaded({ force = false } = {}) {
  if (!force && commentAssistState.authorsLoaded) {
    return Array.isArray(commentAssistState.authors) ? commentAssistState.authors : [];
  }
  if (commentAssistState.authorsLoading) {
    return Array.isArray(commentAssistState.authors) ? commentAssistState.authors : [];
  }

  const requestId = ++commentAssistAuthorsRequestId;
  commentAssistState.authorsLoading = true;
  if (force) {
    commentAssistState.authorsError = "";
  }
  scheduleCommentAssistRefresh(0);

  try {
    const response = await sendRuntimeMessageSafe({
      type: "MYVOICE_GET_SETUP_AUTHORS",
      force: Boolean(force)
    });
    if (requestId !== commentAssistAuthorsRequestId) {
      return Array.isArray(commentAssistState.authors) ? commentAssistState.authors : [];
    }
    if (!response || !response.ok) {
      const msg = response && response.error ? response.error : "Не удалось загрузить авторов из системы.";
      commentAssistState.authors = [];
      commentAssistState.authorsLoaded = true;
      commentAssistState.authorsError = msg;
      return [];
    }
    setCommentAssistAuthors(response.authors);
    return commentAssistState.authors;
  } catch (err) {
    if (requestId !== commentAssistAuthorsRequestId) {
      return Array.isArray(commentAssistState.authors) ? commentAssistState.authors : [];
    }
    const msg = err instanceof Error ? err.message : String(err || "Не удалось загрузить авторов из системы.");
    commentAssistState.authors = [];
    commentAssistState.authorsLoaded = true;
    commentAssistState.authorsError = msg;
    return [];
  } finally {
    if (requestId === commentAssistAuthorsRequestId) {
      commentAssistState.authorsLoading = false;
    }
    scheduleCommentAssistRefresh(0);
  }
}

function toCommentAssistAuthorPayload(author) {
  if (!author || typeof author !== "object") return null;
  const fullName = cleanText(author.full_name);
  if (!fullName) return null;
  return {
    full_name: fullName,
    role: cleanText(author.role),
    history: cleanText(author.history),
    linkedin_url: cleanText(author.linkedin_url)
  };
}

function setCommentAssistStatus(text, kind = "") {
  commentAssistState.statusText = cleanText(text);
  commentAssistState.statusKind = kind === "error" || kind === "ok" ? kind : "";
  commentAssistState.statusDetails = "";
}

function setCommentAssistError(rawMessage) {
  const msg = cleanText(rawMessage);
  const low = msg.toLowerCase();
  let text = msg || "Ошибка генерации комментария.";

  if (low.includes("can't reach backend") || low.includes("failed to fetch") || low.includes("network error")) {
    text = "Нет связи с backend. Проверь адрес в extension options.";
  } else if (low.includes("401") || low.includes("unauthorized")) {
    text = "Нужен вход в MyVOICE. Открой extension options и нажми Open Login.";
  } else if (low.includes("403")) {
    text = "Доступ к генерации ограничен. Проверь тариф или лимиты.";
  } else if (low.includes("404")) {
    text = "Сервис генерации не найден на backend.";
  } else if (low.includes("автор") && (low.includes("не выбран") || low.includes("добав"))) {
    text = "Выберите автора в блоке MyVOICE's и попробуйте снова.";
  }

  commentAssistState.statusText = text;
  commentAssistState.statusKind = "error";
  commentAssistState.statusDetails = msg || "";
}

function readCurrentPostTextForAssist(editor = null) {
  const editorNode = editor instanceof Element ? editor : null;
  const container = editorNode ? findLinkedInPostContainerFromNode(editorNode) : null;
  if (container) {
    const extracted = extractPostFromArticle(container);
    const postText = cleanText(extracted && extracted.text);
    if (postText) return postText;
  }

  const extracted = extractFromCurrentPage(window.location.href);
  if (!extracted || !extracted.ok || !extracted.data) {
    const msg = extracted && extracted.error ? extracted.error : "Не удалось прочитать текст поста.";
    throw new Error(msg);
  }
  const postText = cleanText(extracted.data.text);
  if (!postText) {
    throw new Error("Пустой текст поста. Откройте полный текст и повторите.");
  }
  return postText;
}

function fillLinkedInCommentEditor(editor, text) {
  const value = String(text || "").replace(/\r\n/g, "\n").trim();
  if (!editor || !value) return false;

  if (editor instanceof HTMLTextAreaElement || editor instanceof HTMLInputElement) {
    editor.focus();
    editor.value = value;
    editor.dispatchEvent(new Event("input", { bubbles: true }));
    editor.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  }

  editor.focus();
  const selection = window.getSelection();
  if (selection) {
    const range = document.createRange();
    range.selectNodeContents(editor);
    selection.removeAllRanges();
    selection.addRange(range);
  }

  let inserted = false;
  try {
    inserted = document.execCommand("insertText", false, value);
  } catch {
    inserted = false;
  }

  if (!inserted) {
    editor.textContent = value;
  }

  try {
    editor.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: value }));
  } catch {
    editor.dispatchEvent(new Event("input", { bubbles: true }));
  }
  editor.dispatchEvent(new Event("change", { bubbles: true }));
  return true;
}

function applyCommentVariant(key) {
  const variants = commentAssistState.variants || {};
  const text = stripCommentVariantLabel(variants[key]);
  if (!text) return false;

  const editor = isLinkedInPostPage(window.location.href)
    ? findLinkedInCommentEditor()
    : (commentAssistTargetArticle && commentAssistTargetArticle.isConnected
        ? (findLinkedInCommentEditor(commentAssistTargetArticle) || findLinkedInCommentEditor())
        : findLinkedInCommentEditor());
  if (!editor) {
    setCommentAssistStatus("Поле комментария не найдено. Нажмите Comment и повторите.", "error");
    return false;
  }

  const ok = fillLinkedInCommentEditor(editor, text);
  if (!ok) {
    setCommentAssistStatus("Не удалось вставить текст в поле комментария.", "error");
    return false;
  }

  commentAssistState.activeVariant = key;
  setCommentAssistStatus(`Подставлен вариант: ${commentVariantLabel(key)}.`, "ok");
  return true;
}

async function generateCommentVariants() {
  if (commentAssistState.generating) return;

  const requestId = ++commentAssistRequestId;
  commentAssistState.generating = true;
  commentAssistState.generationStartedAt = Date.now();
  setCommentAssistStatus("Проверяю выбранного автора...");
  scheduleCommentAssistRefresh(0);

  try {
    setCommentAssistStatus("Загружаю авторов из системы...");
    scheduleCommentAssistRefresh(0);
    const authors = await ensureCommentAssistAuthorsLoaded();
    if (requestId !== commentAssistRequestId) return;

    setCommentAssistStatus("Проверяю выбранного автора...");
    scheduleCommentAssistRefresh(0);
    const selectedAuthor = getSelectedCommentAssistAuthor();
    if (!authors.length || !selectedAuthor) {
      throw new Error(commentAssistState.authorsError || "Добавьте автора в MyVOICE Settings и выберите его.");
    }
    const authorPayload = toCommentAssistAuthorPayload(selectedAuthor);
    if (!authorPayload) {
      throw new Error("Автор не выбран. Выберите автора и повторите.");
    }

    setCommentAssistStatus("Читаю текст поста...");
    scheduleCommentAssistRefresh(0);

    const editor = isLinkedInPostPage(window.location.href)
      ? findLinkedInCommentEditor()
      : (commentAssistTargetArticle && commentAssistTargetArticle.isConnected
          ? findLinkedInCommentEditor(commentAssistTargetArticle)
          : findLinkedInCommentEditor());
    if (!editor) {
      throw new Error("Поле комментария не найдено. Нажмите Comment и повторите.");
    }
    ensureCommentAssistStateForEditor(editor);
    const postText = readCurrentPostTextForAssist(editor);
    if (requestId !== commentAssistRequestId) return;

    setCommentAssistStatus("Нормализую текст поста...");
    scheduleCommentAssistRefresh(0);

    setCommentAssistStatus("Отправляю запрос в MyVOICE...");
    scheduleCommentAssistRefresh(0);
    startCommentAssistStatusTicker(requestId);

    const response = await sendRuntimeMessageSafe({
      type: "MYVOICE_GENERATE_COMMENT_VARIANTS",
      postText,
      author: authorPayload
    });
    if (requestId !== commentAssistRequestId) return;
    stopCommentAssistStatusTicker();

    setCommentAssistStatus("Получаю и проверяю ответ...");
    scheduleCommentAssistRefresh(0);

    if (!response || !response.ok || !response.variants) {
      const msg = response && response.error ? response.error : "Сервер не вернул варианты.";
      throw new Error(msg);
    }

    setCommentAssistStatus("Разбираю варианты комментария...");
    scheduleCommentAssistRefresh(0);

    const variants = {
      short: stripCommentVariantLabel(response.variants.short),
      medium: stripCommentVariantLabel(response.variants.medium),
      long: stripCommentVariantLabel(response.variants.long)
    };
    const available = getAvailableCommentVariants(variants);
    if (!available.length) {
      throw new Error("Получен пустой ответ от генератора.");
    }

    commentAssistState.variants = variants;
    commentAssistState.activeVariant = getDefaultCommentVariantKey(variants);
    if (commentAssistState.activeVariant) {
      setCommentAssistStatus("Финализирую и подставляю лучший вариант...");
      scheduleCommentAssistRefresh(0);
      applyCommentVariant(commentAssistState.activeVariant);
    } else {
      setCommentAssistStatus("Варианты получены, выберите длину комментария.");
    }
  } catch (err) {
    if (requestId !== commentAssistRequestId) return;
    stopCommentAssistStatusTicker();
    const msg = err instanceof Error ? err.message : String(err || "Ошибка генерации.");
    setCommentAssistError(msg);
  } finally {
    stopCommentAssistStatusTicker();
    if (requestId === commentAssistRequestId) {
      commentAssistState.generating = false;
      commentAssistState.generationStartedAt = 0;
      scheduleCommentAssistRefresh(0);
    }
  }
}

function renderCommentAssist(root) {
  if (!root) return;
  root.replaceChildren();

  const card = document.createElement("div");
  card.className = "myvoice-comment-assist__card";

  const top = document.createElement("div");
  top.className = "myvoice-comment-assist__top";

  const brand = document.createElement("div");
  brand.className = "myvoice-comment-assist__brand";

  const logo = document.createElement("span");
  logo.className = "myvoice-comment-assist__logo";
  logo.appendChild(createMyvoiceLogoImage());
  brand.appendChild(logo);

  const brandMeta = document.createElement("div");
  brandMeta.className = "myvoice-comment-assist__brand-meta";

  const title = document.createElement("p");
  title.className = "myvoice-comment-assist__title";
  title.textContent = "MyVOICE's";
  brandMeta.appendChild(title);

  const subtitle = document.createElement("p");
  subtitle.className = "myvoice-comment-assist__subtitle";
  subtitle.textContent = "Помощник по комментариям";
  brandMeta.appendChild(subtitle);

  brand.appendChild(brandMeta);

  top.appendChild(brand);

  const generateBtn = document.createElement("button");
  generateBtn.type = "button";
  generateBtn.className = "myvoice-comment-assist__btn";
  generateBtn.disabled = commentAssistState.generating;
  const hasVariants = Boolean(commentAssistState.variants);
  const generationSeconds = commentAssistState.generationStartedAt
    ? Math.max(1, Math.floor((Date.now() - commentAssistState.generationStartedAt) / 1000))
    : 0;
  generateBtn.textContent = commentAssistState.generating
    ? `Генерация ${generationSeconds} c`
    : hasVariants
      ? "Перегенерировать"
      : "Сгенерировать";
  generateBtn.addEventListener("click", () => {
    generateCommentVariants();
  });
  top.appendChild(generateBtn);

  card.appendChild(top);

  const authorBlock = document.createElement("div");
  authorBlock.className = "myvoice-comment-assist__author";

  const authorHead = document.createElement("div");
  authorHead.className = "myvoice-comment-assist__author-head";

  const authorLabel = document.createElement("label");
  authorLabel.className = "myvoice-comment-assist__author-label";
  authorLabel.setAttribute("for", COMMENT_ASSIST_AUTHOR_SELECT_ID);
  authorLabel.textContent = "Автор комментария";
  authorHead.appendChild(authorLabel);

  const refreshAuthorsBtn = document.createElement("button");
  refreshAuthorsBtn.type = "button";
  refreshAuthorsBtn.className = "myvoice-comment-assist__author-refresh";
  refreshAuthorsBtn.textContent = commentAssistState.authorsLoading ? "Обновляю..." : "Обновить";
  refreshAuthorsBtn.disabled = commentAssistState.generating || commentAssistState.authorsLoading;
  refreshAuthorsBtn.addEventListener("click", () => {
    ensureCommentAssistAuthorsLoaded({ force: true });
  });
  authorHead.appendChild(refreshAuthorsBtn);
  authorBlock.appendChild(authorHead);

  const authorSelect = document.createElement("select");
  authorSelect.id = COMMENT_ASSIST_AUTHOR_SELECT_ID;
  authorSelect.className = "myvoice-comment-assist__author-select";
  const authors = Array.isArray(commentAssistState.authors) ? commentAssistState.authors : [];
  const selectedAuthor = getSelectedCommentAssistAuthor();
  if (commentAssistState.authorsLoading) {
    authorSelect.appendChild(new Option("Загружаю авторов...", ""));
  } else if (authors.length) {
    for (const author of authors) {
      const rolePart = cleanText(author.role) ? ` - ${cleanText(author.role)}` : "";
      authorSelect.appendChild(new Option(`${author.full_name}${rolePart}`, author.key));
    }
    const selectedKey = selectedAuthor ? selectedAuthor.key : authors[0].key;
    authorSelect.value = selectedKey;
    if (cleanText(authorSelect.value) !== selectedKey) {
      authorSelect.value = authors[0].key;
    }
  } else {
    const placeholder = commentAssistState.authorsError
      ? "Не удалось загрузить авторов"
      : "Нет авторов в системе";
    authorSelect.appendChild(new Option(placeholder, ""));
  }

  authorSelect.disabled = commentAssistState.generating || commentAssistState.authorsLoading || !authors.length;
  authorSelect.addEventListener("change", () => {
    const nextKey = cleanText(authorSelect.value);
    commentAssistState.selectedAuthorKey = nextKey;
    writePreferredCommentAuthorKey(nextKey);
    const nextAuthor = getSelectedCommentAssistAuthor();
    if (nextAuthor) {
      commentAssistState.selectedAuthorKey = nextAuthor.key;
      writePreferredCommentAuthorKey(nextAuthor.key);
    }
    scheduleCommentAssistRefresh(0);
  });
  authorBlock.appendChild(authorSelect);

  const authorHint = document.createElement("p");
  authorHint.className = "myvoice-comment-assist__author-hint";
  if (authors.length && selectedAuthor) {
    if (cleanText(selectedAuthor.role)) {
      authorHint.textContent = selectedAuthor.role;
    } else {
      authorHint.textContent = `Пишем от имени: ${selectedAuthor.full_name}`;
    }
  } else if (commentAssistState.authorsLoading) {
    authorHint.textContent = "Получаю список авторов из вашего аккаунта MyVOICE.";
  } else if (commentAssistState.authorsError) {
    authorHint.classList.add("error");
    authorHint.textContent = cleanText(commentAssistState.authorsError);
  } else {
    authorHint.textContent = "Добавьте автора в MyVOICE Settings, чтобы писать комментарии от его лица.";
  }
  authorBlock.appendChild(authorHint);

  card.appendChild(authorBlock);

  if (commentAssistState.variants) {
    const variantsRow = document.createElement("div");
    variantsRow.className = "myvoice-comment-assist__variants";
    for (const key of ["short", "medium", "long"]) {
      const hasText = Boolean(cleanText(commentAssistState.variants[key]));
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "myvoice-comment-assist__variant";
      if (commentAssistState.activeVariant === key) {
        btn.classList.add("active");
      }
      btn.disabled = !hasText;
      btn.textContent = commentVariantLabel(key);
      btn.addEventListener("click", () => {
        applyCommentVariant(key);
        scheduleCommentAssistRefresh(0);
      });
      variantsRow.appendChild(btn);
    }
    card.appendChild(variantsRow);
  }

  const status = document.createElement("div");
  status.className = `myvoice-comment-assist__status${commentAssistState.statusKind ? ` ${commentAssistState.statusKind}` : ""}`;
  status.textContent = commentAssistState.statusText || "Выберите автора и нажмите «Сгенерировать».";
  if (commentAssistState.statusDetails) {
    status.title = commentAssistState.statusDetails;
  }
  card.appendChild(status);

  root.appendChild(card);
}

function refreshCommentAssist() {
  const isPostPage = isLinkedInPostPage(window.location.href);
  let editor = null;
  let feedContainer = null;
  let feedCommentBox = null;
  if (isPostPage) {
    editor = findLinkedInCommentEditor();
  } else {
    // Feed: show the block only when a comment editor is visible (after user clicks Comment / focuses composer).
    // Heal stale targets (LinkedIn React re-renders can replace nodes).
    if ((!commentAssistTargetArticle || !commentAssistTargetArticle.isConnected) && cleanText(commentAssistTargetActivityId)) {
      const healed = findLinkedInPostContainerForActivityId(commentAssistTargetActivityId);
      if (healed) {
        commentAssistTargetArticle = healed;
      }
    }
    if ((!commentAssistTargetCommentBox || !commentAssistTargetCommentBox.isConnected) && commentAssistTargetArticle && commentAssistTargetArticle.isConnected) {
      const foundBox =
        commentAssistTargetArticle.querySelector(".comments-comment-box, [class*='comments-comment-box']") || null;
      if (foundBox instanceof HTMLElement) {
        commentAssistTargetCommentBox = foundBox;
      }
    }

    if (commentAssistTargetCommentBox && commentAssistTargetCommentBox.isConnected) {
      feedCommentBox = commentAssistTargetCommentBox;
      editor = findLinkedInCommentEditor(feedCommentBox) || null;
      if (!commentAssistTargetArticle || !commentAssistTargetArticle.isConnected) {
        const mapped = findLinkedInPostContainerFromNode(feedCommentBox);
        if (mapped) commentAssistTargetArticle = mapped;
      }
    }
    if (commentAssistTargetArticle && commentAssistTargetArticle.isConnected) {
      feedContainer = commentAssistTargetArticle;
      editor = findLinkedInCommentEditor(commentAssistTargetArticle) || null;
    } else {
      // Avoid jumping to a different post immediately after user clicked Comment.
      const recentlyTargeted = Date.now() - commentAssistTargetUpdatedAt < 3500;
      if (!recentlyTargeted) {
        editor = findLinkedInCommentEditor();
        if (editor) {
          setCommentAssistTargetFromNode(editor);
        }
      }
    }
    if (editor && (!commentAssistTargetArticle || !commentAssistTargetArticle.contains(editor))) {
      setCommentAssistTargetFromNode(editor);
    }
    if (!feedContainer && commentAssistTargetArticle && commentAssistTargetArticle.isConnected) {
      feedContainer = commentAssistTargetArticle;
    }

    // If we still don't have a target container, try to use the visible comment box wrapper as an anchor.
    if (!feedContainer) {
      feedCommentBox = findVisibleLinkedInCommentBox();
      if (feedCommentBox) {
        setCommentAssistTargetFromNode(feedCommentBox);
        if (commentAssistTargetArticle && commentAssistTargetArticle.isConnected) {
          feedContainer = commentAssistTargetArticle;
        }
        if (!editor) {
          editor = findLinkedInCommentEditor(feedCommentBox) || null;
        }
      }
    } else if (!editor) {
      // We have a container target; use it to locate the visible comment box wrapper for fallback mounting.
      if (!feedCommentBox) {
        feedCommentBox = findVisibleLinkedInCommentBox(feedContainer);
      }
      if (feedCommentBox) {
        editor = findLinkedInCommentEditor(feedCommentBox) || null;
      }
    }
  }

  // On /feed/ we still render a block even if the editor isn't found yet.
  // We'll mount it near the post's action bar and re-run refresh when the editor appears.
  let mount = null;
  // Feed: if we have a concrete comment box, always mount right above it (even if editor not detected yet).
  if (!isPostPage && feedCommentBox && feedCommentBox.parentElement) {
    mount = { parent: feedCommentBox.parentElement, before: feedCommentBox };
    if (!editor) {
      setCommentAssistStatus("Нажмите в поле комментария, чтобы подставить текст.", "");
    } else {
      ensureCommentAssistStateForEditor(editor);
    }
  } else if (editor) {
    ensureCommentAssistStateForEditor(editor);
    mount = resolveCommentAssistMount(editor);
  } else if (!isPostPage && feedContainer) {
    mount = resolveCommentAssistFallbackMountForFeed(feedContainer);
    setCommentAssistStatus("Нажмите в поле комментария, чтобы подставить текст.", "");
  } else {
    removeCommentAssistRoot();
    return;
  }

  if (!mount || !mount.parent) return;
  const profilePanel = document.getElementById(PROFILE_PANEL_ID);
  if (profilePanel && profilePanel.contains(mount.parent)) {
    removeCommentAssistRoot();
    return;
  }

  upsertCommentAssistStyles();
  let root = document.getElementById(COMMENT_ASSIST_ROOT_ID);
  if (!root) {
    root = document.createElement("div");
    root.id = COMMENT_ASSIST_ROOT_ID;
  }
  const desiredParent = mount.parent;
  const desiredBefore = Object.prototype.hasOwnProperty.call(mount, "before") ? mount.before : null;
  const shouldMove =
    root.parentElement !== desiredParent ||
    (desiredBefore ? root.nextSibling !== desiredBefore : root.nextSibling !== null);
  if (shouldMove) {
    if (desiredBefore) {
      desiredParent.insertBefore(root, desiredBefore);
    } else {
      desiredParent.appendChild(root);
    }
  }
  if (isCommentAssistInteractionActive(root)) {
    return;
  }
  renderCommentAssist(root);
  if (!commentAssistState.authorsLoaded && !commentAssistState.authorsLoading) {
    ensureCommentAssistAuthorsLoaded();
  }
}

function scheduleCommentAssistRefresh(delay = COMMENT_ASSIST_REFRESH_DELAY_MS) {
  if (commentAssistRefreshTimer) window.clearTimeout(commentAssistRefreshTimer);
  commentAssistRefreshTimer = window.setTimeout(() => {
    commentAssistRefreshTimer = null;
    refreshCommentAssist();
  }, delay);
}

function watchLinkedInNavigation() {
  const navigationKeyForUrl = (rawUrl) => {
    const url = String(rawUrl || "").trim();
    if (!url) return "";
    try {
      const parsed = new URL(url);
      if (!isLinkedInHost(parsed.hostname)) return url;
      const normalizedPost = normalizeLinkedInPostUrl(url);
      if (normalizedPost) return normalizedPost;
      parsed.search = "";
      parsed.hash = "";
      return parsed.toString().replace(/\/+$/, "");
    } catch {
      return url;
    }
  };

  const onLocationMaybeChanged = () => {
    const nowUrl = window.location.href;
    const nowKey = navigationKeyForUrl(nowUrl);
    if (nowKey === profilePanelLastUrl) return;
    profilePanelLastUrl = nowKey;
    scheduleProfilePanelRefresh();
    resetCommentAssistState("");
    commentAssistTargetArticle = null;
    commentAssistTargetCommentBox = null;
    commentAssistTargetActivityId = "";
    commentAssistTargetUpdatedAt = 0;
    scheduleCommentAssistRefresh();
  };

  profilePanelLastUrl = navigationKeyForUrl(window.location.href);
  scheduleProfilePanelRefresh(600);
  scheduleCommentAssistRefresh(650);
  window.setInterval(() => {
    onLocationMaybeChanged();
    scheduleCommentAssistRefresh();
  }, 800);
  window.addEventListener("popstate", onLocationMaybeChanged);

  const originalPushState = history.pushState;
  history.pushState = function patchedPushState(...args) {
    const rv = originalPushState.apply(this, args);
    onLocationMaybeChanged();
    return rv;
  };

  const originalReplaceState = history.replaceState;
  history.replaceState = function patchedReplaceState(...args) {
    const rv = originalReplaceState.apply(this, args);
    onLocationMaybeChanged();
    return rv;
  };
}

if (window.top === window.self) {
  profilePanelCollapsed = readCollapsedPreference();
  bindProfilePanelCardOpenHandlers();
  bindCommentAssistFeedTriggers();
  watchLinkedInNavigation();
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!message || !message.type) return;

  if (message.type === "MYVOICE_EXTRACT_POST") {
    try {
      sendResponse(extractFromCurrentPage(message.url));
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err || "Unknown error");
      sendResponse({ ok: false, error: msg });
    }
    return;
  }

  if (message.type === "MYVOICE_EXTRACT_PROFILE_POSTS") {
    extractProfilePostsFromCurrentPage(message)
      .then((payload) => sendResponse(payload))
      .catch((err) => {
        const msg = err instanceof Error ? err.message : String(err || "Unknown error");
        sendResponse({ ok: false, error: msg });
      });
    return true;
  }
});
