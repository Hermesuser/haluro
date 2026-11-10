/**
 * Haluro — Laboratorio Analógico Digital (v2.4.3)
 * Precision frontend controller: 72-stock film simulation, C-41/B&W optical negative
 * inversion (RA-4, ECP 2383, Minilab, V-Log), B&W chemical toners & fine-art papers,
 * unified multi-frame Roll Analysis, 3-Way CMY split-toning, color-protected soft clip,
 * luminance optical sharpening, 16-bit TIFF export, and native Analog EXIF stamping.
 */

const FAVORITES_KEY = "haluro_favorites_v2";
const ANALOG_EXIF_STORAGE_KEY = "haluro_analog_exif_v23";

function loadAnalogExifStorage() {
  try {
    const raw = localStorage.getItem(ANALOG_EXIF_STORAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch (_) {
    return {};
  }
}

function saveAnalogExifStorage(metaObj) {
  try {
    localStorage.setItem(ANALOG_EXIF_STORAGE_KEY, JSON.stringify(metaObj || {}));
  } catch (_) {
    // Ignore storage quota errors
  }
}

function detectInitialPlatform() {
  const ua = (navigator.userAgent || "").toLowerCase();
  if (ua.includes("win")) return "windows";
  if (ua.includes("mac")) return "macos";
  return "linux";
}

function loadFavorites() {
  try {
    const raw = localStorage.getItem(FAVORITES_KEY);
    return new Set(raw ? JSON.parse(raw) : ["portra400", "gold200", "cinestill800t", "hp5", "velvia50"]);
  } catch (_) {
    return new Set(["portra400", "gold200", "cinestill800t", "hp5"]);
  }
}

function saveFavorites(favSet) {
  try {
    localStorage.setItem(FAVORITES_KEY, JSON.stringify([...favSet]));
  } catch (_) {
    // Ignore storage quota errors
  }
}

const state = {
  platform: detectInitialPlatform(), // 'macos' | 'windows' | 'linux'
  appMode: "simulation", // 'simulation' | 'negative'
  films: [],
  filteredFilms: [],
  favorites: loadFavorites(),
  selectedFilm: "portra400",
  category: "all",
  search: "",

  frames: [], // { filename, name, is_raw, thumb_url }
  activeFrameIndex: 0,

  // Mode 1: Film Simulation controls
  ev: 0.0,
  halation: 1.0,
  grain: 1.0,
  vignette: 1.0,
  date: false,

  // Shared non-destructive geometry & export
  rotate: 0, // 0 | 90 | 180 | 270
  flip_h: false,
  outputFormat: "jpg", // 'jpg' | 'png' | 'tiff'

  // Viewport & Light Table
  viewMode: "split", // 'split' | 'full' | 'original' | 'sheet'
  prevViewMode: "split",
  holdingOriginal: false,
  splitPercent: 50,
  zoom: 1.0,
  panX: 0,
  panY: 0,
  safelight: false,

  // Cache tracker so we don't re-request original base64 on every slider tick
  lastOriginalKey: "",
  lastRollResult: null,
  contactSheetCache: null,
  copiedRecipe: null,
  analogMeta: loadAnalogExifStorage(),
  updateInfo: null,
};

const negativeState = {
  filmType: "color", // 'color' | 'bw'
  scanSource: "camera_raw", // 'camera_raw' | 'scanner_raw' | 'flatbed_tiff'
  preSaturation: 1.0,
  lightSource: "standard", // 'standard' | 'cool' | 'warm'
  colorMethod: "dynamic", // 'dynamic' | 'shadow_weighted' | 'roll_locked'
  rollBounds: null, // { d_min: [r,g,b], d_max: [r,g,b] } | null
  rollFramesCount: 0,
  toneVariant: "standard", // 'soft' | 'standard' | 'vivid' | 'highlight_soft' | 'shadow_soft'
  printFinish: "none",
  finishAmount: 1.0,
  bwToner: "neutral",
  bwTonerStrength: 1.0,
  profile: "frontier",
  baseColor: null, // [r_lin, g_lin, b_lin] or null (auto)
  baseHex: "#E45F21",
  eyedropperActive: false,
  eyedropperMode: null, // null | 'base' | 'scene_wb'

  borderBuffer: 0.06,
  cropPct: 0.0,

  brightness: 0.0,
  midtoneNd: 0.0,
  contrast: 0.0,
  pushPull: 0.0,
  lights: 0.0,
  darks: 0.0,
  whites: 0.0,
  blacks: 0.0,
  blackClip: 0.0,
  whiteClip: 0.0,
  clipProtect: true,
  inkyBlacks: 0.0,
  rpTone: 0.0,
  saturation: 1.0,

  activeCmyZone: "global", // 'global' | 'shadows' | 'mids' | 'highs'
  cmy: [0.0, 0.0, 0.0], // Global [Cyan-Red, Magenta-Green, Yellow-Blue]
  shadowsTint: [0.0, 0.0, 0.0],
  midsTint: [0.0, 0.0, 0.0],
  highsTint: [0.0, 0.0, 0.0],
  shadowsRange: 0.5,
  highsRange: 0.5,
  temp: 0.0,
  tint: 0.0,
  warming85: 0.0,
  skylightFilter: 0.0,
  shadeFilter: 0.0,
  sharpenMode: "off", // 'off' | 'lab' | 'scanner'
  sharpenAmount: 1.0,
  glow: 1.0,
  fade: 1.0,
};

const PROFILE_LABELS = {
  ra4_paper: "Papel Cuarto Oscuro RA-4",
  cine_ecp: "Copia de Cine ECP 2383",
  frontier: "Fuji Frontier SP-3000",
  noritsu: "Noritsu HS-1800",
  pakon: "Pakon F135 Plus",
  vlog_flat: "Logarítmico Latitud (V-Log)",
  linear: "Lineal Plano",
  bw: "Gelatina de Plata B&N",
};

const BW_TONER_LABELS = {
  neutral: "Plata Neutra",
  selenium_1: "Selenio #1",
  selenium_2: "Selenio #2",
  selenium_3: "Selenio #3",
  palladium: "Platino / Paladio",
  sepia_sulfide: "Sepia Sulfuro",
  copper_iron: "Cobre y Hierro",
  warmtone_foma: "Clorobromuro Cálido",
  cooltone: "Bromuro Frío",
  cotton_matte: "Algodón Mate Museo",
};

const BW_TONER_DESCS = {
  neutral: "Copia baritada clásica de plata pura (R=G=B) sin virado químico.",
  selenium_1: " Mayor D-max en negros y sombra fría sutil de archivo de galería.",
  selenium_2: "Negros profundos berenjena-plateados sobre luces de papel limpio.",
  selenium_3: "Virado intenso de exposición con sombra ciruela y alto microcontraste.",
  palladium: "Estética artesanal en contacto: medios tonos cálidos aterciopelados.",
  sepia_sulfide: "Virado clásico al sulfuro marrón chocolate con conservación cálida.",
  copper_iron: "Split-toning químico: sombras azul de Prusia y medios tonos terracota.",
  warmtone_foma: "Emulsión cálida de clorobromuro sobre base marfil cremosa.",
  cooltone: "Tonalidad metálica azul-negra sobre papel blanco óptico brillante.",
  cotton_matte: "Papel 100% algodón sin blanqueadores ópticos y negro mate suave.",
};

let debounceTimer = null;
let previewAbortController = null;
let offscreenHistCanvas = null;
let offscreenLoupeCanvas = null;
let loupeSourceReady = false;

// =============================================================
// COLOR SCIENCE HELPERS (Linear -> sRGB IEC 61966-2-1)
// =============================================================

function linearChannelToSrgbByte(v) {
  const c = Math.max(0, Math.min(1, Number(v) || 0));
  const s = c <= 0.0031308 ? c * 12.92 : 1.055 * Math.pow(c, 1 / 2.4) - 0.055;
  return Math.max(0, Math.min(255, Math.round(s * 255)));
}

function linearRgbToHexClient(rgb) {
  if (!Array.isArray(rgb) || rgb.length < 3) return "#E45F21";
  const maxVal = Math.max(rgb[0], rgb[1], rgb[2]);
  // Handle normalized [0..1] linear floats vs legacy [0..255]
  const bytes =
    maxVal > 1.5
      ? rgb.slice(0, 3).map((x) => Math.max(0, Math.min(255, Math.round(x))))
      : rgb.slice(0, 3).map(linearChannelToSrgbByte);
  return (
    "#" +
    bytes
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("")
      .toUpperCase()
  );
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str == null ? "" : String(str);
  return div.innerHTML;
}

// =============================================================
// INITIALIZATION
// =============================================================

function getOsCopy() {
  if (state.platform === "windows") {
    return {
      fileManager: "Explorador de archivos",
      fileManagerShort: "Explorador",
      revealCta: "Mostrar en Explorador",
      inFileManager: "En Explorador",
      deviceName: "Windows 11",
      saveKbd: "Ctrl + S",
      saveAsKbd: "Ctrl + Shift + S",
      openKbd: "Ctrl + O",
      copyRecipeKbd: "Ctrl+Shift+C",
      pasteRecipeKbd: "Ctrl+Shift+V",
      copyPasteKbd: "Ctrl + Shift + C / V",
      downloadsPrefix: "Descargas\\",
    };
  }
  if (state.platform === "linux") {
    return {
      fileManager: "Gestor de archivos",
      fileManagerShort: "Archivos",
      revealCta: "Mostrar en carpeta",
      inFileManager: "En carpeta",
      deviceName: "tu equipo",
      saveKbd: "Ctrl + S",
      saveAsKbd: "Ctrl + Shift + S",
      openKbd: "Ctrl + O",
      copyRecipeKbd: "Ctrl+Shift+C",
      pasteRecipeKbd: "Ctrl+Shift+V",
      copyPasteKbd: "Ctrl + Shift + C / V",
      downloadsPrefix: "~/Downloads/",
    };
  }
  return {
    fileManager: "Finder",
    fileManagerShort: "Finder",
    revealCta: "Mostrar en Finder",
    inFileManager: "En Finder",
    deviceName: "tu Mac",
    saveKbd: "⌘ S",
    saveAsKbd: "⇧ ⌘ S",
    openKbd: "⌘ O",
    copyRecipeKbd: "⇧⌘C",
    pasteRecipeKbd: "⇧⌘V",
    copyPasteKbd: "⇧ ⌘ C / V",
    downloadsPrefix: "~/Downloads/",
  };
}

function applyPlatformUI() {
  const copy = getOsCopy();
  document.body.dataset.platform = state.platform;

  const uploadLbl = document.getElementById("uploadBtnLabel");
  if (uploadLbl) uploadLbl.title = `Importar archivos desde ${copy.deviceName} (${copy.openKbd})`;

  const saveBtn = document.getElementById("saveDownloadsBtn");
  if (saveBtn) saveBtn.title = `Guardar a resolución completa en Descargas (${copy.saveKbd})`;

  const saveAsBtn = document.getElementById("saveAsBtn");
  if (saveAsBtn) saveAsBtn.title = `Elegir carpeta y nombre con diálogo nativo (${copy.saveAsKbd})`;

  const openFolderBtn = document.getElementById("openFolderBtn");
  if (openFolderBtn) {
    openFolderBtn.textContent = `Abrir carpeta interna de revelados en ${copy.fileManagerShort}`;
  }

  const modalZipBtn = document.getElementById("modalSaveZipBtn");
  if (modalZipBtn) {
    modalZipBtn.textContent = `Guardar archivo ZIP en Descargas y mostrar en ${copy.fileManagerShort}`;
  }

  const historyCopy = document.getElementById("historyHelperCopy");
  if (historyCopy) {
    historyCopy.textContent =
      `Tus archivos RAW y negativos originales jamás se modifican. Puedes localizar cualquier copia en ${copy.fileManager} o restaurar su receta exacta en el laboratorio:`;
  }

  const kbdSave = document.getElementById("kbdSave");
  const kbdSaveAs = document.getElementById("kbdSaveAs");
  const kbdOpen = document.getElementById("kbdOpen");
  const kbdCopyPaste = document.getElementById("kbdCopyPaste");
  if (kbdSave) kbdSave.textContent = copy.saveKbd;
  if (kbdSaveAs) kbdSaveAs.textContent = copy.saveAsKbd;
  if (kbdOpen) kbdOpen.textContent = copy.openKbd;
  if (kbdCopyPaste) kbdCopyPaste.textContent = copy.copyPasteKbd;

  const copyBtn = document.getElementById("copyRecipeBtn");
  const pasteBtn = document.getElementById("pasteRecipeBtn");
  if (copyBtn) copyBtn.title = `Copiar receta óptica del fotograma activo (${copy.copyRecipeKbd})`;
  if (pasteBtn) pasteBtn.title = `Pegar receta copiada en este fotograma (${copy.pasteRecipeKbd})`;
}

async function syncRuntimePlatform() {
  try {
    const res = await fetch("/api/health");
    if (!res.ok) return;
    const data = await res.json();
    if (data && data.platform && data.platform !== state.platform) {
      state.platform = data.platform;
      applyPlatformUI();
      renderFilmStrip();
    }
  } catch (_) {
    // Non-fatal; client UA fallback remains active
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  applyPlatformUI();
  initAnalogExifControls();
  initUIListeners();
  syncNegProcessPanels();
  selectCmyZone("global");
  initSplitSlider();
  initZoomAndPan();
  initEyedropperViewport();
  initDragAndDrop();
  initDoubleClickReset();
  initKeyboardShortcuts();

  syncRuntimePlatform();
  await fetchFilms();
  await loadSamplePhoto(false);

  // Smart update checker: silently query remote version manifest after 2.5s
  setTimeout(() => {
    checkForUpdates(false);
  }, 2500);
});

async function fetchFilms() {
  try {
    const res = await fetch("/api/films");
    const data = await res.json();
    state.films = data.films || [];
    applyFilters();
  } catch (err) {
    console.error("Error cargando catálogo de películas:", err);
    showToast("Error de catálogo", "No se pudo cargar la lista de películas.");
  }
}

// =============================================================
// LEFT SIDEBAR: 72 FILM STOCKS & FAVORITES
// =============================================================

function applyFilters() {
  const q = state.search.toLowerCase().trim();
  state.filteredFilms = state.films.filter((f) => {
    const matchesCat =
      state.category === "all" ||
      (state.category === "fav" ? state.favorites.has(f.key) : f.kind === state.category);
    const matchesSearch =
      !q ||
      f.name.toLowerCase().includes(q) ||
      f.brand.toLowerCase().includes(q) ||
      f.key.toLowerCase().includes(q) ||
      (f.desc && f.desc.toLowerCase().includes(q));
    return matchesCat && matchesSearch;
  });

  const badge = document.getElementById("filmCountBadge");
  if (badge) badge.textContent = String(state.filteredFilms.length);

  renderFilmShelf();
}

function renderFilmShelf() {
  const container = document.getElementById("filmList");
  if (!container) return;
  container.innerHTML = "";

  if (state.filteredFilms.length === 0) {
    const empty = document.createElement("div");
    empty.className = "film-empty";
    empty.textContent =
      state.category === "fav"
        ? "Aún no tienes películas marcadas con ★ Favoritas."
        : "Ninguna película coincide con tu búsqueda.";
    container.appendChild(empty);
    return;
  }

  const frag = document.createDocumentFragment();
  state.filteredFilms.forEach((film) => {
    const isFav = state.favorites.has(film.key);
    const card = document.createElement("div");
    card.className = `film-card ${film.key === state.selectedFilm ? "selected" : ""}`;
    card.dataset.key = film.key;
    card.dataset.kind = film.kind || "neg";
    card.setAttribute("role", "option");
    card.setAttribute("tabindex", "0");
    card.setAttribute("aria-selected", film.key === state.selectedFilm ? "true" : "false");

    const header = document.createElement("div");
    header.className = "film-card-header";

    const title = document.createElement("span");
    title.className = "film-title";
    title.textContent = film.name;

    const badges = document.createElement("div");
    badges.className = "film-badges-right";

    const iso = document.createElement("span");
    iso.className = "film-iso";
    iso.textContent = `ISO ${film.iso}`;

    const favBtn = document.createElement("button");
    favBtn.type = "button";
    favBtn.className = `fav-btn ${isFav ? "is-fav" : ""}`;
    favBtn.title = isFav ? "Quitar de favoritas" : "Añadir a favoritas";
    favBtn.setAttribute("aria-label", favBtn.title);
    favBtn.textContent = isFav ? "★" : "☆";
    favBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      toggleFavoriteFilm(film.key);
    });

    badges.appendChild(iso);
    badges.appendChild(favBtn);
    header.appendChild(title);
    header.appendChild(badges);

    const meta = document.createElement("div");
    meta.className = "film-card-meta";
    meta.textContent = film.desc ? `${film.category} · ${film.desc}` : film.category;

    card.appendChild(header);
    card.appendChild(meta);

    card.addEventListener("click", () => selectFilm(film.key));
    card.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        selectFilm(film.key);
      }
    });

    frag.appendChild(card);
  });

  container.appendChild(frag);
}

