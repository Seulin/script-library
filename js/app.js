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
  toggleAll: document.getElementById("toggle-all"),
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

  els.scriptHeader.innerHTML = `
    <h2>${escapeHTML(data.drama || "제목 없음")}</h2>
    <div class="sub">${escapeHTML(sub)}</div>
  `;

  els.lines.innerHTML = "";
  let lineNo = 0;
  (data.lines || []).forEach((entry) => {
    const isDialogue = !entry.type || entry.type === "dialogue";
    els.lines.appendChild(renderEntry(entry, isDialogue ? ++lineNo : null));
  });

  if (!data.lines || data.lines.length === 0) {
    els.lines.innerHTML = `<p class="empty">아직 대사가 없습니다.</p>`;
  }

  // 새 대본을 열 때는 항상 '해석 숨김' 상태로 초기화
  setAllDetails(false);
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

// 전체 대사의 디테일(해석·설명·뉘앙스·예문)을 일괄로 펼치거나 접는다.
function setAllDetails(open) {
  els.lines.querySelectorAll(".line").forEach((row) => {
    row.classList.toggle("open", open);
  });
  els.toggleAll.setAttribute("aria-pressed", String(open));
  els.toggleAll.textContent = open ? "해석 숨기기" : "해석 보기";
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
  if (line.nuance) {
    detail.push(`<p class="nuance">${escapeHTML(line.nuance)}</p>`);
  }
  if (Array.isArray(line.examples) && line.examples.length > 0) {
    const items = line.examples.map((ex) => `<li>${escapeHTML(ex)}</li>`).join("");
    detail.push(`<ul class="examples">${items}</ul>`);
  }

  row.innerHTML = `
    <button class="line-main" type="button">
      <span class="line-no">${no ?? ""}</span>
      <span class="speaker">${escapeHTML(line.speaker || "")}</span>
      <span class="english">${renderSegments(line.english)}</span>
    </button>
    <div class="line-detail">${detail.join("")}</div>
  `;

  row.querySelector(".line-main").addEventListener("click", () => {
    row.classList.toggle("open");
  });

  return row;
}

function escapeHTML(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/* ---------- 시작 ---------- */

els.toggleAll.addEventListener("click", () => {
  const open = els.toggleAll.getAttribute("aria-pressed") === "true";
  setAllDetails(!open);
});

window.addEventListener("hashchange", router);
router();
