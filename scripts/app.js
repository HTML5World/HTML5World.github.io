(() => {
  const cfg = window.H5W_CONFIG || { catalogPath: "games.json" };
  const $ = selector => document.querySelector(selector);
  const state = { games: [], category: "All", query: "", sort: "featured" };
  const els = {
    grid: $("#game-grid"), featured: $("#featured-grid"), count: $("#results-count"),
    empty: $("#empty-state"), error: $("#load-error"), input: $("#search-input"),
    category: $("#category-filter"), sort: $("#sort-filter"), clear: $("#clear-filter")
  };

  $("#year").textContent = new Date().getFullYear();

  const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[char]));

  function safeHttpUrl(value) {
    try {
      const url = new URL(String(value || ""), location.href);
      return ["https:", "http:"].includes(url.protocol) ? url.href : "";
    } catch {
      return "";
    }
  }

  function card(game) {
    const thumbnail = safeHttpUrl(game.thumbnail);
    const destination = safeHttpUrl(game.url);
    const fallback = esc(String(game.name || "H5").slice(0, 2).toUpperCase());
    const image = thumbnail
      ? `<img src="${esc(thumbnail)}" alt="" loading="lazy" onload="this.nextElementSibling.hidden=true" onerror="this.hidden=true;this.nextElementSibling.hidden=false">`
      : "";
    const featuredBadge = game.featured ? '<span class="game-badge">✦ FEATURED</span>' : "";
    const category = esc(game.category || "Arcade");
    const description = esc(game.description || "Play this game free in your browser.");

    if (!destination) return "";
    return `<a class="game-card" href="${esc(destination)}" aria-label="Play ${esc(game.name)}">
      <div class="game-thumb">${image}<span class="thumb-fallback" ${thumbnail ? "hidden" : ""}>${fallback}</span>${featuredBadge}<span class="thumb-play" aria-hidden="true">▶</span></div>
      <div class="game-meta"><div class="game-title-row"><h3>${esc(game.name)}</h3><span class="card-arrow" aria-hidden="true">↗</span></div>
        <p>${description}</p><div class="game-bottom"><span class="game-category">${category}</span><span class="play-link">PLAY NOW</span></div></div>
    </a>`;
  }

  function visibleGames() {
    let list = [...state.games];
    if (state.category !== "All") {
      list = list.filter(game => String(game.category || "Arcade").toLowerCase() === state.category.toLowerCase());
    }
    if (state.query) {
      list = list.filter(game => [game.name, game.description, game.category, ...(game.tags || [])]
        .join(" ").toLowerCase().includes(state.query));
    }
    if (state.sort === "name") list.sort((a, b) => String(a.name).localeCompare(String(b.name)));
    else if (state.sort === "newest") list.sort((a, b) => String(b.updated).localeCompare(String(a.updated)));
    else list.sort((a, b) => Number(Boolean(b.featured)) - Number(Boolean(a.featured)) || String(b.updated).localeCompare(String(a.updated)));
    return list;
  }

  function render() {
    const categories = [...new Set(["Action", "Racing", "Puzzle", "Sports", "Arcade", "Adventure", ...state.games.map(game => game.category || "Arcade")])].sort();
    const selected = els.category.value || state.category;
    els.category.innerHTML = '<option value="All">All categories</option>' + categories
      .map(category => `<option value="${esc(category)}">${esc(category)}</option>`).join("");
    els.category.value = categories.includes(selected) || selected === "All" ? selected : state.category;

    const list = visibleGames();
    const cards = list.map(card).filter(Boolean);
    els.count.textContent = `${cards.length} ${cards.length === 1 ? "game" : "games"} available`;
    els.grid.innerHTML = cards.join("");

    const featured = state.games.filter(game => game.featured).slice(0, 4);
    const picks = (featured.length ? featured : state.games.slice(0, 4)).map(card).filter(Boolean);
    els.featured.innerHTML = picks.join("") || '<div class="loading-card">New games will appear here as they are published.</div>';
    els.empty.hidden = cards.length !== 0;
    els.clear.hidden = !(state.category !== "All" || state.query);
    document.querySelectorAll(".category-tile").forEach(tile => {
      tile.classList.toggle("selected", tile.dataset.category === state.category);
      tile.setAttribute("aria-pressed", String(tile.dataset.category === state.category));
    });
  }

  function showError(message) {
    els.error.hidden = false;
    els.error.textContent = message;
  }

  async function getGames() {
    try {
      const response = await fetch(cfg.catalogPath || "games.json", { cache: "no-store" });
      if (!response.ok) throw new Error(`Could not load the game library (HTTP ${response.status}).`);
      const data = await response.json();
      if (!Array.isArray(data)) throw new Error("The generated game library has an invalid format.");
      state.games = data.filter(game => game && game.name && safeHttpUrl(game.url));
      render();
      if (!state.games.length) {
        showError("No published games were discovered yet. Make sure a public game repository has GitHub Pages enabled and an index.html file in its Pages folder.");
      }
    } catch (error) {
      showError(`${error.message} In the HTML5World portal repository, open Actions and run “Discover games and update library”.`);
    }
  }

  els.input.addEventListener("input", event => {
    state.query = event.target.value.trim().toLowerCase();
    render();
  });
  $("#search-form").addEventListener("submit", event => {
    event.preventDefault();
    $("#all-games").scrollIntoView({ behavior: "smooth" });
  });
  els.category.addEventListener("change", event => {
    state.category = event.target.value;
    render();
  });
  els.sort.addEventListener("change", event => {
    state.sort = event.target.value;
    render();
  });
  $("#category-grid").addEventListener("click", event => {
    const tile = event.target.closest("[data-category]");
    if (!tile) return;
    state.category = state.category === tile.dataset.category ? "All" : tile.dataset.category;
    els.category.value = state.category;
    render();
    $("#all-games").scrollIntoView({ behavior: "smooth" });
  });
  els.clear.addEventListener("click", () => {
    state.category = "All";
    state.query = "";
    els.input.value = "";
    els.category.value = "All";
    render();
  });

  const themeButton = $("#theme-toggle");
  function setTheme(theme) {
    document.body.classList.toggle("light", theme === "light");
    themeButton.textContent = theme === "light" ? "☾" : "☼";
    themeButton.setAttribute("aria-label", theme === "light" ? "Switch to dark theme" : "Switch to light theme");
    try { localStorage.setItem("h5w-theme", theme); } catch { /* Storage can be unavailable in private browsing. */ }
  }
  let savedTheme = "dark";
  try { savedTheme = localStorage.getItem("h5w-theme") || "dark"; } catch { /* Use dark theme by default. */ }
  setTheme(savedTheme === "light" ? "light" : "dark");
  themeButton.addEventListener("click", () => setTheme(document.body.classList.contains("light") ? "dark" : "light"));

  const menuButton = $("#mobile-menu");
  const nav = $("#main-nav");
  menuButton.addEventListener("click", () => {
    const open = nav.classList.toggle("open");
    menuButton.setAttribute("aria-expanded", String(open));
    menuButton.setAttribute("aria-label", open ? "Close navigation" : "Open navigation");
    menuButton.textContent = open ? "×" : "☰";
  });
  nav.querySelectorAll("a").forEach(link => link.addEventListener("click", () => {
    nav.classList.remove("open");
    menuButton.setAttribute("aria-expanded", "false");
    menuButton.setAttribute("aria-label", "Open navigation");
    menuButton.textContent = "☰";
  }));
  document.addEventListener("keydown", event => {
    if (event.key === "/" && !["INPUT", "TEXTAREA"].includes(document.activeElement.tagName)) {
      event.preventDefault();
      els.input.focus();
    }
  });

  getGames();
})();