function toggleFavoriteFilm(filmKey) {
  if (state.favorites.has(filmKey)) {
    state.favorites.delete(filmKey);
  } else {
    state.favorites.add(filmKey);
  }
  saveFavorites(state.favorites);
  applyFilters();
}

function selectFilm(key) {
  state.selectedFilm = key;
  document.querySelectorAll(".film-card").forEach((el) => {
    const sel = el.dataset.key === key;
    el.classList.toggle("selected", sel);
    el.setAttribute("aria-selected", sel ? "true" : "false");
  });
  saveActiveFrameRecipe();
  updateActiveRecipeBanner();
  requestPreview();
}

// =============================================================
// SAMPLE LOADING, FILE IMPORT & 35MM FILM STRIP
// =============================================================

async function loadSamplePhoto(forceNegative = false) {
  const useNeg = forceNegative || state.appMode === "negative";
  if (useNeg) {
    return loadNegativeSample();
  }
  showLoading(true, "Cargando muestra Canon RAW de 16 bits…");
  try {
    const res = await fetch("/api/load_sample", { method: "POST" });
    const data = await res.json();
    if (data.filename) {
      const existingIdx = state.frames.findIndex((f) => f.filename === data.filename);
      const entry = {
        filename: data.filename,
        name: data.name || data.filename,
        is_raw: true,
        thumb_url: data.thumb_url || `/api/thumbnail/${encodeURIComponent(data.filename)}`,
      };
      if (existingIdx >= 0) {
        state.frames[existingIdx] = entry;
        state.activeFrameIndex = existingIdx;
      } else {
        state.frames.push(entry);
        state.activeFrameIndex = state.frames.length - 1;
      }
      state.lastOriginalKey = "";
      renderFilmStrip();
      await requestPreview(true);
    }
  } catch (err) {
    console.error("Error cargando muestra RAW:", err);
    showToast("Error", "No se pudo cargar la muestra RAW.");
  } finally {
    showLoading(false);
  }
}

async function loadNegativeSample() {
  showLoading(true, "Cargando escaneo de negativo C-41 de prueba…");
  try {
    const res = await fetch("/api/negative/load_sample", { method: "POST" });
    const data = await res.json();
    if (data.filename) {
      const existingIdx = state.frames.findIndex((f) => f.filename === data.filename);
      const entry = {
        filename: data.filename,
        name: data.name || data.filename,
        is_raw: false,
        thumb_url: data.thumb_url || `/api/thumbnail/${encodeURIComponent(data.filename)}`,
      };
      if (existingIdx >= 0) {
        state.frames[existingIdx] = entry;
        state.activeFrameIndex = existingIdx;
      } else {
        state.frames.push(entry);
        state.activeFrameIndex = state.frames.length - 1;
      }
      state.lastOriginalKey = "";
      renderFilmStrip();
      await autoDetectBaseColor(false);
      await requestPreview(true);
    }
  } catch (err) {
    console.error("Error cargando negativo de muestra:", err);
    showToast("Error", "No se pudo cargar el negativo de prueba.");
  } finally {
    showLoading(false);
  }
}

async function importFiles(fileList) {
  const files = Array.from(fileList || []);
  if (!files.length) return;

  showLoading(true, `Importando ${files.length} fotograma(s) al laboratorio…`);
  let importedCount = 0;

  try {
    for (const file of files) {
      const formData = new FormData();
      formData.append("file", file);
      const res = await fetch("/api/upload", { method: "POST", body: formData });
      const data = await res.json();
      if (res.ok && data.filename) {
        const entry = {
          filename: data.filename,
          name: data.name || file.name,
          is_raw: Boolean(data.is_raw),
          thumb_url:
            data.thumb_url || `/api/thumbnail/${encodeURIComponent(data.filename)}?t=${Date.now()}`,
        };
        const existingIdx = state.frames.findIndex((f) => f.filename === data.filename);
        if (existingIdx >= 0) {
          state.frames[existingIdx] = entry;
          state.activeFrameIndex = existingIdx;
        } else {
          state.frames.push(entry);
          state.activeFrameIndex = state.frames.length - 1;
        }
        importedCount += 1;
      }
    }

    if (importedCount > 0) {
      state.lastOriginalKey = "";
      resetZoom();
      renderFilmStrip();
      if (state.appMode === "negative") {
        await autoDetectBaseColor(false);
      }
      await requestPreview(true);
      showToast(
        "Importación completada",
        `${importedCount} fotograma(s) listos en la mesa de luz (original intacto).`
      );
    }
  } catch (err) {
    console.error("Error importando archivos:", err);
    showToast("Error de importación", "Verifica que el formato del archivo sea compatible.");
  } finally {
    showLoading(false);
  }
}

function renderFilmStrip() {
  const strip = document.getElementById("stripFrames");
  if (!strip) return;
  strip.innerHTML = "";

  state.frames.forEach((frame, idx) => {
    const thumb = document.createElement("div");
    thumb.className = `film-frame-thumb ${idx === state.activeFrameIndex ? "active" : ""}`;
    thumb.title = `${frame.name} (Fotograma #${idx + 1})`;
    thumb.setAttribute("tabindex", "0");

    const img = document.createElement("img");
    img.src = frame.thumb_url || `/api/thumbnail/${encodeURIComponent(frame.filename)}`;
    img.alt = frame.name;
    img.loading = "lazy";

    const badge = document.createElement("div");
    badge.className = "frame-number-badge";
    const numSpan = document.createElement("span");
    numSpan.textContent = `${String(idx + 1).padStart(2, "0")}A`;
    const typeSpan = document.createElement("span");
    typeSpan.textContent = frame.is_raw ? "RAW" : "SCAN";
    badge.appendChild(numSpan);
    badge.appendChild(typeSpan);

    thumb.appendChild(img);
    thumb.appendChild(badge);

    const activate = async () => {
      if (state.activeFrameIndex === idx && state.viewMode !== "sheet") return;
      saveActiveFrameRecipe();
      state.activeFrameIndex = idx;
      state.lastOriginalKey = "";
      const hadRecipe = loadFrameRecipe(idx);
      renderFilmStrip();
      if (state.viewMode === "sheet") setViewMode("split");
      if (state.appMode === "negative" && (!hadRecipe || negativeState.baseColor === null)) {
        await autoDetectBaseColor(false);
      }
      saveActiveFrameRecipe();
      requestPreview(true);
    };

    thumb.addEventListener("click", activate);
    thumb.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        activate();
      }
    });

    strip.appendChild(thumb);
  });

  // Quick "+ Añadir" frame button at end of filmstrip
  const addBtn = document.createElement("button");
  addBtn.type = "button";
  addBtn.className = "film-frame-add";
  addBtn.title = `Importar más fotogramas al rollo (${getOsCopy().openKbd})`;
  addBtn.innerHTML = `<span style="font-size:15px;line-height:1;">+</span><span>Añadir</span>`;
  addBtn.addEventListener("click", () => {
    document.getElementById("fileInput")?.click();
  });
  strip.appendChild(addBtn);
}

// =============================================================
// MODE SWITCHING (SIMULATION <-> NEGATIVE LAB)
// =============================================================

async function switchStudioMode(mode) {
  if (mode !== "simulation" && mode !== "negative") return;
  state.appMode = mode;

  if (negativeState.eyedropperActive) {
    setEyedropperActive(false);
  }

  const isNeg = mode === "negative";
  const tabSim = document.getElementById("tabDarkroomsMode");
  const tabNeg = document.getElementById("tabNegativeMode");
  tabSim?.classList.toggle("active", !isNeg);
  tabSim?.setAttribute("aria-selected", !isNeg ? "true" : "false");
  tabNeg?.classList.toggle("active", isNeg);
  tabNeg?.setAttribute("aria-selected", isNeg ? "true" : "false");

  const shelfPane = document.getElementById("shelfContainer");
  const negLeftPane = document.getElementById("negativeLabContainer");
  const simRight = document.getElementById("simInspectorControls");
  const negRight = document.getElementById("negInspectorControls");

  if (shelfPane) shelfPane.style.display = isNeg ? "none" : "flex";
  if (negLeftPane) negLeftPane.style.display = isNeg ? "flex" : "none";
  if (simRight) simRight.style.display = isNeg ? "none" : "block";
  if (negRight) negRight.style.display = isNeg ? "block" : "none";

  const sampleLabel = document.getElementById("loadSampleLabel");
  if (sampleLabel) {
    sampleLabel.textContent = isNeg ? "Muestra negativo" : "Cargar muestra RAW";
  }

  const origLabel = document.getElementById("originalLabel");
  if (origLabel) {
    origLabel.textContent = isNeg ? "Negativo escaneado" : "Original";
  }

  updateActiveRecipeBanner();

  // If switching to Negative mode and only SAMPLE.CR2 is loaded, load sample negative automatically
  const activeFrame = state.frames[state.activeFrameIndex];
  if (isNeg && (!activeFrame || activeFrame.filename === "SAMPLE.CR2")) {
    await loadNegativeSample();
    return;
  }

  state.lastOriginalKey = "";
  if (isNeg && negativeState.baseColor === null) {
    await autoDetectBaseColor(false);
  }
  requestPreview(true);
}

function updateActiveRecipeBanner() {
  const statFilm = document.getElementById("statFilm");
  const devLabel = document.getElementById("developedLabel");

  if (state.appMode === "negative") {
    const isBw = negativeState.filmType === "bw" || negativeState.profile === "bw";
    let label = `Positivo · ${PROFILE_LABELS[negativeState.profile] || negativeState.profile}`;
    if (isBw && negativeState.bwToner && negativeState.bwToner !== "neutral") {
      label = `B&N · ${BW_TONER_LABELS[negativeState.bwToner] || negativeState.bwToner}`;
    }
    if (statFilm) statFilm.textContent = label;
    if (devLabel) devLabel.textContent = label;
  } else {
    const filmObj = state.films.find((f) => f.key === state.selectedFilm);
    const name = filmObj ? filmObj.name : state.selectedFilm;
    if (statFilm) statFilm.textContent = name;
    if (devLabel) devLabel.textContent = name;
  }
}

function syncNegProcessPanels() {
  const isBw = negativeState.filmType === "bw" || negativeState.profile === "bw";
  const colorPanel = document.getElementById("negColorFinishPanel");
  const bwPanel = document.getElementById("negBwChemPanel");
  const preSatGroup = document.getElementById("negPreSatGroup");
  const finishAmtGroup = document.getElementById("negFinishAmountGroup");
  const sharpAmtGroup = document.getElementById("negSharpenAmountGroup");

  if (colorPanel) colorPanel.style.display = isBw ? "none" : "flex";
  if (bwPanel) bwPanel.style.display = isBw ? "flex" : "none";
  if (preSatGroup) preSatGroup.style.display = isBw ? "none" : "flex";
  if (finishAmtGroup) {
    finishAmtGroup.style.display = negativeState.printFinish !== "none" ? "flex" : "none";
  }
  if (sharpAmtGroup) {
    sharpAmtGroup.style.display = negativeState.sharpenMode !== "off" ? "flex" : "none";
  }

  const descEl = document.getElementById("negBwTonerDesc");
  if (descEl) {
    descEl.textContent = (BW_TONER_DESCS[negativeState.bwToner] || "").trim();
  }

  const rollBadge = document.getElementById("rollCalBadge");
  if (rollBadge) {
    const activeRoll = Boolean(negativeState.rollBounds && negativeState.colorMethod === "roll_locked");
    rollBadge.style.display = activeRoll ? "inline-flex" : "none";
    if (activeRoll && negativeState.rollFramesCount > 0) {
      rollBadge.textContent = `Rollo · ${negativeState.rollFramesCount}`;
    }
  }
}

function getZoneTripletRef(zone) {
  if (zone === "shadows") return negativeState.shadowsTint;
  if (zone === "mids") return negativeState.midsTint;
  if (zone === "highs") return negativeState.highsTint;
  return negativeState.cmy;
}

function updateCmyZoneDots() {
  const zones = [
    ["shadows", negativeState.shadowsTint],
    ["mids", negativeState.midsTint],
    ["highs", negativeState.highsTint],
  ];
  zones.forEach(([zKey, arr]) => {
    const btn = document.querySelector(`#cmyZoneBar .seg-btn[data-zone="${zKey}"]`);
    if (btn) {
      const hasTint = Array.isArray(arr) && arr.some((v) => Math.abs(Number(v) || 0) > 0.005);
      btn.classList.toggle("has-tint", hasTint);
    }
  });
}

function selectCmyZone(zone) {
  const validZone = ["global", "shadows", "mids", "highs"].includes(zone) ? zone : "global";
  negativeState.activeCmyZone = validZone;

  document.querySelectorAll("#cmyZoneBar .seg-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.zone === validZone);
  });

  const globalPane = document.getElementById("cmyGlobalPane");
  const zonePane = document.getElementById("cmyZonePane");
  if (globalPane) globalPane.style.display = validZone === "global" ? "flex" : "none";
  if (zonePane) zonePane.style.display = validZone === "global" ? "none" : "flex";

  if (validZone !== "global") {
    const zoneNames = { shadows: "Sombras", mids: "Medios", highs: "Luces" };
    const zName = zoneNames[validZone] || "Zona";
    const fmtS = (v) => `${v > 0 ? "+" : ""}${Number(v).toFixed(2)}`;
    const trip = getZoneTripletRef(validZone);

    const rl = document.getElementById("zoneRedLabel");
    const gl = document.getElementById("zoneGreenLabel");
    const bl = document.getElementById("zoneBlueLabel");
    if (rl) rl.textContent = `Cian ↔ Rojo (${zName})`;
    if (gl) gl.textContent = `Magenta ↔ Verde (${zName})`;
    if (bl) bl.textContent = `Amarillo ↔ Azul (${zName})`;

    setSliderSilent("zoneCmyRedSlider", "zoneCmyRedVal", trip[0], fmtS(trip[0]));
    setSliderSilent("zoneCmyGreenSlider", "zoneCmyGreenVal", trip[1], fmtS(trip[1]));
    setSliderSilent("zoneCmyBlueSlider", "zoneCmyBlueVal", trip[2], fmtS(trip[2]));
  }
  updateCmyZoneDots();
}

// =============================================================
// NON-BLOCKING REAL-TIME PREVIEW ENGINE
// =============================================================

function triggerDebouncedPreview() {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => requestPreview(false), 75);
}

function computeOriginalCacheKey(filename) {
  const cropKey = state.appMode === "negative" ? negativeState.cropPct.toFixed(3) : "0";
  return `${filename}|${state.rotate}|${state.flip_h}|${cropKey}`;
}

