(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);

  const loginView = $("login-view");
  const searchView = $("search-view");
  const statusbar = $("statusbar");
  const loginForm = $("login-form");
  const loginError = $("login-error");
  const searchForm = $("search-form");
  const queryInput = $("query-input");
  const searchMeta = $("search-meta");
  const grid = $("results-grid");
  const taskName = $("task-name");
  const userName = $("user-name");
  const logoutBtn = $("logout-btn");

  const lightbox = $("lightbox");
  const lightboxImg = $("lightbox-img");
  const lightboxId = $("lightbox-id");
  const lightboxMeta = $("lightbox-meta");
  const submitBtn = $("submit-btn");
  const closeLightboxBtn = $("close-lightbox-btn");
  const submitResult = $("submit-result");

  const confirmDialog = $("confirm-dialog");
  const confirmYes = $("confirm-yes");
  const confirmNo = $("confirm-no");

  const STORAGE_KEY = "castle5000_last_search";
  const TASK_POLL_MS = 5000;

  let currentImageId = null;
  let taskRunning = false;

  async function api(path, options = {}) {
    const resp = await fetch(path, {
      method: "GET",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      ...options,
    });
    let body = null;
    try {
      body = await resp.json();
    } catch {
      /* no body */
    }
    if (!resp.ok) {
      const message = body && body.message ? body.message : `HTTP ${resp.status}`;
      const code = body && body.code ? body.code : "error";
      const err = new Error(message);
      err.code = code;
      err.status = resp.status;
      throw err;
    }
    return body;
  }

  function showLoggedIn(username) {
    loginView.hidden = true;
    searchView.hidden = false;
    statusbar.hidden = false;
    userName.textContent = username;
  }

  function showLoggedOut() {
    loginView.hidden = false;
    searchView.hidden = true;
    statusbar.hidden = true;
  }

  loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    loginError.hidden = true;
    const username = $("username").value;
    const password = $("password").value;
    try {
      const data = await api("/api/login", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      });
      showLoggedIn(data.username);
      restoreLastSearch();
      pollTask();
    } catch (err) {
      loginError.textContent = err.message || "Đăng nhập thất bại";
      loginError.hidden = false;
    }
  });

  logoutBtn.addEventListener("click", async () => {
    try {
      await api("/api/logout", { method: "POST" });
    } catch {
      /* ignore */
    }
    showLoggedOut();
  });

  function renderResults(results) {
    grid.innerHTML = "";
    for (const r of results) {
      const tile = document.createElement("div");
      tile.className = "thumb";

      const img = document.createElement("img");
      img.src = r.thumb;
      img.loading = "lazy";
      img.dataset.id = r.id;
      img.title = `${r.id} (score ${r.score.toFixed(3)})`;
      img.addEventListener("click", () => openLightbox(r.id));

      const label = document.createElement("span");
      label.className = "thumb-id";
      label.textContent = r.id;

      tile.appendChild(img);
      tile.appendChild(label);
      grid.appendChild(tile);
    }
  }

  function saveLastSearch(query, results) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ query, results }));
    } catch {
      /* storage may be unavailable; non-critical */
    }
  }

  function restoreLastSearch() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      const { query, results } = JSON.parse(raw);
      queryInput.value = query || "";
      if (Array.isArray(results) && results.length) {
        renderResults(results);
        searchMeta.textContent = `${results.length} kết quả (đã lưu từ lần tìm trước)`;
      }
    } catch {
      /* ignore corrupt/missing storage */
    }
  }

  searchForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const query = queryInput.value.trim();
    if (!query) return;
    searchMeta.textContent = "Đang tìm...";
    try {
      const data = await api("/api/search", {
        method: "POST",
        body: JSON.stringify({ query, k: 50 }),
      });
      renderResults(data.results);
      searchMeta.textContent = `${data.results.length} kết quả, ${data.took_ms}ms`;
      saveLastSearch(query, data.results);
    } catch (err) {
      if (err.status === 401) {
        showLoggedOut();
        return;
      }
      searchMeta.textContent = `Lỗi: ${err.message}`;
    }
  });

  function openLightbox(id) {
    currentImageId = id;
    lightboxImg.src = `/images/${id}`;
    lightboxImg.alt = id;
    submitResult.textContent = "";
    lightboxId.textContent = id;
    lightboxMeta.innerHTML = "";
    lightbox.hidden = false;
    loadMetadata(id);
  }

  async function loadMetadata(id) {
    try {
      const meta = await api(`/api/metadata/${encodeURIComponent(id)}`);
      if (currentImageId !== id) return;
      lightboxMeta.innerHTML = `
        <p><strong>Lớp đối tượng:</strong> ${meta.classes
          .map((c) => `${escapeHtml(c)} (${meta.class_count[c] ?? 0})`)
          .join(", ")}</p>
        <p><strong>Mô tả:</strong> ${escapeHtml(meta.description)}</p>
      `;
    } catch {
      if (currentImageId === id) lightboxMeta.innerHTML = "";
    }
  }

  function escapeHtml(s) {
    return s
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  closeLightboxBtn.addEventListener("click", () => {
    lightbox.hidden = true;
    currentImageId = null;
  });

  submitBtn.addEventListener("click", () => {
    if (!currentImageId) return;
    confirmDialog.hidden = false;
  });

  confirmNo.addEventListener("click", () => {
    confirmDialog.hidden = true;
  });

  confirmYes.addEventListener("click", async () => {
    confirmDialog.hidden = true;
    if (!currentImageId) return;
    const id = currentImageId;
    submitResult.textContent = "Đang gửi...";
    try {
      const data = await api("/api/submit", {
        method: "POST",
        body: JSON.stringify({ id }),
      });
      submitResult.textContent = `Kết quả: ${verdictLabel(data.verdict)} (${data.message || ""})`;
      const thumb = grid.querySelector(`img[data-id="${cssEscape(id)}"]`);
      if (thumb) thumb.classList.add("submitted");
    } catch (err) {
      if (err.status === 401) {
        submitResult.textContent = "Phiên đã hết hạn, vui lòng đăng nhập lại.";
        setTimeout(() => {
          lightbox.hidden = true;
          showLoggedOut();
        }, 1500);
        return;
      }
      submitResult.textContent = `Lỗi: ${err.message}`;
    }
  });

  function verdictLabel(v) {
    return (
      { correct: "ĐÚNG", wrong: "SAI", pending: "ĐANG CHỜ CHẤM", rejected: "BỊ TỪ CHỐI", error: "LỖI" }[v] || v
    );
  }

  function cssEscape(s) {
    return s.replace(/["\\]/g, "\\$&");
  }

  async function pollTask() {
    try {
      const task = await api("/api/task");
      taskRunning = task.running;
      if (!task.running) {
        taskName.textContent = "Chưa có task đang chạy";
      } else {
        taskName.textContent = `${task.name} (${task.task_group || ""})`;
      }
      setSearchEnabled(task.running);
    } catch (err) {
      if (err.status === 401) {
        showLoggedOut();
        return;
      }
      // DRES unreachable or no evaluation configured: fail soft, keep retrying.
      taskName.textContent = "Không lấy được thông tin task";
    } finally {
      setTimeout(pollTask, TASK_POLL_MS);
    }
  }

  function setSearchEnabled(enabled) {
    queryInput.disabled = !enabled;
    searchForm.querySelector("button").disabled = !enabled;
    if (!enabled) {
      searchMeta.textContent = "Chưa có task đang chạy";
    }
  }

  // If DRES has no evaluation configured at all (dev/local mode), don't
  // permanently lock the UI -- /api/task returns running:false, which still
  // lets setSearchEnabled(false) show an explanatory message rather than
  // crashing. Students only ever see this once a real evaluation starts.

  (async function init() {
    try {
      const me = await api("/api/me");
      showLoggedIn(me.username);
      restoreLastSearch();
      pollTask();
    } catch {
      showLoggedOut();
    }
  })();
})();
