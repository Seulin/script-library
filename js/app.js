// 영어 드라마 대본 공부 - 앱 로직 (해시 라우팅)
//   #/                        → 대본 목록 페이지
//   #/episode/<file 확장자 제외> → 대본 보기 페이지
// 데이터는 data/index.json(목록) 과 data/<file>(대본 본문)에서 로드한다.

const els = {
  viewList: document.getElementById("view-list"),
  viewScript: document.getElementById("view-script"),
  episodeGrid: document.getElementById("episode-grid"),
  scriptHeader: document.getElementById("script-header"),
  lines: document.getElementById("lines"),
  episodeNav: document.getElementById("episode-nav"),
};

let dramasCache = null; // index.json 의 dramas 배열 캐시

async function loadJSON(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${path} 불러오기 실패 (${res.status})`);
  return res.json();
}

async function getDramas() {
  if (dramasCache) return dramasCache;
  const index = await loadJSON("data/index.json");
  dramasCache = index.dramas || [];
  return dramasCache;
}

/* ---------- 라우팅 ---------- */

function parseHash() {
  const hash = location.hash.replace(/^#/, "") || "/";
  const m = hash.match(/^\/episode\/(.+)$/);
  if (m) return { name: "script", id: decodeURIComponent(m[1]) };
  return { name: "list" };
}

function showView(name) {
  els.viewList.hidden = name !== "list";
  els.viewScript.hidden = name !== "script";
  window.scrollTo(0, 0);
}

async function router() {
  const route = parseHash();
  if (route.name === "script") {
    await renderScriptPage(route.id);
  } else {
    await renderListPage();
  }
}

/* ---------- 목록 페이지 ---------- */

async function renderListPage() {
  showView("list");
  document.title = "Script Library";
  let dramas;
  try {
    dramas = await getDramas();
  } catch (err) {
    els.episodeGrid.innerHTML = `<p class="loading">목록을 불러오지 못했습니다.<br>로컬 서버로 실행 중인지 확인하세요.</p>`;
    console.error(err);
    return;
  }

  if (dramas.length === 0) {
    els.episodeGrid.innerHTML = `<p class="empty">아직 등록된 대본이 없습니다.</p>`;
    return;
  }

  els.episodeGrid.innerHTML = "";
  dramas.forEach((drama) => {
    const group = document.createElement("section");
    group.className = "drama-group";

    const episodes = drama.episodes || [];
    const cards = episodes
      .map((ep) => {
        const id = ep.file.replace(/\.json$/, "");
        return `
      <a class="episode-card" href="#/episode/${id}">
        <span class="ep-title">${escapeHTML(ep.title)}</span>
      </a>`;
      })
      .join("");

    group.innerHTML = `
      <h2 class="drama-name">${escapeHTML(drama.title)}</h2>
      <div class="episode-cards">${cards || '<p class="empty">에피소드가 없습니다.</p>'}</div>
    `;
    els.episodeGrid.appendChild(group);
  });
}

/* ---------- 대본 보기 페이지 ---------- */

async function renderScriptPage(id) {
  showView("script");
  els.scriptHeader.innerHTML = "";
  els.lines.innerHTML = `<p class="loading">불러오는 중…</p>`;

  let data;
  try {
    data = await loadJSON(`data/${id}.json`);
  } catch (err) {
    els.lines.innerHTML = `<p class="empty">대본을 불러오지 못했습니다.</p>`;
    console.error(err);
    return;
  }

  const sub = [
    data.season != null ? `Season ${data.season}` : null,
    data.episode != null ? `Episode ${data.episode}` : null,
    data.scene ? data.scene : null,
  ]
    .filter(Boolean)
    .join(" · ");

  const credits = [];
  if (data.writtenBy) credits.push(`Written by ${data.writtenBy}`);
  if (data.transcribedBy) credits.push(`Transcribed by ${data.transcribedBy}`);
  const creditsHTML = credits.length
    ? `<div class="script-credits">${credits
        .map((c) => `<div>${escapeHTML(c)}</div>`)
        .join("")}</div>`
    : "";

  const dramaTag = data.drama
    ? `<div class="drama-tag">${escapeHTML(data.drama)}</div>`
    : "";

  els.scriptHeader.innerHTML = `
    ${dramaTag}
    <h2>${escapeHTML(data.title || data.drama || "제목 없음")}</h2>
    <div class="sub">${escapeHTML(sub)}</div>
    ${creditsHTML}
  `;

  document.title = data.title || data.drama || "Script Library";

  els.lines.innerHTML = "";
  let lineNo = 0;
  (data.lines || []).forEach((entry) => {
    const isDialogue = !entry.type || entry.type === "dialogue";
    els.lines.appendChild(renderEntry(entry, isDialogue ? ++lineNo : null));
  });

  if (!data.lines || data.lines.length === 0) {
    els.lines.innerHTML = `<p class="empty">아직 대사가 없습니다.</p>`;
  }

  await updateEpisodeNav(id);
}

// index.json 안에서 현재 에피소드(id)의 앞/뒤 에피소드 id를 찾는다.
async function getEpisodeNeighbors(id) {
  const dramas = await getDramas();
  const toId = (ep) => ep.file.replace(/\.json$/, "");
  for (const drama of dramas) {
    const eps = drama.episodes || [];
    const idx = eps.findIndex((ep) => toId(ep) === id);
    if (idx !== -1) {
      return {
        prev: idx > 0 ? eps[idx - 1] : null,
        next: idx < eps.length - 1 ? eps[idx + 1] : null,
      };
    }
  }
  return { prev: null, next: null };
}

// 하단 플로팅 이동 바의 이전/이후 버튼을 현재 위치에 맞춰 갱신한다.
async function updateEpisodeNav(id) {
  const nav = els.episodeNav;
  if (!nav) return;
  let neighbors = { prev: null, next: null };
  try {
    neighbors = await getEpisodeNeighbors(id);
  } catch (err) {
    console.error(err);
  }
  setNavBtn(nav.querySelector(".epnav-prev"), neighbors.prev);
  setNavBtn(nav.querySelector(".epnav-next"), neighbors.next);
}

// 대상 에피소드가 있으면 링크 활성화(+제목 툴팁), 없으면(경계) 비활성화.
function setNavBtn(el, ep) {
  if (ep) {
    const epId = ep.file.replace(/\.json$/, "");
    el.setAttribute("href", `#/episode/${epId}`);
    el.classList.remove("disabled");
    el.removeAttribute("aria-disabled");
    if (ep.title) el.title = ep.title;
  } else {
    el.removeAttribute("href");
    el.classList.add("disabled");
    el.setAttribute("aria-disabled", "true");
    el.removeAttribute("title");
  }
}