async function requestPreview(forceOriginal = false) {
  if (state.frames.length === 0) return;

  if (previewAbortController) {
    previewAbortController.abort();
  }
  const controller = new AbortController();
  previewAbortController = controller;

  const activeFrame = state.frames[state.activeFrameIndex];
  const origKey = computeOriginalCacheKey(activeFrame.filename);
  const needOriginal = forceOriginal || origKey !== state.lastOriginalKey || !document.getElementById("imgOriginal")?.src;

  setRenderBusy(true);

  try {
    if (state.appMode === "negative") {
      const res = await fetch("/api/negative/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify({
          filename: activeFrame.filename,
          include_original: needOriginal,
          ...buildNegativePayload(),
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Error al revelar negativo");

      applyPreviewResult(data, origKey, needOriginal);
      updateActiveRecipeBanner();
    } else {
      const res = await fetch("/api/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify({
          filename: activeFrame.filename,
          film: state.selectedFilm,
          ev: state.ev,
          halation: state.halation,
          grain: state.grain,
          vignette: state.vignette,
          date: state.date,
          rotate: state.rotate,
          flip_h: state.flip_h,
          include_original: needOriginal,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Error en vista previa");

      applyPreviewResult(data, origKey, needOriginal);
      if (data.film && data.film.name) {
        document.getElementById("developedLabel").textContent = data.film.name;
        document.getElementById("statFilm").textContent = data.film.name;
      }
    }
  } catch (err) {
    if (err.name === "AbortError") return;
    console.error("Preview error:", err);
  } finally {
    if (previewAbortController === controller) {
      setRenderBusy(false);
    }
  }
}

function applyPreviewResult(data, origKey, requestedOriginal) {
  const imgOrig = document.getElementById("imgOriginal");
  const imgDev = document.getElementById("imgDeveloped");

  if (requestedOriginal && data.original && imgOrig) {
    loupeSourceReady = false;
    imgOrig.onload = () => {
      if (negativeState.eyedropperMode !== "scene_wb") {
        prepareLoupeBuffer(imgOrig);
      }
    };
    imgOrig.src = data.original;
    state.lastOriginalKey = origKey;
  }

  if (data.developed && imgDev) {
    imgDev.onload = () => {
      renderHistogramFromImage(imgDev);
      if (negativeState.eyedropperMode === "scene_wb") {
        prepareLoupeBuffer(imgDev);
      }
    };
    imgDev.src = data.developed;
  }

  const statRes = document.getElementById("statResolution");
  const statTime = document.getElementById("statTime");
  if (statRes && data.width && data.height) {
    statRes.textContent = `${data.width}×${data.height}`;
  }
  if (statTime && data.render_time != null) {
    statTime.textContent = `${Math.round(data.render_time * 1000)} ms`;
  }
}

function buildNegativePayload() {
  return {
    film_type: negativeState.filmType,
    scan_source: negativeState.scanSource,
    pre_saturation: negativeState.preSaturation,
    light_source: negativeState.lightSource,
    color_method: negativeState.colorMethod,
    roll_bounds: negativeState.rollBounds
      ? {
          d_min: [...negativeState.rollBounds.d_min],
          d_max: [...negativeState.rollBounds.d_max],
        }
      : null,
    tone_variant: negativeState.toneVariant,
    print_finish: negativeState.printFinish,
    finish_amount: negativeState.finishAmount,
    bw_toner: negativeState.bwToner,
    bw_toner_strength: negativeState.bwTonerStrength,
    profile: negativeState.profile,
    base_color: negativeState.baseColor ? [...negativeState.baseColor] : null,
    border_buffer: negativeState.borderBuffer,
    crop_pct: negativeState.cropPct,
    brightness: negativeState.brightness,
    midtone_nd: negativeState.midtoneNd,
    contrast: negativeState.contrast,
    push_pull: negativeState.pushPull,
    lights: negativeState.lights,
    darks: negativeState.darks,
    whites: negativeState.whites,
    blacks: negativeState.blacks,
    black_clip: negativeState.blackClip,
    white_clip: negativeState.whiteClip,
    clip_protect: negativeState.clipProtect,
    inky_blacks: negativeState.inkyBlacks,
    rp_tone: negativeState.rpTone,
    saturation: negativeState.saturation,
    printer_cmy: [...negativeState.cmy],
    shadows_tint: [...negativeState.shadowsTint],
    mids_tint: [...negativeState.midsTint],
    highs_tint: [...negativeState.highsTint],
    shadows_range: negativeState.shadowsRange,
    highs_range: negativeState.highsRange,
    temp: negativeState.temp,
    tint: negativeState.tint,
    warming_85: negativeState.warming85,
    skylight_filter: negativeState.skylightFilter,
    shade_filter: negativeState.shadeFilter,
    sharpen_mode: negativeState.sharpenMode,
    sharpen_amount: negativeState.sharpenAmount,
    glow: negativeState.glow,
    fade: negativeState.fade,
    rotate: state.rotate,
    flip_h: state.flip_h,
  };
}

// =============================================================
// PER-FRAME RECIPE MEMORY, COPY/PASTE & ROLL SYNC
// =============================================================

function snapshotSimRecipe() {
  return {
    film: state.selectedFilm,
    ev: state.ev,
    halation: state.halation,
    grain: state.grain,
    vignette: state.vignette,
    date: state.date,
    rotate: state.rotate,
    flip_h: state.flip_h,
  };
}

function snapshotNegRecipe() {
  return {
    ...buildNegativePayload(),
    base_hex: negativeState.baseHex,
  };
}

function saveActiveFrameRecipe() {
  const frame = state.frames[state.activeFrameIndex];
  if (!frame) return;
  if (state.appMode === "negative") {
    frame.negRecipe = snapshotNegRecipe();
  } else {
    frame.simRecipe = snapshotSimRecipe();
  }
}

function setSliderSilent(sliderId, labelId, val, textVal) {
  const el = document.getElementById(sliderId);
  const lbl = document.getElementById(labelId);
  if (el && val != null) el.value = String(val);
  if (lbl && textVal != null) lbl.textContent = textVal;
}

function applySimRecipeToUI(rec) {
  if (!rec) return;
  state.selectedFilm = rec.film || state.selectedFilm;
  state.ev = Number(rec.ev ?? 0);
  state.halation = Number(rec.halation ?? 1.0);
  state.grain = Number(rec.grain ?? 1.0);
  state.vignette = Number(rec.vignette ?? 1.0);
  state.date = Boolean(rec.date);
  if (typeof rec.rotate === "number") state.rotate = rec.rotate;
  if (typeof rec.flip_h === "boolean") state.flip_h = rec.flip_h;

  document.querySelectorAll(".film-card").forEach((el) => {
    const sel = el.dataset.key === state.selectedFilm;
    el.classList.toggle("selected", sel);
    el.setAttribute("aria-selected", sel ? "true" : "false");
  });
  document.getElementById("flipHBtn")?.classList.toggle("active", state.flip_h);

  setSliderSilent("evSlider", "evVal", state.ev, `${state.ev > 0 ? "+" : ""}${state.ev.toFixed(1)} EV`);
  setSliderSilent("halationSlider", "halationVal", state.halation, `${state.halation.toFixed(1)}x`);
  setSliderSilent("grainSlider", "grainVal", state.grain, `${state.grain.toFixed(1)}x`);
  setSliderSilent("vignetteSlider", "vignetteVal", state.vignette, `${state.vignette.toFixed(1)}x`);
  const dt = document.getElementById("dateToggle");
  if (dt) dt.checked = state.date;
  updateActiveRecipeBanner();
}

function applyNegRecipeToUI(rec, preserveCurrentBaseIfMissing = false) {
  if (!rec) return;
  const fmtS = (v) => `${v > 0 ? "+" : ""}${Number(v).toFixed(2)}`;
  const fmtPct = (v) => `${Math.round(Number(v) * 100)}%`;
  const parseTrip = (arr) =>
    Array.isArray(arr)
      ? [Number(arr[0] ?? 0), Number(arr[1] ?? 0), Number(arr[2] ?? 0)]
      : [0.0, 0.0, 0.0];

  negativeState.filmType = rec.film_type || "color";
  negativeState.scanSource = rec.scan_source || "camera_raw";
  negativeState.preSaturation = Number(rec.pre_saturation ?? 1.0);
  negativeState.lightSource = rec.light_source || "standard";
  negativeState.colorMethod = rec.color_method || "dynamic";
  if (rec.roll_bounds && Array.isArray(rec.roll_bounds.d_min) && Array.isArray(rec.roll_bounds.d_max)) {
    negativeState.rollBounds = {
      d_min: parseTrip(rec.roll_bounds.d_min),
      d_max: parseTrip(rec.roll_bounds.d_max),
    };
  } else if (!preserveCurrentBaseIfMissing) {
    negativeState.rollBounds = null;
  }
  negativeState.toneVariant = rec.tone_variant || "standard";
  negativeState.printFinish = rec.print_finish || "none";
  negativeState.finishAmount = Number(rec.finish_amount ?? 1.0);
  negativeState.bwToner = rec.bw_toner || "neutral";
  negativeState.bwTonerStrength = Number(rec.bw_toner_strength ?? 1.0);
  negativeState.profile = rec.profile || rec.profile_key || "frontier";
  negativeState.borderBuffer = Number(rec.border_buffer ?? 0.06);
  negativeState.cropPct = Number(rec.crop_pct ?? 0.0);
  negativeState.brightness = Number(rec.brightness ?? 0.0);
  negativeState.midtoneNd = Number(rec.midtone_nd ?? 0.0);
  negativeState.contrast = Number(rec.contrast ?? 0.0);
  negativeState.pushPull = Number(rec.push_pull ?? 0.0);
  negativeState.lights = Number(rec.lights ?? 0.0);
  negativeState.darks = Number(rec.darks ?? 0.0);
  negativeState.whites = Number(rec.whites ?? 0.0);
  negativeState.blacks = Number(rec.blacks ?? 0.0);
  negativeState.blackClip = Number(rec.black_clip ?? 0.0);
  negativeState.whiteClip = Number(rec.white_clip ?? 0.0);
  negativeState.clipProtect = rec.clip_protect !== undefined ? Boolean(rec.clip_protect) : true;
  negativeState.inkyBlacks = Number(rec.inky_blacks ?? 0.0);
  negativeState.rpTone = Number(rec.rp_tone ?? 0.0);
  negativeState.saturation = Number(rec.saturation ?? 1.0);
  negativeState.cmy = parseTrip(rec.printer_cmy);
  negativeState.shadowsTint = parseTrip(rec.shadows_tint);
  negativeState.midsTint = parseTrip(rec.mids_tint);
  negativeState.highsTint = parseTrip(rec.highs_tint);
  negativeState.shadowsRange = Number(rec.shadows_range ?? 0.5);
  negativeState.highsRange = Number(rec.highs_range ?? 0.5);
  negativeState.temp = Number(rec.temp ?? 0.0);
  negativeState.tint = Number(rec.tint ?? 0.0);
  negativeState.warming85 = Number(rec.warming_85 ?? 0.0);
  negativeState.skylightFilter = Number(rec.skylight_filter ?? 0.0);
  negativeState.shadeFilter = Number(rec.shade_filter ?? 0.0);
  negativeState.sharpenMode = rec.sharpen_mode || "off";
  negativeState.sharpenAmount = Number(rec.sharpen_amount ?? 1.0);
  negativeState.glow = Number(rec.glow ?? 1.0);
  negativeState.fade = Number(rec.fade ?? 1.0);

  if (typeof rec.rotate === "number") state.rotate = rec.rotate;
  if (typeof rec.flip_h === "boolean") state.flip_h = rec.flip_h;
  document.getElementById("flipHBtn")?.classList.toggle("active", state.flip_h);

  if (Array.isArray(rec.base_color)) {
    setBaseColor(rec.base_color, rec.base_hex || null, null);
  } else if (!preserveCurrentBaseIfMissing) {
    negativeState.baseColor = null;
  }

  document.getElementById("btnTypeColor")?.classList.toggle("active", negativeState.filmType === "color");
  document.getElementById("btnTypeBW")?.classList.toggle("active", negativeState.filmType === "bw");

  document.querySelectorAll("#negScanSourceBar .seg-btn").forEach((b) => {
    b.classList.toggle("active", b.dataset.source === negativeState.scanSource);
  });
  document.querySelectorAll("#negLightSourceBar .seg-btn").forEach((b) => {
    b.classList.toggle("active", b.dataset.light === negativeState.lightSource);
  });
  document.querySelectorAll("#negColorMethodBar .seg-btn").forEach((b) => {
    b.classList.toggle("active", b.dataset.method === negativeState.colorMethod);
  });
  document.querySelectorAll("#negToneVariantBar .seg-btn").forEach((b) => {
    b.classList.toggle("active", b.dataset.tone === negativeState.toneVariant);
  });
  document.querySelectorAll("#negSharpenModeBar .seg-btn").forEach((b) => {
    b.classList.toggle("active", b.dataset.sharpen === negativeState.sharpenMode);
  });
  document.querySelectorAll("#negProfileList .profile-card").forEach((c) => {
    c.classList.toggle("selected", c.dataset.profile === negativeState.profile);
  });

  const pfSel = document.getElementById("negPrintFinishSelect");
  if (pfSel) pfSel.value = negativeState.printFinish;
  const bwSel = document.getElementById("negBwTonerSelect");
  if (bwSel) bwSel.value = negativeState.bwToner;

  setSliderSilent("negPreSatSlider", "negPreSatVal", negativeState.preSaturation, `${negativeState.preSaturation.toFixed(2)}x`);
  const finPct = Math.round(negativeState.finishAmount * 100);
  setSliderSilent("negFinishAmountSlider", "negFinishAmountVal", finPct, `${finPct}%`);
  const bwStrPct = Math.round(negativeState.bwTonerStrength * 100);
  setSliderSilent("negBwTonerStrengthSlider", "negBwTonerStrengthVal", bwStrPct, `${bwStrPct}%`);

  const bufPct = Math.round(negativeState.borderBuffer * 100);
  const cropPctUi = Number((negativeState.cropPct * 100).toFixed(1));
  setSliderSilent("negBufferSlider", "negBufferVal", bufPct, `${bufPct}%`);
  setSliderSilent("negCropSlider", "negCropVal", cropPctUi, `${cropPctUi.toFixed(1).replace(/\.0$/, "")}%`);

  setSliderSilent("negBrightnessSlider", "negBrightnessVal", negativeState.brightness, fmtS(negativeState.brightness));
  setSliderSilent("negMidtoneNdSlider", "negMidtoneNdVal", negativeState.midtoneNd, fmtS(negativeState.midtoneNd));
  setSliderSilent("negContrastSlider", "negContrastVal", negativeState.contrast, fmtS(negativeState.contrast));
  setSliderSilent("negPushPullSlider", "negPushPullVal", negativeState.pushPull, fmtS(negativeState.pushPull));
  setSliderSilent("negLightsSlider", "negLightsVal", negativeState.lights, fmtS(negativeState.lights));
  setSliderSilent("negDarksSlider", "negDarksVal", negativeState.darks, fmtS(negativeState.darks));
  setSliderSilent("negWhitesSlider", "negWhitesVal", negativeState.whites, fmtS(negativeState.whites));
  setSliderSilent("negBlacksSlider", "negBlacksVal", negativeState.blacks, fmtS(negativeState.blacks));
  setSliderSilent("negBlackClipSlider", "negBlackClipVal", negativeState.blackClip, fmtS(negativeState.blackClip));
  setSliderSilent("negWhiteClipSlider", "negWhiteClipVal", negativeState.whiteClip, fmtS(negativeState.whiteClip));
  const cpToggle = document.getElementById("negClipProtectToggle");
  if (cpToggle) cpToggle.checked = negativeState.clipProtect;
  setSliderSilent("negInkyBlacksSlider", "negInkyBlacksVal", negativeState.inkyBlacks, fmtPct(negativeState.inkyBlacks));
  setSliderSilent("negRpToneSlider", "negRpToneVal", negativeState.rpTone, fmtPct(negativeState.rpTone));
  setSliderSilent("negSatSlider", "negSatVal", negativeState.saturation, `${negativeState.saturation.toFixed(2)}x`);

  setSliderSilent("cmyRedSlider", "cmyRedVal", negativeState.cmy[0], fmtS(negativeState.cmy[0]));
  setSliderSilent("cmyGreenSlider", "cmyGreenVal", negativeState.cmy[1], fmtS(negativeState.cmy[1]));
  setSliderSilent("cmyBlueSlider", "cmyBlueVal", negativeState.cmy[2], fmtS(negativeState.cmy[2]));
  setSliderSilent("negTempSlider", "negTempVal", negativeState.temp, fmtS(negativeState.temp));
  setSliderSilent("negTintSlider", "negTintVal", negativeState.tint, fmtS(negativeState.tint));

  const shRangePct = Math.round(negativeState.shadowsRange * 100);
  const hiRangePct = Math.round(negativeState.highsRange * 100);
  setSliderSilent("negShadowsRangeSlider", "negShadowsRangeVal", shRangePct, `${shRangePct}%`);
  setSliderSilent("negHighsRangeSlider", "negHighsRangeVal", hiRangePct, `${hiRangePct}%`);

  const sharpPct = Math.round(negativeState.sharpenAmount * 100);
  setSliderSilent("negSharpenAmountSlider", "negSharpenAmountVal", sharpPct, `${sharpPct}%`);
  setSliderSilent("negWarming85Slider", "negWarming85Val", negativeState.warming85, fmtPct(negativeState.warming85));
  setSliderSilent("negSkylightSlider", "negSkylightVal", negativeState.skylightFilter, fmtPct(negativeState.skylightFilter));
  setSliderSilent("negShadeSlider", "negShadeVal", negativeState.shadeFilter, fmtPct(negativeState.shadeFilter));
  setSliderSilent("negGlowSlider", "negGlowVal", negativeState.glow, `${negativeState.glow.toFixed(1)}x`);
  setSliderSilent("negFadeSlider", "negFadeVal", negativeState.fade, `${negativeState.fade.toFixed(1)}x`);

  selectCmyZone(negativeState.activeCmyZone);
  syncNegProcessPanels();
  updateActiveRecipeBanner();
}

function loadFrameRecipe(idx) {
  const frame = state.frames[idx];
  if (!frame) return false;
  if (state.appMode === "negative") {
    if (frame.negRecipe) {
      applyNegRecipeToUI(frame.negRecipe, false);
      return true;
    }
    negativeState.baseColor = null;
    return false;
  }
  if (frame.simRecipe) {
    applySimRecipeToUI(frame.simRecipe);
    return true;
  }
  return false;
}

function copyCurrentRecipe() {
  saveActiveFrameRecipe();
  if (state.appMode === "negative") {
    state.copiedRecipe = { mode: "negative", data: snapshotNegRecipe() };
  } else {
    state.copiedRecipe = { mode: "simulation", data: snapshotSimRecipe() };
  }
  const pasteBtn = document.getElementById("pasteRecipeBtn");
  if (pasteBtn) pasteBtn.disabled = false;
  const label =
    state.appMode === "negative"
      ? PROFILE_LABELS[negativeState.profile] || negativeState.profile
      : state.films.find((f) => f.key === state.selectedFilm)?.name || state.selectedFilm;
  showToast("Receta copiada", `${label} lista para pegar en otros fotogramas.`);
}

async function pasteCopiedRecipe() {
  if (!state.copiedRecipe) return;
  if (state.copiedRecipe.mode !== state.appMode) {
    await switchStudioMode(state.copiedRecipe.mode);
  }
  if (state.copiedRecipe.mode === "negative") {
    // Keep active frame's own rotation/flip unless needed, apply grading + base
    const merged = {
      ...state.copiedRecipe.data,
      rotate: state.rotate,
      flip_h: state.flip_h,
    };
    applyNegRecipeToUI(merged, true);
  } else {
    const merged = {
      ...state.copiedRecipe.data,
      rotate: state.rotate,
      flip_h: state.flip_h,
    };
    applySimRecipeToUI(merged);
  }
  saveActiveFrameRecipe();
  state.lastOriginalKey = "";
  await requestPreview(true);
  showToast("Receta aplicada", "Ajustes pegados en el fotograma actual.");
}

function syncRecipeToRoll() {
  if (state.frames.length === 0) return;
  saveActiveFrameRecipe();
  const isNeg = state.appMode === "negative";
  const baseSnap = isNeg ? snapshotNegRecipe() : snapshotSimRecipe();

  state.frames.forEach((f) => {
    if (isNeg) {
      const prevRot = f.negRecipe?.rotate ?? state.rotate;
      const prevFlip = f.negRecipe?.flip_h ?? state.flip_h;
      f.negRecipe = { ...baseSnap, rotate: prevRot, flip_h: prevFlip };
    } else {
      const prevRot = f.simRecipe?.rotate ?? state.rotate;
      const prevFlip = f.simRecipe?.flip_h ?? state.flip_h;
      f.simRecipe = { ...baseSnap, rotate: prevRot, flip_h: prevFlip };
    }
  });

  showToast(
    "Rollo sincronizado",
    `Receta óptica aplicada a los ${state.frames.length} fotograma(s) del rollo.`
  );
}

function buildPerFrameRecipesMap() {
  saveActiveFrameRecipe();
  const map = {};
  const isNeg = state.appMode === "negative";
  state.frames.forEach((f) => {
    const rec = isNeg ? f.negRecipe : f.simRecipe;
    if (rec) {
      map[f.filename] = rec;
    }
  });
  return map;
}

// =============================================================
// NEGATIVE BASE MASK CALIBRATION & EYEDROPPER LOUPE
// =============================================================

function setBaseColor(linearRgb, serverHex = null, subtitle = null) {
  negativeState.baseColor = Array.isArray(linearRgb) ? linearRgb : null;
  const hex = serverHex || linearRgbToHexClient(linearRgb);
  negativeState.baseHex = hex;

  const swatch = document.getElementById("baseSwatch");
  const hexLabel = document.getElementById("baseHex");
  const subLabel = document.getElementById("baseRgbLabel");
  const loupeDot = document.getElementById("loupeDot");

  if (swatch) swatch.style.backgroundColor = hex;
  if (hexLabel) hexLabel.textContent = hex.toUpperCase();
  if (loupeDot) loupeDot.style.backgroundColor = hex;

  if (subLabel) {
    if (subtitle) {
      subLabel.textContent = subtitle;
    } else if (Array.isArray(linearRgb) && linearRgb.length === 3) {
      subLabel.textContent = `D-min ${linearRgb.map((v) => Number(v).toFixed(2)).join(" / ")}`;
    } else {
      subLabel.textContent = negativeState.filmType === "bw" ? "Soporte B&N" : "Soporte C-41";
    }
  }
}

async function autoDetectBaseColor(triggerPreviewAfter = true) {
  const activeFrame = state.frames[state.activeFrameIndex];
  if (!activeFrame) return;

  try {
    const res = await fetch("/api/negative/auto_detect_base", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        filename: activeFrame.filename,
        rotate: state.rotate,
        flip_h: state.flip_h,
      }),
    });
    const data = await res.json();
    if (res.ok && data.base_color) {
      setBaseColor(data.base_color, data.base_hex || data.hex, "Auto D-min");
      if (triggerPreviewAfter) {
        requestPreview(false);
      }
    }
  } catch (err) {
    console.error("Auto base error:", err);
  }
}

async function analyzeFullRoll() {
  if (state.frames.length === 0) return;
  showLoading(true, `Analizando densitometría unificada de ${state.frames.length} fotograma(s)…`);
  try {
    const filenames = state.frames.map((f) => f.filename);
    const perFrameRecipes = buildPerFrameRecipesMap();
    const res = await fetch("/api/negative/analyze_roll", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        filenames,
        per_frame_recipes: perFrameRecipes,
        ...buildNegativePayload(),
      }),
    });
    const data = await res.json();
    if (!res.ok || !data.base_color || !data.roll_bounds) {
      throw new Error(data.error || "No se pudo calibrar el rollo");
    }

    negativeState.rollBounds = {
      d_min: [...data.roll_bounds.d_min],
      d_max: [...data.roll_bounds.d_max],
    };
    negativeState.rollFramesCount = data.frames_analyzed || state.frames.length;
    negativeState.colorMethod = "roll_locked";

    setBaseColor(data.base_color, data.base_hex || data.hex, "Rollo unificado");
    document.querySelectorAll("#negColorMethodBar .seg-btn").forEach((b) => {
      b.classList.toggle("active", b.dataset.method === "roll_locked");
    });
    syncNegProcessPanels();

    const baseSnap = snapshotNegRecipe();
    state.frames.forEach((f) => {
      if (f.negRecipe) {
        f.negRecipe = {
          ...f.negRecipe,
          base_color: [...data.base_color],
          base_hex: negativeState.baseHex,
          color_method: "roll_locked",
          roll_bounds: {
            d_min: [...data.roll_bounds.d_min],
            d_max: [...data.roll_bounds.d_max],
          },
        };
      } else {
        f.negRecipe = { ...baseSnap };
      }
    });

    saveActiveFrameRecipe();
    await requestPreview(false);
    showToast(
      "Rollo calibrado",
      `Soporte D-min y envolvente dinámica fijados en ${negativeState.rollFramesCount} fotograma(s).`
    );
  } catch (err) {
    console.error("Roll analysis error:", err);
    showToast("Error al analizar rollo", err.message || "Verifica los fotogramas importados.");
  } finally {
    showLoading(false);
  }
}

// =============================================================
// ANALOG EXIF TECHNICAL SHEET & CAPTION BUILDER
// =============================================================

const ANALOG_EXIF_FIELD_MAP = [
  ["exifCameraMake", "camera_make"],
  ["exifCameraModel", "camera_model"],
  ["exifLens", "lens"],
  ["exifFilmStock", "film_stock"],
  ["exifShotIso", "shot_iso"],
  ["exifFilmFormat", "film_format"],
  ["exifDevProcess", "dev_process"],
  ["exifScanner", "scanner"],
  ["exifPhotographer", "photographer"],
  ["exifNotes", "notes"],
];

function buildAnalogMetaPayload() {
  const out = {};
  if (!state.analogMeta || typeof state.analogMeta !== "object") return out;
  ANALOG_EXIF_FIELD_MAP.forEach(([, key]) => {
    const raw = state.analogMeta[key];
    if (raw != null) {
      const trimmed = String(raw).trim();
      if (trimmed) out[key] = trimmed.slice(0, 240);
    }
  });
  return out;
}

function updateExifStatusBadge() {
  const badge = document.getElementById("exifStatusBadge");
  if (!badge) return;
  const activeCount = Object.keys(buildAnalogMetaPayload()).length;
  badge.textContent = activeCount > 0 ? "Activa" : "Opcional";
  badge.classList.toggle("badge-emerald", activeCount > 0);
}

function applyAnalogMetaToUI(metaObj, persist = true) {
  const next = {};
  if (metaObj && typeof metaObj === "object") {
    ANALOG_EXIF_FIELD_MAP.forEach(([, key]) => {
      if (metaObj[key] != null) {
        const s = String(metaObj[key]).trim();
        if (s) next[key] = s.slice(0, 240);
      }
    });
  }
  state.analogMeta = next;
  ANALOG_EXIF_FIELD_MAP.forEach(([domId, key]) => {
    const el = document.getElementById(domId);
    if (el) el.value = next[key] || "";
  });
  if (persist) {
    saveAnalogExifStorage(state.analogMeta);
  }
  updateExifStatusBadge();
}

function formatAnalogCaptionClient(metaObj) {
  const m = metaObj || {};
  const parts = [];
  const cam = [m.camera_make, m.camera_model].filter(Boolean).join(" ").trim();
  if (cam) parts.push(cam);
  if (m.lens) parts.push(m.lens);

  let filmPart = m.film_stock || "";
  if (m.film_format) {
    filmPart = filmPart ? `${filmPart} (${m.film_format})` : m.film_format;
  }
  if (m.shot_iso) {
    filmPart = filmPart ? `${filmPart} @ ISO ${m.shot_iso}` : `ISO ${m.shot_iso}`;
  }
  if (filmPart) parts.push(filmPart);

  if (m.dev_process) parts.push(`Proceso ${m.dev_process}`);
  if (m.scanner) parts.push(`Captura ${m.scanner}`);
  if (m.photographer) parts.push(`© ${m.photographer}`);
  if (m.notes) parts.push(m.notes);

  if (parts.length === 0) {
    const activeRecipe = document.getElementById("statFilm")?.textContent || "Haluro";
    return `Revelado en Haluro · ${activeRecipe}`;
  }
  return parts.join(" · ");
}

async function copyAnalogCaptionToClipboard() {
  const caption = formatAnalogCaptionClient(buildAnalogMetaPayload());
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(caption);
    } else {
      const ta = document.createElement("textarea");
      ta.value = caption;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
    }
    showToast("Pie técnico copiado", caption);
  } catch (err) {
    console.error("Clipboard error:", err);
    showToast("Pie técnico generado", caption);
  }
}

function initAnalogExifControls() {
  applyAnalogMetaToUI(state.analogMeta, false);

  ANALOG_EXIF_FIELD_MAP.forEach(([domId, key]) => {
    const el = document.getElementById(domId);
    if (!el) return;
    const syncField = () => {
      const val = String(el.value || "").trim();
      if (val) {
        state.analogMeta[key] = val.slice(0, 240);
      } else {
        delete state.analogMeta[key];
      }
      saveAnalogExifStorage(state.analogMeta);
      updateExifStatusBadge();
    };
    el.addEventListener("input", syncField);
    el.addEventListener("change", syncField);
  });

  document.getElementById("btnCopyAnalogCaption")?.addEventListener("click", copyAnalogCaptionToClipboard);
  document.getElementById("btnClearAnalogExif")?.addEventListener("click", () => {
    applyAnalogMetaToUI({}, true);
    showToast("Ficha técnica limpia", "Se han vaciado los campos EXIF opcionales.");
  });
}

function setEyedropperMode(mode) {
  const cleanMode = mode === "base" || mode === "scene_wb" ? mode : null;
  const wasActive = negativeState.eyedropperActive;
  negativeState.eyedropperMode = cleanMode;
  negativeState.eyedropperActive = Boolean(cleanMode);

  const btnBase = document.getElementById("btnEyedropper");
  const tipBase = document.getElementById("eyedropperTip");
  const btnScene = document.getElementById("btnSceneWbEyedropper");
  const tipScene = document.getElementById("sceneWbTip");
  const wrapper = document.getElementById("splitWrapper");
  const loupe = document.getElementById("eyedropperLoupe");

  btnBase?.classList.toggle("active", cleanMode === "base");
  if (tipBase) tipBase.style.display = cleanMode === "base" ? "block" : "none";

  btnScene?.classList.toggle("active", cleanMode === "scene_wb");
  if (tipScene) tipScene.style.display = cleanMode === "scene_wb" ? "block" : "none";

  wrapper?.classList.toggle("eyedropper-active", negativeState.eyedropperActive);
  if (!negativeState.eyedropperActive && loupe) {
    loupe.style.display = "none";
  }

  if (cleanMode === "base") {
    if (!wasActive) state.prevViewMode = state.viewMode;
    setViewMode("original");
    prepareLoupeBuffer(document.getElementById("imgOriginal"));
  } else if (cleanMode === "scene_wb") {
    if (!wasActive) state.prevViewMode = state.viewMode;
    setViewMode("full");
    prepareLoupeBuffer(document.getElementById("imgDeveloped"));
  } else if (wasActive && state.prevViewMode && state.prevViewMode !== state.viewMode) {
    setViewMode(state.prevViewMode);
  }
}

function setEyedropperActive(active) {
  setEyedropperMode(active ? "base" : null);
}

function applySolvedCmy(cmyArr) {
  if (!Array.isArray(cmyArr) || cmyArr.length < 3) return;
  const fmtS = (v) => `${v > 0 ? "+" : ""}${Number(v).toFixed(2)}`;
  negativeState.cmy = [
    Number(cmyArr[0]) || 0,
    Number(cmyArr[1]) || 0,
    Number(cmyArr[2]) || 0,
  ];
  setSliderSilent("cmyRedSlider", "cmyRedVal", negativeState.cmy[0], fmtS(negativeState.cmy[0]));
  setSliderSilent("cmyGreenSlider", "cmyGreenVal", negativeState.cmy[1], fmtS(negativeState.cmy[1]));
  setSliderSilent("cmyBlueSlider", "cmyBlueVal", negativeState.cmy[2], fmtS(negativeState.cmy[2]));
  saveActiveFrameRecipe();
}