// 항목 유형에 따라 적절한 렌더러로 분기한다. no는 대사 라인 번호.
function renderEntry(entry, no) {
  switch (entry.type) {
    case "scene":
      return renderBlock("scene", entry.text);
    case "section":
      return renderBlock("section", entry.text);
    case "direction":
      return renderBlock("direction", entry.text);
    default:
      return renderLine(entry, no);
  }
}

// 장면·섹션·지침처럼 화자 없는 단일 블록 항목.
function renderBlock(kind, text) {
  const el = document.createElement("div");
  el.className = kind;
  el.innerHTML = renderSegments(text);
  return el;
}


// 값은 문자열(전부 방영) 또는 [{text, unseen?}] 조각 배열(혼합).
// unseen 조각(원 방영본엔 없던 확장본 부분)은 회색으로 연하게 표시한다.
// 영어 대사와 해석 모두 같은 규칙을 따른다.
function renderSegments(value) {
  const parts = Array.isArray(value) ? value : [{ text: value || "" }];
  return parts
    .map((part) => {
      const html = markParens(escapeHTML(part.text || ""));
      return part.unseen ? `<span class="unseen-text">${html}</span>` : html;
    })
    .join("");
}

// 대사 안 인라인 행동 지침 (…) 을 본문과 다르게 표시한다.
// escapeHTML 이후의 안전한 문자열에 적용(괄호는 이스케이프되지 않음).
function markParens(escaped) {
  return escaped.replace(
    /\([^)]*\)/g,
    '<span class="inline-direction">$&</span>'
  );
}

function renderLine(line, no) {
  const row = document.createElement("div");
  row.className = "line";

  const detail = [];
  if (line.korean) {
    detail.push(`<p class="korean">${renderSegments(line.korean)}</p>`);
  }
  if (line.explanation) {
    detail.push(`<p class="explanation">${escapeHTML(line.explanation)}</p>`);
  }
  if (Array.isArray(line.examples) && line.examples.length > 0) {
    const items = line.examples.map((ex) => `<li>${escapeHTML(ex)}</li>`).join("");
    detail.push(`<ul class="examples">${items}</ul>`);
  }

  row.innerHTML = `
    <div class="line-row">
      <button class="line-main" type="button">
        <span class="line-no">${no ?? ""}</span>
        <span class="speaker">${escapeHTML(line.speaker || "")}</span>
        <span class="english">${renderSegments(line.english)}</span>
      </button>
      <button class="line-copy" type="button" aria-label="영어 대사 복사" title="영어 대사 복사">${COPY_ICON}</button>
    </div>
    <div class="line-detail">${detail.join("")}</div>
  `;

  row.querySelector(".line-main").addEventListener("click", () => {
    row.classList.toggle("open");
  });

  const copyBtn = row.querySelector(".line-copy");
  copyBtn.addEventListener("click", () => {
    copyText(englishPlainText(line.english), copyBtn);
  });

  return row;
}

const COPY_ICON = "📋";

// 복사용 영어 대사 평문. 조각 배열이면 이어 붙이고, 무대 지시 (…)는 빼고
// 공백을 정리한다. 지시를 빼면 빈 문자열이 되는 경우(줄 전체가 지시)만 원문 유지.
function englishPlainText(value) {
  const parts = Array.isArray(value) ? value : [{ text: value || "" }];
  const full = parts.map((p) => p.text || "").join("");
  const spoken = full.replace(/\([^)]*\)/g, " ").replace(/\s+/g, " ").trim();
  return spoken || full.replace(/\s+/g, " ").trim();
}

async function copyText(text, btn) {
  if (!text) return;
  let ok = false;
  try {
    await navigator.clipboard.writeText(text);
    ok = true;
  } catch (_) {
    ok = legacyCopy(text);
  }
  if (!ok) return;
  btn.classList.add("copied");
  btn.textContent = "✓";
  clearTimeout(btn._copiedTimer);
  btn._copiedTimer = setTimeout(() => {
    btn.classList.remove("copied");
    btn.textContent = COPY_ICON;
  }, 1100);
}

// clipboard API를 못 쓰는 환경(구형·비보안 컨텍스트)용 대체.
function legacyCopy(text) {
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch (_) {
    return false;
  }
}

function escapeHTML(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/* ---------- 시작 ---------- */

window.addEventListener("hashchange", router);
router();