async function autoBalanceSceneWb() {
  const activeFrame = state.frames[state.activeFrameIndex];
  if (!activeFrame || state.appMode !== "negative") return;
  setRenderBusy(true);
  try {
    const res = await fetch("/api/negative/auto_scene_wb", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        filename: activeFrame.filename,
        ...buildNegativePayload(),
      }),
    });
    const data = await res.json();
    if (res.ok && Array.isArray(data.printer_cmy)) {
      applySolvedCmy(data.printer_cmy);
      await requestPreview(false);
      showToast("Auto WB aplicado", "Luces de ampliadora equilibradas sobre los medios tonos.");
    }
  } catch (err) {
    console.error("Auto scene WB error:", err);
  } finally {
    setRenderBusy(false);
  }
}

function prepareLoupeBuffer(imgEl) {
  try {
    if (!imgEl || !imgEl.naturalWidth) return;
    if (!offscreenLoupeCanvas) offscreenLoupeCanvas = document.createElement("canvas");
    const scale = Math.min(1, 512 / Math.max(imgEl.naturalWidth, imgEl.naturalHeight));
    offscreenLoupeCanvas.width = Math.max(1, Math.round(imgEl.naturalWidth * scale));
    offscreenLoupeCanvas.height = Math.max(1, Math.round(imgEl.naturalHeight * scale));
    const ctx = offscreenLoupeCanvas.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(imgEl, 0, 0, offscreenLoupeCanvas.width, offscreenLoupeCanvas.height);
    loupeSourceReady = true;
  } catch (_) {
    loupeSourceReady = false;
  }
}

function initEyedropperViewport() {
  const wrapper = document.getElementById("splitWrapper");
  const loupe = document.getElementById("eyedropperLoupe");
  const loupeDot = document.getElementById("loupeDot");
  const loupeLabel = document.getElementById("loupeLabel");

  if (!wrapper) return;

  wrapper.addEventListener("mousemove", (e) => {
    if (!negativeState.eyedropperActive || state.appMode !== "negative") return;
    const rect = wrapper.getBoundingClientRect();
    if (!rect.width || !rect.height) return;

    const xPct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    const yPct = Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height));

    if (loupe) {
      loupe.style.display = "inline-flex";
      loupe.style.left = `${(xPct * 100).toFixed(2)}%`;
      loupe.style.top = `${(yPct * 100).toFixed(2)}%`;
    }

    if (loupeSourceReady && offscreenLoupeCanvas) {
      const ctx = offscreenLoupeCanvas.getContext("2d", { willReadFrequently: true });
      const px = Math.min(offscreenLoupeCanvas.width - 1, Math.floor(xPct * offscreenLoupeCanvas.width));
      const py = Math.min(offscreenLoupeCanvas.height - 1, Math.floor(yPct * offscreenLoupeCanvas.height));
      const d = ctx.getImageData(px, py, 1, 1).data;
      const hex =
        "#" +
        [d[0], d[1], d[2]]
          .map((v) => v.toString(16).padStart(2, "0"))
          .join("")
          .toUpperCase();
      if (loupeDot) loupeDot.style.backgroundColor = hex;
      if (loupeLabel) {
        loupeLabel.textContent =
          negativeState.eyedropperMode === "scene_wb" ? `Neutro ${hex}` : hex;
      }
    }
  });

  wrapper.addEventListener("mouseleave", () => {
    if (loupe) loupe.style.display = "none";
  });

  wrapper.addEventListener("click", async (e) => {
    if (!negativeState.eyedropperActive || state.appMode !== "negative") return;
    if (e.target.closest("#splitDivider")) return;

    const rect = wrapper.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const xPct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    const yPct = Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height));
    const activeFrame = state.frames[state.activeFrameIndex];
    if (!activeFrame) return;

    if (negativeState.eyedropperMode === "scene_wb") {
      try {
        const res = await fetch("/api/negative/sample_neutral_wb", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            filename: activeFrame.filename,
            x_pct: xPct,
            y_pct: yPct,
            ...buildNegativePayload(),
          }),
        });
        const data = await res.json();
        if (res.ok && Array.isArray(data.printer_cmy)) {
          applySolvedCmy(data.printer_cmy);
          setEyedropperMode(null);
          await requestPreview(false);
          showToast("Gris neutro calibrado", "Luces CMY ajustadas sobre el punto muestreado.");
        }
      } catch (err) {
        console.error("Scene WB sample error:", err);
        setEyedropperMode(null);
      }
      return;
    }

    try {
      const res = await fetch("/api/negative/sample_point", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          filename: activeFrame.filename,
          x_pct: xPct,
          y_pct: yPct,
          rotate: state.rotate,
          flip_h: state.flip_h,
        }),
      });
      const data = await res.json();
      if (res.ok && data.base_color) {
        setBaseColor(data.base_color, data.base_hex || data.hex, "Muestra manual");
        saveActiveFrameRecipe();
        setEyedropperMode(null);
        await requestPreview(false);
        showToast("Soporte calibrado", `D-min neutralizado en ${data.base_hex || ""}`);
      }
    } catch (err) {
      console.error("Eyedropper sample error:", err);
      setEyedropperMode(null);
    }
  });
}

// =============================================================
// REAL-TIME RGB & LUMINANCE DENSITOMETER HISTOGRAM
// =============================================================

function renderHistogramFromImage(imgEl) {
  const canvas = document.getElementById("histogramCanvas");
  if (!canvas || !imgEl || !imgEl.naturalWidth) return;

  if (!offscreenHistCanvas) {
    offscreenHistCanvas = document.createElement("canvas");
  }
  const sampleW = 240;
  const sampleH = Math.max(1, Math.round((imgEl.naturalHeight / imgEl.naturalWidth) * sampleW));
  offscreenHistCanvas.width = sampleW;
  offscreenHistCanvas.height = sampleH;

  const sCtx = offscreenHistCanvas.getContext("2d", { willReadFrequently: true });
  sCtx.drawImage(imgEl, 0, 0, sampleW, sampleH);
  const { data } = sCtx.getImageData(0, 0, sampleW, sampleH);

  const rBins = new Uint32Array(256);
  const gBins = new Uint32Array(256);
  const bBins = new Uint32Array(256);
  const yBins = new Uint32Array(256);

  const totalPixels = sampleW * sampleH;
  let shadowClipCount = 0;
  let highlightClipCount = 0;

  for (let i = 0; i < data.length; i += 4) {
    const r = data[i];
    const g = data[i + 1];
    const b = data[i + 2];
    const luma = Math.min(255, Math.round(0.2126 * r + 0.7152 * g + 0.0722 * b));

    rBins[r] += 1;
    gBins[g] += 1;
    bBins[b] += 1;
    yBins[luma] += 1;

    if (luma <= 2) shadowClipCount += 1;
    if (luma >= 253 || r >= 254 || g >= 254 || b >= 254) highlightClipCount += 1;
  }

  // Update clipping indicators
  const shadowPct = (shadowClipCount / totalPixels) * 100;
  const highPct = (highlightClipCount / totalPixels) * 100;
  const clipS = document.getElementById("clipShadows");
  const clipH = document.getElementById("clipHighlights");
  if (clipS) {
    clipS.textContent = `Sombras ${shadowPct.toFixed(1)}%`;
    clipS.classList.toggle("warn", shadowPct > 2.0);
  }
  if (clipH) {
    clipH.textContent = `Luces ${highPct.toFixed(1)}%`;
    clipH.classList.toggle("warn", highPct > 1.5);
  }

  // Normalize ignoring extreme spikes at bin 0 and 255 for clean legibility
  let maxPeak = 1;
  for (let b = 2; b < 254; b++) {
    maxPeak = Math.max(maxPeak, rBins[b], gBins[b], bBins[b], yBins[b]);
  }

  const dpr = window.devicePixelRatio || 1;
  const cssW = canvas.clientWidth || 272;
  const cssH = canvas.clientHeight || 84;
  if (canvas.width !== Math.round(cssW * dpr) || canvas.height !== Math.round(cssH * dpr)) {
    canvas.width = Math.round(cssW * dpr);
    canvas.height = Math.round(cssH * dpr);
  }

  const ctx = canvas.getContext("2d");
  ctx.save();
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, cssW, cssH);

  // Subtle zone gridlines (25%, 50%, 75%)
  ctx.strokeStyle = "rgba(255, 255, 255, 0.06)";
  ctx.lineWidth = 1;
  [0.25, 0.5, 0.75].forEach((pos) => {
    const x = Math.round(cssW * pos) + 0.5;
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, cssH);
    ctx.stroke();
  });

  ctx.globalCompositeOperation = "screen";

  const drawChannel = (bins, fillStyle, strokeStyle) => {
    ctx.beginPath();
    ctx.moveTo(0, cssH);
    for (let i = 0; i < 256; i++) {
      const x = (i / 255) * cssW;
      const norm = Math.min(1, bins[i] / maxPeak);
      // Slight gamma lift on bin height so subtle shadow/highlight tails are readable
      const h = Math.pow(norm, 0.78) * (cssH - 6);
      ctx.lineTo(x, cssH - h);
    }
    ctx.lineTo(cssW, cssH);
    ctx.closePath();
    ctx.fillStyle = fillStyle;
    ctx.fill();
    ctx.strokeStyle = strokeStyle;
    ctx.lineWidth = 1.1;
    ctx.stroke();
  };

  drawChannel(rBins, "rgba(229, 75, 75, 0.26)", "rgba(235, 95, 95, 0.75)");
  drawChannel(gBins, "rgba(58, 190, 120, 0.24)", "rgba(75, 210, 138, 0.75)");
  drawChannel(bBins, "rgba(68, 142, 238, 0.26)", "rgba(92, 162, 250, 0.75)");

  ctx.globalCompositeOperation = "source-over";
  ctx.beginPath();
  for (let i = 0; i < 256; i++) {
    const x = (i / 255) * cssW;
    const norm = Math.min(1, yBins[i] / maxPeak);
    const y = cssH - Math.pow(norm, 0.78) * (cssH - 6);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.strokeStyle = "rgba(236, 238, 242, 0.72)";
  ctx.lineWidth = 1.2;
  ctx.stroke();

  ctx.restore();
}

// =============================================================
// VIEWPORT: SPLIT SLIDER, VIEW MODES, GEOMETRY & ZOOM/PAN
// =============================================================

function initSplitSlider() {
  const wrapper = document.getElementById("splitWrapper");
  const divider = document.getElementById("splitDivider");
  if (!wrapper || !divider) return;

  let dragging = false;

  const updateFromClientX = (clientX) => {
    if (state.viewMode !== "split") return;
    const rect = wrapper.getBoundingClientRect();
    if (!rect.width) return;
    let pct = ((clientX - rect.left) / rect.width) * 100;
    pct = Math.max(0, Math.min(100, pct));
    applySplitPercent(pct);
  };

  divider.addEventListener("mousedown", (e) => {
    e.stopPropagation();
    dragging = true;
  });
  window.addEventListener("mouseup", () => {
    dragging = false;
  });
  window.addEventListener("mousemove", (e) => {
    if (dragging) updateFromClientX(e.clientX);
  });

  divider.addEventListener(
    "touchstart",
    (e) => {
      e.stopPropagation();
      dragging = true;
    },
    { passive: true }
  );
  window.addEventListener("touchend", () => {
    dragging = false;
  });
  window.addEventListener(
    "touchmove",
    (e) => {
      if (dragging && e.touches[0]) updateFromClientX(e.touches[0].clientX);
    },
    { passive: true }
  );

  // Keyboard support on the split divider handle
  divider.addEventListener("keydown", (e) => {
    if (e.key === "ArrowLeft") {
      e.preventDefault();
      applySplitPercent(Math.max(0, state.splitPercent - 5));
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      applySplitPercent(Math.min(100, state.splitPercent + 5));
    }
  });
}

function applySplitPercent(pct) {
  state.splitPercent = pct;
  const divider = document.getElementById("splitDivider");
  const imgOrig = document.getElementById("imgOriginal");
  if (divider) {
    divider.style.left = `${pct}%`;
    divider.setAttribute("aria-valuenow", String(Math.round(pct)));
  }
  if (imgOrig && state.viewMode === "split") {
    imgOrig.style.clipPath = `polygon(0 0, ${pct}% 0, ${pct}% 100%, 0 100%)`;
  }
}

function setViewMode(mode) {
  state.viewMode = mode;

  document.getElementById("viewSplitBtn")?.classList.toggle("active", mode === "split");
  document.getElementById("viewFullBtn")?.classList.toggle("active", mode === "full");
  document.getElementById("viewOrigBtn")?.classList.toggle("active", mode === "original");
  document.getElementById("viewSheetBtn")?.classList.toggle("active", mode === "sheet");

  const splitWrapper = document.getElementById("splitWrapper");
  const sheetContainer = document.getElementById("sheetContainer");
  const divider = document.getElementById("splitDivider");
  const imgOrig = document.getElementById("imgOriginal");
  const origLabel = document.getElementById("originalLabel");
  const devLabel = document.getElementById("developedLabel");

  if (mode === "sheet") {
    if (splitWrapper) splitWrapper.style.display = "none";
    if (sheetContainer) sheetContainer.style.display = "block";
    generateContactSheetPreview();
    return;
  }

  if (splitWrapper) splitWrapper.style.display = "block";
  if (sheetContainer) sheetContainer.style.display = "none";

  if (mode === "split") {
    if (divider) divider.style.display = "block";
    if (origLabel) origLabel.style.display = "block";
    if (devLabel) devLabel.style.display = "block";
    if (imgOrig) {
      imgOrig.style.clipPath = `polygon(0 0, ${state.splitPercent}% 0, ${state.splitPercent}% 100%, 0 100%)`;
    }
  } else if (mode === "full") {
    if (divider) divider.style.display = "none";
    if (origLabel) origLabel.style.display = "none";
    if (devLabel) devLabel.style.display = "block";
    if (imgOrig) {
      imgOrig.style.clipPath = "polygon(0 0, 0 0, 0 100%, 0 100%)";
    }
  } else if (mode === "original") {
    if (divider) divider.style.display = "none";
    if (origLabel) origLabel.style.display = "block";
    if (devLabel) devLabel.style.display = "none";
    if (imgOrig) {
      imgOrig.style.clipPath = "polygon(0 0, 100% 0, 100% 100%, 0 100%)";
    }
  }
}

function initZoomAndPan() {
  const container = document.getElementById("canvasContainer");
  const wrapper = document.getElementById("splitWrapper");
  if (!container || !wrapper) return;

  let panning = false;
  let startX = 0;
  let startY = 0;

  container.addEventListener(
    "wheel",
    (e) => {
      if (state.viewMode === "sheet") return;
      e.preventDefault();
      const delta = e.deltaY < 0 ? 0.2 : -0.2;
      setZoom(state.zoom + delta);
    },
    { passive: false }
  );

  wrapper.addEventListener("mousedown", (e) => {
    if (state.zoom <= 1.01 || negativeState.eyedropperActive) return;
    if (e.target.closest("#splitDivider")) return;
    panning = true;
    startX = e.clientX - state.panX;
    startY = e.clientY - state.panY;
    wrapper.classList.add("is-panning");
  });

  window.addEventListener("mousemove", (e) => {
    if (!panning) return;
    state.panX = e.clientX - startX;
    state.panY = e.clientY - startY;
    applyZoomTransform();
  });

  window.addEventListener("mouseup", () => {
    if (panning) {
      panning = false;
      wrapper.classList.remove("is-panning");
    }
  });
}

function setZoom(nextZoom) {
  const clamped = Math.max(1.0, Math.min(4.0, Math.round(nextZoom * 100) / 100));
  state.zoom = clamped;
  if (clamped <= 1.01) {
    state.panX = 0;
    state.panY = 0;
  }
  applyZoomTransform();
}

function resetZoom() {
  state.zoom = 1.0;
  state.panX = 0;
  state.panY = 0;
  applyZoomTransform();
}

function applyZoomTransform() {
  const wrapper = document.getElementById("splitWrapper");
  const readout = document.getElementById("zoomResetBtn");
  if (wrapper) {
    wrapper.style.transform =
      state.zoom <= 1.01
        ? "none"
        : `translate(${state.panX}px, ${state.panY}px) scale(${state.zoom})`;
  }
  if (readout) {
    readout.textContent = state.zoom <= 1.01 ? "Ajustar" : `${Math.round(state.zoom * 100)}%`;
  }
}

function rotateCurrentFrame(deltaDeg) {
  state.rotate = (((state.rotate + deltaDeg) % 360) + 360) % 360;
  saveActiveFrameRecipe();
  state.lastOriginalKey = "";
  requestPreview(true);
}

function toggleHorizontalFlip() {
  state.flip_h = !state.flip_h;
  document.getElementById("flipHBtn")?.classList.toggle("active", state.flip_h);
  saveActiveFrameRecipe();
  state.lastOriginalKey = "";
  requestPreview(true);
}

// =============================================================
// GLOBAL DRAG & DROP IMPORT
// =============================================================

function initDragAndDrop() {
  const overlay = document.getElementById("dropzoneOverlay");
  if (!overlay) return;

  let dragDepth = 0;

  window.addEventListener("dragenter", (e) => {
    if (!e.dataTransfer || !Array.from(e.dataTransfer.types).includes("Files")) return;
    e.preventDefault();
    dragDepth += 1;
    overlay.classList.add("active");
  });

  window.addEventListener("dragover", (e) => {
    if (!e.dataTransfer || !Array.from(e.dataTransfer.types).includes("Files")) return;
    e.preventDefault();
  });

  window.addEventListener("dragleave", (e) => {
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) {
      overlay.classList.remove("active");
    }
  });

  window.addEventListener("drop", async (e) => {
    e.preventDefault();
    dragDepth = 0;
    overlay.classList.remove("active");
    if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      await importFiles(e.dataTransfer.files);
    }
  });
}

// =============================================================
// DOUBLE-CLICK SLIDER RESET & SECTION RESETS
// =============================================================

function initDoubleClickReset() {
  document.querySelectorAll('input[type="range"][data-default]').forEach((slider) => {
    slider.addEventListener("dblclick", () => {
      const defVal = slider.dataset.default;
      if (defVal != null) {
        slider.value = defVal;
        slider.dispatchEvent(new Event("input", { bubbles: true }));
      }
    });
  });
}

function resetSimulationControls() {
  const defaults = [
    ["evSlider", "0.0"],
    ["halationSlider", "1.0"],
    ["grainSlider", "1.0"],
    ["vignetteSlider", "1.0"],
  ];
  defaults.forEach(([id, val]) => {
    const el = document.getElementById(id);
    if (el) {
      el.value = val;
      el.dispatchEvent(new Event("input", { bubbles: true }));
    }
  });
  const dateToggle = document.getElementById("dateToggle");
  if (dateToggle && dateToggle.checked) {
    dateToggle.checked = false;
    dateToggle.dispatchEvent(new Event("change", { bubbles: true }));
  }
}

function resetNegativeTonalControls() {
  const ids = [
    ["negBrightnessSlider", "0.0"],
    ["negMidtoneNdSlider", "0.0"],
    ["negContrastSlider", "0.0"],
    ["negPushPullSlider", "0.0"],
    ["negLightsSlider", "0.0"],
    ["negDarksSlider", "0.0"],
    ["negWhitesSlider", "0.0"],
    ["negBlacksSlider", "0.0"],
    ["negBlackClipSlider", "0.00"],
    ["negWhiteClipSlider", "0.00"],
    ["negInkyBlacksSlider", "0.0"],
    ["negRpToneSlider", "0.0"],
    ["negSatSlider", "1.0"],
  ];
  ids.forEach(([id, val]) => {
    const el = document.getElementById(id);
    if (el) {
      el.value = val;
      el.dispatchEvent(new Event("input", { bubbles: true }));
    }
  });
  const cpToggle = document.getElementById("negClipProtectToggle");
  if (cpToggle && !cpToggle.checked) {
    cpToggle.checked = true;
    cpToggle.dispatchEvent(new Event("change", { bubbles: true }));
  }
}

function resetNegativeOpticalControls() {
  negativeState.sharpenMode = "off";
  document.querySelectorAll("#negSharpenModeBar .seg-btn").forEach((b) => {
    b.classList.toggle("active", b.dataset.sharpen === "off");
  });
  const ids = [
    ["negSharpenAmountSlider", "100"],
    ["negWarming85Slider", "0.0"],
    ["negSkylightSlider", "0.0"],
    ["negShadeSlider", "0.0"],
    ["negGlowSlider", "1.0"],
    ["negFadeSlider", "1.0"],
  ];
  ids.forEach(([id, val]) => {
    const el = document.getElementById(id);
    if (el) {
      el.value = val;
      el.dispatchEvent(new Event("input", { bubbles: true }));
    }
  });
  syncNegProcessPanels();
}

function resetNegativeColorControls() {
  negativeState.shadowsTint = [0.0, 0.0, 0.0];
  negativeState.midsTint = [0.0, 0.0, 0.0];
  negativeState.highsTint = [0.0, 0.0, 0.0];
  const ids = [
    ["cmyRedSlider", "0.0"],
    ["cmyGreenSlider", "0.0"],
    ["cmyBlueSlider", "0.0"],
    ["negTempSlider", "0.0"],
    ["negTintSlider", "0.0"],
    ["negShadowsRangeSlider", "50"],
    ["negHighsRangeSlider", "50"],
  ];
  ids.forEach(([id, val]) => {
    const el = document.getElementById(id);
    if (el) {
      el.value = val;
      el.dispatchEvent(new Event("input", { bubbles: true }));
    }
  });
  selectCmyZone(negativeState.activeCmyZone);
}

// =============================================================
// KEYBOARD SHORTCUTS
// =============================================================

function initKeyboardShortcuts() {
  window.addEventListener("keydown", (e) => {
    const tag = (e.target && e.target.tagName) || "";
    const inTextInput =
      tag === "SELECT" ||
      tag === "TEXTAREA" ||
      (tag === "INPUT" &&
        e.target.type !== "range" &&
        e.target.type !== "checkbox" &&
        e.target.type !== "file");

    // Escape closes active eyedropper or open modals
    if (e.key === "Escape") {
      if (negativeState.eyedropperActive) {
        setEyedropperMode(null);
        return;
      }
      document.querySelectorAll(".modal-backdrop.active").forEach((m) => m.classList.remove("active"));
      return;
    }

    // Cmd/Ctrl + S / Shift+Cmd+S / Cmd+O / Shift+Cmd+C / Shift+Cmd+V
    if (e.metaKey || e.ctrlKey) {
      const k = e.key.toLowerCase();
      if (k === "s") {
        e.preventDefault();
        if (e.shiftKey) saveAsWithDialog();
        else saveDirectToDownloads();
        return;
      }
      if (k === "o") {
        e.preventDefault();
        document.getElementById("fileInput")?.click();
        return;
      }
      if (e.shiftKey && k === "c") {
        e.preventDefault();
        copyCurrentRecipe();
        return;
      }
      if (e.shiftKey && k === "v") {
        e.preventDefault();
        pasteCopiedRecipe();
        return;
      }
    }

    if (inTextInput) return;

    // Hold '\' for quick before/after original inspection
    if (e.key === "\\" && !state.holdingOriginal && state.viewMode !== "sheet") {
      state.holdingOriginal = true;
      state.prevViewMode = state.viewMode;
      setViewMode("original");
      return;
    }

    if (e.key === "1") setViewMode("split");
    else if (e.key === "2") setViewMode("full");
    else if (e.key === "3") setViewMode("sheet");
    else if (e.key === "0") resetZoom();
    else if (e.key === "+" || e.key === "=") setZoom(state.zoom + 0.25);
    else if (e.key === "-") setZoom(state.zoom - 0.25);
    else if (e.key === "r" || e.key === "R") {
      rotateCurrentFrame(e.shiftKey ? -90 : 90);
    } else if (e.key === "f" || e.key === "F") {
      toggleHorizontalFlip();
    } else if ((e.key === "i" || e.key === "I") && state.appMode === "negative") {
      setEyedropperMode(negativeState.eyedropperMode === "base" ? null : "base");
    } else if ((e.key === "w" || e.key === "W") && state.appMode === "negative") {
      setEyedropperMode(negativeState.eyedropperMode === "scene_wb" ? null : "scene_wb");
    } else if (e.key === "l" || e.key === "L") {
      toggleSafelight();
    } else if (e.key === "?") {
      document.getElementById("shortcutsModal")?.classList.toggle("active");
    }
  });

  window.addEventListener("keyup", (e) => {
    if (e.key === "\\" && state.holdingOriginal) {
      state.holdingOriginal = false;
      setViewMode(state.prevViewMode || "split");
    }
  });
}

function toggleSafelight() {
  state.safelight = !state.safelight;
  document.body.classList.toggle("theme-safelight", state.safelight);
  document.getElementById("safelightToggle")?.classList.toggle("active", state.safelight);
}

// =============================================================
// EXPORT, SAVE AS, CONTACT SHEET & RECIPE RESTORATION
// =============================================================

async function saveDirectToDownloads() {
  if (state.frames.length === 0) return;
  if (state.viewMode === "sheet") {
    return saveContactSheetOnly(false);
  }
  const activeFrame = state.frames[state.activeFrameIndex];
  const fmtUpper = state.outputFormat.toUpperCase();

  showLoading(true, `Revelando copia maestra (${fmtUpper}) en Descargas…`);
  try {
    const endpoint =
      state.appMode === "negative"
        ? "/api/negative/save_to_downloads"
        : "/api/save_direct_to_downloads";

    const analogMeta = buildAnalogMetaPayload();
    const payload =
      state.appMode === "negative"
        ? {
            filename: activeFrame.filename,
            format: state.outputFormat,
            reveal: true,
            analog_meta: analogMeta,
            ...buildNegativePayload(),
          }
        : {
            filename: activeFrame.filename,
            film: state.selectedFilm,
            ev: state.ev,
            halation: state.halation,
            grain: state.grain,
            vignette: state.vignette,
            date: state.date,
            rotate: state.rotate,
            flip_h: state.flip_h,
            format: state.outputFormat,
            reveal: true,
            analog_meta: analogMeta,
          };

    const res = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok || !data.success) {
      throw new Error(data.error || "No se pudo guardar el archivo");
    }

    const copy = getOsCopy();
    showToast(
      `Guardado (${data.width}×${data.height})`,
      `${copy.downloadsPrefix}${data.filename} · Original intacto`,
      copy.revealCta,
      () => revealFileInFinder(data.saved_path)
    );
  } catch (err) {
    console.error("Save error:", err);
    showToast("Error al guardar", err.message || "Revisa permisos de escritura.");
  } finally {
    showLoading(false);
  }
}

async function saveAsWithDialog() {
  if (state.frames.length === 0) return;
  if (state.viewMode === "sheet") {
    return saveContactSheetOnly(true);
  }
  const activeFrame = state.frames[state.activeFrameIndex];
  const stem = activeFrame.filename.replace(/\.[^/.]+$/, "");
  const ext = state.outputFormat === "tiff" ? ".tiff" : state.outputFormat === "png" ? ".png" : ".jpg";
  const defaultName =
    state.appMode === "negative"
      ? `${stem}_positive_${negativeState.profile}${ext}`
      : `${stem}_${state.selectedFilm}${ext}`;

  try {
    let chosenPath = null;

    if (window.pywebview && window.pywebview.api && window.pywebview.api.save_file_dialog) {
      chosenPath = await window.pywebview.api.save_file_dialog(defaultName);
    } else {
      const dlgRes = await fetch("/api/choose_save_path", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ default_name: defaultName }),
      });
      const dlgData = await dlgRes.json();
      if (dlgData.cancelled) return;
      chosenPath = dlgData.chosen_path;
    }

    if (!chosenPath) return;

    showLoading(true, "Guardando copia maestra a resolución nativa…");
    const endpoint =
      state.appMode === "negative" ? "/api/negative/save_to_path" : "/api/save_to_path";

    const analogMeta = buildAnalogMetaPayload();
    const payload =
      state.appMode === "negative"
        ? {
            filename: activeFrame.filename,
            dest_path: chosenPath,
            analog_meta: analogMeta,
            ...buildNegativePayload(),
          }
        : {
            filename: activeFrame.filename,
            film: state.selectedFilm,
            ev: state.ev,
            halation: state.halation,
            grain: state.grain,
            vignette: state.vignette,
            date: state.date,
            rotate: state.rotate,
            flip_h: state.flip_h,
            dest_path: chosenPath,
            analog_meta: analogMeta,
          };

    const res = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (res.ok && data.success) {
      showToast(
        "Archivo exportado",
        data.saved_path,
        getOsCopy().revealCta,
        () => revealFileInFinder(data.saved_path)
      );
    } else {
      throw new Error(data.error || "Fallo al escribir archivo");
    }
  } catch (err) {
    console.error("Save As error:", err);
    showToast("Error en Guardar como", err.message || "Operación interrumpida.");
  } finally {
    showLoading(false);
  }
}

async function developFullRoll() {
  if (state.frames.length === 0) return;
  showLoading(
    true,
    `Revelando ${state.frames.length} fotograma(s) a máxima resolución y creando hoja de contactos…`
  );

  try {
    const filenames = state.frames.map((f) => f.filename);
    const perFrameRecipes = buildPerFrameRecipesMap();
    const analogMeta = buildAnalogMetaPayload();
    const isNeg = state.appMode === "negative";
    const endpoint = isNeg ? "/api/negative/develop_full" : "/api/develop_full";
    const payload = isNeg
      ? {
          filenames,
          sheet: true,
          format: state.outputFormat,
          roll_name: "HALURO_NEG",
          per_frame_recipes: perFrameRecipes,
          analog_meta: analogMeta,
          ...buildNegativePayload(),
        }
      : {
          filenames,
          film: state.selectedFilm,
          ev: state.ev,
          halation: state.halation,
          grain: state.grain,
          vignette: state.vignette,
          date: state.date,
          rotate: state.rotate,
          flip_h: state.flip_h,
          format: state.outputFormat,
          sheet: true,
          roll_name: "HALURO_ROLL",
          per_frame_recipes: perFrameRecipes,
          analog_meta: analogMeta,
        };

    const res = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok || !data.success) throw new Error(data.error || "Fallo al procesar rollo");

    state.lastRollResult = data;
    const summary = document.getElementById("modalSummary");
    if (summary) {
      summary.textContent = `Se procesaron ${data.total_frames} fotograma(s) en ${data.elapsed_seconds}s sin tocar tus archivos originales. Incluye hoja de contactos de archivo.`;
    }
    document.getElementById("resultModal")?.classList.add("active");
  } catch (err) {
    console.error("Error revelando rollo:", err);
    showToast("Error en lote", err.message || "No se pudo completar el rollo.");
  } finally {
    showLoading(false);
  }
}

function buildContactSheetSignature() {
  const filenames = state.frames.map((f) => f.filename).join(",");
  const recipes = JSON.stringify(buildPerFrameRecipesMap());
  if (state.appMode === "negative") {
    return `neg_${filenames}_${recipes}_${JSON.stringify(buildNegativePayload())}`;
  } else {
    return `pos_${filenames}_${recipes}_${state.selectedFilm}_${state.ev}_${state.halation}_${state.grain}_${state.vignette}_${state.date}_${state.rotate}_${state.flip_h}`;
  }
}

async function generateContactSheetPreview() {
  if (state.frames.length === 0) return;
  const sig = buildContactSheetSignature();
  const sheetImg = document.getElementById("sheetPreview");

  // Instant display from client-side cache if settings didn't change
  if (state.contactSheetCache && state.contactSheetCache.signature === sig && state.contactSheetCache.url) {
    if (sheetImg) {
      sheetImg.src = state.contactSheetCache.url;
    }
    return;
  }

  showLoading(true, "Componiendo hoja de contactos analógica…");
  try {
    const filenames = state.frames.map((f) => f.filename);
    const perFrameRecipes = buildPerFrameRecipesMap();
    const isNeg = state.appMode === "negative";
    const endpoint = isNeg ? "/api/negative/contact_sheet_preview" : "/api/contact_sheet_preview";
    const payload = isNeg
      ? {
          filenames,
          roll_name: "PREVIEW_NEG",
          per_frame_recipes: perFrameRecipes,
          ...buildNegativePayload(),
        }
      : {
          filenames,
          film: state.selectedFilm,
          ev: state.ev,
          halation: state.halation,
          grain: state.grain,
          vignette: state.vignette,
          date: state.date,
          rotate: state.rotate,
          flip_h: state.flip_h,
          roll_name: "PREVIEW",
          per_frame_recipes: perFrameRecipes,
        };

    const res = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (data.success && data.sheet_url) {
      if (sheetImg) {
        sheetImg.src = data.sheet_url;
      }
      state.contactSheetCache = { signature: sig, url: data.sheet_url };
    }
  } catch (err) {
    console.error("Contact sheet preview error:", err);
    showToast("Error en contactos", err.message || "No se pudo componer la hoja.");
  } finally {
    showLoading(false);
  }
}

async function saveContactSheetOnly(withDialog = false) {
  if (state.frames.length === 0) return;
  const isNeg = state.appMode === "negative";
  const rollName = isNeg ? "HALURO_NEG" : "HALURO_ROLL";
  const defaultName = `Haluro_Contactos_${rollName}.jpg`;

  try {
    let chosenPath = null;
    if (withDialog) {
      if (window.pywebview && window.pywebview.api && window.pywebview.api.save_file_dialog) {
        chosenPath = await window.pywebview.api.save_file_dialog(defaultName);
      } else {
        const dlgRes = await fetch("/api/choose_save_path", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ default_name: defaultName }),
        });
        const dlgData = await dlgRes.json();
        if (dlgData.cancelled) return;
        chosenPath = dlgData.chosen_path;
      }
      if (!chosenPath) return;
    }

    showLoading(true, "Generando y guardando hoja de contactos en alta resolución…");
    const filenames = state.frames.map((f) => f.filename);
    const perFrameRecipes = buildPerFrameRecipesMap();
    const endpoint = isNeg ? "/api/negative/save_contact_sheet" : "/api/save_contact_sheet";
    const payload = isNeg
      ? {
          filenames,
          roll_name: rollName,
          dest_path: chosenPath,
          reveal: true,
          per_frame_recipes: perFrameRecipes,
          ...buildNegativePayload(),
        }
      : {
          filenames,
          film: state.selectedFilm,
          ev: state.ev,
          halation: state.halation,
          grain: state.grain,
          vignette: state.vignette,
          date: state.date,
          rotate: state.rotate,
          flip_h: state.flip_h,
          roll_name: rollName,
          dest_path: chosenPath,
          reveal: true,
          per_frame_recipes: perFrameRecipes,
        };

    const res = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok || !data.success) {
      throw new Error(data.error || "No se pudo guardar la hoja de contactos");
    }

    const copy = getOsCopy();
    showToast(
      `Hoja de contactos guardada (${data.width}×${data.height})`,
      `${copy.downloadsPrefix}${data.filename}`,
      copy.revealCta,
      () => revealFileInFinder(data.saved_path)
    );
  } catch (err) {
    console.error("Save contact sheet error:", err);
    showToast("Error al guardar contactos", err.message || "Operación interrumpida.");
  } finally {
    showLoading(false);
  }
}

async function openHistoryModal() {
  const modal = document.getElementById("historyModal");
  const list = document.getElementById("historyList");
  if (!modal || !list) return;

  modal.classList.add("active");
  list.innerHTML = `<div class="film-empty">Consultando archivo del laboratorio…</div>`;

  try {
    const res = await fetch("/api/history");
    const data = await res.json();
    const items = data.history || [];

    list.innerHTML = "";
    if (items.length === 0) {
      list.innerHTML = `<div class="film-empty">Aún no has exportado ninguna copia revelada. Pulsa <strong>Guardar</strong> para crear tu primera copia maestra.</div>`;
      return;
    }

    items.forEach((item) => {
      const meta = item.meta || {};
      const isNeg = meta.mode === "negative_inversion";
      const recipeTitle = isNeg
        ? `Negativo → ${meta.profile_name || meta.profile_key || "Minilab"}`
        : meta.film_name || meta.film_key || "Película analógica";

      const row = document.createElement("div");
      row.className = "history-item";

      const thumb = document.createElement("img");
      thumb.className = "history-thumb";
      thumb.src = `${item.url}?t=${Date.now()}`;
      thumb.alt = item.filename;

      const info = document.createElement("div");
      info.className = "history-info";

      const nameEl = document.createElement("div");
      nameEl.className = "history-name";
      nameEl.textContent = item.filename;

      const metaEl = document.createElement("div");
      metaEl.className = "history-meta";
      const resTxt = meta.output_resolution ? ` · ${meta.output_resolution}` : "";
      metaEl.textContent = `${recipeTitle}${resTxt} · ${item.mtime}`;

      info.appendChild(nameEl);
      info.appendChild(metaEl);

      const actions = document.createElement("div");
      actions.className = "history-actions";

      if (meta.mode) {
        const restoreBtn = document.createElement("button");
        restoreBtn.type = "button";
        restoreBtn.className = "btn btn-outline btn-xs";
        restoreBtn.textContent = "Restaurar receta";
        restoreBtn.addEventListener("click", () => {
          restoreRecipeFromMeta(meta);
          modal.classList.remove("active");
        });
        actions.appendChild(restoreBtn);
      }

      const finderBtn = document.createElement("button");
      finderBtn.type = "button";
      finderBtn.className = "btn btn-secondary btn-xs";
      finderBtn.textContent = getOsCopy().inFileManager;
      finderBtn.addEventListener("click", () => revealFileInFinder(item.path));
      actions.appendChild(finderBtn);

      row.appendChild(thumb);
      row.appendChild(info);
      row.appendChild(actions);
      list.appendChild(row);
    });
  } catch (err) {
    list.innerHTML = `<div class="film-empty">Error al leer el historial de versiones.</div>`;
  }
}

async function restoreRecipeFromMeta(meta) {
  if (!meta) return;

  if (typeof meta.rotate === "number") state.rotate = meta.rotate;
  if (typeof meta.flip_h === "boolean") {
    state.flip_h = meta.flip_h;
    document.getElementById("flipHBtn")?.classList.toggle("active", state.flip_h);
  }

  if (meta.mode === "negative_inversion") {
    await switchStudioMode("negative");
    applyNegRecipeToUI(
      {
        ...meta,
        profile: meta.profile_key || meta.profile || "frontier",
      },
      true
    );
    if (Array.isArray(meta.base_color)) {
      setBaseColor(meta.base_color, null, "Receta restaurada");
    }
  } else {
    await switchStudioMode("simulation");
    applySimRecipeToUI({
      film: meta.film_key || state.selectedFilm,
      ev: meta.ev_adjust ?? 0,
      halation: meta.halation_mult ?? 1.0,
      grain: meta.grain_mult ?? 1.0,
      vignette: meta.vignette_mult ?? 1.0,
      date: Boolean(meta.date_stamp),
      rotate: meta.rotate,
      flip_h: meta.flip_h,
    });
  }

  if (meta.analog_meta && typeof meta.analog_meta === "object" && Object.keys(meta.analog_meta).length > 0) {
    applyAnalogMetaToUI(meta.analog_meta, true);
  }

  saveActiveFrameRecipe();
  state.lastOriginalKey = "";
  updateActiveRecipeBanner();
  await requestPreview(true);
  showToast("Receta restaurada", "Todos los parámetros ópticos se han aplicado.");
}

// =============================================================
// DOM LISTENERS WIRING
// =============================================================

function initUIListeners() {
  // Primary mode tabs
  document.getElementById("tabDarkroomsMode")?.addEventListener("click", () => switchStudioMode("simulation"));
  document.getElementById("tabNegativeMode")?.addEventListener("click", () => switchStudioMode("negative"));

  // Top bar utilities & export
  document.getElementById("loadSampleBtn")?.addEventListener("click", () => loadSamplePhoto());
  document.getElementById("fileInput")?.addEventListener("change", (e) => {
    importFiles(e.target.files);
    e.target.value = "";
  });
  document.getElementById("safelightToggle")?.addEventListener("click", toggleSafelight);
  document.getElementById("historyBtn")?.addEventListener("click", openHistoryModal);
  document.getElementById("shortcutsBtn")?.addEventListener("click", () => {
    document.getElementById("shortcutsModal")?.classList.add("active");
  });
  document.getElementById("aboutBtn")?.addEventListener("click", () => {
    document.getElementById("aboutModal")?.classList.add("active");
  });

  // Smart update system listeners
  document.getElementById("updateBadgeBtn")?.addEventListener("click", openUpdateModal);
  document.getElementById("closeUpdateModalBtn")?.addEventListener("click", closeUpdateModal);
  document.getElementById("btnDismissUpdate")?.addEventListener("click", closeUpdateModal);
  document.getElementById("btnCheckUpdateManual")?.addEventListener("click", () => checkForUpdates(true));
  document.getElementById("btnDownloadUpdate")?.addEventListener("click", triggerUpdateDownload);

  document.getElementById("saveDownloadsBtn")?.addEventListener("click", saveDirectToDownloads);
  document.getElementById("saveAsBtn")?.addEventListener("click", saveAsWithDialog);
  document.getElementById("saveSheetBtn")?.addEventListener("click", () => saveContactSheetOnly(false));
  document.getElementById("sheetQuickSaveBtn")?.addEventListener("click", () => saveContactSheetOnly(false));
  document.getElementById("sheetSaveAsBtn")?.addEventListener("click", () => saveContactSheetOnly(true));
  document.getElementById("developFullBtn")?.addEventListener("click", developFullRoll);

  // Catalog search & category filter pills
  document.getElementById("filmSearch")?.addEventListener("input", (e) => {
    state.search = e.target.value;
    applyFilters();
  });

  document.querySelectorAll(".filter-pill").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".filter-pill").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.category = btn.dataset.category || "all";
      applyFilters();
    });
  });

  // Viewport modes & geometry
  document.getElementById("viewSplitBtn")?.addEventListener("click", () => setViewMode("split"));
  document.getElementById("viewFullBtn")?.addEventListener("click", () => setViewMode("full"));
  document.getElementById("viewOrigBtn")?.addEventListener("click", () => setViewMode("original"));
  document.getElementById("viewSheetBtn")?.addEventListener("click", () => setViewMode("sheet"));

  document.getElementById("rotateLeftBtn")?.addEventListener("click", () => rotateCurrentFrame(-90));
  document.getElementById("rotateRightBtn")?.addEventListener("click", () => rotateCurrentFrame(90));
  document.getElementById("flipHBtn")?.addEventListener("click", toggleHorizontalFlip);

  document.getElementById("zoomInBtn")?.addEventListener("click", () => setZoom(state.zoom + 0.25));
  document.getElementById("zoomOutBtn")?.addEventListener("click", () => setZoom(state.zoom - 0.25));
  document.getElementById("zoomResetBtn")?.addEventListener("click", resetZoom);

  // Per-frame recipe copy / paste / roll sync
  document.getElementById("copyRecipeBtn")?.addEventListener("click", copyCurrentRecipe);
  document.getElementById("pasteRecipeBtn")?.addEventListener("click", pasteCopiedRecipe);
  document.getElementById("syncRollBtn")?.addEventListener("click", syncRecipeToRoll);

  // Simulation controls
  document.getElementById("resetSimBtn")?.addEventListener("click", resetSimulationControls);

  const bindRange = (sliderId, labelId, formatter, onValue) => {
    const el = document.getElementById(sliderId);
    const lbl = document.getElementById(labelId);
    if (!el) return;
    el.addEventListener("input", (e) => {
      const val = parseFloat(e.target.value);
      if (lbl) lbl.textContent = formatter(val);
      onValue(val);
      saveActiveFrameRecipe();
      triggerDebouncedPreview();
    });
  };

  const fmtSigned = (v) => `${v > 0 ? "+" : ""}${v.toFixed(2)}`;

  bindRange("evSlider", "evVal", (v) => `${v > 0 ? "+" : ""}${v.toFixed(1)} EV`, (v) => {
    state.ev = v;
  });
  bindRange("halationSlider", "halationVal", (v) => `${v.toFixed(1)}x`, (v) => {
    state.halation = v;
  });
  bindRange("grainSlider", "grainVal", (v) => `${v.toFixed(1)}x`, (v) => {
    state.grain = v;
  });
  bindRange("vignetteSlider", "vignetteVal", (v) => `${v.toFixed(1)}x`, (v) => {
    state.vignette = v;
  });

  document.getElementById("dateToggle")?.addEventListener("change", (e) => {
    state.date = e.target.checked;
    requestPreview(false);
  });

  // Negative Lab left sidebar controls
  document.getElementById("btnTypeColor")?.addEventListener("click", () => {
    negativeState.filmType = "color";
    document.getElementById("btnTypeColor")?.classList.add("active");
    document.getElementById("btnTypeBW")?.classList.remove("active");
    syncNegProcessPanels();
    updateActiveRecipeBanner();
    if (negativeState.profile === "bw") {
      selectNegativeProfile("frontier");
    } else {
      saveActiveFrameRecipe();
      requestPreview(false);
    }
  });

  document.getElementById("btnTypeBW")?.addEventListener("click", () => {
    negativeState.filmType = "bw";
    document.getElementById("btnTypeBW")?.classList.add("active");
    document.getElementById("btnTypeColor")?.classList.remove("active");
    syncNegProcessPanels();
    selectNegativeProfile("bw");
  });

  document.querySelectorAll("#negScanSourceBar .seg-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#negScanSourceBar .seg-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      negativeState.scanSource = btn.dataset.source || "camera_raw";
      saveActiveFrameRecipe();
      requestPreview(false);
    });
  });

  bindRange("negPreSatSlider", "negPreSatVal", (v) => `${v.toFixed(2)}x`, (v) => {
    negativeState.preSaturation = v;
  });

  document.querySelectorAll("#negLightSourceBar .seg-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#negLightSourceBar .seg-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      negativeState.lightSource = btn.dataset.light || "standard";
      saveActiveFrameRecipe();
      requestPreview(false);
    });
  });

  document.querySelectorAll("#negColorMethodBar .seg-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#negColorMethodBar .seg-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      negativeState.colorMethod = btn.dataset.method || "dynamic";
      syncNegProcessPanels();
      saveActiveFrameRecipe();
      if (negativeState.colorMethod === "roll_locked" && !negativeState.rollBounds) {
        analyzeFullRoll();
      } else {
        requestPreview(false);
      }
    });
  });

  document.getElementById("btnAnalyzeRoll")?.addEventListener("click", analyzeFullRoll);

  document.querySelectorAll("#negToneVariantBar .seg-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#negToneVariantBar .seg-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      negativeState.toneVariant = btn.dataset.tone || "standard";
      saveActiveFrameRecipe();
      requestPreview(false);
    });
  });

  document.getElementById("negPrintFinishSelect")?.addEventListener("change", (e) => {
    negativeState.printFinish = e.target.value || "none";
    syncNegProcessPanels();
    saveActiveFrameRecipe();
    requestPreview(false);
  });

  bindRange("negFinishAmountSlider", "negFinishAmountVal", (v) => `${Math.round(v)}%`, (v) => {
    negativeState.finishAmount = v / 100;
  });

  document.getElementById("negBwTonerSelect")?.addEventListener("change", (e) => {
    negativeState.bwToner = e.target.value || "neutral";
    syncNegProcessPanels();
    updateActiveRecipeBanner();
    saveActiveFrameRecipe();
    requestPreview(false);
  });

  bindRange("negBwTonerStrengthSlider", "negBwTonerStrengthVal", (v) => `${Math.round(v)}%`, (v) => {
    negativeState.bwTonerStrength = v / 100;
  });

  document.getElementById("btnAutoBase")?.addEventListener("click", () => autoDetectBaseColor(true));
  document.getElementById("btnEyedropper")?.addEventListener("click", () => {
    setEyedropperMode(negativeState.eyedropperMode === "base" ? null : "base");
  });

  document.getElementById("btnSceneWbEyedropper")?.addEventListener("click", () => {
    setEyedropperMode(negativeState.eyedropperMode === "scene_wb" ? null : "scene_wb");
  });
  document.getElementById("btnAutoSceneWb")?.addEventListener("click", autoBalanceSceneWb);

  bindRange("negBufferSlider", "negBufferVal", (v) => `${Math.round(v)}%`, (v) => {
    negativeState.borderBuffer = v / 100;
  });
  bindRange("negCropSlider", "negCropVal", (v) => `${v.toFixed(1).replace(/\.0$/, "")}%`, (v) => {
    negativeState.cropPct = v / 100;
  });

  document.querySelectorAll("#negProfileList .profile-card").forEach((card) => {
    card.addEventListener("click", () => selectNegativeProfile(card.dataset.profile));
    card.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        selectNegativeProfile(card.dataset.profile);
      }
    });
  });

  // Negative Lab right sidebar tonal, CMY & optical filter controls
  document.getElementById("resetNegTonalBtn")?.addEventListener("click", resetNegativeTonalControls);
  document.getElementById("resetNegColorBtn")?.addEventListener("click", resetNegativeColorControls);
  document.getElementById("resetNegOpticalBtn")?.addEventListener("click", resetNegativeOpticalControls);

  const fmtPct0 = (v) => `${Math.round(v * 100)}%`;

  bindRange("negBrightnessSlider", "negBrightnessVal", fmtSigned, (v) => {
    negativeState.brightness = v;
  });
  bindRange("negMidtoneNdSlider", "negMidtoneNdVal", fmtSigned, (v) => {
    negativeState.midtoneNd = v;
  });
  bindRange("negContrastSlider", "negContrastVal", fmtSigned, (v) => {
    negativeState.contrast = v;
  });
  bindRange("negPushPullSlider", "negPushPullVal", fmtSigned, (v) => {
    negativeState.pushPull = v;
  });
  bindRange("negLightsSlider", "negLightsVal", fmtSigned, (v) => {
    negativeState.lights = v;
  });
  bindRange("negDarksSlider", "negDarksVal", fmtSigned, (v) => {
    negativeState.darks = v;
  });
  bindRange("negWhitesSlider", "negWhitesVal", fmtSigned, (v) => {
    negativeState.whites = v;
  });
  bindRange("negBlacksSlider", "negBlacksVal", fmtSigned, (v) => {
    negativeState.blacks = v;
  });
  bindRange("negBlackClipSlider", "negBlackClipVal", fmtSigned, (v) => {
    negativeState.blackClip = v;
  });
  bindRange("negWhiteClipSlider", "negWhiteClipVal", fmtSigned, (v) => {
    negativeState.whiteClip = v;
  });
  document.getElementById("negClipProtectToggle")?.addEventListener("change", (e) => {
    negativeState.clipProtect = Boolean(e.target.checked);
    saveActiveFrameRecipe();
    requestPreview(false);
  });
  bindRange("negInkyBlacksSlider", "negInkyBlacksVal", fmtPct0, (v) => {
    negativeState.inkyBlacks = v;
  });
  bindRange("negRpToneSlider", "negRpToneVal", fmtPct0, (v) => {
    negativeState.rpTone = v;
  });
  bindRange("negSatSlider", "negSatVal", (v) => `${v.toFixed(2)}x`, (v) => {
    negativeState.saturation = v;
  });

  document.querySelectorAll("#cmyZoneBar .seg-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      selectCmyZone(btn.dataset.zone || "global");
    });
  });

  bindRange("cmyRedSlider", "cmyRedVal", fmtSigned, (v) => {
    negativeState.cmy[0] = v;
  });
  bindRange("cmyGreenSlider", "cmyGreenVal", fmtSigned, (v) => {
    negativeState.cmy[1] = v;
  });
  bindRange("cmyBlueSlider", "cmyBlueVal", fmtSigned, (v) => {
    negativeState.cmy[2] = v;
  });
  bindRange("zoneCmyRedSlider", "zoneCmyRedVal", fmtSigned, (v) => {
    getZoneTripletRef(negativeState.activeCmyZone)[0] = v;
    updateCmyZoneDots();
  });
  bindRange("zoneCmyGreenSlider", "zoneCmyGreenVal", fmtSigned, (v) => {
    getZoneTripletRef(negativeState.activeCmyZone)[1] = v;
    updateCmyZoneDots();
  });
  bindRange("zoneCmyBlueSlider", "zoneCmyBlueVal", fmtSigned, (v) => {
    getZoneTripletRef(negativeState.activeCmyZone)[2] = v;
    updateCmyZoneDots();
  });
  bindRange("negShadowsRangeSlider", "negShadowsRangeVal", (v) => `${Math.round(v)}%`, (v) => {
    negativeState.shadowsRange = v / 100;
  });
  bindRange("negHighsRangeSlider", "negHighsRangeVal", (v) => `${Math.round(v)}%`, (v) => {
    negativeState.highsRange = v / 100;
  });
  bindRange("negTempSlider", "negTempVal", fmtSigned, (v) => {
    negativeState.temp = v;
  });
  bindRange("negTintSlider", "negTintVal", fmtSigned, (v) => {
    negativeState.tint = v;
  });

  document.querySelectorAll("#negSharpenModeBar .seg-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#negSharpenModeBar .seg-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      negativeState.sharpenMode = btn.dataset.sharpen || "off";
      syncNegProcessPanels();
      saveActiveFrameRecipe();
      requestPreview(false);
    });
  });

  bindRange("negSharpenAmountSlider", "negSharpenAmountVal", (v) => `${Math.round(v)}%`, (v) => {
    negativeState.sharpenAmount = v / 100;
  });

  bindRange("negWarming85Slider", "negWarming85Val", fmtPct0, (v) => {
    negativeState.warming85 = v;
  });
  bindRange("negSkylightSlider", "negSkylightVal", fmtPct0, (v) => {
    negativeState.skylightFilter = v;
  });
  bindRange("negShadeSlider", "negShadeVal", fmtPct0, (v) => {
    negativeState.shadeFilter = v;
  });
  bindRange("negGlowSlider", "negGlowVal", (v) => `${v.toFixed(1)}x`, (v) => {
    negativeState.glow = v;
  });
  bindRange("negFadeSlider", "negFadeVal", (v) => `${v.toFixed(1)}x`, (v) => {
    negativeState.fade = v;
  });

  // Output master format selector
  document.querySelectorAll("#outputFormatPills .fmt-pill").forEach((pill) => {
    pill.addEventListener("click", () => {
      document.querySelectorAll("#outputFormatPills .fmt-pill").forEach((p) => p.classList.remove("active"));
      pill.classList.add("active");
      state.outputFormat = pill.dataset.format || "jpg";
    });
  });

  document.getElementById("openFolderBtn")?.addEventListener("click", async () => {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.open_developed_folder) {
      await window.pywebview.api.open_developed_folder();
      return;
    }
    await fetch("/api/open_folder", { method: "POST" });
  });

  // Modal actions & backdrop dismissal
  document.getElementById("closeModalBtn")?.addEventListener("click", () => {
    document.getElementById("resultModal")?.classList.remove("active");
  });
  document.getElementById("closeHistoryBtn")?.addEventListener("click", () => {
    document.getElementById("historyModal")?.classList.remove("active");
  });
  document.getElementById("closeShortcutsBtn")?.addEventListener("click", () => {
    document.getElementById("shortcutsModal")?.classList.remove("active");
  });
  document.getElementById("closeAboutBtn")?.addEventListener("click", () => {
    document.getElementById("aboutModal")?.classList.remove("active");
  });
  document.getElementById("btnCopyAboutInfo")?.addEventListener("click", () => {
    const text =
      "Haluro — Laboratorio Analógico Digital (v2.4.3)\n" +
      "Desarrollador: Fotógrafo César Fernández Ardiles (Oregano, Chile)\n" +
      "Licencia: MIT (Software libre y gratuito)\n" +
      "Emulación: 72 películas químicas + Inversión óptica C-41 / B&N\n" +
      "100% No destructivo · 100% Local y privado\n" +
      "Exportación: TIFF 16-bit real (48-bit RGB) + EXIF analógico";
    navigator.clipboard?.writeText(text).then(() => {
      showToast("Ficha copiada al portapapeles", "Información técnica y de autor de Haluro.");
    });
  });

  document.querySelectorAll(".modal-backdrop").forEach((backdrop) => {
    backdrop.addEventListener("click", (e) => {
      if (e.target === backdrop) backdrop.classList.remove("active");
    });
  });

  document.getElementById("modalSaveZipBtn")?.addEventListener("click", async () => {
    if (!state.lastRollResult) return;
    const res = await fetch("/api/save_zip_to_downloads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ roll_folder: state.lastRollResult.roll_folder }),
    });
    const data = await res.json();
    if (data.success) {
      document.getElementById("resultModal")?.classList.remove("active");
      showToast("ZIP guardado en Descargas", data.saved_path);
    }
  });

  document.getElementById("modalOpenRollBtn")?.addEventListener("click", () => {
    if (state.lastRollResult?.roll_dir) {
      revealFileInFinder(state.lastRollResult.roll_dir);
    }
  });
}

function selectNegativeProfile(profileKey) {
  if (!profileKey) return;
  negativeState.profile = profileKey;
  document.querySelectorAll("#negProfileList .profile-card").forEach((c) => {
    c.classList.toggle("selected", c.dataset.profile === profileKey);
    c.setAttribute("aria-selected", c.dataset.profile === profileKey ? "true" : "false");
  });
  syncNegProcessPanels();
  saveActiveFrameRecipe();
  updateActiveRecipeBanner();
  requestPreview(false);
}

// =============================================================
// FEEDBACK HELPERS (LOADING, BUSY DOT, FINDER, TOASTS)
// =============================================================

function setRenderBusy(isBusy) {
  document.getElementById("renderDot")?.classList.toggle("busy", Boolean(isBusy));
}

function showLoading(visible, message = "Procesando en el laboratorio…") {
  const overlay = document.getElementById("loadingOverlay");
  const msgEl = document.getElementById("loadingMessage");
  if (msgEl && message) msgEl.textContent = message;
  overlay?.classList.toggle("active", Boolean(visible));
}

async function revealFileInFinder(path) {
  if (window.pywebview && window.pywebview.api && window.pywebview.api.reveal_file) {
    await window.pywebview.api.reveal_file(path);
    return;
  }
  await fetch("/api/reveal_in_finder", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
}

function showToast(title, desc, actionLabel = null, actionCallback = null) {
  const container = document.getElementById("toastContainer");
  if (!container) return;

  const toast = document.createElement("div");
  toast.className = "toast";

  const content = document.createElement("div");
  content.className = "toast-content";

  const tEl = document.createElement("div");
  tEl.className = "toast-title";
  tEl.textContent = title;

  const dEl = document.createElement("div");
  dEl.className = "toast-desc";
  dEl.textContent = desc;

  content.appendChild(tEl);
  content.appendChild(dEl);
  toast.appendChild(content);

  if (actionLabel && typeof actionCallback === "function") {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "toast-action";
    btn.textContent = actionLabel;
    btn.addEventListener("click", () => {
      actionCallback();
      toast.remove();
    });
    toast.appendChild(btn);
  }

  container.appendChild(toast);
  setTimeout(() => {
    if (toast.parentNode) toast.remove();
  }, 5500);
}

// =============================================================
// SMART IN-APP UPDATE SYSTEM
// =============================================================

async function checkForUpdates(manual = false) {
  const statusEl = document.getElementById("aboutUpdateStatus");
  const manualBtn = document.getElementById("btnCheckUpdateManual");
  const manualLabel = document.getElementById("btnCheckUpdateManualLabel");
  const badgeBtn = document.getElementById("updateBadgeBtn");
  const badgeText = document.getElementById("updateBadgeText");

  if (manual) {
    if (statusEl) statusEl.textContent = "Comprobando actualizaciones con GitHub...";
    if (manualLabel) manualLabel.textContent = "Buscando...";
    if (manualBtn) manualBtn.disabled = true;
  }

  try {
    const res = await fetch("/api/check-update");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    state.updateInfo = data;

    if (data.update_available) {
      if (badgeBtn) {
        badgeBtn.style.display = "inline-flex";
        if (badgeText) badgeText.textContent = `v${data.latest_version} disponible`;
      }
      if (statusEl) {
        statusEl.classList.add("has-update");
        statusEl.textContent = `✨ Nueva versión v${data.latest_version} disponible (${data.release_date || "reciente"})`;
      }
      if (manual) {
        openUpdateModal();
      } else {
        showToast(
          "Actualización de Haluro disponible",
          `La versión v${data.latest_version} está lista para descargar con mejoras de laboratorio.`,
          "Ver novedades",
          () => openUpdateModal()
        );
      }
    } else {
      if (badgeBtn) badgeBtn.style.display = "none";
      if (data.offline) {
        if (statusEl) statusEl.textContent = `Modo offline · Versión ${data.current_version} instalada`;
        if (manual) {
          showToast("Modo Offline", "No fue posible comprobar actualizaciones. Verifica tu conexión a internet.");
        }
      } else {
        if (statusEl) {
          statusEl.classList.remove("has-update");
          statusEl.textContent = `Versión ${data.current_version} instalada (¡Al día!)`;
        }
        if (manual) {
          showToast("Haluro está actualizado", `Estás utilizando la versión más reciente (v${data.current_version}).`);
        }
      }
    }
  } catch (err) {
    console.debug("Comprobación de actualización omitida:", err);
    if (manual) {
      if (statusEl) statusEl.textContent = "Error al conectar con el servidor de actualizaciones.";
      showToast("Comprobación no disponible", "No se pudo consultar el repositorio en este momento.");
    }
  } finally {
    if (manual) {
      if (manualLabel) manualLabel.textContent = "Comprobar ahora";
      if (manualBtn) manualBtn.disabled = false;
    }
  }
}

function openUpdateModal() {
  const modal = document.getElementById("updateModal");
  if (!modal) return;
  const info = state.updateInfo;
  if (!info || !info.update_available) {
    checkForUpdates(true);
    return;
  }

  const titleEl = document.getElementById("updateModalTitle");
  const versionTag = document.getElementById("updateVersionTag");
  const descEl = document.getElementById("updateModalDesc");
  const listEl = document.getElementById("updateHighlightsList");
  const platEl = document.getElementById("updatePlatformLabel");
  const dlLabel = document.getElementById("btnDownloadUpdateLabel");

  if (titleEl) titleEl.textContent = info.title || `¡Haluro v${info.latest_version} disponible!`;
  if (versionTag) versionTag.textContent = `v${info.current_version} ➔ v${info.latest_version}`;
  if (descEl && info.description) descEl.textContent = info.description;
  if (platEl) platEl.textContent = `Equipo detectado: ${info.platform}`;
  if (dlLabel) dlLabel.textContent = `Descargar para ${info.platform}`;

  if (listEl) {
    listEl.innerHTML = "";
    const items = info.highlights && info.highlights.length > 0
      ? info.highlights
      : ["Mejoras generales de rendimiento y calibración de color."];
    items.forEach((itemText) => {
      const li = document.createElement("li");
      li.textContent = itemText;
      listEl.appendChild(li);
    });
  }

  // Close about modal if open so they don't stack
  document.getElementById("aboutModal")?.classList.remove("active");
  modal.classList.add("active");
}

function closeUpdateModal() {
  document.getElementById("updateModal")?.classList.remove("active");
}

async function triggerUpdateDownload() {
  const info = state.updateInfo;
  if (!info) return;
  const downloadUrl = info.download_url || info.all_releases_url || "https://github.com/Hermesuser/haluro/releases/latest";

  try {
    await fetch("/api/open-external", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: downloadUrl }),
    });
  } catch (_) {
    window.open(downloadUrl, "_blank", "noopener");
  }

  showToast(
    "Descarga de actualización iniciada",
    "Se ha abierto el enlace en tu navegador para descargar el instalador."
  );
  closeUpdateModal();
}
