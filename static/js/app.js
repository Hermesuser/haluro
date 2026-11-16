/**
 * Haluro — Laboratorio Analógico Digital (v2.5.0)
 * Precision frontend controller: 80-stock film simulation, C-41/B&W optical negative
 * inversion (RA-4, ECP 2383, Minilab, V-Log), B&W chemical toners & fine-art papers,
 * unified multi-frame Roll Analysis, 3-Way CMY split-toning, color-protected soft clip,
 * luminance optical sharpening, 16-bit TIFF export, and native Analog EXIF stamping.
 */

const FAVORITES_KEY = "haluro_favorites_v2";
const ANALOG_EXIF_STORAGE_KEY = "haluro_analog_exif_v23";
const USER_PREFS_KEY = "haluro_user_prefs_v1";
const FRAME_RECIPES_KEY = "haluro_frame_recipes_v1";
const MAX_STORED_FRAMES = 50;

/**
 * Local-session guard.
 *
 * The backend only listens on 127.0.0.1, but a page open in the same browser
 * could still forge requests against it, and a DNS-rebinding attack could make
 * the browser believe the app lives on a foreign origin. The server issues a
 * per-process token in a <meta> tag and requires it on every state-changing
 * call, so we inject it into every outgoing request here, once.
 */
(function installLocalSessionGuard() {
  const meta = document.querySelector('meta[name="haluro-api-token"]');
  const token = meta ? (meta.content || "").trim() : "";
  if (!token) return;
  const nativeFetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    const options = init || {};
    const headers = new Headers(options.headers || {});
    if (!headers.has("X-Haluro-Token")) {
      headers.set("X-Haluro-Token", token);
    }
    return nativeFetch(input, { ...options, headers });
  };
})();

// Iconos SVG en línea (estrella llena/hueca y aspa) — comillas simples para no romper el JS
const ICON_STAR_FILL = '<svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor" aria-hidden="true"><path d="M12 2.6l2.9 5.9 6.5.95-4.7 4.58 1.1 6.47L12 17.44 6.2 20.5l1.1-6.47L2.6 9.45l6.5-.95z"/></svg>';
const ICON_STAR_OUTLINE = '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" aria-hidden="true"><path d="M12 2.6l2.9 5.9 6.5.95-4.7 4.58 1.1 6.47L12 17.44 6.2 20.5l1.1-6.47L2.6 9.45l6.5-.95z"/></svg>';
const ICON_X_MARK = '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>';

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

// =============================================================
// PERSISTENCIA DE PREFERENCIAS DE USUARIO (entre sesiones)
// =============================================================

const USER_PREFS_DEFAULTS = {
  appMode: "simulation",
  selectedFilm: "portra400",
  // Simulación
  ev: 0.0,
  halation: 1.0,
  grain: 1.0,
  vignette: 1.0,
  date: false,
  rotate: 0,
  flip_h: false,
  flip_v: false,
  straighten: 0.0,
  keystone_v: 0.0,
  keystone_h: 0.0,
  auto_crop_straighten: true,
  outputFormat: "jpg",
  viewMode: "split",
  splitPercent: 50,
  zoom: 1.0,
  panX: 0,
  panY: 0,
  // Negativo
  filmType: "color",
  scanSource: "camera_raw",
  preSaturation: 1.0,
  lightSource: "standard",
  colorMethod: "dynamic",
  toneVariant: "standard",
  printFinish: "none",
  finishAmount: 1.0,
  bwToner: "neutral",
  bwTonerStrength: 1.0,
  bwGrade00: 0.0,
  bwGrade5: 0.0,
  bwPreflash: 0.0,
  profile: "frontier",
  easelBorder: "none",
  dryDownComp: 0.0,
  uiEssential: false,
};

function loadUserPreferences() {
  try {
    const raw = localStorage.getItem(USER_PREFS_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return { ...USER_PREFS_DEFAULTS, ...parsed };
  } catch (_) {
    return null;
  }
}

function saveUserPreferences() {
  try {
    const prefs = {
      appMode: state.appMode,
      selectedFilm: state.selectedFilm,
      devProcess: state.devProcess,
      ev: state.ev,
      halation: state.halation,
      grain: state.grain,
      grainAsa: state.grainAsa,
      vignette: state.vignette,
      shadows: state.shadows,
      mids: state.mids,
      highlights: state.highlights,
      date: state.date,
      rotate: state.rotate,
      flip_h: state.flip_h,
      flip_v: state.flip_v,
      outputFormat: state.outputFormat,
      viewMode: state.viewMode,
      splitPercent: state.splitPercent,
      zoom: state.zoom,
      panX: state.panX,
      panY: state.panY,
      filmType: negativeState.filmType,
      scanSource: negativeState.scanSource,
      preSaturation: negativeState.preSaturation,
      lightSource: negativeState.lightSource,
      colorMethod: negativeState.colorMethod,
      toneVariant: negativeState.toneVariant,
      printFinish: negativeState.printFinish,
      finishAmount: negativeState.finishAmount,
      bwToner: negativeState.bwToner,
      bwTonerStrength: negativeState.bwTonerStrength,
      bwGrade00: negativeState.bwGrade00,
      bwGrade5: negativeState.bwGrade5,
      bwPreflash: negativeState.bwPreflash,
      profile: negativeState.profile,
      easelBorder: state.easelBorder,
      dryDownComp: state.dryDownComp,
      uiEssential: state.uiEssential,
    };
    localStorage.setItem(USER_PREFS_KEY, JSON.stringify(prefs));
  } catch (_) {
    // Ignore storage quota errors
  }
}

// Persistencia de recetas por frame entre sesiones (no destructivo)
function loadStoredFrameRecipes() {
  try {
    const raw = localStorage.getItem(FRAME_RECIPES_KEY);
    if (!raw) return {};
    return JSON.parse(raw);
  } catch (_) {
    return {};
  }
}

function saveStoredFrameRecipes() {
  try {
    const framesByName = {};
    for (const frame of state.frames) {
      if (!frame.filename) continue;
      const entry = {};
      if (frame.simRecipe) entry.simRecipe = frame.simRecipe;
      if (frame.negRecipe) entry.negRecipe = frame.negRecipe;
      if (frame.pickStatus) entry.pickStatus = frame.pickStatus;
      framesByName[frame.filename] = entry;
    }
    // Limitar cuota: mantener solo los últimos N frames
    const names = Object.keys(framesByName);
    if (names.length > MAX_STORED_FRAMES) {
      const keep = names.slice(names.length - MAX_STORED_FRAMES);
      const trimmed = {};
      for (const n of keep) trimmed[n] = framesByName[n];
      Object.assign(framesByName, trimmed);
    }
    localStorage.setItem(FRAME_RECIPES_KEY, JSON.stringify(framesByName));
  } catch (_) {
    // Ignore storage quota errors
  }
}

function restoreFrameRecipe(frame) {
  if (!frame || !frame.filename) return;
  try {
    const raw = localStorage.getItem(FRAME_RECIPES_KEY);
    if (!raw) return;
    const store = JSON.parse(raw);
    const entry = store[frame.filename];
    if (!entry) return;
    if (entry.simRecipe) frame.simRecipe = clonePlain(entry.simRecipe);
    if (entry.negRecipe) frame.negRecipe = clonePlain(entry.negRecipe);
    if (entry.pickStatus !== undefined) frame.pickStatus = entry.pickStatus;
    // Reconstruir stacks de undo/redo vacíos para este frame
    ensureFrameHistory(frame);
  } catch (_) {
    // Ignorar errores de almacenamiento
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
  filmSort: "catalog", // 'catalog' | 'iso'

  frames: [], // { filename, name, is_raw, thumb_url, pickStatus: null|'pick'|'reject' }
  activeFrameIndex: 0,

  // Mode 1: Film Simulation controls
  devProcess: "standard",
  ev: 0.0,
  halation: 1.0,
  grain: 1.0,
  grainAsa: "auto",
  vignette: 1.0,
  // Tonal zones (exposure per zone, in stops)
  shadows: 0.0,
  mids: 0.0,
  highlights: 0.0,
  // Tone curve: control points per channel (null = identity)
  curve: null,
  curveChannel: "rgb",
  date: false,

  // Shared non-destructive geometry & export
  rotate: 0, // 0 | 90 | 180 | 270
  flip_h: false,
  flip_v: false,
  straighten: 0.0, // -45..45 deg
  keystone_v: 0.0, // -30..30 deg
  keystone_h: 0.0, // -30..30 deg
  crop_rect: null, // null | { x, y, w, h } normalized [0..1]
  auto_crop_straighten: true,
  cropMode: false,
  horizonDrawMode: false,
  cropAspect: "free",
  cropAspectSwapped: false,
  outputFormat: "jpg", // 'jpg' | 'png' | 'tiff' | 'dng' | 'original'
  easelBorder: "none",
  dryDownComp: 0.0,

  // Viewport & Light Table
  viewMode: "split", // 'split' | 'full' | 'original' | 'sheet' | 'teststrip'
  prevViewMode: "split",
  testStripStepEv: 0.5,
  testStripSteps: [],
  holdingOriginal: false,
  splitPercent: 50,
  zoom: 1.0,
  panX: 0,
  panY: 0,
  safelight: false,
  sidebarsCollapsed: false,
  uiEssential: false,
  spacePressed: false,
  zebraMode: { shadows: false, highlights: false },

  // Contact Sheet Light Table
  sheetColumns: 4,
  sheetRollName: "",
  hideRejectedInSheet: false,
  sheetZoom: 1.0,
  sheetPanX: 0,
  sheetPanY: 0,
  sheetLayout: [],

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
  filmSubstrate: "c41_orange", // 'c41_orange' | 'clear_base' | 'phoenix' | 'warm_base' | 'creative_switch'
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
  bwGrade00: 0.0,
  bwGrade5: 0.0,
  bwPreflash: 0.0,
  profile: "frontier",
  baseColor: null, // [r_lin, g_lin, b_lin] or null (auto)
  baseHex: "#E45F21",
  eyedropperActive: false,
  eyedropperMode: null, // null | 'base' | 'scene_wb'

  borderBuffer: 0.06,
  cropPct: 0.0,
  keepSprockets: false,
  flatFieldFile: null,
  flatFieldLabel: "",
  flatFieldStrength: 1.0,
  showBorderGuide: false,
  borderGuideTempActive: false,

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
  dustRadius: 0.008,
  dustSpots: [],
  curve: null,
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

let previewAbortController = null;
let offscreenHistCanvas = null;
let offscreenOrigLoupeCanvas = null;
let offscreenDevLoupeCanvas = null;
let origLoupeSourceReady = false;
let devLoupeSourceReady = false;
let suppressAutoSliderUndo = false;
let lastFocusedBeforeModal = null;

function setBackgroundInert(inert) {
  ["header.app-header", "main.studio-layout"].forEach((sel) => {
    const el = document.querySelector(sel);
    if (!el) return;
    // Use the attribute rather than the IDL property: `HTMLElement.inert` does
    // not exist on Safari / WKWebView before 15.5, where assigning it silently
    // created a meaningless JS property and left the background focusable.
    el.toggleAttribute("inert", Boolean(inert));
    if (Boolean(inert)) {
      el.setAttribute("aria-hidden", "true");
    } else {
      el.removeAttribute("aria-hidden");
    }
  });
}

function setModalOpen(modalOrId, open) {
  const modal = typeof modalOrId === "string" ? document.getElementById(modalOrId) : modalOrId;
  if (!modal) return;
  const shouldOpen = Boolean(open);

  if (shouldOpen) {
    if (!document.querySelector(".modal-backdrop.active") && document.activeElement instanceof HTMLElement) {
      lastFocusedBeforeModal = document.activeElement;
    }
    modal.classList.add("active");
    modal.setAttribute("aria-hidden", "false");
    setBackgroundInert(true);

    requestAnimationFrame(() => {
      const target = modal.querySelector(
        "button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])"
      );
      if (target && typeof target.focus === "function") {
        target.focus();
      } else {
        const box = modal.querySelector(".modal-box");
        if (box) {
          box.setAttribute("tabindex", "-1");
          box.focus();
        }
      }
    });
    return;
  }

  modal.classList.remove("active");
  modal.setAttribute("aria-hidden", "true");
  if (!document.querySelector(".modal-backdrop.active")) {
    setBackgroundInert(false);
    if (lastFocusedBeforeModal && lastFocusedBeforeModal.isConnected && typeof lastFocusedBeforeModal.focus === "function") {
      lastFocusedBeforeModal.focus();
    }
    lastFocusedBeforeModal = null;
  }
}

function toggleZenSidebars(forceState = null) {
  const next = forceState === null ? !state.sidebarsCollapsed : Boolean(forceState);
  state.sidebarsCollapsed = next;
  document.querySelector(".studio-layout")?.classList.toggle("sidebars-collapsed", next);
  const btn = document.getElementById("zenToggleBtn");
  if (btn) {
    btn.classList.toggle("active", next);
    btn.setAttribute("aria-pressed", next ? "true" : "false");
  }
  setTimeout(() => {
    applyZoomTransform();
  }, 180);
}

function toggleEssentialView(forceState = null, { silent = false } = {}) {
  const next = forceState === null ? !state.uiEssential : Boolean(forceState);
  state.uiEssential = next;
  document.body.classList.toggle("ui-essential", next);
  const btn = document.getElementById("uiComplexityBtn");
  const lbl = document.getElementById("uiComplexityLabel");
  if (btn) {
    btn.classList.toggle("active", next);
    btn.setAttribute("aria-pressed", next ? "true" : "false");
  }
  if (lbl) lbl.textContent = next ? "Esencial" : "Completa";
  if (next && typeof selectCmyZone === "function" && negativeState.activeCmyZone !== "global") {
    selectCmyZone("global");
  }
  if (!silent) {
    saveUserPreferences();
    showToast(
      next ? "Vista Esencial (Minilab)" : "Vista Completa de laboratorio",
      next
        ? "Controles rápidos tipo Minilab activos (pulsa V para volver)."
        : "Todos los cajones de calibración y EXIF visibles."
    );
  }
}

function nudgeExposure(delta) {
  if (state.frames.length === 0) return;
  pushUndoSnapshotForFrame();
  if (state.appMode === "negative") {
    const next = Math.max(-1.0, Math.min(1.0, Math.round((negativeState.brightness + delta) * 100) / 100));
    negativeState.brightness = next;
    const fmtS = `${next > 0 ? "+" : ""}${next.toFixed(2)}`;
    setSliderSilent("negBrightnessSlider", "negBrightnessVal", next, fmtS);
  } else {
    const slider = document.getElementById("evSlider");
    const minEv = slider ? parseFloat(slider.min) : -2.0;
    const maxEv = slider ? parseFloat(slider.max) : 2.0;
    const next = Math.max(minEv, Math.min(maxEv, Math.round((state.ev + delta) * 10) / 10));
    state.ev = next;
    setSliderSilent("evSlider", "evVal", next, `${next > 0 ? "+" : ""}${next.toFixed(1)} EV`);
  }
  saveActiveFrameRecipe();
  saveUserPreferences();
  requestPreview(false);
}

function nudgeCmyChannel(channelIdx, delta) {
  if (state.appMode !== "negative" || negativeState.filmType !== "color" || state.frames.length === 0) return;
  if (negativeState.activeCmyZone !== "global") selectCmyZone("global");
  pushUndoSnapshotForFrame();
  const cur = Number(negativeState.cmy[channelIdx]) || 0;
  const next = Math.max(-1.0, Math.min(1.0, Math.round((cur + delta) * 100) / 100));
  negativeState.cmy[channelIdx] = next;
  const sliderMap = [
    ["cmyRedSlider", "cmyRedVal"],
    ["cmyGreenSlider", "cmyGreenVal"],
    ["cmyBlueSlider", "cmyBlueVal"],
  ];
  const pair = sliderMap[channelIdx];
  if (pair) {
    setSliderSilent(pair[0], pair[1], next, `${next > 0 ? "+" : ""}${next.toFixed(2)}`);
  }
  saveActiveFrameRecipe();
  requestPreview(false);
}

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
      undoRedoKbd: "Ctrl + Z / Ctrl + Y",
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
      undoRedoKbd: "Ctrl + Z / Ctrl + Shift + Z",
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
    undoRedoKbd: "⌘ Z / ⇧ ⌘ Z",
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
  const kbdUndoRedo = document.getElementById("kbdUndoRedo");
  if (kbdSave) kbdSave.textContent = copy.saveKbd;
  if (kbdSaveAs) kbdSaveAs.textContent = copy.saveAsKbd;
  if (kbdOpen) kbdOpen.textContent = copy.openKbd;
  if (kbdCopyPaste) kbdCopyPaste.textContent = copy.copyPasteKbd;
  if (kbdUndoRedo) kbdUndoRedo.textContent = copy.undoRedoKbd;

  const copyBtn = document.getElementById("copyRecipeBtn");
  const pasteBtn = document.getElementById("pasteRecipeBtn");
  if (copyBtn) copyBtn.title = `Copiar receta óptica del fotograma activo (${copy.copyRecipeKbd})`;
  if (pasteBtn) pasteBtn.title = `Pegar receta copiada en este fotograma (${copy.pasteRecipeKbd})`;

  updateContextualExportBar();
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
  document.querySelectorAll(".modal-backdrop").forEach((m) => m.setAttribute("aria-hidden", "true"));
  initAnalogExifControls();
  initUIListeners();
  enhanceControlPrecision();
  initCurveEditor();
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
  await applyStoredPreferences();
  await loadSamplePhoto(false);

  // Smart update checker: silently query remote version manifest after 2.5s
  setTimeout(() => {
    checkForUpdates(false);
  }, 2500);
});

async function applyStoredPreferences() {
  const prefs = loadUserPreferences();
  if (!prefs) return;

  // Restaurar modo de aplicación
  if (prefs.appMode && prefs.appMode !== state.appMode) {
    await switchStudioMode(prefs.appMode);
  }

  // Restaurar película seleccionada (solo si existe en el catálogo cargado)
  if (prefs.selectedFilm) {
    const filmExists = state.films.some((f) => f.key === prefs.selectedFilm);
    if (filmExists) {
      state.selectedFilm = prefs.selectedFilm;
      selectFilm(prefs.selectedFilm);
    }
  }

  // Restaurar controles de simulación
  for (const key of ["devProcess", "ev", "halation", "grain", "grainAsa", "vignette", "shadows", "mids", "highlights", "date", "rotate", "flip_h", "outputFormat", "easelBorder", "dryDownComp", "viewMode", "splitPercent", "zoom", "panX", "panY"]) {
    if (key in prefs) state[key] = prefs[key];
  }
  if (state.viewMode === "teststrip") state.viewMode = "split";

  // Restaurar controles de negativo
  for (const key of ["filmType", "filmSubstrate", "scanSource", "preSaturation", "lightSource", "colorMethod", "toneVariant", "printFinish", "finishAmount", "bwToner", "bwTonerStrength", "bwGrade00", "bwGrade5", "bwPreflash", "profile", "keepSprockets"]) {
    if (key in prefs) negativeState[key] = prefs[key];
  }

  // Aplicar valores a sliders y UI
  applyPrefsToUI(prefs);
  if ("uiEssential" in prefs) {
    toggleEssentialView(Boolean(prefs.uiEssential), { silent: true });
  }
}

function applyPrefsToUI(prefs) {
  const setSlider = (id, val) => {
    const el = document.getElementById(id);
    if (el && val !== undefined) {
      el.value = val;
      el.dispatchEvent(new Event("input"));
    }
  };
  const setCheckbox = (id, val) => {
    const el = document.getElementById(id);
    if (el && val !== undefined) el.checked = Boolean(val);
  };

  if (prefs.devProcess !== undefined) {
    const el = document.getElementById("simDevProcessSelect");
    if (el) el.value = prefs.devProcess || "standard";
  }
  if (prefs.grainAsa !== undefined) {
    const el = document.getElementById("grainAsaSelect");
    if (el) el.value = prefs.grainAsa || "auto";
  }
  if (prefs.ev !== undefined) setSlider("evSlider", prefs.ev);
  if (prefs.halation !== undefined) setSlider("halationSlider", prefs.halation);
  if (prefs.grain !== undefined) setSlider("grainSlider", prefs.grain);
  if (prefs.vignette !== undefined) setSlider("vignetteSlider", prefs.vignette);
  if (prefs.shadows !== undefined) setSlider("shadowsSlider", prefs.shadows);
  if (prefs.mids !== undefined) setSlider("midsSlider", prefs.mids);
  if (prefs.highlights !== undefined) setSlider("highlightsSlider", prefs.highlights);
  if (prefs.date !== undefined) setCheckbox("dateToggle", prefs.date);
  if (prefs.rotate !== undefined) {
    const el = document.getElementById("rotateSlider");
    if (el) el.value = prefs.rotate;
  }
  if (prefs.flip_h !== undefined) setCheckbox("flipHToggle", prefs.flip_h);
  if (prefs.flip_v !== undefined) state.flip_v = Boolean(prefs.flip_v);
  if (prefs.outputFormat !== undefined) {
    state.outputFormat = prefs.outputFormat || "jpg";
    document.querySelectorAll("#outputFormatPills .fmt-pill").forEach((pill) => {
      const isMatch = pill.dataset.format === state.outputFormat;
      pill.classList.toggle("active", isMatch);
      pill.setAttribute("aria-checked", isMatch ? "true" : "false");
    });
  }
  if (prefs.easelBorder !== undefined) {
    const el = document.getElementById("easelBorderSelect");
    if (el) el.value = prefs.easelBorder || "none";
  }
  if (prefs.dryDownComp !== undefined) {
    const el = document.getElementById("dryDownSelect");
    if (el) el.value = Number(prefs.dryDownComp || 0).toFixed(2).replace(/0$/, "");
  }

  // Negativo UI
  if (prefs.filmType !== undefined) {
    const btn = document.getElementById(prefs.filmType === "color" ? "btnTypeColor" : "btnTypeBW");
    if (btn) btn.click();
  }
  if (prefs.filmSubstrate !== undefined) {
    const el = document.getElementById("negSubstrateSelect");
    if (el) el.value = prefs.filmSubstrate;
  }
  if (prefs.lightSource !== undefined) {
    const btn = document.querySelector(`#negLightSourceBar .seg-btn[data-light="${prefs.lightSource}"]`);
    if (btn) btn.click();
  }
  if (prefs.toneVariant !== undefined) {
    const btn = document.querySelector(`#negToneVariantBar .seg-btn[data-tone="${prefs.toneVariant}"]`);
    if (btn) btn.click();
  }
  if (prefs.printFinish !== undefined) {
    const el = document.getElementById("negPrintFinishSelect");
    if (el) el.value = prefs.printFinish;
  }
  if (prefs.bwToner !== undefined) {
    const el = document.getElementById("negBwTonerSelect");
    if (el) el.value = prefs.bwToner;
  }
  if (prefs.profile !== undefined) {
    // selectNegativeProfile hace click interno; aplicamos directamente si existe
    const card = document.querySelector(`#negProfileList .profile-card[data-profile="${prefs.profile}"]`);
    if (card) card.click();
  }
  if (prefs.finishAmount !== undefined) setSlider("negFinishAmountSlider", prefs.finishAmount * 100);
  if (prefs.bwTonerStrength !== undefined) setSlider("negBwTonerStrengthSlider", prefs.bwTonerStrength * 100);
  if (prefs.bwGrade00 !== undefined) setSlider("negBwGrade00Slider", prefs.bwGrade00);
  if (prefs.bwGrade5 !== undefined) setSlider("negBwGrade5Slider", prefs.bwGrade5);
  if (prefs.bwPreflash !== undefined) setSlider("negBwPreflashSlider", prefs.bwPreflash * 100);
  if (prefs.borderBuffer !== undefined) setSlider("negBufferSlider", prefs.borderBuffer * 100);
  if (prefs.cropPct !== undefined) setSlider("negCropSlider", prefs.cropPct * 100);
  if (prefs.keepSprockets !== undefined) setCheckbox("negKeepSprocketsToggle", prefs.keepSprockets);
  if (prefs.brightness !== undefined) setSlider("negBrightnessSlider", prefs.brightness);
  if (prefs.midtoneNd !== undefined) setSlider("negMidtoneNdSlider", prefs.midtoneNd);
  if (prefs.contrast !== undefined) setSlider("negContrastSlider", prefs.contrast);
  if (prefs.pushPull !== undefined) setSlider("negPushPullSlider", prefs.pushPull);
  if (prefs.lights !== undefined) setSlider("negLightsSlider", prefs.lights);
  if (prefs.darks !== undefined) setSlider("negDarksSlider", prefs.darks);
  if (prefs.whites !== undefined) setSlider("negWhitesSlider", prefs.whites);
  if (prefs.blacks !== undefined) setSlider("negBlacksSlider", prefs.blacks);
  if (prefs.blackClip !== undefined) setSlider("negBlackClipSlider", prefs.blackClip);
  if (prefs.whiteClip !== undefined) setSlider("negWhiteClipSlider", prefs.whiteClip);
  if (prefs.clipProtect !== undefined) setCheckbox("negClipProtectToggle", prefs.clipProtect);
  if (prefs.inkyBlacks !== undefined) setSlider("negInkyBlacksSlider", prefs.inkyBlacks);
  if (prefs.rpTone !== undefined) setSlider("negRpToneSlider", prefs.rpTone);
  if (prefs.saturation !== undefined) setSlider("negSatSlider", prefs.saturation);
  if (prefs.sharpenMode !== undefined) {
    const btn = document.querySelector(`#negSharpenModeBar .seg-btn[data-sharpen="${prefs.sharpenMode}"]`);
    if (btn) btn.click();
  }
  if (prefs.sharpenAmount !== undefined) setSlider("negSharpenAmountSlider", prefs.sharpenAmount * 100);
  if (prefs.warming85 !== undefined) setSlider("negWarming85Slider", prefs.warming85);
  if (prefs.temp !== undefined) setSlider("negTempSlider", prefs.temp);
  if (prefs.tint !== undefined) setSlider("negTintSlider", prefs.tint);
}

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
// LEFT SIDEBAR: 80 FILM STOCKS & FAVORITES
// =============================================================

function applyFilters() {
  const q = state.search.toLowerCase().trim();
  const clearBtn = document.getElementById("clearFilmSearchBtn");
  if (clearBtn) clearBtn.hidden = !state.search;
  const userLutToolbar = document.getElementById("userLutToolbar");
  if (userLutToolbar) userLutToolbar.hidden = state.category !== "user";

  const filtered = state.films.filter((f) => {
    const matchesCat =
      state.category === "all" ||
      (state.category === "fav" ? state.favorites.has(f.key) : f.kind === state.category);
    const isoText = `iso ${f.iso || ""}`;
    const matchesSearch =
      !q ||
      f.name.toLowerCase().includes(q) ||
      f.brand.toLowerCase().includes(q) ||
      f.key.toLowerCase().includes(q) ||
      isoText.includes(q) ||
      (f.desc && f.desc.toLowerCase().includes(q));
    return matchesCat && matchesSearch;
  });

  if (state.filmSort === "iso") {
    filtered.sort((a, b) => (Number(a.iso) || 0) - (Number(b.iso) || 0));
  }

  state.filteredFilms = filtered;

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
        ? "Aún no tienes películas marcadas como favoritas."
        : state.category === "user"
          ? "Aún no tienes LUTs propios. Pulsa «+ LUT» para importar archivos .cube."
          : "Ninguna película coincide con tu búsqueda.";
    container.appendChild(empty);
    return;
  }

  const frag = document.createDocumentFragment();
  state.filteredFilms.forEach((film) => {
    const isFav = state.favorites.has(film.key);
    const isSelected = film.key === state.selectedFilm;
    const card = document.createElement("div");
    card.className = `film-card ${isSelected ? "selected" : ""}`;
    card.dataset.key = film.key;
    card.dataset.kind = film.kind || "neg";
    card.setAttribute("role", "listitem");

    const selectBtn = document.createElement("button");
    selectBtn.type = "button";
    selectBtn.className = "film-card-select-btn";
    selectBtn.setAttribute("aria-pressed", isSelected ? "true" : "false");

    const header = document.createElement("div");
    header.className = "film-card-header";

    const title = document.createElement("span");
    title.className = "film-title";
    title.textContent = film.name;
    title.title = film.name; // el nombre puede recortarse: el tooltip lo revela

    const badges = document.createElement("div");
    badges.className = "film-badges-right";

    const iso = document.createElement("span");
    iso.className = "film-iso";
    iso.textContent = `ISO ${film.iso}`;

    badges.appendChild(iso);
    header.appendChild(title);
    header.appendChild(badges);

    const meta = document.createElement("div");
    meta.className = "film-card-meta";
    meta.textContent = film.desc ? `${film.category} · ${film.desc}` : film.category;

    selectBtn.appendChild(header);
    selectBtn.appendChild(meta);
    selectBtn.addEventListener("click", () => selectFilm(film.key));

    const favBtn = document.createElement("button");
    favBtn.type = "button";
    favBtn.className = `fav-btn ${isFav ? "is-fav" : ""}`;
    favBtn.title = isFav ? "Quitar de favoritas" : "Añadir a favoritas";
    favBtn.setAttribute("aria-label", `${favBtn.title}: ${film.name}`);
    favBtn.setAttribute("aria-pressed", isFav ? "true" : "false");
    favBtn.innerHTML = isFav ? ICON_STAR_FILL : ICON_STAR_OUTLINE;
    favBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      toggleFavoriteFilm(film.key);
    });

    card.appendChild(selectBtn);
    if (film.is_user_lut) {
      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.className = "user-lut-delete-btn";
      delBtn.title = "Eliminar LUT de usuario";
      delBtn.setAttribute("aria-label", `Eliminar LUT: ${film.name}`);
      delBtn.textContent = "×";
      delBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        deleteUserLut(film);
      });
      card.appendChild(delBtn);
    }
    card.appendChild(favBtn);

    frag.appendChild(card);
  });

  container.appendChild(frag);
}

async function uploadUserLuts(fileList) {
  const files = Array.from(fileList || []).filter((f) => f && f.name);
  if (!files.length) return;

  const spaceSelect = document.getElementById("userLutSpaceSelect");
  const lutSpace = spaceSelect ? spaceSelect.value : "srgb";
  const form = new FormData();
  form.append("lut_space", lutSpace);
  files.forEach((f) => form.append("files", f));

  try {
    const res = await fetch("/api/user_luts", { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok || !data.success) {
      showToast("Error al importar LUT", data.error || "No se pudo cargar el archivo .cube.");
      return;
    }

    if (Array.isArray(data.films)) {
      state.films = data.films;
    } else {
      await fetchFilms();
    }

    // Switch to "Mis LUTs" tab and select the first newly added LUT
    const userPill = document.querySelector('.filter-pill[data-category="user"]');
    if (userPill) {
      setToggleGroupActive(".filter-pill", userPill, "aria-pressed");
      state.category = "user";
    }
    applyFilters();

    if (data.added && data.added.length > 0) {
      selectFilm(data.added[0].key);
    }

    const addedCount = (data.added || []).length;
    const errCount = (data.errors || []).length;
    if (errCount > 0) {
      showToast(
        "LUTs importados con avisos",
        `${addedCount} añadido(s), ${errCount} rechazado(s): ${data.errors[0].filename} (${data.errors[0].error})`
      );
    } else {
      showToast("LUTs importados", `${addedCount} archivo(s) .cube listos en «Mis LUTs».`);
    }
  } catch (err) {
    console.error("Error subiendo LUTs de usuario:", err);
    showToast("Error de red", "No se pudieron importar los archivos .cube.");
  }
}

async function deleteUserLut(film) {
  try {
    const res = await fetch(`/api/user_luts/${encodeURIComponent(film.key)}`, { method: "DELETE" });
    const data = await res.json();
    if (!res.ok || !data.success) {
      showToast("Error al eliminar", data.error || "No se pudo eliminar el LUT.");
      return;
    }
    if (Array.isArray(data.films)) {
      state.films = data.films;
    } else {
      await fetchFilms();
    }
    if (state.selectedFilm === film.key) {
      selectFilm("portra400");
    } else {
      applyFilters();
    }
    showToast("LUT eliminado", `Se eliminó «${film.name}».`);
  } catch (err) {
    console.error("Error eliminando LUT de usuario:", err);
    showToast("Error de red", "No se pudo eliminar el LUT.");
  }
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
  if (key && key !== state.selectedFilm) {
    pushUndoSnapshotForFrame();
  }
  state.selectedFilm = key;
  document.querySelectorAll(".film-card").forEach((el) => {
    const sel = el.dataset.key === key;
    el.classList.toggle("selected", sel);
    const btn = el.querySelector(".film-card-select-btn");
    if (btn) btn.setAttribute("aria-pressed", sel ? "true" : "false");
  });
  saveActiveFrameRecipe();
  updateActiveRecipeBanner();
  renderBorderGuideOverlay();
  drawCurveEditor();
  requestPreview();
  saveUserPreferences();
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
        is_sample: true,
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
      syncEmptyRollButtons(false);
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
        is_sample: true,
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
      syncEmptyRollButtons(false);
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

  // Replace untouched single demo sample cleanly so user rolls stay pure
  const replacingUntouchedSample =
    state.frames.length === 1 &&
    state.frames[0].is_sample &&
    !isFrameCustomized(state.frames[0]);

  try {
    const newEntries = [];
    const failedMessages = [];
    for (const file of files) {
      const formData = new FormData();
      formData.append("file", file);
      const res = await fetch("/api/upload", { method: "POST", body: formData });
      let data = {};
      try {
        data = await res.json();
      } catch (_) {
        data = {};
      }
      if (res.ok && data.filename) {
        newEntries.push({
          filename: data.filename,
          name: data.name || file.name,
          is_raw: Boolean(data.is_raw),
          is_sample: false,
          thumb_url:
            data.thumb_url || `/api/thumbnail/${encodeURIComponent(data.filename)}?t=${Date.now()}`,
        });
        importedCount += 1;
      } else {
        failedMessages.push(`${file.name}: ${data.error || `Error HTTP ${res.status}`}`);
      }
    }

    if (importedCount > 0) {
      if (replacingUntouchedSample) {
        state.frames = [];
        state.activeFrameIndex = 0;
      }
      newEntries.forEach((entry) => {
        const existingIdx = state.frames.findIndex((f) => f.filename === entry.filename);
        if (existingIdx >= 0) {
          state.frames[existingIdx] = entry;
          state.activeFrameIndex = existingIdx;
          restoreFrameRecipe(state.frames[existingIdx]);
        } else {
          state.frames.push(entry);
          state.activeFrameIndex = state.frames.length - 1;
          restoreFrameRecipe(state.frames[state.activeFrameIndex]);
        }
      });

      state.lastOriginalKey = "";
      state.contactSheetCache = null;
      resetZoom();
      syncEmptyRollButtons(false);
      renderFilmStrip();
      if (state.appMode === "negative") {
        await autoDetectBaseColor(false);
      }
      await requestPreview(true);
      if (state.viewMode === "sheet") {
        generateContactSheetPreview();
      }
      const msg = failedMessages.length
        ? `${importedCount} cargada(s), ${failedMessages.length} omitida(s): ${failedMessages[0]}`
        : `${importedCount} fotograma(s) listos en la mesa de luz (original intacto).`;
      showToast("Importación completada", msg);
    } else if (failedMessages.length > 0) {
      showToast("No se pudo importar", failedMessages[0]);
    }
  } catch (err) {
    console.error("Error importando archivos:", err);
    showToast("Error de importación", "Verifica que el formato del archivo sea compatible.");
  } finally {
    showLoading(false);
  }
}

function getEffectiveRollName() {
  const custom = (state.sheetRollName || "").trim();
  if (custom) return custom;
  return state.appMode === "negative" ? "HALURO NEG" : "HALURO ROLL";
}

function isFrameCustomized(frame) {
  if (!frame) return false;
  if (state.appMode === "negative") {
    const r = frame.negRecipe;
    if (!r) return false;
    return (
      (r.profile && r.profile !== "frontier") ||
      (r.tone_variant && r.tone_variant !== "standard") ||
      (r.print_finish && r.print_finish !== "none") ||
      (r.bw_toner && r.bw_toner !== "neutral") ||
      Math.abs(r.brightness || 0) > 0.01 ||
      Math.abs(r.midtone_nd || 0) > 0.01 ||
      Math.abs(r.contrast || 0) > 0.01 ||
      Math.abs(r.push_pull || 0) > 0.01 ||
      Math.abs(r.lights || 0) > 0.01 ||
      Math.abs(r.darks || 0) > 0.01 ||
      Math.abs(r.whites || 0) > 0.01 ||
      Math.abs(r.blacks || 0) > 0.01 ||
      Math.abs(r.inky_blacks || 0) > 0.01 ||
      Math.abs(r.rp_tone || 0) > 0.01 ||
      Math.abs((r.saturation ?? 1.0) - 1.0) > 0.02 ||
      (Array.isArray(r.printer_cmy) && r.printer_cmy.some((v) => Math.abs(v) > 0.01)) ||
      (Array.isArray(r.shadows_tint) && r.shadows_tint.some((v) => Math.abs(v) > 0.01)) ||
      (Array.isArray(r.mids_tint) && r.mids_tint.some((v) => Math.abs(v) > 0.01)) ||
      (Array.isArray(r.highs_tint) && r.highs_tint.some((v) => Math.abs(v) > 0.01)) ||
      Math.abs(r.temp || 0) > 0.01 ||
      Math.abs(r.tint || 0) > 0.01 ||
      Math.abs(r.warming_85 || 0) > 0.01 ||
      Math.abs(r.skylight_filter || 0) > 0.01 ||
      Math.abs(r.shade_filter || 0) > 0.01 ||
      (r.sharpen_mode && r.sharpen_mode !== "off") ||
      Math.abs((r.glow ?? 1.0) - 1.0) > 0.05 ||
      Math.abs((r.fade ?? 1.0) - 1.0) > 0.05 ||
      Boolean(r.rotate) ||
      Boolean(r.flip_h)
    );
  }
  const r = frame.simRecipe;
  if (!r) return false;
  return (
    (r.film && r.film !== "portra400") ||
    Math.abs(r.ev || 0) > 0.01 ||
    Math.abs((r.halation ?? 1.0) - 1.0) > 0.05 ||
    Math.abs((r.grain ?? 1.0) - 1.0) > 0.05 ||
    (r.grain_asa && r.grain_asa !== "auto") ||
    Math.abs((r.vignette ?? 1.0) - 1.0) > 0.05 ||
    Boolean(r.date) ||
    Boolean(r.rotate) ||
    Boolean(r.flip_h)
  );
}

function updateActiveThumbEditedIndicator() {
  const strip = document.getElementById("stripFrames");
  if (!strip) return;
  const thumbs = strip.querySelectorAll(".film-frame-thumb");
  const activeThumb = thumbs[state.activeFrameIndex];
  const activeFrame = state.frames[state.activeFrameIndex];
  if (!activeThumb || !activeFrame) return;

  const custom = isFrameCustomized(activeFrame);
  let dot = activeThumb.querySelector(".frame-edited-dot");
  if (custom && !dot) {
    dot = document.createElement("span");
    dot.className = "frame-edited-dot";
    dot.title = "Fotograma con ajustes personalizados";
    activeThumb.appendChild(dot);
  } else if (!custom && dot) {
    dot.remove();
  }
}

async function activateFrameByIndex(idx, viewModeFromSheet = "full") {
  if (idx < 0 || idx >= state.frames.length) return;
  if (state.activeFrameIndex === idx && state.viewMode !== "sheet") return;
  saveActiveFrameRecipe();
  state.activeFrameIndex = idx;
  state.lastOriginalKey = "";
  const hadRecipe = loadFrameRecipe(idx);
  renderFilmStrip();
  const stripEl = document.getElementById("stripFrames");
  const activeThumb = stripEl?.querySelectorAll(".film-frame-thumb")[idx];
  if (stripEl && activeThumb) {
    const targetLeft = activeThumb.offsetLeft - (stripEl.clientWidth - activeThumb.clientWidth) / 2;
    stripEl.scrollTo({ left: Math.max(0, targetLeft), behavior: "smooth" });
  }
  if (state.viewMode === "sheet") setViewMode(viewModeFromSheet);
  if (state.appMode === "negative" && (!hadRecipe || negativeState.baseColor === null)) {
    await autoDetectBaseColor(false);
  }
  saveActiveFrameRecipe();
  requestPreview(true);
}

function updateUndoRedoButtons() {
  const undoBtn = document.getElementById("undoBtn");
  const redoBtn = document.getElementById("redoBtn");
  const frame = state.frames[state.activeFrameIndex];
  const unavailable = !frame || state.frames.length === 0 || state.viewMode === "sheet";
  if (unavailable) {
    if (undoBtn) undoBtn.disabled = true;
    if (redoBtn) redoBtn.disabled = true;
    return;
  }
  ensureFrameHistory(frame);
  const mode = state.appMode;
  if (undoBtn) undoBtn.disabled = (frame.undoStack[mode]?.length || 0) === 0;
  if (redoBtn) redoBtn.disabled = (frame.redoStack[mode]?.length || 0) === 0;
}

function updateToolbarAvailability() {
  const empty = state.frames.length === 0;
  const isSheet = state.viewMode === "sheet";

  [
    "saveDownloadsBtn",
    "saveAsBtn",
    "saveSheetBtn",
    "developFullBtn",
    "exportMoreBtn",
    "zoomOutBtn",
    "zoomResetBtn",
    "zoomInBtn",
    "viewSplitBtn",
    "viewFullBtn",
    "viewOrigBtn",
    "viewSheetBtn",
  ].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.disabled = empty;
  });

  [
    "rotateLeftBtn",
    "rotateRightBtn",
    "flipHBtn",
    "copyRecipeBtn",
    "syncRollBtn",
  ].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.disabled = empty || isSheet;
  });

  const pasteBtn = document.getElementById("pasteRecipeBtn");
  if (pasteBtn) {
    pasteBtn.disabled = empty || isSheet || !state.copiedRecipe;
  }

  updateUndoRedoButtons();
}

function syncEmptyRollButtons(isEmpty) {
  const empty = Boolean(isEmpty);
  document.body.classList.toggle("roll-empty", empty);
  const stockLbl = document.getElementById("statFilmLabel");
  if (stockLbl) stockLbl.textContent = empty ? "Receta preseleccionada" : "Receta activa";

  updateToolbarAvailability();

  const emptyBox = document.getElementById("emptyCanvasState");
  const splitWrapper = document.getElementById("splitWrapper");
  const sheetContainer = document.getElementById("sheetContainer");
  if (emptyBox) {
    emptyBox.style.display = empty ? "flex" : "none";
  }
  if (!empty) {
    if (state.viewMode === "sheet") {
      if (sheetContainer) sheetContainer.style.display = "flex";
      if (splitWrapper) splitWrapper.style.display = "none";
    } else {
      if (splitWrapper) splitWrapper.style.display = "block";
      if (sheetContainer) sheetContainer.style.display = "none";
    }
  } else {
    if (splitWrapper) splitWrapper.style.display = "none";
    if (sheetContainer) sheetContainer.style.display = "none";
  }
}

function getCullCounts() {
  let picks = 0;
  let rejects = 0;
  for (const frame of state.frames) {
    if (frame.pickStatus === "pick") picks += 1;
    else if (frame.pickStatus === "reject") rejects += 1;
  }
  return { picks, rejects, total: state.frames.length };
}

function getSheetFrames() {
  if (!state.hideRejectedInSheet) return state.frames;
  return state.frames.filter((frame) => frame.pickStatus !== "reject");
}

function updateCullSummaryUI() {
  const { picks, rejects, total } = getCullCounts();
  const bar = document.getElementById("stripCullBar");
  const text = document.getElementById("cullSummaryText");
  const clearBtn = document.getElementById("btnCullClearRejected");
  const sheetFilterBtn = document.getElementById("sheetHideRejectedBtn");
  const rejectedBadge = document.getElementById("rejectedCountBadge");

  if (bar) {
    const showBar = total > 0 && (picks > 0 || rejects > 0);
    bar.style.display = showBar ? "flex" : "none";
  }
  if (text) {
    const parts = [];
    if (picks > 0) parts.push(`${picks} elegida${picks === 1 ? "" : "s"}`);
    if (rejects > 0) parts.push(`${rejects} descartada${rejects === 1 ? "" : "s"}`);
    if (parts.length === 0) parts.push("Sin marcas aún");
    text.textContent = parts.join(" · ");
  }
  if (clearBtn) {
    clearBtn.style.display = rejects > 0 ? "inline-flex" : "none";
  }

  if (rejectedBadge) {
    rejectedBadge.textContent = String(rejects);
  }
  if (sheetFilterBtn) {
    sheetFilterBtn.style.display = rejects > 0 ? "inline-flex" : "none";
    if (rejects === 0 && state.hideRejectedInSheet) {
      state.hideRejectedInSheet = false;
    }
    sheetFilterBtn.classList.toggle("active", Boolean(state.hideRejectedInSheet && rejects > 0));
    sheetFilterBtn.setAttribute("aria-pressed", state.hideRejectedInSheet && rejects > 0 ? "true" : "false");
  }
}

function setFramePickStatus(idx, nextStatus, { silent = false } = {}) {
  const frame = state.frames[idx];
  if (!frame) return;
  const normalized = nextStatus === "pick" || nextStatus === "reject" ? nextStatus : null;
  if ((frame.pickStatus || null) === normalized) return;
  frame.pickStatus = normalized;
  state.contactSheetCache = null;
  renderFilmStrip();
  if (state.viewMode === "sheet" && state.hideRejectedInSheet) {
    if (getSheetFrames().length === 0) {
      state.hideRejectedInSheet = false;
      updateCullSummaryUI();
      showToast("Todos descartados", "Se muestran todos los fotogramas para no dejar la hoja vacía.");
    }
    generateContactSheetPreview();
  }
  if (!silent) {
    const labels = {
      pick: ["Fotograma elegido", `${frame.name} marcado para revelar.`],
      reject: ["Fotograma descartado", `${frame.name} marcado como descarte.`],
      null: ["Marca eliminada", `${frame.name} sin clasificación.`],
    };
    const [title, desc] = labels[String(normalized)];
    showToast(title, desc);
  }
}

function cycleFramePickStatus(idx) {
  const frame = state.frames[idx];
  if (!frame) return;
  const order = { null: "pick", pick: "reject", reject: null };
  const current = frame.pickStatus || null;
  setFramePickStatus(idx, order[String(current)] ?? "pick", { silent: true });
}

async function removeRejectedFrames() {
  const rejectsCount = state.frames.filter((f) => f.pickStatus === "reject").length;
  if (!rejectsCount) return;

  saveActiveFrameRecipe();
  const backup = {
    frames: clonePlain(state.frames),
    activeFrameIndex: state.activeFrameIndex,
  };
  const activeFilename = state.frames[state.activeFrameIndex]?.filename;
  const kept = state.frames.filter((f) => f.pickStatus !== "reject");

  state.frames = kept;
  state.contactSheetCache = null;
  state.sheetLayout = [];
  state.lastOriginalKey = "";
  state.hideRejectedInSheet = false;

  const restoreRejected = async () => {
    state.frames = backup.frames;
    state.activeFrameIndex = Math.max(0, Math.min(backup.activeFrameIndex, state.frames.length - 1));
    state.contactSheetCache = null;
    state.lastOriginalKey = "";
    syncEmptyRollButtons(false);
    loadFrameRecipe(state.activeFrameIndex);
    renderFilmStrip();
    await requestPreview(true);
    if (state.viewMode === "sheet") generateContactSheetPreview();
  };

  if (state.frames.length === 0) {
    state.activeFrameIndex = 0;
    renderEmptyRollUI();
    showToast(
      "Descartes retirados",
      `Se retiraron ${rejectsCount} fotograma(s) descartado(s).`,
      "Deshacer",
      restoreRejected
    );
    return;
  }

  const nextActiveIdx = state.frames.findIndex((f) => f.filename === activeFilename);
  state.activeFrameIndex = nextActiveIdx >= 0 ? nextActiveIdx : 0;
  const hadRecipe = loadFrameRecipe(state.activeFrameIndex);
  syncEmptyRollButtons(false);
  renderFilmStrip();
  if (state.appMode === "negative" && (!hadRecipe || negativeState.baseColor === null)) {
    await autoDetectBaseColor(false);
  }
  await requestPreview(true);
  if (state.viewMode === "sheet") {
    generateContactSheetPreview();
  }
  showToast(
    "Descartes retirados",
    `Se retiraron ${rejectsCount} fotograma(s) de la tira.`,
    "Deshacer",
    restoreRejected
  );
}

function reorderFrame(fromIdx, toIdx) {
  if (
    fromIdx < 0 ||
    toIdx < 0 ||
    fromIdx >= state.frames.length ||
    toIdx >= state.frames.length ||
    fromIdx === toIdx
  ) {
    return;
  }
  saveActiveFrameRecipe();
  const activeFrameRef = state.frames[state.activeFrameIndex];
  const [moved] = state.frames.splice(fromIdx, 1);
  state.frames.splice(toIdx, 0, moved);
  const newActiveIdx = state.frames.indexOf(activeFrameRef);
  if (newActiveIdx >= 0) state.activeFrameIndex = newActiveIdx;
  state.contactSheetCache = null;
  state.sheetLayout = [];
  renderFilmStrip();
  if (state.viewMode === "sheet") {
    generateContactSheetPreview();
  }
  showToast("Orden actualizado", `${moved.name} movido a la posición #${toIdx + 1}.`);
}

function renderEmptyRollUI() {
  syncEmptyRollButtons(true);
  renderFilmStrip();
  updateCullSummaryUI();
  const statRes = document.getElementById("statResolution");
  const statTime = document.getElementById("statTime");
  if (statRes) statRes.textContent = "Sin fotogramas";
  if (statTime) statTime.textContent = "—";
  const histCanvas = document.getElementById("histogramCanvas");
  if (histCanvas) {
    const ctx = histCanvas.getContext("2d");
    ctx?.clearRect(0, 0, histCanvas.width, histCanvas.height);
  }
}

async function removeFrameByIndex(idx) {
  if (idx < 0 || idx >= state.frames.length) return;
  saveActiveFrameRecipe();
  const prevIndex = state.activeFrameIndex;
  const removed = clonePlain(state.frames[idx]);
  state.frames.splice(idx, 1);
  state.contactSheetCache = null;
  state.sheetLayout = [];
  state.lastOriginalKey = "";

  const restoreRemoved = async () => {
    const insertAt = Math.max(0, Math.min(idx, state.frames.length));
    state.frames.splice(insertAt, 0, removed);
    state.activeFrameIndex = insertAt;
    state.contactSheetCache = null;
    state.lastOriginalKey = "";
    syncEmptyRollButtons(false);
    loadFrameRecipe(state.activeFrameIndex);
    renderFilmStrip();
    await requestPreview(true);
    if (state.viewMode === "sheet") generateContactSheetPreview();
  };

  if (state.frames.length === 0) {
    state.activeFrameIndex = 0;
    renderEmptyRollUI();
    showToast("Fotograma retirado", `${removed.name} eliminado del rollo.`, "Deshacer", restoreRemoved);
    return;
  }

  if (state.activeFrameIndex >= state.frames.length) {
    state.activeFrameIndex = state.frames.length - 1;
  } else if (idx < state.activeFrameIndex) {
    state.activeFrameIndex -= 1;
  }

  const hadRecipe = loadFrameRecipe(state.activeFrameIndex);
  syncEmptyRollButtons(false);
  renderFilmStrip();
  if (state.appMode === "negative" && (!hadRecipe || negativeState.baseColor === null)) {
    await autoDetectBaseColor(false);
  }
  await requestPreview(true);
  if (state.viewMode === "sheet") {
    generateContactSheetPreview();
  }
  if (idx === prevIndex || removed.negRecipe || removed.simRecipe) {
    showToast("Fotograma retirado", `${removed.name} eliminado del rollo.`, "Deshacer", restoreRemoved);
  }
}

function clearRollFrames() {
  if (state.frames.length === 0) return;
  saveActiveFrameRecipe();
  const backup = {
    frames: clonePlain(state.frames),
    activeFrameIndex: state.activeFrameIndex,
    rollBounds: negativeState.rollBounds ? clonePlain(negativeState.rollBounds) : null,
    rollFramesCount: negativeState.rollFramesCount || 0,
  };
  const count = state.frames.length;
  state.frames = [];
  state.activeFrameIndex = 0;
  state.contactSheetCache = null;
  state.sheetLayout = [];
  state.lastOriginalKey = "";
  negativeState.rollBounds = null;
  renderEmptyRollUI();
  showToast(
    "Rollo vaciado",
    `Se retiraron ${count} fotograma(s) de la mesa de luz.`,
    "Deshacer",
    async () => {
      state.frames = backup.frames;
      state.activeFrameIndex = Math.max(0, Math.min(backup.activeFrameIndex, state.frames.length - 1));
      negativeState.rollBounds = backup.rollBounds;
      negativeState.rollFramesCount = backup.rollFramesCount;
      state.lastOriginalKey = "";
      syncEmptyRollButtons(false);
      loadFrameRecipe(state.activeFrameIndex);
      renderFilmStrip();
      await requestPreview(true);
      if (state.viewMode === "sheet") generateContactSheetPreview();
    }
  );
}

let draggingFrameIndex = null;

function renderFilmStrip() {
  const strip = document.getElementById("stripFrames");
  if (!strip) return;
  // Clearing innerHTML resets the scroll position of the horizontal film
  // strip, which used to throw the photographer back to the first frame
  // whenever a pick/reject mark was toggled. Preserve it explicitly.
  const previousScrollLeft = strip.scrollLeft;
  strip.innerHTML = "";

  state.frames.forEach((frame, idx) => {
    const pickStatus = frame.pickStatus || null;
    const thumb = document.createElement("div");
    thumb.className = [
      "film-frame-thumb",
      idx === state.activeFrameIndex ? "active" : "",
      pickStatus === "pick" ? "pick-pick" : pickStatus === "reject" ? "pick-reject" : "",
    ]
      .filter(Boolean)
      .join(" ");
    thumb.dataset.index = String(idx);
    const custom = isFrameCustomized(frame);
    const sampleNote = frame.is_sample ? " · Muestra de prueba" : "";
    const pickNote =
      pickStatus === "pick" ? " · Elegido" : pickStatus === "reject" ? " · Descartado" : "";
    thumb.title = custom
      ? `${frame.name} (Fotograma #${idx + 1}${sampleNote}${pickNote} · Con ajustes propios)`
      : `${frame.name} (Fotograma #${idx + 1}${sampleNote}${pickNote})`;

    if (custom) {
      const dot = document.createElement("span");
      dot.className = "frame-edited-dot";
      dot.title = "Fotograma con ajustes personalizados";
      thumb.appendChild(dot);
    }

    const pickBtn = document.createElement("button");
    pickBtn.type = "button";
    pickBtn.className = "frame-pick-btn";
    pickBtn.innerHTML = pickStatus === "pick" ? ICON_STAR_FILL : pickStatus === "reject" ? ICON_X_MARK : "·";
    pickBtn.title =
      pickStatus === "pick"
        ? "Elegido (P) — clic para marcar descarte"
        : pickStatus === "reject"
        ? "Descartado (X) — clic para quitar marca"
        : "Clasificar fotograma (P elegir / X descartar)";
    pickBtn.setAttribute("aria-label", `Clasificar ${frame.name}`);
    pickBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      cycleFramePickStatus(idx);
    });
    thumb.appendChild(pickBtn);

    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "frame-remove-btn";
    removeBtn.title = "Quitar este fotograma del rollo";
    removeBtn.setAttribute("aria-label", `Quitar ${frame.name}`);
    removeBtn.textContent = "×";
    removeBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      removeFrameByIndex(idx);
    });
    thumb.appendChild(removeBtn);

    const img = document.createElement("img");
    img.src = frame.thumb_url || `/api/thumbnail/${encodeURIComponent(frame.filename)}`;
    img.alt = frame.name;
    img.loading = "lazy";
    img.draggable = false;

    const scrim = document.createElement("div");
    scrim.className = "frame-bottom-scrim";

    const nameCap = document.createElement("div");
    nameCap.className = "frame-name-caption";
    nameCap.textContent = frame.name;
    nameCap.title = frame.name; // el rótulo se recorta en fotogramas largos

    const badge = document.createElement("div");
    badge.className = "frame-number-badge";
    const numSpan = document.createElement("span");
    numSpan.textContent = `${String(idx + 1).padStart(2, "0")}A`;
    const typeSpan = document.createElement("span");
    typeSpan.textContent = frame.is_sample ? `DEMO · ${frame.is_raw ? "RAW" : "SCAN"}` : frame.is_raw ? "RAW" : "SCAN";
    badge.appendChild(numSpan);
    badge.appendChild(typeSpan);

    scrim.appendChild(nameCap);
    scrim.appendChild(badge);
    const selectBtn = document.createElement("button");
    selectBtn.type = "button";
    selectBtn.className = "film-frame-select-btn";
    selectBtn.setAttribute("aria-label", `Seleccionar fotograma ${idx + 1}: ${frame.name}`);
    if (idx === state.activeFrameIndex) {
      selectBtn.setAttribute("aria-current", "true");
    }
    selectBtn.appendChild(img);
    selectBtn.appendChild(scrim);
    selectBtn.addEventListener("click", () => activateFrameByIndex(idx, "split"));
    thumb.appendChild(selectBtn);

    // Drag-to-reorder frames within the light table strip
    thumb.draggable = state.frames.length > 1;
    if (thumb.draggable) {
      thumb.addEventListener("dragstart", (e) => {
        draggingFrameIndex = idx;
        thumb.classList.add("dragging");
        if (e.dataTransfer) {
          e.dataTransfer.effectAllowed = "move";
          e.dataTransfer.setData("text/x-haluro-frame", String(idx));
        }
      });
      thumb.addEventListener("dragover", (e) => {
        const types = Array.from(e.dataTransfer?.types || []);
        if (!types.includes("text/x-haluro-frame") || draggingFrameIndex === null || draggingFrameIndex === idx) {
          return;
        }
        e.preventDefault();
        if (e.dataTransfer) e.dataTransfer.dropEffect = "move";
        const rect = thumb.getBoundingClientRect();
        const isAfter = e.clientX >= rect.left + rect.width / 2;
        thumb.classList.toggle("drag-over-before", !isAfter);
        thumb.classList.toggle("drag-over-after", isAfter);
      });
      thumb.addEventListener("dragleave", () => {
        thumb.classList.remove("drag-over-before", "drag-over-after");
      });
      thumb.addEventListener("drop", (e) => {
        const types = Array.from(e.dataTransfer?.types || []);
        if (!types.includes("text/x-haluro-frame") || draggingFrameIndex === null) return;
        e.preventDefault();
        e.stopPropagation();
        const rect = thumb.getBoundingClientRect();
        const isAfter = e.clientX >= rect.left + rect.width / 2;
        const fromIdx = draggingFrameIndex;
        let toIdx = isAfter ? idx + 1 : idx;
        if (fromIdx < toIdx) toIdx -= 1;
        thumb.classList.remove("drag-over-before", "drag-over-after");
        draggingFrameIndex = null;
        reorderFrame(fromIdx, toIdx);
      });
      thumb.addEventListener("dragend", () => {
        draggingFrameIndex = null;
        strip.querySelectorAll(".film-frame-thumb").forEach((el) => {
          el.classList.remove("dragging", "drag-over-before", "drag-over-after");
        });
      });
    }

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

  if (state.frames.length > 0) {
    const clearBtn = document.createElement("button");
    clearBtn.type = "button";
    clearBtn.className = "film-frame-clear";
    clearBtn.id = "clearRollBtn";
    clearBtn.title = "Retirar todos los fotogramas de la tira (no borra archivos originales)";
    clearBtn.innerHTML = `<span style="font-size:13px;line-height:1;">${ICON_X_MARK}</span><span>Vaciar</span>`;
    clearBtn.addEventListener("click", clearRollFrames);
    strip.appendChild(clearBtn);
  }

  updateCullSummaryUI();
  updateUndoRedoButtons();

  // Restore the horizontal position the photographer was looking at.
  if (previousScrollLeft > 0) {
    strip.scrollLeft = previousScrollLeft;
  }
}

// =============================================================
// MODE SWITCHING (SIMULATION <-> NEGATIVE LAB)
// =============================================================

async function switchStudioMode(mode) {
  if (mode !== "simulation" && mode !== "negative") return;
  state.appMode = mode;
  saveUserPreferences();

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

  const sampleBtn = document.getElementById("loadSampleBtn");
  if (sampleBtn) {
    sampleBtn.title = isNeg
      ? "Cargar escaneo de negativo C-41 de prueba"
      : "Cargar fotografía Canon RAW de prueba";
  }
  const emptySampleBtn = document.getElementById("emptySampleBtn");
  if (emptySampleBtn) {
    emptySampleBtn.textContent = isNeg ? "Cargar muestra negativo" : "Cargar foto de prueba RAW";
  }

  const origLabel = document.getElementById("originalLabel");
  if (origLabel) {
    origLabel.textContent = isNeg ? "Negativo escaneado" : "Original";
  }

  const rollInput = document.getElementById("sheetRollNameInput");
  if (rollInput) {
    rollInput.placeholder = isNeg ? "HALURO NEG" : "HALURO ROLL";
  }

  updateActiveRecipeBanner();
  renderBorderGuideOverlay();
  drawCurveEditor();

  // Swap demo sample cleanly per mode when the roll only holds built-in demo frames
  const onlySamples = state.frames.length > 0 && state.frames.every((f) => f.is_sample);
  if (onlySamples) {
    state.frames = [];
    state.activeFrameIndex = 0;
    state.contactSheetCache = null;
    if (isNeg) {
      await loadNegativeSample();
    } else {
      await loadSamplePhoto(false);
    }
    if (state.viewMode === "sheet") {
      generateContactSheetPreview();
    }
    return;
  }

  state.lastOriginalKey = "";
  syncEmptyRollButtons(state.frames.length === 0);
  renderFilmStrip();
  updateUndoRedoButtons();
  if (state.frames.length === 0) {
    renderEmptyRollUI();
    return;
  }
  if (isNeg && negativeState.baseColor === null) {
    await autoDetectBaseColor(false);
  }
  if (state.viewMode === "sheet") {
    generateContactSheetPreview();
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

const SUBSTRATE_HINTS = {
  c41_orange: "Emulsiones C-41 tradicionales con máscara naranja (Portra, Gold, Superia).",
  clear_base: "Base transparente sin máscara naranja intensa (Aerocolor IV, SantaColor, cine sin remjet).",
  phoenix: "Harman Phoenix I/II: atenúa el cruce magenta en sombras y suaviza contraste extremo.",
  warm_base: "Lomo '92 / Redscale: protege la paleta cálida y evita neutralizarla a gris.",
  creative_switch: "Harman Azure / Lomo Purple: preserva el intercambio intencional de tintes.",
};

function syncNegProcessPanels() {
  const isBw = negativeState.filmType === "bw" || negativeState.profile === "bw";
  const colorPanel = document.getElementById("negColorFinishPanel");
  const bwPanel = document.getElementById("negBwChemPanel");
  const substrateGroup = document.getElementById("negSubstrateGroup");
  const preSatGroup = document.getElementById("negPreSatGroup");
  const finishAmtGroup = document.getElementById("negFinishAmountGroup");
  const sharpAmtGroup = document.getElementById("negSharpenAmountGroup");

  if (colorPanel) colorPanel.style.display = isBw ? "none" : "flex";
  if (bwPanel) bwPanel.style.display = isBw ? "flex" : "none";
  if (substrateGroup) substrateGroup.style.display = isBw ? "none" : "flex";
  if (preSatGroup) preSatGroup.style.display = isBw ? "none" : "flex";

  const subHintEl = document.getElementById("negSubstrateHint");
  if (subHintEl) {
    subHintEl.textContent = SUBSTRATE_HINTS[negativeState.filmSubstrate] || SUBSTRATE_HINTS.c41_orange;
  }
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

  const cropSlider = document.getElementById("negCropSlider");
  const cropVal = document.getElementById("negCropVal");
  if (cropSlider) {
    cropSlider.disabled = Boolean(negativeState.keepSprockets);
    cropSlider.style.opacity = negativeState.keepSprockets ? "0.45" : "";
  }
  if (cropVal && negativeState.keepSprockets) {
    cropVal.textContent = "0% (Reborde)";
  }

  const hasFF = Boolean(negativeState.flatFieldFile);
  const ffClearBtn = document.getElementById("btnClearFlatField");
  const ffStatus = document.getElementById("negFlatFieldStatus");
  const ffStrengthGroup = document.getElementById("negFlatFieldStrengthGroup");
  if (ffClearBtn) ffClearBtn.style.display = hasFF ? "inline-flex" : "none";
  if (ffStrengthGroup) ffStrengthGroup.style.display = hasFF ? "flex" : "none";
  if (ffStatus) {
    ffStatus.textContent = hasFF
      ? negativeState.flatFieldLabel || `Activo: ${negativeState.flatFieldFile}`
      : "Sin calibración de campo plano.";
  }

  renderBorderGuideOverlay();
}

let borderGuideFlashTimer = null;

function renderBorderGuideOverlay() {
  const overlay = document.getElementById("borderGuideOverlay");
  const box = document.getElementById("borderGuideAnalysisBox");
  const tag = document.getElementById("borderGuideTag");
  if (!overlay || !box) return;

  const visible =
    state.appMode === "negative" &&
    state.viewMode !== "sheet" &&
    state.frames.length > 0 &&
    (negativeState.showBorderGuide || negativeState.borderGuideTempActive);

  if (!visible) {
    overlay.style.display = "none";
    return;
  }

  const crop = negativeState.keepSprockets ? 0 : Math.min(0.45, Math.max(0, Number(negativeState.cropPct) || 0));
  const rawBuf = Math.max(0, Number(negativeState.borderBuffer) || 0);
  const effBuf = negativeState.keepSprockets ? Math.max(rawBuf, 0.12) : rawBuf;
  const relInset = Math.max(0, (effBuf - crop) / Math.max(1 - 2 * crop, 0.10));
  const insetPct = Math.min(44, relInset * 100);

  box.style.inset = `${insetPct.toFixed(2)}%`;
  if (tag) {
    const bufLabel = `${Math.round(effBuf * 100)}%`;
    if (negativeState.keepSprockets) {
      tag.textContent = `Zona de cálculo (-${bufLabel} borde) · Sprockets conservados`;
    } else if (crop > 0.001) {
      const cropStr = `${(crop * 100).toFixed(1).replace(/\.0$/, "")}%`;
      tag.textContent = `Zona de cálculo (-${bufLabel} borde · Recorte ${cropStr})`;
    } else {
      tag.textContent = `Zona de cálculo (-${bufLabel} borde)`;
    }
  }
  overlay.style.display = "block";
}

function flashBorderGuideOverlay() {
  negativeState.borderGuideTempActive = true;
  renderBorderGuideOverlay();
  if (borderGuideFlashTimer) clearTimeout(borderGuideFlashTimer);
  borderGuideFlashTimer = setTimeout(() => {
    negativeState.borderGuideTempActive = false;
    renderBorderGuideOverlay();
  }, 950);
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
    const active = btn.dataset.zone === validZone;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-selected", active ? "true" : "false");
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

/**
 * Non-blocking real-time preview engine.
 *
 * The debounce used to be a single global timer: moving one slider cancelled
 * the pending preview of another, so a quick adjustment on two controls left
 * one of them showing a stale frame. The timer is now keyed by control.
 */
const debounceTimers = new Map();

function triggerDebouncedPreview(key = "default") {
  const pending = debounceTimers.get(key);
  if (pending) clearTimeout(pending);
  debounceTimers.set(
    key,
    setTimeout(() => {
      debounceTimers.delete(key);
      requestPreview(false);
    }, 75)
  );
}

let lastPreviewErrorToastAt = 0;

function computeOriginalCacheKey(filename) {
  const uncroppedForBase = state.appMode === "negative" && negativeState.eyedropperMode === "base";
  const cropKey = state.appMode === "negative" && !uncroppedForBase ? negativeState.cropPct.toFixed(3) : "0";
  const cRect = state.cropMode || uncroppedForBase || !state.crop_rect
    ? "none"
    : `${state.crop_rect.x.toFixed(4)},${state.crop_rect.y.toFixed(4)},${state.crop_rect.w.toFixed(4)},${state.crop_rect.h.toFixed(4)}`;
  return `${filename}|${state.rotate}|${state.flip_h}|${state.flip_v}|${state.straighten.toFixed(2)}|${state.keystone_v.toFixed(1)}|${state.keystone_h.toFixed(1)}|${cRect}|${state.auto_crop_straighten}|${cropKey}`;
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
    if (state.viewMode === "teststrip") {
      const res = await fetch("/api/test_strip", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify(
          state.appMode === "negative"
            ? {
                mode: "negative",
                filename: activeFrame.filename,
                step_ev: state.testStripStepEv,
                ...buildNegativePayload(),
              }
            : {
                mode: "simulation",
                filename: activeFrame.filename,
                step_ev: state.testStripStepEv,
                ...buildSimulationPayload(),
              }
        ),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Error generando tira de prueba");
      applyTestStripResult(data);
      return;
    }

    if (state.appMode === "negative") {
      const res = await fetch("/api/negative/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify({
          filename: activeFrame.filename,
          include_original: needOriginal,
          original_uncropped: negativeState.eyedropperMode === "base",
          ...buildNegativePayload(),
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Error al revelar negativo");

      applyPreviewResult(data, origKey, needOriginal);
      updateActiveRecipeBanner();
      renderBorderGuideOverlay();
      drawCurveEditor();
    } else {
      const res = await fetch("/api/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify({
          filename: activeFrame.filename,
          include_original: needOriginal,
          ...buildSimulationPayload(),
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
    const now = Date.now();
    if (now - lastPreviewErrorToastAt > 3000) {
      lastPreviewErrorToastAt = now;
      showToast("Error en vista previa", err.message || "No se pudo revelar este fotograma.");
    }
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
    origLoupeSourceReady = false;
    imgOrig.onload = () => {
      prepareLoupeBuffer(imgOrig, "orig");
    };
    imgOrig.src = data.original;
    state.lastOriginalKey = origKey;
  }

  if (data.developed && imgDev) {
    devLoupeSourceReady = false;
    imgDev.onload = () => {
      prepareLoupeBuffer(imgDev, "dev");
      renderHistogramFromImage(imgDev);
    };
    imgDev.src = data.developed;
  }

  const statRes = document.getElementById("statResolution");
  const statTime = document.getElementById("statTime");
  if (statRes && data.width && data.height) {
    statRes.textContent = `${data.width}×${data.height}`;
    state.activePreviewWidth = data.width;
    state.activePreviewHeight = data.height;
  }
  if (statTime && data.render_time != null) {
    statTime.textContent = `${Math.round(data.render_time * 1000)} ms`;
  }
  if (state.maskEditMode) {
    requestAnimationFrame(() => renderLocalMaskOverlay());
  }
  updateOutputFormatHint();
}

function updateOutputFormatHint() {
  const hintEl = document.getElementById("outputFormatHint");
  if (!hintEl) return;
  const frame = state.frames?.[state.activeFrameIndex];
  const rawExts = new Set([".cr2", ".cr3", ".dng", ".nef", ".arw", ".orf", ".rw2", ".raf", ".pef", ".srw", ".iiq"]);
  const name = (frame?.filename || frame?.name || "").toLowerCase();
  const dotIdx = name.lastIndexOf(".");
  const ext = dotIdx >= 0 ? name.slice(dotIdx) : "";
  const isRaw = Boolean(frame?.is_raw || rawExts.has(ext));
  const fmt = state.outputFormat || "jpg";

  if (fmt === "original") {
    if (!frame) {
      hintEl.textContent = "Mantiene JPG/PNG/TIFF de entrada, o exporta Linear DNG 16-bit para archivos RAW.";
    } else if (isRaw) {
      const extLabel = ext ? ext.toUpperCase() : "RAW";
      hintEl.textContent = `Entrada ${extLabel} → Original exporta Linear DNG 16-bit (.dng) editable sin pérdida.`;
    } else {
      const extLabel = ext ? ext.toUpperCase() : "JPG";
      hintEl.textContent = `Entrada ${extLabel} → Original conserva el mismo formato (${extLabel}).`;
    }
  } else if (fmt === "dng") {
    hintEl.textContent = "Linear DNG 16-bit: estándar RAW editable compatible con Lightroom, ACR y Darktable.";
  } else if (fmt === "tiff") {
    hintEl.textContent = "TIFF maestro de 16 bits por canal (48-bit RGB) sin compresión con pérdida.";
  } else {
    hintEl.textContent = "";
  }
}

function buildSharedOpticsPayload() {
  return {
    denoise_luma: Number(state.denoiseLuma || 0),
    denoise_chroma: Number(state.denoiseChroma || 0),
    defringe: Number(state.defringe || 0),
    sharpen_mode: negativeState.sharpenMode || "off",
    sharpen_amount: Number(negativeState.sharpenAmount ?? 1.0),
    dust_spots: (negativeState.dustSpots || []).map((s) => ({ x: s.x, y: s.y, r: s.r })),
    local_masks: (state.localMasks || []).map((m) => ({ ...m })),
  };
}

function buildSimulationPayload() {
  return {
    film: state.selectedFilm,
    dev_process: state.devProcess || "standard",
    ev: state.ev,
    halation: state.halation,
    grain: state.grain,
    grain_asa: state.grainAsa || "auto",
    vignette: state.vignette,
    shadows: state.shadows,
    mids: state.mids,
    highlights: state.highlights,
    curve: curvePayload(state.curve),
    date: state.date,
    ...buildGeometryPayload(true),
    ...buildSharedOpticsPayload(),
  };
}

function buildGeometryPayload(forPreview = false) {
  return {
    rotate: state.rotate,
    flip_h: state.flip_h,
    flip_v: state.flip_v,
    straighten: Number(state.straighten) || 0.0,
    keystone_v: Number(state.keystone_v) || 0.0,
    keystone_h: Number(state.keystone_h) || 0.0,
    crop_rect: forPreview && state.cropMode ? null : state.crop_rect ? { ...state.crop_rect } : null,
    auto_crop_straighten: forPreview && state.cropMode ? false : Boolean(state.auto_crop_straighten),
  };
}

function buildNegativePayload(forPreview = true) {
  return {
    film_type: negativeState.filmType,
    film_substrate: negativeState.filmSubstrate,
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
    bw_grade00: negativeState.bwGrade00,
    bw_grade5: negativeState.bwGrade5,
    bw_preflash: negativeState.bwPreflash,
    profile: negativeState.profile,
    base_color: negativeState.baseColor ? [...negativeState.baseColor] : null,
    border_buffer: negativeState.borderBuffer,
    crop_pct: negativeState.cropPct,
    keep_sprockets: negativeState.keepSprockets,
    flat_field_file: negativeState.flatFieldFile || "",
    flat_field_strength: negativeState.flatFieldStrength,
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
    dust_spots: (negativeState.dustSpots || []).map((s) => ({ x: s.x, y: s.y, r: s.r })),
    curve: curvePayload(negativeState.curve),
    ...buildGeometryPayload(forPreview),
    ...buildSharedOpticsPayload(),
  };
}

// =============================================================
// PER-FRAME RECIPE MEMORY, COPY/PASTE & ROLL SYNC
// =============================================================

function formatZoneEv(v) {
  const n = Number(v) || 0;
  return `${n > 0 ? "+" : ""}${n.toFixed(1)} EV`;
}

function snapshotSimRecipe() {
  return {
    film: state.selectedFilm,
    dev_process: state.devProcess || "standard",
    ev: state.ev,
    halation: state.halation,
    grain: state.grain,
    grain_asa: state.grainAsa || "auto",
    vignette: state.vignette,
    shadows: state.shadows,
    mids: state.mids,
    highlights: state.highlights,
    curve: state.curve ? cloneCurve(state.curve) : null,
    date: state.date,
    ...buildGeometryPayload(false),
    ...buildSharedOpticsPayload(),
  };
}

function snapshotNegRecipe() {
  return {
    ...buildNegativePayload(false),
    base_hex: negativeState.baseHex,
    flat_field_label: negativeState.flatFieldLabel,
  };
}

function clonePlain(obj) {
  return JSON.parse(JSON.stringify(obj));
}

function ensureFrameHistory(frame) {
  if (!frame.undoStack) frame.undoStack = { simulation: [], negative: [] };
  if (!frame.redoStack) frame.redoStack = { simulation: [], negative: [] };
}

function captureModeRecipeSnapshot(mode = state.appMode) {
  return clonePlain(mode === "negative" ? snapshotNegRecipe() : snapshotSimRecipe());
}

function pushUndoSnapshotForFrame(
  frame = state.frames[state.activeFrameIndex],
  mode = state.appMode,
  explicitSnap = null
) {
  if (!frame) return;
  ensureFrameHistory(frame);
  const stack = frame.undoStack[mode] || (frame.undoStack[mode] = []);
  const snap = clonePlain(explicitSnap || captureModeRecipeSnapshot(mode));
  if (stack.length > 0 && JSON.stringify(stack[stack.length - 1]) === JSON.stringify(snap)) {
    return;
  }
  stack.push(snap);
  if (stack.length > 40) stack.shift();
  frame.redoStack[mode] = [];
  updateUndoRedoButtons();
}

function applyRecipeHistorySnapshot(snap, mode) {
  if (!snap) return;
  if (mode === "negative") {
    applyNegRecipeToUI(clonePlain(snap), false);
  } else {
    applySimRecipeToUI(clonePlain(snap));
  }
  saveActiveFrameRecipe();
  state.lastOriginalKey = "";
  requestPreview(true);
}

function performUndo() {
  const frame = state.frames[state.activeFrameIndex];
  if (!frame) return;
  ensureFrameHistory(frame);
  const mode = state.appMode;
  const undoStack = frame.undoStack[mode];
  if (!undoStack || undoStack.length === 0) return;

  const currentSnap = captureModeRecipeSnapshot(mode);
  const prevSnap = undoStack.pop();
  frame.redoStack[mode].push(currentSnap);
  applyRecipeHistorySnapshot(prevSnap, mode);
  updateUndoRedoButtons();
  showToast("Deshecho", "Se restauró el ajuste anterior de este fotograma.");
}

function performRedo() {
  const frame = state.frames[state.activeFrameIndex];
  if (!frame) return;
  ensureFrameHistory(frame);
  const mode = state.appMode;
  const redoStack = frame.redoStack[mode];
  if (!redoStack || redoStack.length === 0) return;

  const currentSnap = captureModeRecipeSnapshot(mode);
  const nextSnap = redoStack.pop();
  frame.undoStack[mode].push(currentSnap);
  applyRecipeHistorySnapshot(nextSnap, mode);
  updateUndoRedoButtons();
  showToast("Rehecho", "Se volvió a aplicar el ajuste.");
}

function saveActiveFrameRecipe() {
  const frame = state.frames[state.activeFrameIndex];
  if (!frame) return;
  if (state.appMode === "negative") {
    frame.negRecipe = snapshotNegRecipe();
  } else {
    frame.simRecipe = snapshotSimRecipe();
  }
  updateActiveThumbEditedIndicator();
  saveStoredFrameRecipes();
}

function setSliderSilent(sliderId, labelId, val, textVal) {
  const el = document.getElementById(sliderId);
  const lbl = document.getElementById(labelId);
  if (el && val != null) el.value = String(val);
  if (lbl && textVal != null) lbl.textContent = textVal;
}

function applySimRecipeToUI(rec) {
  if (!rec) return;
  const rawFilm = rec.film === "cinestill400t" ? "cinestill400d" : rec.film;
  state.selectedFilm = rawFilm || state.selectedFilm;
  state.devProcess = rec.dev_process || "standard";
  const devProcSel = document.getElementById("simDevProcessSelect");
  if (devProcSel) devProcSel.value = state.devProcess;
  state.ev = Number(rec.ev ?? 0);
  state.halation = Number(rec.halation ?? 1.0);
  state.grain = Number(rec.grain ?? 1.0);
  state.grainAsa = rec.grain_asa || "auto";
  const grainAsaSel = document.getElementById("grainAsaSelect");
  if (grainAsaSel) grainAsaSel.value = state.grainAsa;
  state.vignette = Number(rec.vignette ?? 1.0);
  state.shadows = Number(rec.shadows ?? 0.0);
  state.mids = Number(rec.mids ?? 0.0);
  state.highlights = Number(rec.highlights ?? 0.0);
  state.curve = rec.curve ? cloneCurve(rec.curve) : null;
  state.date = Boolean(rec.date);
  if (typeof rec.rotate === "number") state.rotate = rec.rotate;
  if (typeof rec.flip_h === "boolean") state.flip_h = rec.flip_h;
  if (typeof rec.flip_v === "boolean") state.flip_v = rec.flip_v;
  state.straighten = Number(rec.straighten ?? 0.0);
  state.keystone_v = Number(rec.keystone_v ?? 0.0);
  state.keystone_h = Number(rec.keystone_h ?? 0.0);
  state.crop_rect = rec.crop_rect ? { ...rec.crop_rect } : null;
  state.auto_crop_straighten = rec.auto_crop_straighten !== false;
  state.denoiseLuma = Number(rec.denoise_luma ?? 0);
  state.denoiseChroma = Number(rec.denoise_chroma ?? 0);
  state.defringe = Number(rec.defringe ?? 0);
  state.localMasks = Array.isArray(rec.local_masks) ? rec.local_masks.map((m) => ({ ...m })) : [];
  state.activeMaskIndex = state.localMasks.length > 0 ? 0 : -1;
  negativeState.sharpenMode = rec.sharpen_mode || "off";
  negativeState.sharpenAmount = Number(rec.sharpen_amount ?? 1.0);
  negativeState.dustSpots = Array.isArray(rec.dust_spots)
    ? rec.dust_spots.map((s) => ({ x: Number(s.x), y: Number(s.y), r: Number(s.r || 0.008) }))
    : [];
  syncGeometryUiControls();
  syncSharedOpticsUI();

  document.querySelectorAll(".film-card").forEach((el) => {
    const sel = el.dataset.key === state.selectedFilm;
    el.classList.toggle("selected", sel);
    const btn = el.querySelector(".film-card-select-btn");
    if (btn) btn.setAttribute("aria-pressed", sel ? "true" : "false");
  });
  document.getElementById("flipHBtn")?.classList.toggle("active", state.flip_h);
  document.getElementById("flipHBtn")?.setAttribute("aria-pressed", state.flip_h ? "true" : "false");

  setSliderSilent("evSlider", "evVal", state.ev, `${state.ev > 0 ? "+" : ""}${state.ev.toFixed(1)} EV`);
  setSliderSilent("halationSlider", "halationVal", state.halation, `${state.halation.toFixed(1)}x`);
  setSliderSilent("grainSlider", "grainVal", state.grain, `${state.grain.toFixed(1)}x`);
  setSliderSilent("vignetteSlider", "vignetteVal", state.vignette, `${state.vignette.toFixed(1)}x`);
  setSliderSilent("shadowsSlider", "shadowsVal", state.shadows, formatZoneEv(state.shadows));
  setSliderSilent("midsSlider", "midsVal", state.mids, formatZoneEv(state.mids));
  setSliderSilent("highlightsSlider", "highlightsVal", state.highlights, formatZoneEv(state.highlights));
  drawCurveEditor();
  const dt = document.getElementById("dateToggle");
  if (dt) dt.checked = state.date;
  updateActiveRecipeBanner();
  renderBorderGuideOverlay();
  drawCurveEditor();
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
  negativeState.filmSubstrate = rec.film_substrate || "c41_orange";
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
  negativeState.bwGrade00 = Number(rec.bw_grade00 ?? 0.0);
  negativeState.bwGrade5 = Number(rec.bw_grade5 ?? 0.0);
  negativeState.bwPreflash = Number(rec.bw_preflash ?? 0.0);
  negativeState.profile = rec.profile || rec.profile_key || "frontier";
  negativeState.borderBuffer = Number(rec.border_buffer ?? 0.06);
  negativeState.cropPct = Number(rec.crop_pct ?? 0.0);
  negativeState.keepSprockets = Boolean(rec.keep_sprockets ?? false);
  negativeState.flatFieldFile = rec.flat_field_file || null;
  negativeState.flatFieldLabel = rec.flat_field_label || (rec.flat_field_file ? `Activo: ${rec.flat_field_file}` : "");
  negativeState.flatFieldStrength = Number(rec.flat_field_strength ?? 1.0);
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
  negativeState.dustSpots = Array.isArray(rec.dust_spots)
    ? rec.dust_spots.map((s) => ({ x: Number(s.x), y: Number(s.y), r: Number(s.r || 0.008) }))
    : [];
  negativeState.curve = rec.curve ? cloneCurve(rec.curve) : null;

  if (typeof rec.rotate === "number") state.rotate = rec.rotate;
  if (typeof rec.flip_h === "boolean") state.flip_h = rec.flip_h;
  if (typeof rec.flip_v === "boolean") state.flip_v = rec.flip_v;
  state.straighten = Number(rec.straighten ?? 0.0);
  state.keystone_v = Number(rec.keystone_v ?? 0.0);
  state.keystone_h = Number(rec.keystone_h ?? 0.0);
  state.crop_rect = rec.crop_rect ? { ...rec.crop_rect } : null;
  state.auto_crop_straighten = rec.auto_crop_straighten !== false;
  state.denoiseLuma = Number(rec.denoise_luma ?? 0);
  state.denoiseChroma = Number(rec.denoise_chroma ?? 0);
  state.defringe = Number(rec.defringe ?? 0);
  state.localMasks = Array.isArray(rec.local_masks) ? rec.local_masks.map((m) => ({ ...m })) : [];
  state.activeMaskIndex = state.localMasks.length > 0 ? 0 : -1;
  negativeState.sharpenMode = rec.sharpen_mode || "off";
  negativeState.sharpenAmount = Number(rec.sharpen_amount ?? 1.0);
  negativeState.dustSpots = Array.isArray(rec.dust_spots)
    ? rec.dust_spots.map((s) => ({ x: Number(s.x), y: Number(s.y), r: Number(s.r || 0.008) }))
    : [];
  syncGeometryUiControls();
  syncSharedOpticsUI();
  document.getElementById("flipHBtn")?.classList.toggle("active", state.flip_h);
  document.getElementById("flipHBtn")?.setAttribute("aria-pressed", state.flip_h ? "true" : "false");

  if (Array.isArray(rec.base_color)) {
    setBaseColor(rec.base_color, rec.base_hex || null, null);
  } else if (!preserveCurrentBaseIfMissing) {
    negativeState.baseColor = null;
  }

  document.getElementById("btnTypeColor")?.classList.toggle("active", negativeState.filmType === "color");
  document.getElementById("btnTypeColor")?.setAttribute("aria-pressed", negativeState.filmType === "color" ? "true" : "false");
  document.getElementById("btnTypeBW")?.classList.toggle("active", negativeState.filmType === "bw");
  document.getElementById("btnTypeBW")?.setAttribute("aria-pressed", negativeState.filmType === "bw" ? "true" : "false");

  document.querySelectorAll("#negScanSourceBar .seg-btn").forEach((b) => {
    const active = b.dataset.source === negativeState.scanSource;
    b.classList.toggle("active", active);
    b.setAttribute("aria-pressed", active ? "true" : "false");
  });
  document.querySelectorAll("#negLightSourceBar .seg-btn").forEach((b) => {
    const active = b.dataset.light === negativeState.lightSource;
    b.classList.toggle("active", active);
    b.setAttribute("aria-pressed", active ? "true" : "false");
  });
  document.querySelectorAll("#negColorMethodBar .seg-btn").forEach((b) => {
    const active = b.dataset.method === negativeState.colorMethod;
    b.classList.toggle("active", active);
    b.setAttribute("aria-pressed", active ? "true" : "false");
  });
  document.querySelectorAll("#negToneVariantBar .seg-btn").forEach((b) => {
    const active = b.dataset.tone === negativeState.toneVariant;
    b.classList.toggle("active", active);
    b.setAttribute("aria-pressed", active ? "true" : "false");
  });
  document.querySelectorAll("#negSharpenModeBar .seg-btn").forEach((b) => {
    const active = b.dataset.sharpen === negativeState.sharpenMode;
    b.classList.toggle("active", active);
    b.setAttribute("aria-pressed", active ? "true" : "false");
  });
  document.querySelectorAll("#negProfileList .profile-card").forEach((c) => {
    const sel = c.dataset.profile === negativeState.profile;
    c.classList.toggle("selected", sel);
    c.setAttribute("aria-selected", sel ? "true" : "false");
  });

  const subSel = document.getElementById("negSubstrateSelect");
  if (subSel) subSel.value = negativeState.filmSubstrate;
  const pfSel = document.getElementById("negPrintFinishSelect");
  if (pfSel) pfSel.value = negativeState.printFinish;
  const bwSel = document.getElementById("negBwTonerSelect");
  if (bwSel) bwSel.value = negativeState.bwToner;

  setSliderSilent("negPreSatSlider", "negPreSatVal", negativeState.preSaturation, `${negativeState.preSaturation.toFixed(2)}x`);
  const finPct = Math.round(negativeState.finishAmount * 100);
  setSliderSilent("negFinishAmountSlider", "negFinishAmountVal", finPct, `${finPct}%`);
  const bwStrPct = Math.round(negativeState.bwTonerStrength * 100);
  setSliderSilent("negBwTonerStrengthSlider", "negBwTonerStrengthVal", bwStrPct, `${bwStrPct}%`);
  setSliderSilent("negBwGrade00Slider", "negBwGrade00Val", negativeState.bwGrade00, fmtS(negativeState.bwGrade00));
  setSliderSilent("negBwGrade5Slider", "negBwGrade5Val", negativeState.bwGrade5, fmtS(negativeState.bwGrade5));
  const pfPct = Math.round(negativeState.bwPreflash * 100);
  setSliderSilent("negBwPreflashSlider", "negBwPreflashVal", pfPct, `${pfPct}%`);

  const bufPct = Math.round(negativeState.borderBuffer * 100);
  const cropPctUi = Number((negativeState.cropPct * 100).toFixed(1));
  setSliderSilent("negBufferSlider", "negBufferVal", bufPct, `${bufPct}%`);
  setSliderSilent("negCropSlider", "negCropVal", cropPctUi, `${cropPctUi.toFixed(1).replace(/\.0$/, "")}%`);
  const spToggle = document.getElementById("negKeepSprocketsToggle");
  if (spToggle) spToggle.checked = negativeState.keepSprockets;

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
  const ffPct = Math.round(negativeState.flatFieldStrength * 100);
  setSliderSilent("negFlatFieldStrengthSlider", "negFlatFieldStrengthVal", ffPct, `${ffPct}%`);
  setSliderSilent("negWarming85Slider", "negWarming85Val", negativeState.warming85, fmtPct(negativeState.warming85));
  setSliderSilent("negSkylightSlider", "negSkylightVal", negativeState.skylightFilter, fmtPct(negativeState.skylightFilter));
  setSliderSilent("negShadeSlider", "negShadeVal", negativeState.shadeFilter, fmtPct(negativeState.shadeFilter));
  setSliderSilent("negGlowSlider", "negGlowVal", negativeState.glow, `${negativeState.glow.toFixed(1)}x`);
  setSliderSilent("negFadeSlider", "negFadeVal", negativeState.fade, `${negativeState.fade.toFixed(1)}x`);

  selectCmyZone(negativeState.activeCmyZone);
  syncNegProcessPanels();
  updateActiveRecipeBanner();
  renderBorderGuideOverlay();
  updateDustSpotsUI();
  drawCurveEditor();
}

function loadFrameRecipe(idx) {
  const frame = state.frames[idx];
  if (!frame) {
    updateUndoRedoButtons();
    return false;
  }
  let loaded = false;
  if (state.appMode === "negative") {
    if (frame.negRecipe) {
      applyNegRecipeToUI(frame.negRecipe, false);
      loaded = true;
    } else {
      negativeState.baseColor = null;
    }
  } else if (frame.simRecipe) {
    applySimRecipeToUI(frame.simRecipe);
    loaded = true;
  }
  updateUndoRedoButtons();
  return loaded;
}

function copyCurrentRecipe() {
  saveActiveFrameRecipe();
  if (state.appMode === "negative") {
    state.copiedRecipe = { mode: "negative", data: snapshotNegRecipe() };
  } else {
    state.copiedRecipe = { mode: "simulation", data: snapshotSimRecipe() };
  }
  updateToolbarAvailability();
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
  pushUndoSnapshotForFrame();
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
  if (state.frames.length === 1) {
    showToast("Rollo de un fotograma", "Añade más fotogramas al rollo para sincronizar esta receta.");
    return;
  }
  saveActiveFrameRecipe();
  const isNeg = state.appMode === "negative";
  const modal = document.getElementById("syncRollModal");
  const colorRow = document.getElementById("syncOptColorRow");
  const baseCropRow = document.getElementById("syncOptBaseCropRow");
  const profTitle = document.getElementById("syncOptProfileTitle");
  const profDesc = document.getElementById("syncOptProfileDesc");
  const optTitle = document.getElementById("syncOptOpticsTitle");
  const optDesc = document.getElementById("syncOptOpticsDesc");
  const baseCropChk = document.getElementById("syncOptBaseCrop");

  if (profTitle) profTitle.textContent = isNeg ? "Perfil, respuesta y curva tonal" : "Película emulada";
  if (profDesc) {
    profDesc.textContent = isNeg
      ? "Perfil de escáner, proceso, contraste, empuje, luces y negros."
      : "Aplica la emulsión seleccionada a todos los fotogramas.";
  }
  if (optTitle) optTitle.textContent = isNeg ? "Óptica, filtros y acabado" : "Exposición (EV), óptica, grano y fecha";
  if (optDesc) {
    optDesc.textContent = isNeg
      ? "Halación/resplandor, velo, filtros 85B/Skylight, nitidez y virado B&N."
      : "Ajuste EV, halación, grano, viñeteado y fechador.";
  }
  if (colorRow) colorRow.style.display = isNeg ? "flex" : "none";
  if (baseCropRow) baseCropRow.style.display = isNeg ? "flex" : "none";
  if (baseCropChk) baseCropChk.checked = false;

  if (modal) {
    setModalOpen(modal, true);
  } else {
    applySyncRecipeToRoll({ profileTone: true, color: true, optics: true, baseCrop: false });
  }
}

function applySyncRecipeToRoll(options = {}) {
  if (state.frames.length === 0) return;
  saveActiveFrameRecipe();
  const isNeg = state.appMode === "negative";
  const srcSnap = isNeg ? snapshotNegRecipe() : snapshotSimRecipe();
  const includeProfileTone = options.profileTone !== false;
  const includeColor = options.color !== false;
  const includeOptics = options.optics !== false;
  const includeBaseCrop = Boolean(options.baseCrop);

  const prevRollBackup = state.frames.map((f) => ({
    simRecipe: f.simRecipe ? clonePlain(f.simRecipe) : null,
    negRecipe: f.negRecipe ? clonePlain(f.negRecipe) : null,
  }));

  const NEG_PROFILE_TONE_KEYS = [
    "film_type", "film_substrate", "scan_source", "pre_saturation", "light_source", "color_method", "roll_bounds",
    "tone_variant", "profile", "brightness", "midtone_nd", "contrast", "push_pull",
    "lights", "darks", "whites", "blacks", "black_clip", "white_clip",
    "clip_protect", "inky_blacks", "rp_tone", "saturation", "curve",
  ];
  const NEG_COLOR_KEYS = [
    "printer_cmy", "shadows_tint", "mids_tint", "highs_tint",
    "shadows_range", "highs_range", "temp", "tint",
  ];
  const NEG_OPTICS_KEYS = [
    "print_finish", "finish_amount", "bw_toner", "bw_toner_strength",
    "bw_grade00", "bw_grade5", "bw_preflash",
    "warming_85", "skylight_filter", "shade_filter", "sharpen_mode", "sharpen_amount",
    "glow", "fade", "flat_field_file", "flat_field_label", "flat_field_strength",
  ];
  const NEG_BASE_CROP_KEYS = [
    "base_color", "base_hex", "border_buffer", "crop_pct", "keep_sprockets",
  ];

  state.frames.forEach((f, idx) => {
    if (idx === state.activeFrameIndex) return;
    const prevRec = isNeg ? f.negRecipe : f.simRecipe;
    if (prevRec) {
      pushUndoSnapshotForFrame(f, state.appMode, prevRec);
    }

    if (isNeg) {
      const target = prevRec ? clonePlain(prevRec) : clonePlain(srcSnap);
      const copyKeys = (keys) => {
        keys.forEach((k) => {
          if (srcSnap[k] !== undefined) target[k] = clonePlain(srcSnap[k]);
        });
      };
      if (includeProfileTone) copyKeys(NEG_PROFILE_TONE_KEYS);
      if (includeColor) copyKeys(NEG_COLOR_KEYS);
      if (includeOptics) copyKeys(NEG_OPTICS_KEYS);
      if (includeBaseCrop) {
        copyKeys(NEG_BASE_CROP_KEYS);
      } else if (!prevRec) {
        // Keep uncalibrated base neutral for frames without prior base measurement unless forced
        target.base_color = null;
      }
      target.rotate = prevRec?.rotate ?? f.negRecipe?.rotate ?? state.rotate;
      target.flip_h = prevRec?.flip_h ?? f.negRecipe?.flip_h ?? state.flip_h;
      f.negRecipe = target;
    } else {
      const target = prevRec ? clonePlain(prevRec) : clonePlain(srcSnap);
      if (includeProfileTone) {
        target.film = srcSnap.film;
        target.dev_process = srcSnap.dev_process || "standard";
      }
      if (includeOptics) {
        target.ev = srcSnap.ev;
        target.halation = srcSnap.halation;
        target.grain = srcSnap.grain;
        target.grain_asa = srcSnap.grain_asa || "auto";
        target.vignette = srcSnap.vignette;
        target.date = srcSnap.date;
      }
      target.rotate = prevRec?.rotate ?? f.simRecipe?.rotate ?? state.rotate;
      target.flip_h = prevRec?.flip_h ?? f.simRecipe?.flip_h ?? state.flip_h;
      f.simRecipe = target;
    }
  });

  renderFilmStrip();
  if (state.viewMode === "sheet") {
    generateContactSheetPreview();
  }

  showToast(
    "Rollo sincronizado",
    `Receta selectiva aplicada a los ${state.frames.length} fotograma(s) del rollo.`,
    "Deshacer",
    async () => {
      state.frames.forEach((f, idx) => {
        const prev = prevRollBackup[idx];
        if (!prev) return;
        f.simRecipe = prev.simRecipe;
        f.negRecipe = prev.negRecipe;
      });
      loadFrameRecipe(state.activeFrameIndex);
      renderFilmStrip();
      await requestPreview(true);
      if (state.viewMode === "sheet") generateContactSheetPreview();
    }
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
  const frameIndexAtRequest = state.activeFrameIndex;
  const activeFrame = state.frames[frameIndexAtRequest];
  if (!activeFrame) return;

  try {
    const res = await fetch("/api/negative/auto_detect_base", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        filename: activeFrame.filename,
        rotate: state.rotate,
        flip_h: state.flip_h,
        film_substrate: negativeState.filmSubstrate,
        flat_field_file: negativeState.flatFieldFile || "",
        flat_field_strength: negativeState.flatFieldStrength,
      }),
    });
    const data = await res.json();
    // The user may have moved to another frame while the detection was in
    // flight. Applying the result now would calibrate the wrong negative and
    // then persist it into that frame's recipe.
    if (state.activeFrameIndex !== frameIndexAtRequest) return;
    if (res.ok && data.base_color) {
      if (triggerPreviewAfter) {
        pushUndoSnapshotForFrame(state.frames[state.activeFrameIndex], "negative");
      }
      setBaseColor(data.base_color, data.base_hex || data.hex, "Auto D-min");
      if (triggerPreviewAfter) {
        saveActiveFrameRecipe();
        requestPreview(false);
      }
    } else if (triggerPreviewAfter) {
      showToast("No se pudo detectar D-min", data.error || "Usa el cuentagotas manual (I) sobre el borde sin exponer.");
    }
  } catch (err) {
    console.error("Auto base error:", err);
    if (triggerPreviewAfter) {
      showToast("Error al detectar soporte", err.message || "Intenta muestrear manualmente el borde.");
    }
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

    state.frames.forEach((f) => {
      if (f.negRecipe) pushUndoSnapshotForFrame(f, "negative", f.negRecipe);
    });
    pushUndoSnapshotForFrame(state.frames[state.activeFrameIndex], "negative");

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

function fillAnalogExifFromActiveRecipe() {
  const next = { ...buildAnalogMetaPayload() };
  if (state.appMode === "simulation") {
    const film = state.films.find((f) => f.key === state.selectedFilm);
    if (film) {
      next.film_stock = film.name;
      if (film.iso) {
        const digits = String(film.iso).replace(/[^\d]/g, "");
        if (digits) next.shot_iso = digits;
      }
      const processByCat = {
        bw: "D-76 / B&N",
        slide: "E-6",
        cine: "ECN-2",
      };
      next.dev_process = processByCat[film.category] || "C-41 Estándar";
    }
    if (!next.scanner) {
      next.scanner = "Haluro Emulación Digital";
    }
  } else {
    const isBw = negativeState.filmType === "bw" || negativeState.profile === "bw";
    next.dev_process = isBw
      ? "B&N Revelado"
      : negativeState.profile === "cine_ecp"
      ? "ECN-2 / ECP 2383"
      : "C-41 Estándar";
    const scannerBySource = {
      camera_raw: "DSLR / Macro RAW",
      scanner_raw: PROFILE_LABELS[negativeState.profile] || "Escáner Minilab",
      flatbed_tiff: "Epson Flatbed V600/V850",
    };
    next.scanner = scannerBySource[negativeState.scanSource] || "Laboratorio Haluro";
    if (!next.film_stock) {
      next.film_stock = isBw ? "Negativo B&N" : "Negativo Color C-41";
    }
  }
  applyAnalogMetaToUI(next, true);
  showToast("Ficha completada", "Campos EXIF rellenados a partir de la receta activa.");
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

  document.getElementById("btnAutoFillExifFromRecipe")?.addEventListener("click", fillAnalogExifFromActiveRecipe);
  document.getElementById("btnCopyAnalogCaption")?.addEventListener("click", copyAnalogCaptionToClipboard);
  document.getElementById("btnClearAnalogExif")?.addEventListener("click", () => {
    applyAnalogMetaToUI({}, true);
    showToast("Ficha técnica limpia", "Se han vaciado los campos EXIF opcionales.");
  });

  // P8: Presets químicos rápidos y Calculadora de reciprocidad (Schwarzschild)
  const chemSel = document.getElementById("exifChemPresetSelect");
  chemSel?.addEventListener("change", () => {
    if (!chemSel.value) return;
    const devInput = document.getElementById("exifDevProcess");
    if (devInput) {
      devInput.value = chemSel.value;
      devInput.dispatchEvent(new Event("input", { bubbles: true }));
      showToast("Preset químico aplicado", chemSel.value);
    }
  });

  const recipFilm = document.getElementById("recipFilmSelect");
  const recipMeasured = document.getElementById("recipMeasuredInput");
  const recipOut = document.getElementById("recipCorrectedOut");
  const recipDelta = document.getElementById("recipDeltaLabel");
  const updateRecipReadout = () => {
    const tMeas = Math.max(0.5, Number(recipMeasured?.value) || 1);
    const val = recipFilm?.value || "1.30";
    let tReal = tMeas;
    if (val === "acros") {
      tReal = tMeas <= 120 ? tMeas : tMeas * Math.pow(tMeas / 120, 0.28);
    } else {
      const p = Number(val) || 1.3;
      tReal = tMeas >= 1.0 ? Math.pow(tMeas, p) : tMeas;
    }
    const evDiff = tMeas > 0 && tReal >= tMeas ? Math.log2(tReal / tMeas) : 0;
    const fmtT = tReal >= 120 ? `${(tReal / 60).toFixed(1)} min (${Math.round(tReal)} s)` : `${tReal.toFixed(1)} s`;
    if (recipOut) recipOut.textContent = fmtT;
    if (recipDelta) recipDelta.textContent = evDiff < 0.05 ? "Sin compensación requerida" : `+${evDiff.toFixed(1)} EV compensación`;
  };
  recipFilm?.addEventListener("change", updateRecipReadout);
  recipMeasured?.addEventListener("input", updateRecipReadout);
  updateRecipReadout();

  document.getElementById("btnInsertRecipToNotes")?.addEventListener("click", () => {
    const notesEl = document.getElementById("exifNotes");
    if (!notesEl) return;
    const optLabel = recipFilm?.selectedOptions?.[0]?.dataset?.label || "Película";
    const tMeas = Math.max(0.5, Number(recipMeasured?.value) || 1);
    const realText = recipOut?.textContent || `${tMeas} s`;
    const snippet = `Reciprocidad ${optLabel}: ${tMeas}s → ${realText}`;
    notesEl.value = notesEl.value.trim() ? `${notesEl.value.trim()} · ${snippet}` : snippet;
    notesEl.dispatchEvent(new Event("input", { bubbles: true }));
    showToast("Reciprocidad anotada", snippet);
  });
}

function updateDustSpotsUI() {
  const count = Array.isArray(negativeState.dustSpots) ? negativeState.dustSpots.length : 0;
  const label = `${count} ${count === 1 ? "mota" : "motas"}`;
  const badge = document.getElementById("dustSpotCountBadge");
  const undoBtn = document.getElementById("btnDustUndo");
  const clearBtn = document.getElementById("btnDustClear");
  if (badge) badge.textContent = label;
  if (undoBtn) undoBtn.disabled = count === 0;
  if (clearBtn) clearBtn.disabled = count === 0;

  const sBadge = document.getElementById("sharedDustCountBadge");
  const sUndo = document.getElementById("sharedDustUndoBtn");
  const sClear = document.getElementById("sharedDustClearBtn");
  if (sBadge) sBadge.textContent = label;
  if (sUndo) sUndo.disabled = count === 0;
  if (sClear) sClear.disabled = count === 0;
  if (typeof updateSharedOpticsBadge === "function") updateSharedOpticsBadge();
}

function undoLastDustSpot() {
  if (!Array.isArray(negativeState.dustSpots) || negativeState.dustSpots.length === 0) return;
  pushUndoSnapshotForFrame(state.frames[state.activeFrameIndex], state.appMode === "negative" ? "negative" : "simulation");
  negativeState.dustSpots.pop();
  updateDustSpotsUI();
  saveActiveFrameRecipe();
  requestPreview(false);
}

function clearAllDustSpots() {
  if (!Array.isArray(negativeState.dustSpots) || negativeState.dustSpots.length === 0) return;
  pushUndoSnapshotForFrame(state.frames[state.activeFrameIndex], state.appMode === "negative" ? "negative" : "simulation");
  negativeState.dustSpots = [];
  updateDustSpotsUI();
  saveActiveFrameRecipe();
  requestPreview(false);
  showToast("Motas restauradas", "Se eliminaron todos los retoques puntuales del fotograma.");
}

function setEyedropperMode(mode) {
  const prevMode = negativeState.eyedropperMode;
  const cleanMode = mode === "base" || mode === "scene_wb" || mode === "dust" ? mode : null;
  const wasActive = negativeState.eyedropperActive;
  negativeState.eyedropperMode = cleanMode;
  negativeState.eyedropperActive = Boolean(cleanMode);

  const btnBase = document.getElementById("btnEyedropper");
  const tipBase = document.getElementById("eyedropperTip");
  const btnScene = document.getElementById("btnSceneWbEyedropper");
  const tipScene = document.getElementById("sceneWbTip");
  const btnDust = document.getElementById("btnDustHealTool");
  const tipDust = document.getElementById("dustHealTip");
  const wrapper = document.getElementById("splitWrapper");
  const loupe = document.getElementById("eyedropperLoupe");

  btnBase?.classList.toggle("active", cleanMode === "base");
  btnBase?.setAttribute("aria-pressed", cleanMode === "base" ? "true" : "false");
  if (tipBase) tipBase.style.display = cleanMode === "base" ? "block" : "none";

  btnScene?.classList.toggle("active", cleanMode === "scene_wb");
  btnScene?.setAttribute("aria-pressed", cleanMode === "scene_wb" ? "true" : "false");
  if (tipScene) tipScene.style.display = cleanMode === "scene_wb" ? "block" : "none";

  btnDust?.classList.toggle("active", cleanMode === "dust");
  btnDust?.setAttribute("aria-pressed", cleanMode === "dust" ? "true" : "false");
  if (tipDust) tipDust.style.display = cleanMode === "dust" ? "block" : "none";
  const sharedDustBtn = document.getElementById("sharedDustHealBtn");
  sharedDustBtn?.classList.toggle("active", cleanMode === "dust");
  sharedDustBtn?.setAttribute("aria-pressed", cleanMode === "dust" ? "true" : "false");

  wrapper?.classList.toggle("eyedropper-active", negativeState.eyedropperActive);
  if (!negativeState.eyedropperActive) {
    wrapper?.classList.remove("space-pan-ready");
    if (loupe) loupe.style.display = "none";
  }

  const enteredBaseWithCrop = cleanMode === "base" && prevMode !== "base" && negativeState.cropPct > 0.002;
  const exitedBaseWithCrop = cleanMode !== "base" && prevMode === "base" && negativeState.cropPct > 0.002;

  if (cleanMode === "base") {
    if (!wasActive) state.prevViewMode = state.viewMode;
    setViewMode("original");
    if (enteredBaseWithCrop && state.frames.length > 0) {
      state.lastOriginalKey = "";
      requestPreview(true);
    } else {
      prepareLoupeBuffer(document.getElementById("imgOriginal"), "orig");
    }
  } else if (cleanMode === "scene_wb" || cleanMode === "dust") {
    if (!wasActive) state.prevViewMode = state.viewMode;
    setViewMode("full");
    prepareLoupeBuffer(document.getElementById("imgDeveloped"), "dev");
    if (exitedBaseWithCrop && state.frames.length > 0) {
      state.lastOriginalKey = "";
      requestPreview(true);
    }
  } else if (wasActive) {
    if (state.prevViewMode && state.prevViewMode !== state.viewMode) {
      setViewMode(state.prevViewMode);
    }
    if (exitedBaseWithCrop && state.frames.length > 0) {
      state.lastOriginalKey = "";
      requestPreview(true);
    }
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
    if (!res.ok || !Array.isArray(data.printer_cmy)) {
      throw new Error(data?.error || "No se pudo equilibrar la escena automáticamente.");
    }
    pushUndoSnapshotForFrame(activeFrame, "negative");
    applySolvedCmy(data.printer_cmy);
    await requestPreview(false);
    showToast("Equilibrio aplicado", "Luces de ampliadora ajustadas sobre los tonos medios.");
  } catch (err) {
    console.error("Auto scene WB error:", err);
    showToast("Error al equilibrar color", err.message || "Prueba muestrear manualmente un punto gris neutro (W).");
  } finally {
    setRenderBusy(false);
  }
}

const ZONE_SYSTEM_ROMAN = ["0", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"];

function getZoneFromRgb(r, g, b) {
  const luma = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  const idx = Math.max(0, Math.min(10, Math.round((luma / 255) * 10)));
  return ZONE_SYSTEM_ROMAN[idx];
}

function getViewportNormalizedCoords(e) {
  const mediaLayer = document.getElementById("splitMediaLayer");
  const wrapper = document.getElementById("splitWrapper");
  const targetRect = (mediaLayer || wrapper)?.getBoundingClientRect();
  if (!targetRect || !targetRect.width || !targetRect.height) return null;
  const xPct = Math.max(0, Math.min(1, (e.clientX - targetRect.left) / targetRect.width));
  const yPct = Math.max(0, Math.min(1, (e.clientY - targetRect.top) / targetRect.height));
  return { xPct, yPct };
}

function sampleCanvasRgb(canvas, xPct, yPct) {
  if (!canvas || !canvas.width || !canvas.height) return null;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  const px = Math.min(canvas.width - 1, Math.max(0, Math.floor(xPct * canvas.width)));
  const py = Math.min(canvas.height - 1, Math.max(0, Math.floor(yPct * canvas.height)));
  const d = ctx.getImageData(px, py, 1, 1).data;
  return { r: d[0], g: d[1], b: d[2], px, py };
}

function drawLoupeMagnifier(sourceCanvas, xPct, yPct) {
  const zoomCanvas = document.getElementById("loupeZoomCanvas");
  if (!zoomCanvas || !sourceCanvas || !sourceCanvas.width || !sourceCanvas.height) return;
  const zCtx = zoomCanvas.getContext("2d");
  const w = zoomCanvas.width;
  const h = zoomCanvas.height;
  const grid = 9;
  const half = 4;
  const cellW = w / grid;
  const cellH = h / grid;

  const sCtx = sourceCanvas.getContext("2d", { willReadFrequently: true });
  const cx = Math.min(sourceCanvas.width - 1, Math.max(0, Math.floor(xPct * sourceCanvas.width)));
  const cy = Math.min(sourceCanvas.height - 1, Math.max(0, Math.floor(yPct * sourceCanvas.height)));

  const x0 = Math.max(0, cx - half);
  const y0 = Math.max(0, cy - half);
  const x1 = Math.min(sourceCanvas.width - 1, cx + half);
  const y1 = Math.min(sourceCanvas.height - 1, cy + half);
  const patchW = x1 - x0 + 1;
  const patchH = y1 - y0 + 1;
  const patch = sCtx.getImageData(x0, y0, patchW, patchH).data;

  zCtx.clearRect(0, 0, w, h);
  for (let dy = -half; dy <= half; dy++) {
    const sy = Math.min(sourceCanvas.height - 1, Math.max(0, cy + dy));
    const localY = sy - y0;
    for (let dx = -half; dx <= half; dx++) {
      const sx = Math.min(sourceCanvas.width - 1, Math.max(0, cx + dx));
      const localX = sx - x0;
      const offset = (localY * patchW + localX) * 4;
      zCtx.fillStyle = `rgb(${patch[offset]}, ${patch[offset + 1]}, ${patch[offset + 2]})`;
      zCtx.fillRect((dx + half) * cellW, (dy + half) * cellH, cellW + 0.5, cellH + 0.5);
    }
  }

  zCtx.strokeStyle = "rgba(255, 255, 255, 0.92)";
  zCtx.lineWidth = 1;
  zCtx.strokeRect(half * cellW + 0.5, half * cellH + 0.5, cellW - 1, cellH - 1);
  zCtx.strokeStyle = "rgba(0, 0, 0, 0.7)";
  zCtx.strokeRect(half * cellW - 0.5, half * cellH - 0.5, cellW + 1, cellH + 1);
}

function prepareLoupeBuffer(imgEl, kind = "dev") {
  const isOrig = kind === "orig";
  try {
    if (!imgEl || !imgEl.naturalWidth) {
      if (isOrig) origLoupeSourceReady = false;
      else devLoupeSourceReady = false;
      return;
    }
    const targetCanvas = isOrig
      ? offscreenOrigLoupeCanvas || (offscreenOrigLoupeCanvas = document.createElement("canvas"))
      : offscreenDevLoupeCanvas || (offscreenDevLoupeCanvas = document.createElement("canvas"));
    const scale = Math.min(1, 1280 / Math.max(imgEl.naturalWidth, imgEl.naturalHeight));
    targetCanvas.width = Math.max(1, Math.round(imgEl.naturalWidth * scale));
    targetCanvas.height = Math.max(1, Math.round(imgEl.naturalHeight * scale));
    const ctx = targetCanvas.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(imgEl, 0, 0, targetCanvas.width, targetCanvas.height);
    if (isOrig) origLoupeSourceReady = true;
    else devLoupeSourceReady = true;
  } catch (_) {
    if (isOrig) origLoupeSourceReady = false;
    else devLoupeSourceReady = false;
  }
}

function initEyedropperViewport() {
  const wrapper = document.getElementById("splitWrapper");
  const loupe = document.getElementById("eyedropperLoupe");
  const loupeDot = document.getElementById("loupeDot");
  const loupeLabel = document.getElementById("loupeLabel");
  const loupeRgb = document.getElementById("loupeRgb");
  const cursorReadout = document.getElementById("cursorReadout");

  if (!wrapper) return;

  // The densitometer used to run on *every* mousemove event: a layout read
  // (getBoundingClientRect) plus a canvas readback (getImageData) at up to
  // 120 Hz saturated the main thread when a 16-bit TIFF was on screen.
  // Coordinates are now sampled and processed once per animation frame.
  let pendingMoveEvent = null;
  let moveFrameRequested = false;

  const processPointerMove = () => {
    moveFrameRequested = false;
    const e = pendingMoveEvent;
    pendingMoveEvent = null;
    if (!e) return;

    const coords = getViewportNormalizedCoords(e);
    if (!coords) return;
    const { xPct, yPct } = coords;

    // Live cursor densitometer readout for any view except sheet
    if (cursorReadout && state.frames.length > 0 && state.viewMode !== "sheet") {
      const readoutCanvas =
        state.viewMode === "original" && origLoupeSourceReady
          ? offscreenOrigLoupeCanvas
          : devLoupeSourceReady
          ? offscreenDevLoupeCanvas
          : null;
      const sample = readoutCanvas ? sampleCanvasRgb(readoutCanvas, xPct, yPct) : null;
      if (sample) {
        const zone = getZoneFromRgb(sample.r, sample.g, sample.b);
        cursorReadout.textContent = `R ${sample.r} · G ${sample.g} · B ${sample.b} · Zona ${zone}`;
      }
    }

    if (!negativeState.eyedropperActive || state.appMode !== "negative" || state.spacePressed) {
      if (loupe && loupe.style.display !== "none" && state.spacePressed) {
        loupe.style.display = "none";
      }
      return;
    }

    const wrapRect = wrapper.getBoundingClientRect();
    if (!wrapRect.width || !wrapRect.height) return;
    const wrapXPct = Math.max(0, Math.min(1, (e.clientX - wrapRect.left) / wrapRect.width));
    const wrapYPct = Math.max(0, Math.min(1, (e.clientY - wrapRect.top) / wrapRect.height));

    if (loupe) {
      loupe.style.display = "inline-flex";
      loupe.style.left = `${(wrapXPct * 100).toFixed(2)}%`;
      loupe.style.top = `${(wrapYPct * 100).toFixed(2)}%`;
      const tx = wrapXPct > 0.72 ? "calc(-100% - 14px)" : "16px";
      const ty = wrapYPct < 0.2 ? "18px" : "-48px";
      loupe.style.transform = `translate(${tx}, ${ty})`;
    }

    const isSceneWb = negativeState.eyedropperMode === "scene_wb";
    const sourceReady = isSceneWb ? devLoupeSourceReady : origLoupeSourceReady;
    const sourceCanvas = isSceneWb ? offscreenDevLoupeCanvas : offscreenOrigLoupeCanvas;

    if (sourceReady && sourceCanvas) {
      drawLoupeMagnifier(sourceCanvas, xPct, yPct);
      const sample = sampleCanvasRgb(sourceCanvas, xPct, yPct);
      if (sample) {
        const hex =
          "#" +
          [sample.r, sample.g, sample.b]
            .map((v) => v.toString(16).padStart(2, "0"))
            .join("")
            .toUpperCase();
        if (loupeDot) loupeDot.style.backgroundColor = hex;
        if (loupeLabel) {
          loupeLabel.textContent = isSceneWb ? `Neutro ${hex}` : hex;
        }
        if (loupeRgb) {
          loupeRgb.textContent = `R${sample.r} G${sample.g} B${sample.b}`;
        }
      }
    }
  };

  wrapper.addEventListener("mousemove", (e) => {
    pendingMoveEvent = e;
    if (!moveFrameRequested) {
      moveFrameRequested = true;
      requestAnimationFrame(processPointerMove);
    }
  });

  wrapper.addEventListener("mouseleave", () => {
    if (loupe) loupe.style.display = "none";
    if (cursorReadout) {
      cursorReadout.textContent = "Mueve el cursor para leer RGB y Zona";
    }
  });

  wrapper.addEventListener("click", async (e) => {
    if (!negativeState.eyedropperActive) return;
    if (negativeState.eyedropperMode !== "dust" && state.appMode !== "negative") return;
    if (state.spacePressed || viewportDragMoved > 4) return;
    if (e.target.closest("#splitDivider")) return;

    const coords = getViewportNormalizedCoords(e);
    if (!coords) return;
    const { xPct, yPct } = coords;
    const activeFrame = state.frames[state.activeFrameIndex];
    if (!activeFrame) return;

    if (negativeState.eyedropperMode === "dust") {
      if (!Array.isArray(negativeState.dustSpots)) negativeState.dustSpots = [];
      if (negativeState.dustSpots.length >= 150) {
        showToast("Límite alcanzado", "Máximo 150 puntos de limpieza por fotograma.");
        setEyedropperMode(null);
        return;
      }
      pushUndoSnapshotForFrame(activeFrame, state.appMode === "negative" ? "negative" : "simulation");
      negativeState.dustSpots.push({
        x: Number(xPct.toFixed(5)),
        y: Number(yPct.toFixed(5)),
        r: Number(negativeState.dustRadius || 0.008),
      });
      updateDustSpotsUI();
      saveActiveFrameRecipe();
      await requestPreview(false);
      return;
    }

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
        if (!res.ok || !Array.isArray(data.printer_cmy)) {
          throw new Error(data?.error || "No se pudo calcular el gris neutro en ese punto.");
        }
        pushUndoSnapshotForFrame(activeFrame, "negative");
        applySolvedCmy(data.printer_cmy);
        setEyedropperMode(null);
        await requestPreview(false);
        showToast("Gris neutro calibrado", "Luces CMY ajustadas sobre el punto muestreado.");
      } catch (err) {
        console.error("Scene WB sample error:", err);
        setEyedropperMode(null);
        showToast("No se pudo muestrear gris", err.message || "Intenta hacer clic sobre un tono neutro sin quemar.");
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
      if (!res.ok || !data.base_color) {
        throw new Error(data?.error || "No se pudo leer el soporte base en ese punto.");
      }
      pushUndoSnapshotForFrame(activeFrame, "negative");
      setBaseColor(data.base_color, data.base_hex || data.hex, "Muestra manual");
      saveActiveFrameRecipe();
      setEyedropperMode(null);
      await requestPreview(false);
      showToast("Soporte calibrado", `D-min neutralizado en ${data.base_hex || ""}`);
    } catch (err) {
      console.error("Eyedropper sample error:", err);
      setEyedropperMode(null);
      showToast("Error al muestrear soporte", err.message || "Intenta hacer clic sobre el borde sin exponer.");
    }
  });
}

// =============================================================
// EDITOR DE CURVA TONAL
//
// La curva se guarda como PUNTOS DE CONTROL (datos), nunca como píxeles:
// así cabe en la receta por fotograma, se copia, se sincroniza con el rollo,
// se deshace y se exporta sin tocar ningún otro mecanismo de la app.
// El motor (engine/pipeline.py) convierte esos puntos en una LUT monótona.
//
// Convención: x = posición de entrada (0 sombra, 1 luz), y = salida.
// El eje y crece hacia arriba: un punto por encima de la diagonal aclara.
// =============================================================

const CURVE_CHANNELS = ["rgb", "l", "r", "g", "b"];
const CURVE_CHANNEL_LABELS = { rgb: "RGB", l: "Luz", r: "R", g: "G", b: "B" };

function getActiveCurve() {
  return state.appMode === "negative" ? negativeState.curve : state.curve;
}

function setActiveCurve(nextCurve) {
  if (state.appMode === "negative") {
    negativeState.curve = nextCurve;
  } else {
    state.curve = nextCurve;
  }
}

function emptyCurve() {
  return { rgb: null, l: null, r: null, g: null, b: null };
}

function cloneCurve(curve) {
  const out = emptyCurve();
  if (!curve || typeof curve !== "object") return out;
  for (const ch of CURVE_CHANNELS) {
    const pts = curve[ch];
    if (Array.isArray(pts) && pts.length) {
      out[ch] = pts.map((p) => [Number(p[0]) || 0, Number(p[1]) || 0]);
    }
  }
  return out;
}

function curveIsIdentity(curve) {
  if (!curve) return true;
  return CURVE_CHANNELS.every((ch) => !curve[ch] || !curve[ch].length);
}

function curvePayload(curve) {
  // Sólo se envían los canales modificados: una receta sin curva no crece.
  const out = {};
  for (const ch of CURVE_CHANNELS) {
    const pts = curve?.[ch];
    if (Array.isArray(pts) && pts.length) {
      out[ch] = pts.map((p) => [
        Math.round(Math.min(Math.max(p[0], 0), 1) * 1000) / 1000,
        Math.round(Math.min(Math.max(p[1], 0), 1) * 1000) / 1000,
      ]);
    }
  }
  return Object.keys(out).length ? out : null;
}

function curvePoints(curve, channel) {
  const pts = curve?.[channel];
  return Array.isArray(pts) ? pts : [];
}

/** Curva efectiva: los extremos (0,0) y (1,1) siempre están, salvo que el
 *  usuario haya colocado un punto justo ahí (para levantar negros o bajar
 *  luces). Es el mismo modelo que usan los reveladores. */
function curveEffectivePoints(curve, channel) {
  const pts = curvePoints(curve, channel).map((p) => [p[0], p[1]]);
  if (!pts.length) return [];
  const hasLow = pts.some((p) => p[0] <= 1e-6);
  const hasHigh = pts.some((p) => p[0] >= 1 - 1e-6);
  if (!hasLow) pts.unshift([0, 0]);
  if (!hasHigh) pts.push([1, 1]);
  return pts.sort((a, b) => a[0] - b[0]);
}

function curveChannelHasEdits(curve, channel) {
  return curvePoints(curve, channel).length > 0;
}

// -------------------------------------------------------------
// Dibujo
// -------------------------------------------------------------

let curveHistBins = null;

function curveCanvasGeometry() {
  const canvas = document.getElementById("curveCanvas");
  if (!canvas) return null;
  const dpr = window.devicePixelRatio || 1;
  const cssW = canvas.clientWidth || 272;
  const cssH = canvas.clientHeight || 248;
  if (canvas.width !== Math.round(cssW * dpr) || canvas.height !== Math.round(cssH * dpr)) {
    canvas.width = Math.round(cssW * dpr);
    canvas.height = Math.round(cssH * dpr);
  }
  return { canvas, ctx: canvas.getContext("2d"), dpr, cssW, cssH };
}

function drawCurveEditor() {
  const geo = curveCanvasGeometry();
  if (!geo) return;
  const { ctx, dpr, cssW, cssH } = geo;

  ctx.save();
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, cssW, cssH);

  // Fondo del canal activo (sutil tinte por canal)
  const channel = state.curveChannel;
  const tints = {
    rgb: "rgba(236, 238, 242, 0.85)",
    l: "rgba(236, 238, 242, 0.85)",
    r: "rgba(229, 75, 75, 0.9)",
    g: "rgba(75, 210, 138, 0.9)",
    b: "rgba(92, 162, 250, 0.9)",
  };
  const accent = tints[channel] || tints.rgb;

  // Histograma de fondo (luminancia de la imagen desarrollada)
  if (curveHistBins) {
    const { yBins, maxPeak } = curveHistBins;
    ctx.beginPath();
    ctx.moveTo(0, cssH);
    for (let i = 0; i < 256; i++) {
      const x = (i / 255) * cssW;
      const norm = Math.min(1, yBins[i] / maxPeak);
      ctx.lineTo(x, cssH - Math.pow(norm, 0.78) * (cssH * 0.72));
    }
    ctx.lineTo(cssW, cssH);
    ctx.closePath();
    ctx.fillStyle = "rgba(236, 238, 242, 0.10)";
    ctx.fill();
  }

  // Rejilla de cuartos
  ctx.strokeStyle = "rgba(255, 255, 255, 0.07)";
  ctx.lineWidth = 1;
  [0.25, 0.5, 0.75].forEach((p) => {
    const x = Math.round(cssW * p) + 0.5;
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, cssH);
    ctx.stroke();
    const y = Math.round(cssH * p) + 0.5;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(cssW, y);
    ctx.stroke();
  });

  // Diagonal neutra (referencia)
  ctx.strokeStyle = "rgba(255, 255, 255, 0.13)";
  ctx.setLineDash([3, 3]);
  ctx.beginPath();
  ctx.moveTo(0, cssH);
  ctx.lineTo(cssW, 0);
  ctx.stroke();
  ctx.setLineDash([]);

  // Curva
  const activeCurve = getActiveCurve();
  const pts = curveEffectivePoints(activeCurve, channel);
  const toPx = (p) => [p[0] * cssW, (1 - p[1]) * cssH];

  if (pts.length) {
    ctx.beginPath();
    // Curva interpolada (monótona por tramos, como en el motor)
    const lut = sampleCurveMonotone(pts, 96);
    lut.forEach((p, i) => {
      const [px, py] = toPx(p);
      if (i === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    });
    ctx.strokeStyle = accent;
    ctx.lineWidth = 1.8;
    ctx.stroke();
  }

  // Puntos de control
  const user = curvePoints(activeCurve, channel);
  user.forEach((p, i) => {
    const [px, py] = toPx(p);
    ctx.beginPath();
    ctx.arc(px, py, 5.5, 0, Math.PI * 2);
    ctx.fillStyle = "#131518";
    ctx.fill();
    ctx.strokeStyle = accent;
    ctx.lineWidth = 2;
    ctx.stroke();
    if (curveDragIndex === i) {
      ctx.beginPath();
      ctx.arc(px, py, 8, 0, Math.PI * 2);
      ctx.strokeStyle = "rgba(229, 149, 40, 0.55)";
      ctx.lineWidth = 1.4;
      ctx.stroke();
    }
  });

  ctx.restore();
}

/** Muestreo de la curva con interpolación monótona por tramos (PCHIP).
 *  Reproduce en el cliente lo que el motor hará en el servidor: el usuario ve
 *  exactamente la curva que se va a exportar. */
function sampleCurveMonotone(points, samples = 96) {
  const pts = points.filter((p) => Number.isFinite(p[0]) && Number.isFinite(p[1]));
  if (!pts.length) return [];
  if (pts.length === 1) return [[pts[0][0], pts[0][1]]];

  const xs = pts.map((p) => p[0]);
  const ys = pts.map((p) => p[1]);

  // Pendientes (método de Fritsch-Carlson: monótono y sin sobreoscilación)
  const n = xs.length;
  const dx = [];
  const dy = [];
  const slope = [];
  for (let i = 0; i < n - 1; i++) {
    dx.push(xs[i + 1] - xs[i]);
    dy.push(ys[i + 1] - ys[i]);
    slope.push(dx[i] === 0 ? 0 : dy[i] / dx[i]);
  }
  const m = new Array(n);
  m[0] = slope[0];
  m[n - 1] = slope[n - 2];
  for (let i = 1; i < n - 1; i++) {
    if (slope[i - 1] * slope[i] <= 0) {
      m[i] = 0;
    } else {
      const w1 = 2 * dx[i] + dx[i - 1];
      const w2 = dx[i] + 2 * dx[i - 1];
      m[i] = (w1 + w2) / (w1 / slope[i - 1] + w2 / slope[i]);
    }
  }

  const out = [];
  for (let s = 0; s < samples; s++) {
    const x = s / (samples - 1);
    let i = 0;
    while (i < n - 2 && xs[i + 1] < x) i++;
    const h = dx[i] || 1e-6;
    const t = (x - xs[i]) / h;
    const t2 = t * t;
    const t3 = t2 * t;
    const h00 = 2 * t3 - 3 * t2 + 1;
    const h10 = t3 - 2 * t2 + t;
    const h01 = -2 * t3 + 3 * t2;
    const h11 = t3 - t2;
    const y =
      h00 * ys[i] + h10 * h * m[i] + h01 * ys[i + 1] + h11 * h * m[i + 1];
    out.push([x, Math.min(Math.max(y, 0), 1)]);
  }
  return out;
}

// -------------------------------------------------------------
// Interacción
// -------------------------------------------------------------

let curveDragIndex = -1;

function curvePointFromEvent(ev) {
  const canvas = document.getElementById("curveCanvas");
  if (!canvas) return null;
  const rect = canvas.getBoundingClientRect();
  const x = Math.min(Math.max((ev.clientX - rect.left) / rect.width, 0), 1);
  const y = Math.min(Math.max(1 - (ev.clientY - rect.top) / rect.height, 0), 1);
  return [x, y];
}

function curveHitTest(pos) {
  const pts = curvePoints(getActiveCurve(), state.curveChannel);
  const canvas = document.getElementById("curveCanvas");
  if (!canvas || !pts.length) return -1;
  const rect = canvas.getBoundingClientRect();
  const r = 12 / Math.max(rect.width, 1);
  for (let i = 0; i < pts.length; i++) {
    const dx = Math.abs(pts[i][0] - pos[0]);
    const dy = Math.abs(pts[i][1] - pos[1]);
    if (dx <= r && dy <= r * (rect.height / Math.max(rect.width, 1)) * 1.6) return i;
  }
  return -1;
}

function curveAddPoint(pos) {
  const channel = state.curveChannel;
  let curve = getActiveCurve();
  if (!curve) {
    curve = emptyCurve();
    setActiveCurve(curve);
  }
  const pts = curvePoints(curve, channel).map((p) => [p[0], p[1]]);
  // Un punto por posición: si ya hay uno muy cerca, se sustituye.
  const near = pts.findIndex((p) => Math.abs(p[0] - pos[0]) < 0.012);
  if (near >= 0) {
    pts[near] = [pos[0], pos[1]];
  } else {
    pts.push([pos[0], pos[1]]);
    pts.sort((a, b) => a[0] - b[0]);
  }
  curve[channel] = pts;
}

function curveRemovePoint(index) {
  const channel = state.curveChannel;
  const curve = getActiveCurve();
  if (!curve) return;
  const pts = curvePoints(curve, channel).map((p) => [p[0], p[1]]);
  if (index < 0 || index >= pts.length) return;
  pts.splice(index, 1);
  curve[channel] = pts.length ? pts : null;
  if (!curve[channel]) delete curve[channel];
}

function curveMovePoint(index, pos) {
  const channel = state.curveChannel;
  const curve = getActiveCurve();
  if (!curve) return;
  const pts = curvePoints(curve, channel).map((p) => [p[0], p[1]]);
  if (index < 0 || index >= pts.length) return;
  pts[index] = [pos[0], pos[1]];
  pts.sort((a, b) => a[0] - b[0]);
  curve[channel] = pts;
  curveDragIndex = pts.findIndex((p) => p[0] === pts[Math.min(index, pts.length - 1)][0]);
}

function setCurveChannel(channel) {
  if (!CURVE_CHANNELS.includes(channel)) return;
  state.curveChannel = channel;
  document.querySelectorAll("#curveTabs .curve-tab").forEach((btn) => {
    const active = btn.dataset.channel === channel;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-selected", active ? "true" : "false");
  });
  drawCurveEditor();
}

function initCurveEditor() {
  const canvas = document.getElementById("curveCanvas");
  if (!canvas) return;

  document.querySelectorAll("#curveTabs .curve-tab").forEach((btn) => {
    btn.addEventListener("click", () => setCurveChannel(btn.dataset.channel));
  });

  document.getElementById("resetCurveBtn")?.addEventListener("click", () => {
    pushUndoSnapshotForFrame();
    const channel = state.curveChannel;
    const curve = getActiveCurve();
    if (curve) {
      delete curve[channel];
    }
    saveActiveFrameRecipe();
    drawCurveEditor();
    triggerDebouncedPreview("curve");
  });

  canvas.addEventListener("pointerdown", (ev) => {
    if (ev.button !== 0) return;
    const pos = curvePointFromEvent(ev);
    if (!pos) return;
    const hit = curveHitTest(pos);
    if (hit < 0) {
      pushUndoSnapshotForFrame();
      curveAddPoint(pos);
      saveActiveFrameRecipe();
      drawCurveEditor();
      triggerDebouncedPreview("curve");
      curveDragIndex = curvePoints(getActiveCurve(), state.curveChannel).length - 1;
    } else {
      pushUndoSnapshotForFrame();
      curveDragIndex = hit;
      canvas.classList.add("is-dragging");
    }
    canvas.setPointerCapture?.(ev.pointerId);
    ev.preventDefault();
  });

  canvas.addEventListener("pointermove", (ev) => {
    if (curveDragIndex < 0) return;
    const pos = curvePointFromEvent(ev);
    if (!pos) return;
    curveMovePoint(curveDragIndex, pos);
    drawCurveEditor();
    triggerDebouncedPreview("curve");
  });

  const endDrag = (ev) => {
    if (curveDragIndex >= 0) {
      curveDragIndex = -1;
      canvas.classList.remove("is-dragging");
      saveActiveFrameRecipe();
      saveUserPreferences();
    }
    canvas.releasePointerCapture?.(ev.pointerId);
  };
  canvas.addEventListener("pointerup", endDrag);
  canvas.addEventListener("pointercancel", endDrag);

  canvas.addEventListener("dblclick", (ev) => {
    const pos = curvePointFromEvent(ev);
    if (!pos) return;
    const hit = curveHitTest(pos);
    if (hit < 0) return;
    pushUndoSnapshotForFrame();
    curveRemovePoint(hit);
    saveActiveFrameRecipe();
    drawCurveEditor();
    triggerDebouncedPreview("curve");
    ev.preventDefault();
  });

  let curveKeyIndex = 0;
  canvas.addEventListener("keydown", (ev) => {
    const channel = state.curveChannel;
    let pts = curvePoints(getActiveCurve(), channel);
    const step = ev.shiftKey ? 0.05 : 0.02;

    if (ev.key === "Enter" || ev.key === " ") {
      ev.preventDefault();
      pushUndoSnapshotForFrame();
      const targetX = pts.length === 0 ? 0.5 : Math.min(0.92, Math.max(0.08, (pts[pts.length - 1][0] + 0.15) % 0.9));
      curveAddPoint([targetX, targetX]);
      pts = curvePoints(getActiveCurve(), channel);
      curveKeyIndex = Math.max(0, pts.findIndex((p) => Math.abs(p[0] - targetX) < 0.02));
      saveActiveFrameRecipe();
      drawCurveEditor();
      triggerDebouncedPreview("curve");
      return;
    }

    if (ev.key === "[" || ev.key === "]") {
      if (!pts.length) return;
      ev.preventDefault();
      curveKeyIndex = (curveKeyIndex + (ev.key === "]" ? 1 : pts.length - 1)) % pts.length;
      return;
    }

    if (ev.key === "Delete" || ev.key === "Backspace") {
      if (!pts.length) return;
      ev.preventDefault();
      pushUndoSnapshotForFrame();
      const idx = Math.min(Math.max(0, curveKeyIndex), pts.length - 1);
      curveRemovePoint(idx);
      pts = curvePoints(getActiveCurve(), channel);
      curveKeyIndex = Math.max(0, Math.min(idx, pts.length - 1));
      saveActiveFrameRecipe();
      drawCurveEditor();
      triggerDebouncedPreview("curve");
      return;
    }

    let dx = 0;
    let dy = 0;
    if (ev.key === "ArrowLeft") dx = -step;
    else if (ev.key === "ArrowRight") dx = step;
    else if (ev.key === "ArrowUp") dy = step;
    else if (ev.key === "ArrowDown") dy = -step;
    else return;

    ev.preventDefault();
    pushUndoSnapshotForFrame();
    if (!pts.length) {
      curveAddPoint([0.5, 0.5]);
      pts = curvePoints(getActiveCurve(), channel);
      curveKeyIndex = 0;
    }
    const idx = Math.min(Math.max(0, curveKeyIndex), pts.length - 1);
    const nx = Math.min(1, Math.max(0, Number((pts[idx][0] + dx).toFixed(3))));
    const ny = Math.min(1, Math.max(0, Number((pts[idx][1] + dy).toFixed(3))));
    curveMovePoint(idx, [nx, ny]);
    const updatedPts = curvePoints(getActiveCurve(), channel);
    const movedIdx = updatedPts.findIndex((p) => Math.abs(p[0] - nx) < 1e-4 && Math.abs(p[1] - ny) < 1e-4);
    if (movedIdx >= 0) curveKeyIndex = movedIdx;
    saveActiveFrameRecipe();
    drawCurveEditor();
    triggerDebouncedPreview("curve");
  });
}


function computeHistBins(imgEl) {
  if (!imgEl || !imgEl.naturalWidth || !imgEl.naturalHeight) return null;
  const maxSample = 256;
  const scale = Math.min(1, maxSample / Math.max(imgEl.naturalWidth, imgEl.naturalHeight));
  const sampleW = Math.max(1, Math.round(imgEl.naturalWidth * scale));
  const sampleH = Math.max(1, Math.round(imgEl.naturalHeight * scale));
  if (!offscreenHistCanvas) offscreenHistCanvas = document.createElement("canvas");
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

  // Normalize ignoring extreme spikes at bin 0 and 255 for clean legibility
  let maxPeak = 1;
  for (let b = 2; b < 254; b++) {
    maxPeak = Math.max(maxPeak, rBins[b], gBins[b], bBins[b], yBins[b]);
  }
  return { rBins, gBins, bBins, yBins, maxPeak, totalPixels, shadowClipCount, highlightClipCount };
}

function renderHistogramFromImage(imgEl) {
  const canvas = document.getElementById("histogramCanvas");
  if (!canvas || !imgEl || !imgEl.naturalWidth) return;

  const bins = computeHistBins(imgEl);
  if (!bins) return;
  const { rBins, gBins, bBins, yBins, maxPeak, totalPixels, shadowClipCount, highlightClipCount } = bins;

  // El editor de curva usa el mismo histograma como fondo
  curveHistBins = bins;
  drawCurveEditor();

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

  if (state.safelight) {
    drawChannel(rBins, "rgba(185, 38, 34, 0.24)", "rgba(218, 62, 52, 0.65)");
    drawChannel(gBins, "rgba(150, 44, 30, 0.18)", "rgba(188, 74, 48, 0.5)");
    drawChannel(bBins, "rgba(120, 28, 28, 0.18)", "rgba(162, 50, 46, 0.45)");
  } else {
    drawChannel(rBins, "rgba(229, 75, 75, 0.26)", "rgba(235, 95, 95, 0.75)");
    drawChannel(gBins, "rgba(58, 190, 120, 0.24)", "rgba(75, 210, 138, 0.75)");
    drawChannel(bBins, "rgba(68, 142, 238, 0.26)", "rgba(92, 162, 250, 0.75)");
  }

  ctx.globalCompositeOperation = "source-over";
  ctx.beginPath();
  for (let i = 0; i < 256; i++) {
    const x = (i / 255) * cssW;
    const norm = Math.min(1, yBins[i] / maxPeak);
    const y = cssH - Math.pow(norm, 0.78) * (cssH - 6);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.strokeStyle = state.safelight ? "rgba(255, 118, 96, 0.9)" : "rgba(236, 238, 242, 0.72)";
  ctx.lineWidth = 1.2;
  ctx.stroke();

  ctx.restore();
  renderZebraOverlay();
  renderBorderGuideOverlay();
}

function renderZebraOverlay() {
  const zebraCanvas = document.getElementById("zebraCanvas");
  const imgDev = document.getElementById("imgDeveloped");
  if (!zebraCanvas) return;

  const active = Boolean(state.zebraMode?.shadows || state.zebraMode?.highlights);
  if (
    !active ||
    state.frames.length === 0 ||
    state.viewMode === "sheet" ||
    !imgDev ||
    !imgDev.naturalWidth
  ) {
    zebraCanvas.style.display = "none";
    return;
  }

  const src = devLoupeSourceReady && offscreenDevLoupeCanvas ? offscreenDevLoupeCanvas : null;
  const maxDim = 640;
  let w;
  let h;
  let srcPixels;

  if (src && src.width && src.height) {
    const scale = Math.min(1, maxDim / Math.max(src.width, src.height));
    w = Math.max(1, Math.round(src.width * scale));
    h = Math.max(1, Math.round(src.height * scale));
    const tmp = document.createElement("canvas");
    tmp.width = w;
    tmp.height = h;
    const tCtx = tmp.getContext("2d", { willReadFrequently: true });
    tCtx.drawImage(src, 0, 0, w, h);
    srcPixels = tCtx.getImageData(0, 0, w, h).data;
  } else {
    const scale = Math.min(1, maxDim / Math.max(imgDev.naturalWidth, imgDev.naturalHeight));
    w = Math.max(1, Math.round(imgDev.naturalWidth * scale));
    h = Math.max(1, Math.round(imgDev.naturalHeight * scale));
    const tmp = document.createElement("canvas");
    tmp.width = w;
    tmp.height = h;
    const tCtx = tmp.getContext("2d", { willReadFrequently: true });
    tCtx.drawImage(imgDev, 0, 0, w, h);
    srcPixels = tCtx.getImageData(0, 0, w, h).data;
  }

  zebraCanvas.width = w;
  zebraCanvas.height = h;
  const zCtx = zebraCanvas.getContext("2d");
  const outImg = zCtx.createImageData(w, h);
  const out = outImg.data;
  const showHi = Boolean(state.zebraMode.highlights);
  const showLo = Boolean(state.zebraMode.shadows);

  for (let i = 0; i < srcPixels.length; i += 4) {
    const r = srcPixels[i];
    const g = srcPixels[i + 1];
    const b = srcPixels[i + 2];
    if (showHi && (r >= 254 || g >= 254 || b >= 254)) {
      out[i] = 255;
      out[i + 1] = 58;
      out[i + 2] = 48;
      out[i + 3] = 184;
    } else if (showLo) {
      const luma = 0.2126 * r + 0.7152 * g + 0.0722 * b;
      if (luma <= 3 && r <= 4 && g <= 4 && b <= 4) {
        out[i] = 64;
        out[i + 1] = 156;
        out[i + 2] = 255;
        out[i + 3] = 184;
      }
    }
  }

  zCtx.putImageData(outImg, 0, 0);
  zebraCanvas.style.display = "block";
  if (state.viewMode === "split") {
    applySplitPercent(state.splitPercent);
  } else if (state.viewMode === "full") {
    zebraCanvas.style.clipPath = "polygon(0 0, 100% 0, 100% 100%, 0 100%)";
  } else if (state.viewMode === "original") {
    zebraCanvas.style.clipPath = "polygon(0 0, 0 0, 0 100%, 0 100%)";
  }
}

function toggleZebraChannel(channel = "both") {
  if (!state.zebraMode) state.zebraMode = { shadows: false, highlights: false };
  if (channel === "shadows") {
    state.zebraMode.shadows = !state.zebraMode.shadows;
  } else if (channel === "highlights") {
    state.zebraMode.highlights = !state.zebraMode.highlights;
  } else {
    const anyOn = state.zebraMode.shadows || state.zebraMode.highlights;
    state.zebraMode.shadows = !anyOn;
    state.zebraMode.highlights = !anyOn;
  }

  const clipS = document.getElementById("clipShadows");
  const clipH = document.getElementById("clipHighlights");
  if (clipS) {
    clipS.classList.toggle("active", state.zebraMode.shadows);
    clipS.setAttribute("aria-pressed", state.zebraMode.shadows ? "true" : "false");
  }
  if (clipH) {
    clipH.classList.toggle("active", state.zebraMode.highlights);
    clipH.setAttribute("aria-pressed", state.zebraMode.highlights ? "true" : "false");
  }

  renderZebraOverlay();
  renderBorderGuideOverlay();
}

// =============================================================
// VIEWPORT: SPLIT SLIDER, VIEW MODES, GEOMETRY & ZOOM/PAN
// =============================================================

function initSplitSlider() {
  const wrapper = document.getElementById("splitWrapper");
  const divider = document.getElementById("splitDivider");
  if (!wrapper || !divider) return;

  let dragging = false;
  // The wrapper width is cached: applySplitPercent() writes styles and then
  // reads clientWidth, which forced a synchronous layout on every pointer
  // move (layout thrashing). The cache is refreshed on resize.
  let cachedWrapWidth = wrapper.clientWidth;
  const refreshWrapWidth = () => {
    cachedWrapWidth = wrapper.clientWidth;
  };
  window.addEventListener("resize", refreshWrapWidth);

  const updateFromClientX = (clientX) => {
    if (state.viewMode !== "split") return;
    const rect = wrapper.getBoundingClientRect();
    if (!rect.width) return;
    let pct = ((clientX - rect.left) / rect.width) * 100;
    pct = Math.max(0, Math.min(100, pct));
    applySplitPercent(pct, cachedWrapWidth);
  };

  divider.addEventListener("mousedown", (e) => {
    e.stopPropagation();
    dragging = true;
  });
  window.addEventListener("mouseup", () => {
    dragging = false;
  });
  // Throttle the drag to one repaint per animation frame.
  let pendingDragX = null;
  let dragFrameRequested = false;
  const flushDrag = () => {
    dragFrameRequested = false;
    const clientX = pendingDragX;
    pendingDragX = null;
    if (clientX !== null) updateFromClientX(clientX);
  };
  window.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    pendingDragX = e.clientX;
    if (!dragFrameRequested) {
      dragFrameRequested = true;
      requestAnimationFrame(flushDrag);
    }
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

function applySplitPercent(pct, wrapWidth = null) {
  state.splitPercent = pct;
  const wrapper = document.getElementById("splitWrapper");
  const divider = document.getElementById("splitDivider");
  const imgOrig = document.getElementById("imgOriginal");
  const zebraCanvas = document.getElementById("zebraCanvas");

  if (divider) {
    divider.style.left = `${pct}%`;
    divider.setAttribute("aria-valuenow", String(Math.round(pct)));
    divider.setAttribute("aria-valuetext", `${Math.round(pct)}%`);
  }

  if (state.viewMode === "split") {
    let localPct = pct;
    const wrapW = wrapWidth !== null ? wrapWidth : wrapper?.clientWidth || 0;
    if (wrapW > 0 && state.zoom > 1.01) {
      localPct = Math.max(
        0,
        Math.min(100, 50 + ((((pct - 50) * wrapW) / 100 - state.panX) / (wrapW * state.zoom)) * 100)
      );
    }
    if (imgOrig) {
      imgOrig.style.clipPath = `polygon(0 0, ${localPct}% 0, ${localPct}% 100%, 0 100%)`;
    }
    if (zebraCanvas) {
      zebraCanvas.style.clipPath = `polygon(${localPct}% 0, 100% 0, 100% 100%, ${localPct}% 100%)`;
    }
  }
}

function updateContextualExportBar() {
  const isSheet = state.viewMode === "sheet";
  const saveBtn = document.getElementById("saveDownloadsBtn");
  const saveLbl = document.getElementById("saveDownloadsLabel");
  const saveSheetBtn = document.getElementById("saveSheetBtn");
  const saveAsBtn = document.getElementById("saveAsBtn");
  const copy = getOsCopy();

  if (isSheet) {
    if (saveLbl) saveLbl.textContent = "Guardar contactos";
    if (saveBtn) saveBtn.title = `Guardar hoja de contactos en alta resolución (${copy.saveKbd})`;
    if (saveAsBtn) saveAsBtn.title = `Elegir carpeta y nombre para la hoja de contactos (${copy.saveAsKbd})`;
    if (saveSheetBtn) saveSheetBtn.style.display = "none";
  } else {
    if (saveLbl) saveLbl.textContent = "Guardar";
    if (saveBtn) saveBtn.title = `Guardar fotografía a resolución completa en Descargas (${copy.saveKbd})`;
    if (saveAsBtn) saveAsBtn.title = `Elegir carpeta y nombre con diálogo nativo (${copy.saveAsKbd})`;
    if (saveSheetBtn) saveSheetBtn.style.display = "flex";
  }
}

function applyTestStripResult(data) {
  const imgDev = document.getElementById("imgDeveloped");
  if (data.strip && imgDev) {
    devLoupeSourceReady = false;
    imgDev.onload = () => {
      prepareLoupeBuffer(imgDev, "dev");
      renderHistogramFromImage(imgDev);
    };
    imgDev.src = data.strip;
  }

  const statRes = document.getElementById("statResolution");
  const statTime = document.getElementById("statTime");
  if (statRes && data.width && data.height) {
    statRes.textContent = `${data.width}×${data.height}`;
  }
  if (statTime && data.render_time != null) {
    statTime.textContent = `${Math.round(data.render_time * 1000)} ms`;
  }

  state.testStripSteps = Array.isArray(data.steps) ? data.steps : [];
  renderTestStripCols(state.testStripSteps);
}

function renderTestStripCols(steps) {
  const colsEl = document.getElementById("testStripCols");
  if (!colsEl) return;
  colsEl.innerHTML = "";
  (steps || []).forEach((step) => {
    const btn = document.createElement("button");
    btn.type = "button";
    const isCenter = Math.abs(Number(step.delta_ev) || 0) < 1e-3;
    btn.className = `test-strip-col${isCenter ? " is-center" : ""}`;
    btn.title = `Aplicar exposición ${step.label}`;
    btn.setAttribute("aria-label", `Aplicar banda ${step.label}`);
    const badge = document.createElement("span");
    badge.className = "test-strip-badge";
    badge.textContent = isCenter ? "Actual" : step.label;
    btn.appendChild(badge);
    btn.addEventListener("click", () => selectTestStripStep(step));
    colsEl.appendChild(btn);
  });
}

function selectTestStripStep(step) {
  if (!step || state.frames.length === 0) return;
  pushUndoSnapshotForFrame();
  if (state.appMode === "negative") {
    const clamped = Math.max(-1.0, Math.min(1.0, Number(step.target_value) || 0));
    negativeState.brightness = clamped;
    const fmtS = `${clamped > 0 ? "+" : ""}${clamped.toFixed(2)}`;
    setSliderSilent("negBrightnessSlider", "negBrightnessVal", clamped, fmtS);
  } else {
    const slider = document.getElementById("evSlider");
    const minEv = slider ? parseFloat(slider.min) : -2.0;
    const maxEv = slider ? parseFloat(slider.max) : 2.0;
    const clamped = Math.max(minEv, Math.min(maxEv, Math.round(Number(step.target_value) * 10) / 10));
    state.ev = clamped;
    setSliderSilent("evSlider", "evVal", clamped, `${clamped > 0 ? "+" : ""}${clamped.toFixed(1)} EV`);
  }
  saveActiveFrameRecipe();
  saveUserPreferences();
  const returnMode = state.prevViewMode === "split" ? "split" : "full";
  setViewMode(returnMode);
  showToast("Tira f-stop aplicada", `Exposición ajustada (${step.label}).`);
}

function setViewMode(mode) {
  const prevMode = state.viewMode;
  if (mode === "teststrip" && prevMode !== "teststrip" && prevMode !== "sheet") {
    state.prevViewMode = prevMode;
  }
  state.viewMode = mode;

  const viewBtnMap = {
    split: "viewSplitBtn",
    full: "viewFullBtn",
    original: "viewOrigBtn",
    sheet: "viewSheetBtn",
    teststrip: "viewTestStripBtn",
  };
  Object.entries(viewBtnMap).forEach(([k, id]) => {
    const el = document.getElementById(id);
    if (el) {
      el.classList.toggle("active", mode === k);
      el.setAttribute("aria-pressed", mode === k ? "true" : "false");
    }
  });

  updateContextualExportBar();

  const stripOverlay = document.getElementById("testStripOverlay");
  if (stripOverlay) {
    stripOverlay.style.display = mode === "teststrip" && state.frames.length > 0 ? "flex" : "none";
  }

  if (state.frames.length === 0) {
    syncEmptyRollButtons(true);
    return;
  }
  syncEmptyRollButtons(false);

  const splitWrapper = document.getElementById("splitWrapper");
  const sheetContainer = document.getElementById("sheetContainer");
  const divider = document.getElementById("splitDivider");
  const imgOrig = document.getElementById("imgOriginal");
  const zebraCanvas = document.getElementById("zebraCanvas");
  const origLabel = document.getElementById("originalLabel");
  const devLabel = document.getElementById("developedLabel");

  if (mode === "sheet") {
    if (splitWrapper) splitWrapper.style.display = "none";
    if (sheetContainer) sheetContainer.style.display = "flex";
    const rollInput = document.getElementById("sheetRollNameInput");
    if (rollInput) {
      rollInput.placeholder = state.appMode === "negative" ? "HALURO NEG" : "HALURO ROLL";
    }
    applyZoomTransform();
    renderZebraOverlay();
    generateContactSheetPreview();
    return;
  }

  if (splitWrapper) splitWrapper.style.display = "block";
  if (sheetContainer) sheetContainer.style.display = "none";
  applyZoomTransform();

  if (mode === "split") {
    if (divider) divider.style.display = "block";
    if (origLabel) origLabel.style.display = "block";
    if (devLabel) devLabel.style.display = "block";
    applySplitPercent(state.splitPercent);
  } else if (mode === "full" || mode === "teststrip") {
    if (divider) divider.style.display = "none";
    if (origLabel) origLabel.style.display = "none";
    if (devLabel) devLabel.style.display = mode === "teststrip" ? "none" : "block";
    if (imgOrig) {
      imgOrig.style.clipPath = "polygon(0 0, 0 0, 0 100%, 0 100%)";
    }
    if (zebraCanvas) {
      zebraCanvas.style.clipPath = "polygon(0 0, 100% 0, 100% 100%, 0 100%)";
    }
  } else if (mode === "original") {
    if (divider) divider.style.display = "none";
    if (origLabel) origLabel.style.display = "block";
    if (devLabel) devLabel.style.display = "none";
    if (imgOrig) {
      imgOrig.style.clipPath = "polygon(0 0, 100% 0, 100% 100%, 0 100%)";
    }
    if (zebraCanvas) {
      zebraCanvas.style.clipPath = "polygon(0 0, 0 0, 0 100%, 0 100%)";
    }
  }
  renderZebraOverlay();
  renderBorderGuideOverlay();
  if (mode === "teststrip" || prevMode === "teststrip") {
    requestPreview(false);
  }
}

let sheetDragMoved = 0;
let viewportDragMoved = 0;

function initZoomAndPan() {
  const container = document.getElementById("canvasContainer");
  const wrapper = document.getElementById("splitWrapper");
  const sheetStage = document.getElementById("sheetStage");
  const sheetWrapper = document.getElementById("sheetWrapper");
  if (!container || !wrapper) return;

  let panning = false;
  let sheetPanning = false;
  let startX = 0;
  let startY = 0;
  let downClientX = 0;
  let downClientY = 0;
  let viewDownX = 0;
  let viewDownY = 0;

  container.addEventListener(
    "wheel",
    (e) => {
      e.preventDefault();
      const delta = e.deltaY < 0 ? 0.2 : -0.2;
      if (state.viewMode === "sheet") {
        setZoom(state.sheetZoom + delta);
      } else {
        setZoom(state.zoom + delta);
      }
    },
    { passive: false }
  );

  wrapper.addEventListener("mousedown", (e) => {
    if (e.button !== 0) return;
    viewportDragMoved = 0;
    viewDownX = e.clientX;
    viewDownY = e.clientY;
    if (e.target.closest("#splitDivider")) return;
    const allowPan = state.zoom > 1.01 && (!negativeState.eyedropperActive || state.spacePressed);
    if (!allowPan) return;
    panning = true;
    startX = e.clientX - state.panX;
    startY = e.clientY - state.panY;
    wrapper.classList.add("is-panning");
  });

  if (sheetStage && sheetWrapper) {
    sheetStage.addEventListener("mousedown", (e) => {
      if (e.button !== 0) return;
      downClientX = e.clientX;
      downClientY = e.clientY;
      sheetDragMoved = 0;
      if (state.sheetZoom <= 1.01) return;
      sheetPanning = true;
      startX = e.clientX - state.sheetPanX;
      startY = e.clientY - state.sheetPanY;
      sheetWrapper.classList.add("is-panning");
    });
  }

  window.addEventListener("mousemove", (e) => {
    if (panning) {
      viewportDragMoved = Math.hypot(e.clientX - viewDownX, e.clientY - viewDownY);
      state.panX = e.clientX - startX;
      state.panY = e.clientY - startY;
      applyZoomTransform();
    } else if (sheetPanning) {
      sheetDragMoved = Math.hypot(e.clientX - downClientX, e.clientY - downClientY);
      state.sheetPanX = e.clientX - startX;
      state.sheetPanY = e.clientY - startY;
      applyZoomTransform();
    }
  });

  window.addEventListener("mouseup", () => {
    if (panning) {
      panning = false;
      wrapper.classList.remove("is-panning");
    }
    if (sheetPanning) {
      sheetPanning = false;
      sheetWrapper?.classList.remove("is-panning");
    }
  });
}

function setZoom(nextZoom) {
  const clamped = Math.max(1.0, Math.min(4.0, Math.round(nextZoom * 100) / 100));
  if (state.viewMode === "sheet") {
    state.sheetZoom = clamped;
    if (clamped <= 1.01) {
      state.sheetPanX = 0;
      state.sheetPanY = 0;
    }
  } else {
    state.zoom = clamped;
    if (clamped <= 1.01) {
      state.panX = 0;
      state.panY = 0;
    }
  }
  applyZoomTransform();
}

function resetZoom() {
  if (state.viewMode === "sheet") {
    state.sheetZoom = 1.0;
    state.sheetPanX = 0;
    state.sheetPanY = 0;
  } else {
    state.zoom = 1.0;
    state.panX = 0;
    state.panY = 0;
  }
  applyZoomTransform();
}

function applyZoomTransform() {
  const wrapper = document.getElementById("splitWrapper");
  const mediaLayer = document.getElementById("splitMediaLayer");
  const sheetWrapper = document.getElementById("sheetWrapper");
  const sheetStage = document.getElementById("sheetStage");
  const readout = document.getElementById("zoomResetBtn");

  if (state.viewMode === "sheet") {
    if (sheetWrapper) {
      sheetWrapper.style.transform =
        state.sheetZoom <= 1.01
          ? "none"
          : `translate(${state.sheetPanX}px, ${state.sheetPanY}px) scale(${state.sheetZoom})`;
    }
    if (sheetStage) {
      sheetStage.classList.toggle("can-pan", state.sheetZoom > 1.01);
    }
    if (readout) {
      readout.textContent = state.sheetZoom <= 1.01 ? "Ajustar" : `${Math.round(state.sheetZoom * 100)}%`;
    }
    return;
  }

  if (wrapper) {
    wrapper.style.transform = "none";
  }
  if (mediaLayer) {
    mediaLayer.style.transform =
      state.zoom <= 1.01
        ? "none"
        : `translate(${state.panX}px, ${state.panY}px) scale(${state.zoom})`;
  }
  if (readout) {
    readout.textContent = state.zoom <= 1.01 ? "Ajustar" : `${Math.round(state.zoom * 100)}%`;
  }
  if (state.viewMode === "split") {
    applySplitPercent(state.splitPercent);
  }
}

function rotateCurrentFrame(deltaDeg) {
  pushUndoSnapshotForFrame();
  state.rotate = (((state.rotate + deltaDeg) % 360) + 360) % 360;
  saveActiveFrameRecipe();
  state.lastOriginalKey = "";
  requestPreview(true);
}

function toggleHorizontalFlip() {
  pushUndoSnapshotForFrame();
  state.flip_h = !state.flip_h;
  document.getElementById("flipHBtn")?.classList.toggle("active", state.flip_h);
  document.getElementById("flipHBtn")?.setAttribute("aria-pressed", state.flip_h ? "true" : "false");
  saveActiveFrameRecipe();
  state.lastOriginalKey = "";
  requestPreview(true);
}

function toggleVerticalFlip() {
  pushUndoSnapshotForFrame();
  state.flip_v = !state.flip_v;
  syncGeometryUiControls();
  saveActiveFrameRecipe();
  state.lastOriginalKey = "";
  requestPreview(true);
}

function hasNonDefaultGeometry() {
  const r = state.crop_rect;
  const hasCrop = Boolean(r && (r.x > 0.002 || r.y > 0.002 || r.w < 0.996 || r.h < 0.996));
  return Boolean(
    hasCrop ||
    Math.abs(Number(state.straighten || 0)) > 0.05 ||
    Math.abs(Number(state.keystone_v || 0)) > 0.05 ||
    Math.abs(Number(state.keystone_h || 0)) > 0.05 ||
    (Number(state.rotate || 0) % 360) !== 0 ||
    state.flip_h ||
    state.flip_v
  );
}

function syncGeometryUiControls() {
  const fvBtn = document.getElementById("flipVBtn");
  if (fvBtn) {
    fvBtn.classList.toggle("active", Boolean(state.flip_v));
    fvBtn.setAttribute("aria-pressed", state.flip_v ? "true" : "false");
  }
  document.getElementById("inspFlipVBtn")?.classList.toggle("active", Boolean(state.flip_v));
  document.getElementById("geomFlipVBtn")?.classList.toggle("active", Boolean(state.flip_v));
  document.getElementById("inspFlipHBtn")?.classList.toggle("active", Boolean(state.flip_h));
  document.getElementById("geomFlipHBtn")?.classList.toggle("active", Boolean(state.flip_h));

  const sValNum = Number(state.straighten || 0);
  const sSlider = document.getElementById("straightenSlider");
  const sVal = document.getElementById("straightenVal");
  if (sSlider) sSlider.value = String(sValNum);
  if (sVal) sVal.textContent = `${sValNum.toFixed(1)}°`;

  const inspSSlider = document.getElementById("inspStraightenSlider");
  const inspSVal = document.getElementById("inspStraightenVal");
  if (inspSSlider) inspSSlider.value = String(sValNum);
  if (inspSVal) inspSVal.textContent = `${sValNum.toFixed(1)}°`;

  const kvSlider = document.getElementById("keystoneVSlider");
  const kvVal = document.getElementById("keystoneVVal");
  if (kvSlider) kvSlider.value = String(state.keystone_v || 0);
  if (kvVal) kvVal.textContent = `${Number(state.keystone_v || 0).toFixed(1)}°`;

  const khSlider = document.getElementById("keystoneHSlider");
  const khVal = document.getElementById("keystoneHVal");
  if (khSlider) khSlider.value = String(state.keystone_h || 0);
  if (khVal) khVal.textContent = `${Number(state.keystone_h || 0).toFixed(1)}°`;

  const autoChk = document.getElementById("autoCropStraightenCheck");
  if (autoChk) autoChk.checked = state.auto_crop_straighten !== false;

  const edited = hasNonDefaultGeometry();
  document.getElementById("cropToolBtn")?.classList.toggle("has-geometry", edited);
  const badge = document.getElementById("geomStatusBadge");
  if (badge) badge.textContent = edited ? "Editado" : "Original";
}

function getAspectRatioValue(aspectKey, imgW, imgH) {
  if (!aspectKey || aspectKey === "free") return null;
  let ratio = null;
  if (aspectKey === "original") {
    ratio = imgW > 0 && imgH > 0 ? imgW / imgH : 1.5;
  } else {
    const parts = aspectKey.split(":").map(Number);
    if (parts.length === 2 && parts[0] > 0 && parts[1] > 0) {
      ratio = parts[0] / parts[1];
    }
  }
  if (!ratio) return null;
  return state.cropAspectSwapped ? 1.0 / ratio : ratio;
}

function renderCropOverlay() {
  const overlay = document.getElementById("cropOverlay");
  const box = document.getElementById("cropBox");
  const imgEl = document.getElementById("imgDeveloped");
  if (!overlay || !box || !state.cropMode) return;

  if (imgEl && imgEl.offsetWidth > 10 && imgEl.offsetHeight > 10) {
    overlay.style.left = `${imgEl.offsetLeft}px`;
    overlay.style.top = `${imgEl.offsetTop}px`;
    overlay.style.width = `${imgEl.offsetWidth}px`;
    overlay.style.height = `${imgEl.offsetHeight}px`;
    overlay.style.right = "auto";
    overlay.style.bottom = "auto";
  }

  const rect = state.crop_rect || { x: 0, y: 0, w: 1, h: 1 };
  const left = Math.max(0, Math.min(0.96, rect.x));
  const top = Math.max(0, Math.min(0.96, rect.y));
  const width = Math.max(0.04, Math.min(1 - left, rect.w));
  const height = Math.max(0.04, Math.min(1 - top, rect.h));

  box.style.left = `${(left * 100).toFixed(3)}%`;
  box.style.top = `${(top * 100).toFixed(3)}%`;
  box.style.width = `${(width * 100).toFixed(3)}%`;
  box.style.height = `${(height * 100).toFixed(3)}%`;

  const mTop = document.getElementById("cropMaskTop");
  const mBottom = document.getElementById("cropMaskBottom");
  const mLeft = document.getElementById("cropMaskLeft");
  const mRight = document.getElementById("cropMaskRight");
  if (mTop) {
    mTop.style.cssText = `left:0;top:0;width:100%;height:${(top * 100).toFixed(3)}%;`;
  }
  if (mBottom) {
    mBottom.style.cssText = `left:0;top:${((top + height) * 100).toFixed(3)}%;width:100%;height:${((1 - top - height) * 100).toFixed(3)}%;`;
  }
  if (mLeft) {
    mLeft.style.cssText = `left:0;top:${(top * 100).toFixed(3)}%;width:${(left * 100).toFixed(3)}%;height:${(height * 100).toFixed(3)}%;`;
  }
  if (mRight) {
    mRight.style.cssText = `left:${((left + width) * 100).toFixed(3)}%;top:${(top * 100).toFixed(3)}%;width:${((1 - left - width) * 100).toFixed(3)}%;height:${(height * 100).toFixed(3)}%;`;
  }

  const baseW = Number(state.activePreviewWidth || imgEl?.naturalWidth || 0);
  const baseH = Number(state.activePreviewHeight || imgEl?.naturalHeight || 0);
  const dimText = baseW > 0 && baseH > 0
    ? `${Math.max(1, Math.round(baseW * width))} × ${Math.max(1, Math.round(baseH * height))} px`
    : `${Math.round(width * 100)}% × ${Math.round(height * 100)}%`;
  const dimBadge = document.getElementById("cropDimensionsBadge");
  if (dimBadge) dimBadge.textContent = dimText;
  const panelDim = document.getElementById("geomDimensionsReadout");
  if (panelDim) panelDim.textContent = dimText;
}

function setCropMode(enabled) {
  const next = Boolean(enabled);
  if (next && state.viewMode === "split") {
    state.cropPrevViewMode = "split";
    setViewMode("full");
  } else if (!next && state.cropPrevViewMode === "split" && state.viewMode === "full") {
    state.cropPrevViewMode = null;
    setViewMode("split");
  } else if (!next) {
    state.cropPrevViewMode = null;
  }

  state.cropMode = next;
  state.horizonDrawMode = false;
  const btn = document.getElementById("cropToolBtn");
  const inspBtn = document.getElementById("openCropFromInspectorBtn");
  const inspLabel = document.getElementById("openCropFromInspectorLabel");
  const panel = document.getElementById("geometryPanel");
  const overlay = document.getElementById("cropOverlay");
  const hBtn = document.getElementById("horizonDrawBtn");
  const hSvg = document.getElementById("horizonLineSvg");

  btn?.classList.toggle("active", state.cropMode);
  btn?.setAttribute("aria-pressed", state.cropMode ? "true" : "false");
  inspBtn?.classList.toggle("active", state.cropMode);
  if (inspLabel) {
    inspLabel.textContent = state.cropMode ? "Cerrar marco de recorte (Esc)" : "Recortar y nivelar en lienzo (C)";
  }
  if (panel) panel.style.display = state.cropMode ? "block" : "none";
  if (overlay) overlay.style.display = state.cropMode ? "block" : "none";
  if (hBtn) {
    hBtn.classList.remove("active");
    hBtn.setAttribute("aria-pressed", "false");
  }
  if (hSvg) hSvg.style.display = "none";

  if (state.cropMode) {
    if (!state.crop_rect) {
      state.crop_rect = { x: 0.0, y: 0.0, w: 1.0, h: 1.0 };
    }
    syncGeometryUiControls();
    renderCropOverlay();
  }
  state.lastOriginalKey = "";
  requestPreview(true);
}

function initGeometryTool() {
  const overlay = document.getElementById("cropOverlay");
  const box = document.getElementById("cropBox");
  if (!overlay || !box) return;

  let dragMode = null; // 'move' | handle ('nw','n','ne','e','se','s','sw','w') | 'horizon'
  let startMouse = { x: 0, y: 0 };
  let startRect = { x: 0, y: 0, w: 1, h: 1 };
  let horizonStart = null;

  overlay.addEventListener("pointerdown", (e) => {
    if (!state.cropMode) return;
    const ovRect = overlay.getBoundingClientRect();
    if (ovRect.width < 10 || ovRect.height < 10) return;

    if (state.horizonDrawMode) {
      e.preventDefault();
      e.stopPropagation();
      dragMode = "horizon";
      horizonStart = {
        x: e.clientX - ovRect.left,
        y: e.clientY - ovRect.top,
      };
      const svg = document.getElementById("horizonLineSvg");
      const line = document.getElementById("horizonGuideLine");
      const ptA = document.getElementById("horizonPtA");
      const ptB = document.getElementById("horizonPtB");
      if (svg && line && ptA && ptB) {
        svg.style.display = "block";
        line.setAttribute("x1", horizonStart.x);
        line.setAttribute("y1", horizonStart.y);
        line.setAttribute("x2", horizonStart.x);
        line.setAttribute("y2", horizonStart.y);
        ptA.setAttribute("cx", horizonStart.x);
        ptA.setAttribute("cy", horizonStart.y);
        ptB.setAttribute("cx", horizonStart.x);
        ptB.setAttribute("cy", horizonStart.y);
      }
      overlay.setPointerCapture?.(e.pointerId);
      return;
    }

    const handleEl = e.target.closest(".crop-handle");
    if (handleEl) {
      dragMode = handleEl.dataset.handle;
    } else if (e.target.closest("#cropBox")) {
      dragMode = "move";
    } else {
      return;
    }
    e.preventDefault();
    e.stopPropagation();
    pushUndoSnapshotForFrame();
    startMouse = { x: e.clientX, y: e.clientY };
    const cur = state.crop_rect || { x: 0, y: 0, w: 1, h: 1 };
    startRect = { ...cur };
    overlay.setPointerCapture?.(e.pointerId);
  });

  overlay.addEventListener("pointermove", (e) => {
    if (!dragMode || !state.cropMode) return;
    const ovRect = overlay.getBoundingClientRect();
    if (ovRect.width < 10 || ovRect.height < 10) return;

    if (dragMode === "horizon" && horizonStart) {
      const curX = Math.max(0, Math.min(ovRect.width, e.clientX - ovRect.left));
      const curY = Math.max(0, Math.min(ovRect.height, e.clientY - ovRect.top));
      document.getElementById("horizonGuideLine")?.setAttribute("x2", curX);
      document.getElementById("horizonGuideLine")?.setAttribute("y2", curY);
      document.getElementById("horizonPtB")?.setAttribute("cx", curX);
      document.getElementById("horizonPtB")?.setAttribute("cy", curY);
      return;
    }

    const dx = (e.clientX - startMouse.x) / ovRect.width;
    const dy = (e.clientY - startMouse.y) / ovRect.height;
    let { x, y, w, h } = startRect;
    const minSize = 0.05;

    if (dragMode === "move") {
      x = Math.max(0, Math.min(1 - w, x + dx));
      y = Math.max(0, Math.min(1 - h, y + dy));
    } else {
      let left = x;
      let top = y;
      let right = x + w;
      let bottom = y + h;

      if (dragMode.includes("w")) left = Math.max(0, Math.min(right - minSize, left + dx));
      if (dragMode.includes("e")) right = Math.min(1, Math.max(left + minSize, right + dx));
      if (dragMode.includes("n")) top = Math.max(0, Math.min(bottom - minSize, top + dy));
      if (dragMode.includes("s")) bottom = Math.min(1, Math.max(top + minSize, bottom + dy));

      w = right - left;
      h = bottom - top;

      const imgEl = document.getElementById("imgDeveloped");
      const imgW = imgEl?.naturalWidth || ovRect.width;
      const imgH = imgEl?.naturalHeight || ovRect.height;
      const targetRatio = getAspectRatioValue(state.cropAspect, imgW, imgH);
      if (targetRatio && ovRect.height > 0) {
        const pxW = w * ovRect.width;
        const pxH = pxW / targetRatio;
        let normH = pxH / ovRect.height;
        if (top + normH > 1.0) {
          normH = 1.0 - top;
          w = (normH * ovRect.height * targetRatio) / ovRect.width;
        }
        h = Math.max(minSize, normH);
      }
      x = left;
      y = top;
    }
    state.crop_rect = { x, y, w, h };
    renderCropOverlay();
  });

  overlay.addEventListener("keydown", (e) => {
    if (!state.cropMode) return;
    const handleEl = e.target.closest(".crop-handle");
    if (!handleEl) return;
    const handle = handleEl.dataset.handle || "";
    const step = e.shiftKey ? 0.05 : 0.01;
    let dx = 0;
    let dy = 0;
    if (e.key === "ArrowLeft") dx = -step;
    else if (e.key === "ArrowRight") dx = step;
    else if (e.key === "ArrowUp") dy = -step;
    else if (e.key === "ArrowDown") dy = step;
    else return;

    e.preventDefault();
    e.stopPropagation();
    pushUndoSnapshotForFrame();
    const cur = state.crop_rect || { x: 0, y: 0, w: 1, h: 1 };
    const minSize = 0.05;
    let left = cur.x;
    let top = cur.y;
    let right = cur.x + cur.w;
    let bottom = cur.y + cur.h;

    if (handle.includes("w")) left = Math.max(0, Math.min(right - minSize, left + dx));
    if (handle.includes("e")) right = Math.min(1, Math.max(left + minSize, right + dx));
    if (handle.includes("n")) top = Math.max(0, Math.min(bottom - minSize, top + dy));
    if (handle.includes("s")) bottom = Math.min(1, Math.max(top + minSize, bottom + dy));

    state.crop_rect = { x: left, y: top, w: right - left, h: bottom - top };
    renderCropOverlay();
    saveActiveFrameRecipe();
  });

  const finishDrag = (e) => {
    if (!dragMode) return;
    if (dragMode === "horizon" && horizonStart) {
      const ovRect = overlay.getBoundingClientRect();
      const endX = e.clientX - ovRect.left;
      const endY = e.clientY - ovRect.top;
      const dx = endX - horizonStart.x;
      const dy = endY - horizonStart.y;
      if (Math.hypot(dx, dy) >= 12) {
        let angleDeg = (Math.atan2(dy, dx) * 180) / Math.PI;
        if (angleDeg > 45) angleDeg -= 90;
        if (angleDeg < -45) angleDeg += 90;
        if (angleDeg > 45) angleDeg -= 90;
        if (angleDeg < -45) angleDeg += 90;
        pushUndoSnapshotForFrame();
        state.straighten = Math.max(-45, Math.min(45, Number((state.straighten - angleDeg).toFixed(1))));
        syncGeometryUiControls();
        saveActiveFrameRecipe();
        state.lastOriginalKey = "";
        requestPreview(true);
      }
      state.horizonDrawMode = false;
      const hBtn = document.getElementById("horizonDrawBtn");
      hBtn?.classList.remove("active");
      hBtn?.setAttribute("aria-pressed", "false");
      const svg = document.getElementById("horizonLineSvg");
      if (svg) svg.style.display = "none";
      horizonStart = null;
    } else {
      saveActiveFrameRecipe();
    }
    dragMode = null;
  };
  overlay.addEventListener("pointerup", finishDrag);
  overlay.addEventListener("pointercancel", finishDrag);

  document.getElementById("cropAspectSelect")?.addEventListener("change", (e) => {
    state.cropAspect = e.target.value || "free";
    const ovRect = overlay.getBoundingClientRect();
    const imgEl = document.getElementById("imgDeveloped");
    const targetRatio = getAspectRatioValue(
      state.cropAspect,
      imgEl?.naturalWidth || ovRect.width,
      imgEl?.naturalHeight || ovRect.height
    );
    if (targetRatio && ovRect.width > 0 && ovRect.height > 0) {
      const cur = state.crop_rect || { x: 0, y: 0, w: 1, h: 1 };
      let newW = cur.w;
      let newH = (newW * ovRect.width) / (targetRatio * ovRect.height);
      if (newH > 1.0) {
        newH = 1.0;
        newW = (newH * ovRect.height * targetRatio) / ovRect.width;
      }
      const cx = cur.x + cur.w * 0.5;
      const cy = cur.y + cur.h * 0.5;
      state.crop_rect = {
        x: Math.max(0, Math.min(1 - newW, cx - newW * 0.5)),
        y: Math.max(0, Math.min(1 - newH, cy - newH * 0.5)),
        w: newW,
        h: newH,
      };
      renderCropOverlay();
    }
  });

  document.getElementById("cropSwapAspectBtn")?.addEventListener("click", () => {
    state.cropAspectSwapped = !state.cropAspectSwapped;
    document.getElementById("cropAspectSelect")?.dispatchEvent(new Event("change"));
  });

  const bindGeomSlider = (sliderId, valId, key, unit, minVal, maxVal) => {
    const el = document.getElementById(sliderId);
    const valEl = document.getElementById(valId);
    if (!el) return;
    el.addEventListener("input", () => {
      state[key] = Number(el.value) || 0;
      if (valEl) valEl.textContent = `${state[key].toFixed(1)}${unit}`;
      if (key === "straighten") {
        const otherId = sliderId === "straightenSlider" ? "inspStraightenSlider" : "straightenSlider";
        const otherValId = valId === "straightenVal" ? "inspStraightenVal" : "straightenVal";
        const otherEl = document.getElementById(otherId);
        const otherVal = document.getElementById(otherValId);
        if (otherEl) otherEl.value = String(state[key]);
        if (otherVal) otherVal.textContent = `${state[key].toFixed(1)}${unit}`;
        const edited = hasNonDefaultGeometry();
        document.getElementById("cropToolBtn")?.classList.toggle("has-geometry", edited);
        const badge = document.getElementById("geomStatusBadge");
        if (badge) badge.textContent = edited ? "Editado" : "Original";
      }
      triggerDebouncedPreview(key);
    });
    el.addEventListener("dblclick", () => {
      pushUndoSnapshotForFrame();
      state[key] = Math.max(minVal, Math.min(maxVal, 0));
      syncGeometryUiControls();
      saveActiveFrameRecipe();
      state.lastOriginalKey = "";
      requestPreview(true);
    });
  };
  bindGeomSlider("straightenSlider", "straightenVal", "straighten", "°", -45, 45);
  bindGeomSlider("inspStraightenSlider", "inspStraightenVal", "straighten", "°", -45, 45);
  bindGeomSlider("keystoneVSlider", "keystoneVVal", "keystone_v", "°", -30, 30);
  bindGeomSlider("keystoneHSlider", "keystoneHVal", "keystone_h", "°", -30, 30);

  document.getElementById("cropGuideSelect")?.addEventListener("change", (e) => {
    const grid = document.getElementById("cropGrid");
    if (grid) grid.dataset.guide = e.target.value || "thirds";
  });

  document.getElementById("openCropFromInspectorBtn")?.addEventListener("click", () => {
    setCropMode(!state.cropMode);
  });
  document.getElementById("inspRotLeftBtn")?.addEventListener("click", () => rotateCurrentFrame(-90));
  document.getElementById("inspRotRightBtn")?.addEventListener("click", () => rotateCurrentFrame(90));
  document.getElementById("inspFlipHBtn")?.addEventListener("click", toggleHorizontalFlip);
  document.getElementById("inspFlipVBtn")?.addEventListener("click", toggleVerticalFlip);
  document.getElementById("inspGeomResetBtn")?.addEventListener("click", () => {
    document.getElementById("cropResetBtn")?.click();
  });

  document.getElementById("autoCropStraightenCheck")?.addEventListener("change", (e) => {
    state.auto_crop_straighten = Boolean(e.target.checked);
    saveActiveFrameRecipe();
    state.lastOriginalKey = "";
    requestPreview(true);
  });

  document.getElementById("horizonDrawBtn")?.addEventListener("click", () => {
    state.horizonDrawMode = !state.horizonDrawMode;
    const hBtn = document.getElementById("horizonDrawBtn");
    hBtn?.classList.toggle("active", state.horizonDrawMode);
    hBtn?.setAttribute("aria-pressed", state.horizonDrawMode ? "true" : "false");
  });

  document.getElementById("geomRotLeftBtn")?.addEventListener("click", () => rotateCurrentFrame(-90));
  document.getElementById("geomRotRightBtn")?.addEventListener("click", () => rotateCurrentFrame(90));
  document.getElementById("geomFlipHBtn")?.addEventListener("click", toggleHorizontalFlip);
  document.getElementById("geomFlipVBtn")?.addEventListener("click", toggleVerticalFlip);

  document.getElementById("cropResetBtn")?.addEventListener("click", () => {
    pushUndoSnapshotForFrame();
    state.straighten = 0.0;
    state.keystone_v = 0.0;
    state.keystone_h = 0.0;
    state.crop_rect = state.cropMode ? { x: 0, y: 0, w: 1, h: 1 } : null;
    state.flip_v = false;
    state.flip_h = false;
    state.rotate = 0;
    syncGeometryUiControls();
    document.getElementById("flipHBtn")?.classList.remove("active");
    document.getElementById("flipHBtn")?.setAttribute("aria-pressed", "false");
    renderCropOverlay();
    saveActiveFrameRecipe();
    state.lastOriginalKey = "";
    requestPreview(true);
  });

  document.getElementById("cropApplyBtn")?.addEventListener("click", () => {
    if (
      state.crop_rect &&
      state.crop_rect.x <= 0.002 &&
      state.crop_rect.y <= 0.002 &&
      state.crop_rect.w >= 0.996 &&
      state.crop_rect.h >= 0.996
    ) {
      state.crop_rect = null;
    }
    saveActiveFrameRecipe();
    setCropMode(false);
  });
  document.getElementById("cropCloseBtn")?.addEventListener("click", () => {
    setCropMode(false);
  });
  document.getElementById("imgDeveloped")?.addEventListener("load", () => {
    if (state.cropMode) renderCropOverlay();
    if (state.maskEditMode) renderLocalMaskOverlay();
  });
  window.addEventListener("resize", () => {
    if (state.cropMode) renderCropOverlay();
    if (state.maskEditMode) renderLocalMaskOverlay();
  });
}

function updateSharedOpticsBadge() {
  const badge = document.getElementById("sharedOpticsBadge");
  if (!badge) return;
  const parts = [];
  const dustCount = Array.isArray(negativeState.dustSpots) ? negativeState.dustSpots.length : 0;
  if (dustCount > 0) parts.push(`${dustCount} motas`);
  if ((state.denoiseLuma || 0) > 0 || (state.denoiseChroma || 0) > 0) parts.push("Ruido");
  if ((state.defringe || 0) > 0) parts.push("Defringe");
  if (negativeState.sharpenMode && negativeState.sharpenMode !== "off") parts.push("Nitidez");
  const maskCount = Array.isArray(state.localMasks) ? state.localMasks.length : 0;
  if (maskCount > 0) parts.push(`${maskCount} ${maskCount === 1 ? "reserva" : "reservas"}`);
  badge.textContent = parts.length > 0 ? parts.join(" · ") : "Neutro";
}

function syncSharedOpticsUI() {
  const dl = Math.round(Number(state.denoiseLuma || 0) * 100);
  const dc = Math.round(Number(state.denoiseChroma || 0) * 100);
  const df = Math.round(Number(state.defringe || 0) * 100);
  setSliderSilent("denoiseLumaSlider", "denoiseLumaVal", dl, `${dl}%`);
  setSliderSilent("denoiseChromaSlider", "denoiseChromaVal", dc, `${dc}%`);
  setSliderSilent("defringeSlider", "defringeVal", df, `${df}%`);

  const mode = negativeState.sharpenMode || "off";
  document.querySelectorAll("#sharedSharpenModeBar .seg-btn, #negSharpenModeBar .seg-btn").forEach((b) => {
    b.classList.toggle("active", b.dataset.sharpen === mode);
  });
  const sAmt = Math.round(Number(negativeState.sharpenAmount ?? 1.0) * 100);
  setSliderSilent("sharedSharpenAmountSlider", "sharedSharpenAmountVal", sAmt, `${sAmt}%`);
  setSliderSilent("negSharpenAmountSlider", "negSharpenAmountVal", sAmt, `${sAmt}%`);
  const sGrp = document.getElementById("sharedSharpenAmountGroup");
  const nGrp = document.getElementById("negSharpenAmountGroup");
  if (sGrp) sGrp.style.display = mode !== "off" ? "block" : "none";
  if (nGrp) nGrp.style.display = mode !== "off" ? "flex" : "none";

  updateDustSpotsUI();
  renderLocalMasksUI();
  updateSharedOpticsBadge();
}

function renderLocalMasksUI() {
  const masks = Array.isArray(state.localMasks) ? state.localMasks : [];
  const countBadge = document.getElementById("localMasksCountBadge");
  const listEl = document.getElementById("localMasksList");
  const editorEl = document.getElementById("activeMaskEditor");
  const toggleBtn = document.getElementById("toggleMaskEditBtn");

  if (countBadge) countBadge.textContent = String(masks.length);
  if (toggleBtn) {
    toggleBtn.disabled = masks.length === 0;
    if (masks.length === 0 && state.maskEditMode) {
      setLocalMaskEditMode(false);
    }
  }

  if (listEl) {
    listEl.innerHTML = "";
    masks.forEach((m, idx) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `mask-chip${idx === state.activeMaskIndex ? " active" : ""}`;
      const evNum = Number(m.ev || 0);
      const evStr = `${evNum >= 0 ? "+" : ""}${evNum.toFixed(1)}EV`;
      btn.textContent = `${m.type === "radial" ? "Radial" : "Grad"} ${idx + 1} (${evStr})`;
      btn.addEventListener("click", () => {
        state.activeMaskIndex = idx;
        renderLocalMasksUI();
        renderLocalMaskOverlay();
      });
      listEl.appendChild(btn);
    });
  }

  const active = masks[state.activeMaskIndex];
  if (editorEl) {
    if (!active) {
      editorEl.style.display = "none";
    } else {
      editorEl.style.display = "flex";
      const evVal = Number(active.ev || 0);
      setSliderSilent("maskEvSlider", "maskEvVal", evVal, `${evVal >= 0 ? "+" : ""}${evVal.toFixed(1)} EV`);
      const featherPct = Math.round(Number(active.feather ?? 0.4) * 100);
      setSliderSilent("maskFeatherSlider", "maskFeatherVal", featherPct, `${featherPct}%`);
      const invChk = document.getElementById("maskInvertCheck");
      if (invChk) invChk.checked = Boolean(active.invert);
    }
  }
  updateSharedOpticsBadge();
}

function setLocalMaskEditMode(enabled) {
  const masks = Array.isArray(state.localMasks) ? state.localMasks : [];
  const next = Boolean(enabled) && masks.length > 0;
  if (next && state.cropMode) setCropMode(false);
  if (next && state.viewMode === "split") {
    state.maskPrevViewMode = "split";
    setViewMode("full");
  } else if (!next && state.maskPrevViewMode === "split" && state.viewMode === "full") {
    state.maskPrevViewMode = null;
    setViewMode("split");
  } else if (!next) {
    state.maskPrevViewMode = null;
  }
  state.maskEditMode = next;
  const btn = document.getElementById("toggleMaskEditBtn");
  const svg = document.getElementById("localMaskOverlay");
  btn?.classList.toggle("active", next);
  btn?.setAttribute("aria-pressed", next ? "true" : "false");
  if (btn) btn.textContent = next ? "Listo" : "Editar en lienzo";
  if (svg) svg.style.display = next ? "block" : "none";
  if (next) {
    if (state.activeMaskIndex < 0 || state.activeMaskIndex >= masks.length) {
      state.activeMaskIndex = 0;
    }
    renderLocalMaskOverlay();
  }
}

function renderLocalMaskOverlay() {
  const svg = document.getElementById("localMaskOverlay");
  const imgEl = document.getElementById("imgDeveloped");
  const masks = Array.isArray(state.localMasks) ? state.localMasks : [];
  const active = masks[state.activeMaskIndex];
  if (!svg || !state.maskEditMode || !active) return;

  if (imgEl && imgEl.offsetWidth > 10 && imgEl.offsetHeight > 10) {
    svg.style.left = `${imgEl.offsetLeft}px`;
    svg.style.top = `${imgEl.offsetTop}px`;
    svg.style.width = `${imgEl.offsetWidth}px`;
    svg.style.height = `${imgEl.offsetHeight}px`;
  }
  const w = svg.clientWidth || imgEl?.offsetWidth || 100;
  const h = svg.clientHeight || imgEl?.offsetHeight || 100;
  const x1 = active.x1 * w;
  const y1 = active.y1 * h;
  const x2 = active.x2 * w;
  const y2 = active.y2 * h;

  svg.innerHTML = "";
  const ns = "http://www.w3.org/2000/svg";
  const feather = Math.max(0.05, Math.min(1.0, Number(active.feather ?? 0.4)));

  const addGuideLine = (cls, ax, ay, bx, by) => {
    const line = document.createElementNS(ns, "line");
    line.setAttribute("class", cls);
    line.setAttribute("x1", String(ax));
    line.setAttribute("y1", String(ay));
    line.setAttribute("x2", String(bx));
    line.setAttribute("y2", String(by));
    svg.appendChild(line);
  };

  const addHandle = (ptId, cx, cy, cursor = "grab", isCenter = false) => {
    const g = document.createElementNS(ns, "g");
    g.setAttribute("class", "mask-handle-group");
    g.setAttribute("data-pt", ptId);
    g.style.cursor = cursor;

    const hit = document.createElementNS(ns, "circle");
    hit.setAttribute("class", "mask-handle-hit");
    hit.setAttribute("cx", String(cx));
    hit.setAttribute("cy", String(cy));
    hit.setAttribute("r", "14");
    g.appendChild(hit);

    const c = document.createElementNS(ns, "circle");
    c.setAttribute("class", isCenter ? "mask-handle mask-handle-center" : "mask-handle");
    c.setAttribute("cx", String(cx));
    c.setAttribute("cy", String(cy));
    c.setAttribute("r", isCenter ? "6" : "5.5");
    g.appendChild(c);

    svg.appendChild(g);
  };

  if (active.type === "radial") {
    const rx = Math.max(12, Math.abs(x2 - x1));
    const ry = Math.max(12, Math.abs(y2 - y1));

    const el = document.createElementNS(ns, "ellipse");
    el.setAttribute("class", "mask-guide-ellipse");
    el.setAttribute("cx", String(x1));
    el.setAttribute("cy", String(y1));
    el.setAttribute("rx", String(rx));
    el.setAttribute("ry", String(ry));
    svg.appendChild(el);

    const innerScale = Math.max(0.02, 1.0 - feather);
    const innerEl = document.createElementNS(ns, "ellipse");
    innerEl.setAttribute("class", "mask-guide-inner");
    innerEl.setAttribute("cx", String(x1));
    innerEl.setAttribute("cy", String(y1));
    innerEl.setAttribute("rx", String(Math.max(4, rx * innerScale)));
    innerEl.setAttribute("ry", String(Math.max(4, ry * innerScale)));
    svg.appendChild(innerEl);

    addHandle("center", x1, y1, "move", true);
    addHandle("rx_pos", x1 + rx, y1, "ew-resize");
    addHandle("rx_neg", x1 - rx, y1, "ew-resize");
    addHandle("ry_pos", x1, y1 + ry, "ns-resize");
    addHandle("ry_neg", x1, y1 - ry, "ns-resize");
  } else {
    const dx = x2 - x1;
    const dy = y2 - y1;
    const len = Math.hypot(dx, dy);
    const mx = (x1 + x2) * 0.5;
    const my = (y1 + y2) * 0.5;

    if (len > 4) {
      const nx = -dy / len;
      const ny = dx / len;
      const bandLen = Math.max(w, h) * 0.45;
      const halfSpan = Math.max(0.02, 0.5 * feather);
      for (const frac of [0.5 - halfSpan, 0.5 + halfSpan]) {
        const bx = x1 + dx * frac;
        const by = y1 + dy * frac;
        addGuideLine("mask-guide-band", bx - nx * bandLen, by - ny * bandLen, bx + nx * bandLen, by + ny * bandLen);
      }
    }
    addGuideLine("mask-guide-line", x1, y1, x2, y2);
    addHandle("p1", x1, y1, "grab");
    addHandle("p2", x2, y2, "grab");
    addHandle("center", mx, my, "move", true);
  }
}

function initSharedDarkroomTools() {
  document.getElementById("sharedDustHealBtn")?.addEventListener("click", () => {
    setEyedropperMode(negativeState.eyedropperMode === "dust" ? null : "dust");
  });
  document.getElementById("sharedDustUndoBtn")?.addEventListener("click", undoLastDustSpot);
  document.getElementById("sharedDustClearBtn")?.addEventListener("click", clearAllDustSpots);

  const bindPctSlider = (sliderId, valId, stateKey) => {
    const el = document.getElementById(sliderId);
    const valEl = document.getElementById(valId);
    if (!el) return;
    el.addEventListener("input", () => {
      const pct = Math.max(0, Math.min(100, Number(el.value) || 0));
      state[stateKey] = pct / 100.0;
      if (valEl) valEl.textContent = `${pct}%`;
      updateSharedOpticsBadge();
      triggerDebouncedPreview(stateKey);
    });
    el.addEventListener("dblclick", () => {
      pushUndoSnapshotForFrame();
      state[stateKey] = 0.0;
      syncSharedOpticsUI();
      saveActiveFrameRecipe();
      requestPreview(false);
    });
  };
  bindPctSlider("denoiseLumaSlider", "denoiseLumaVal", "denoiseLuma");
  bindPctSlider("denoiseChromaSlider", "denoiseChromaVal", "denoiseChroma");
  bindPctSlider("defringeSlider", "defringeVal", "defringe");

  document.querySelectorAll("#sharedSharpenModeBar .seg-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      pushUndoSnapshotForFrame();
      negativeState.sharpenMode = btn.dataset.sharpen || "off";
      syncSharedOpticsUI();
      saveActiveFrameRecipe();
      requestPreview(false);
    });
  });

  document.getElementById("sharedSharpenAmountSlider")?.addEventListener("input", (e) => {
    const pct = Math.max(0, Math.min(200, Number(e.target.value) || 100));
    negativeState.sharpenAmount = pct / 100.0;
    syncSharedOpticsUI();
    triggerDebouncedPreview("sharpen_amount");
  });

  const addMask = (type) => {
    if (!Array.isArray(state.localMasks)) state.localMasks = [];
    if (state.localMasks.length >= 8) {
      showToast("Límite de máscaras", "Máximo 8 reservas Dodge & Burn por fotograma.");
      return;
    }
    pushUndoSnapshotForFrame();
    const mask = type === "radial"
      ? { type: "radial", x1: 0.5, y1: 0.5, x2: 0.78, y2: 0.78, ev: 0.5, feather: 0.5, invert: false }
      : { type: "linear", x1: 0.5, y1: 0.12, x2: 0.5, y2: 0.62, ev: -0.6, feather: 0.45, invert: false };
    state.localMasks.push(mask);
    state.activeMaskIndex = state.localMasks.length - 1;
    renderLocalMasksUI();
    setLocalMaskEditMode(true);
    saveActiveFrameRecipe();
    requestPreview(false);
  };

  document.getElementById("addLinearMaskBtn")?.addEventListener("click", () => addMask("linear"));
  document.getElementById("addRadialMaskBtn")?.addEventListener("click", () => addMask("radial"));
  document.getElementById("toggleMaskEditBtn")?.addEventListener("click", () => {
    setLocalMaskEditMode(!state.maskEditMode);
  });

  document.getElementById("maskEvSlider")?.addEventListener("input", (e) => {
    const active = state.localMasks?.[state.activeMaskIndex];
    if (!active) return;
    active.ev = Number(e.target.value) || 0;
    renderLocalMasksUI();
    triggerDebouncedPreview("local_masks");
  });
  document.getElementById("maskFeatherSlider")?.addEventListener("input", (e) => {
    const active = state.localMasks?.[state.activeMaskIndex];
    if (!active) return;
    active.feather = Math.max(0.05, Math.min(1.0, (Number(e.target.value) || 40) / 100.0));
    renderLocalMasksUI();
    renderLocalMaskOverlay();
    triggerDebouncedPreview("local_masks");
  });
  document.getElementById("maskInvertCheck")?.addEventListener("change", (e) => {
    const active = state.localMasks?.[state.activeMaskIndex];
    if (!active) return;
    active.invert = Boolean(e.target.checked);
    saveActiveFrameRecipe();
    requestPreview(false);
  });
  document.getElementById("deleteActiveMaskBtn")?.addEventListener("click", () => {
    if (!Array.isArray(state.localMasks) || state.activeMaskIndex < 0) return;
    pushUndoSnapshotForFrame();
    state.localMasks.splice(state.activeMaskIndex, 1);
    state.activeMaskIndex = state.localMasks.length > 0 ? Math.min(state.activeMaskIndex, state.localMasks.length - 1) : -1;
    renderLocalMasksUI();
    renderLocalMaskOverlay();
    saveActiveFrameRecipe();
    requestPreview(false);
  });
  document.getElementById("resetSharedOpticsBtn")?.addEventListener("click", () => {
    pushUndoSnapshotForFrame();
    state.denoiseLuma = 0;
    state.denoiseChroma = 0;
    state.defringe = 0;
    state.localMasks = [];
    state.activeMaskIndex = -1;
    negativeState.sharpenMode = "off";
    negativeState.sharpenAmount = 1.0;
    negativeState.dustSpots = [];
    setLocalMaskEditMode(false);
    syncSharedOpticsUI();
    saveActiveFrameRecipe();
    requestPreview(false);
  });

  const svg = document.getElementById("localMaskOverlay");
  if (svg) {
    let dragState = null;
    svg.addEventListener("pointerdown", (e) => {
      const hEl = e.target.closest(".mask-handle-group, .mask-handle");
      if (!hEl || !state.maskEditMode) return;
      const active = state.localMasks?.[state.activeMaskIndex];
      if (!active) return;
      const rect = svg.getBoundingClientRect();
      if (rect.width < 10 || rect.height < 10) return;
      e.preventDefault();
      e.stopPropagation();
      dragState = {
        pt: hEl.dataset.pt,
        startNx: (e.clientX - rect.left) / rect.width,
        startNy: (e.clientY - rect.top) / rect.height,
        x1: active.x1,
        y1: active.y1,
        x2: active.x2,
        y2: active.y2,
      };
      pushUndoSnapshotForFrame();
      svg.setPointerCapture?.(e.pointerId);
    });
    svg.addEventListener("pointermove", (e) => {
      if (!dragState || !state.maskEditMode) return;
      const active = state.localMasks?.[state.activeMaskIndex];
      if (!active) return;
      const rect = svg.getBoundingClientRect();
      if (rect.width < 10 || rect.height < 10) return;
      const nx = Math.max(-0.2, Math.min(1.2, (e.clientX - rect.left) / rect.width));
      const ny = Math.max(-0.2, Math.min(1.2, (e.clientY - rect.top) / rect.height));
      const dnx = nx - dragState.startNx;
      const dny = ny - dragState.startNy;

      if (dragState.pt === "center") {
        active.x1 = Number((dragState.x1 + dnx).toFixed(4));
        active.y1 = Number((dragState.y1 + dny).toFixed(4));
        active.x2 = Number((dragState.x2 + dnx).toFixed(4));
        active.y2 = Number((dragState.y2 + dny).toFixed(4));
      } else if (dragState.pt === "rx_pos" || dragState.pt === "rx_neg") {
        const rx = Math.max(0.03, Math.min(1.2, Math.abs(nx - active.x1)));
        active.x2 = Number((active.x1 + rx).toFixed(4));
        if (e.shiftKey) {
          const aspect = rect.width / Math.max(1, rect.height);
          active.y2 = Number((active.y1 + rx * aspect).toFixed(4));
        }
      } else if (dragState.pt === "ry_pos" || dragState.pt === "ry_neg") {
        const ry = Math.max(0.03, Math.min(1.2, Math.abs(ny - active.y1)));
        active.y2 = Number((active.y1 + ry).toFixed(4));
        if (e.shiftKey) {
          const aspect = rect.height / Math.max(1, rect.width);
          active.x2 = Number((active.x1 + ry * aspect).toFixed(4));
        }
      } else if (dragState.pt === "p1") {
        active.x1 = Number(nx.toFixed(4));
        active.y1 = Number(ny.toFixed(4));
      } else {
        active.x2 = Number(nx.toFixed(4));
        active.y2 = Number(ny.toFixed(4));
      }
      renderLocalMaskOverlay();
      triggerDebouncedPreview("local_masks");
    });
    const endDrag = () => {
      if (!dragState) return;
      dragState = null;
      saveActiveFrameRecipe();
      requestPreview(false);
    };
    svg.addEventListener("pointerup", endDrag);
    svg.addEventListener("pointercancel", endDrag);
    window.addEventListener("resize", () => {
      if (state.maskEditMode) renderLocalMaskOverlay();
    });
  }
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
    const types = Array.from(e.dataTransfer?.types || []);
    dragDepth = 0;
    overlay.classList.remove("active");
    if (!types.includes("Files")) return;
    e.preventDefault();
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

function enhanceControlPrecision() {
  const cmySliderIds = new Set([
    "cmyRedSlider",
    "cmyGreenSlider",
    "cmyBlueSlider",
    "zoneCmyRedSlider",
    "zoneCmyGreenSlider",
    "zoneCmyBlueSlider",
  ]);

  document.querySelectorAll(".control-group").forEach((group) => {
    const labelRow = group.querySelector(".control-label");
    const slider = group.querySelector('input[type="range"]');
    const valEl = labelRow?.querySelector(".control-val");
    if (!slider || !valEl) return;

    const isCmy = cmySliderIds.has(slider.id);
    if (isCmy) {
      slider.step = "0.01";
    }

    const minVal = parseFloat(slider.min);
    const maxVal = parseFloat(slider.max);
    const defVal = parseFloat(slider.dataset.default ?? "0");

    // Magnetic center-zero detent on pointer drags only (keyboard arrows remain unblocked)
    if (minVal < 0 && maxVal > 0 && Math.abs(defVal) < 1e-6) {
      let pointerDragging = false;
      slider.addEventListener("pointerdown", () => {
        pointerDragging = true;
      });
      window.addEventListener("pointerup", () => {
        pointerDragging = false;
      });
      slider.addEventListener(
        "input",
        () => {
          if (!pointerDragging || suppressAutoSliderUndo) return;
          const v = parseFloat(slider.value);
          if (v !== 0 && Math.abs(v) <= 0.025) {
            slider.value = "0";
          }
        },
        true
      );
    }

    // Inline numeric edit when clicking or pressing Enter/Space on the numeric readout
    valEl.title = valEl.title || "Clic o Enter para escribir un valor exacto";
    valEl.setAttribute("role", "button");
    valEl.setAttribute("tabindex", "0");
    valEl.setAttribute(
      "aria-label",
      `Editar valor numérico para ${labelRow.firstElementChild?.textContent || slider.id}`
    );
    const openInlineEdit = () => {
      if (labelRow.querySelector(".val-inline-edit")) return;
      const beforeSnap = captureModeRecipeSnapshot();
      const input = document.createElement("input");
      input.type = "text";
      input.inputMode = "decimal";
      input.className = "val-inline-edit";
      input.value = String(parseFloat(slider.value));
      input.setAttribute("aria-label", `Valor numérico para ${labelRow.firstElementChild?.textContent || slider.id}`);

      valEl.style.display = "none";
      valEl.parentNode.insertBefore(input, valEl.nextSibling);
      input.focus();
      input.select();

      let closed = false;
      const commitOrCancel = (commit) => {
        if (closed) return;
        closed = true;
        const cleanRaw = input.value.trim().replace(",", ".").replace(/[^\d.+-]/g, "");
        input.remove();
        valEl.style.display = "";
        if (!commit || !cleanRaw) return;
        const parsed = parseFloat(cleanRaw);
        if (Number.isNaN(parsed)) return;
        const clamped = Math.max(minVal, Math.min(maxVal, parsed));
        pushUndoSnapshotForFrame(state.frames[state.activeFrameIndex], state.appMode, beforeSnap);
        suppressAutoSliderUndo = true;
        try {
          slider.value = String(clamped);
          slider.dispatchEvent(new Event("input", { bubbles: true }));
        } finally {
          suppressAutoSliderUndo = false;
        }
      };

      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          commitOrCancel(true);
        } else if (e.key === "Escape") {
          e.preventDefault();
          commitOrCancel(false);
        }
      });
      input.addEventListener("blur", () => commitOrCancel(true));
    };
    valEl.addEventListener("click", openInlineEdit);
    valEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        openInlineEdit();
      }
    });

    // Inject fine - / + 0.02 nudge buttons on the 6 CMY sliders
    if (isCmy && !labelRow.querySelector(".control-val-tools")) {
      const tools = document.createElement("span");
      tools.className = "control-val-tools";
      valEl.parentNode.insertBefore(tools, valEl);
      tools.appendChild(valEl);

      const nudgeGroup = document.createElement("span");
      nudgeGroup.className = "step-nudge-group";

      const makeNudgeBtn = (delta, symbol, title) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "step-nudge-btn";
        btn.textContent = symbol;
        btn.title = title;
        btn.setAttribute("aria-label", title);
        btn.addEventListener("click", (e) => {
          e.stopPropagation();
          const cur = parseFloat(slider.value) || 0;
          const next = Math.max(minVal, Math.min(maxVal, Math.round((cur + delta) * 100) / 100));
          if (Math.abs(next - cur) < 1e-6) return;
          pushUndoSnapshotForFrame();
          suppressAutoSliderUndo = true;
          try {
            slider.value = String(next);
            slider.dispatchEvent(new Event("input", { bubbles: true }));
          } finally {
            suppressAutoSliderUndo = false;
          }
        });
        return btn;
      };

      nudgeGroup.appendChild(makeNudgeBtn(-0.02, "−", "Ajuste fino −0.02"));
      nudgeGroup.appendChild(makeNudgeBtn(0.02, "+", "Ajuste fino +0.02"));
      tools.appendChild(nudgeGroup);
    }
  });
}

function resetSlidersWithUndo(ids, postHook = null) {
  const beforeSnap = captureModeRecipeSnapshot();
  suppressAutoSliderUndo = true;
  try {
    ids.forEach(([id, val]) => {
      const el = document.getElementById(id);
      if (el) {
        el.value = val;
        el.dispatchEvent(new Event("input", { bubbles: true }));
      }
    });
    if (postHook) postHook();
  } finally {
    suppressAutoSliderUndo = false;
  }
  const afterSnap = captureModeRecipeSnapshot();
  if (JSON.stringify(beforeSnap) !== JSON.stringify(afterSnap)) {
    pushUndoSnapshotForFrame(state.frames[state.activeFrameIndex], state.appMode, beforeSnap);
  }
}

function resetSimulationControls() {
  resetSlidersWithUndo(
    [
      ["evSlider", "0.0"],
      ["halationSlider", "1.0"],
      ["grainSlider", "1.0"],
      ["vignetteSlider", "1.0"],
      ["shadowsSlider", "0.0"],
      ["midsSlider", "0.0"],
      ["highlightsSlider", "0.0"],
    ],
    () => {
      const devProcSel = document.getElementById("simDevProcessSelect");
      if (devProcSel && devProcSel.value !== "standard") {
        devProcSel.value = "standard";
        devProcSel.dispatchEvent(new Event("change", { bubbles: true }));
      }
      const grainAsaSel = document.getElementById("grainAsaSelect");
      if (grainAsaSel && grainAsaSel.value !== "auto") {
        grainAsaSel.value = "auto";
        grainAsaSel.dispatchEvent(new Event("change", { bubbles: true }));
      }
      const dateToggle = document.getElementById("dateToggle");
      if (dateToggle && dateToggle.checked) {
        dateToggle.checked = false;
        dateToggle.dispatchEvent(new Event("change", { bubbles: true }));
      }
    }
  );
}

function resetNegativeTonalControls() {
  resetSlidersWithUndo(
    [
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
    ],
    () => {
      const cpToggle = document.getElementById("negClipProtectToggle");
      if (cpToggle && !cpToggle.checked) {
        cpToggle.checked = true;
        cpToggle.dispatchEvent(new Event("change", { bubbles: true }));
      }
    }
  );
}

function resetNegativeOpticalControls() {
  resetSlidersWithUndo(
    [
      ["negSharpenAmountSlider", "100"],
      ["negWarming85Slider", "0.0"],
      ["negSkylightSlider", "0.0"],
      ["negShadeSlider", "0.0"],
      ["negGlowSlider", "1.0"],
      ["negFadeSlider", "1.0"],
    ],
    () => {
      negativeState.sharpenMode = "off";
      document.querySelectorAll("#negSharpenModeBar .seg-btn").forEach((b) => {
        const active = b.dataset.sharpen === "off";
        b.classList.toggle("active", active);
        b.setAttribute("aria-pressed", active ? "true" : "false");
      });
      syncNegProcessPanels();
    }
  );
}

function resetNegativeColorControls() {
  resetSlidersWithUndo(
    [
      ["cmyRedSlider", "0.0"],
      ["cmyGreenSlider", "0.0"],
      ["cmyBlueSlider", "0.0"],
      ["negTempSlider", "0.0"],
      ["negTintSlider", "0.0"],
      ["negShadowsRangeSlider", "50"],
      ["negHighsRangeSlider", "50"],
    ],
    () => {
      negativeState.shadowsTint = [0.0, 0.0, 0.0];
      negativeState.midsTint = [0.0, 0.0, 0.0];
      negativeState.highsTint = [0.0, 0.0, 0.0];
      selectCmyZone(negativeState.activeCmyZone);
    }
  );
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

    const activeModal = document.querySelector(".modal-backdrop.active");

    // Modal focus trap on Tab
    if (e.key === "Tab" && activeModal) {
      const focusables = Array.from(
        activeModal.querySelectorAll(
          "button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])"
        )
      ).filter((el) => el.offsetParent !== null);
      if (focusables.length > 0) {
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && (document.activeElement === last || !activeModal.contains(document.activeElement))) {
          e.preventDefault();
          first.focus();
        }
      }
      return;
    }

    // Escape closes export menu, active eyedropper, or dismissible open modals
    if (e.key === "Escape") {
      const exportMenu = document.getElementById("exportMenu");
      if (exportMenu?.classList.contains("open")) {
        exportMenu.classList.remove("open");
        document.getElementById("exportMoreBtn")?.setAttribute("aria-expanded", "false");
        return;
      }
      if (negativeState.eyedropperActive) {
        setEyedropperMode(null);
        return;
      }
      if (state.viewMode === "teststrip") {
        setViewMode(state.prevViewMode === "split" ? "split" : "full");
        return;
      }
      document
        .querySelectorAll(".modal-backdrop.active:not(#batchProgressModal)")
        .forEach((m) => setModalOpen(m, false));
      return;
    }

    // Cmd/Ctrl + S / Shift+Cmd+S / Cmd+O / Cmd+Z / Shift+Cmd+Z / Shift+Cmd+C / Shift+Cmd+V
    if (e.metaKey || e.ctrlKey) {
      const k = e.key.toLowerCase();
      if (k === "z" && !inTextInput) {
        e.preventDefault();
        if (e.shiftKey) performRedo();
        else performUndo();
        return;
      }
      if (k === "y" && !e.shiftKey && !inTextInput) {
        e.preventDefault();
        performRedo();
        return;
      }
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

    if (inTextInput || activeModal) return;

    // NOTE: Tab is deliberately NOT hijacked here. Capturing it made every
    // slider, the 80-stock catalogue and the toolbar buttons unreachable by
    // keyboard (WCAG 2.1.1 / 2.4.3). The Zen sidebar toggle now lives on its
    // own button (zenToggleBtn) and on Cmd/Ctrl+Alt+Z.

    // Zen / clean-table mode (Cmd/Ctrl + Alt + Z)
    if ((e.metaKey || e.ctrlKey) && e.altKey && (e.key === "z" || e.key === "Z")) {
      e.preventDefault();
      toggleZenSidebars();
      return;
    }

    // Space holds temporary pan override (especially over active eyedropper)
    if (
      (e.code === "Space" || e.key === " ") &&
      (negativeState.eyedropperActive || !e.target?.closest("button, a, select, input, summary"))
    ) {
      e.preventDefault();
      if (!state.spacePressed) {
        state.spacePressed = true;
        const wrapper = document.getElementById("splitWrapper");
        wrapper?.classList.toggle("space-pan-ready", negativeState.eyedropperActive || state.zoom > 1.01);
        const loupe = document.getElementById("eyedropperLoupe");
        if (loupe && negativeState.eyedropperActive) loupe.style.display = "none";
      }
      return;
    }

    if (
      (e.key === "ArrowLeft" || e.key === "ArrowRight") &&
      !e.metaKey &&
      !e.ctrlKey &&
      !e.altKey &&
      state.frames.length > 1
    ) {
      if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA" || e.target?.id === "splitDivider") {
        return;
      }
      e.preventDefault();
      const delta = e.key === "ArrowRight" ? 1 : -1;
      const nextIdx = Math.max(0, Math.min(state.frames.length - 1, state.activeFrameIndex + delta));
      if (nextIdx !== state.activeFrameIndex) {
        activateFrameByIndex(nextIdx, state.viewMode === "sheet" ? "full" : state.viewMode);
      }
      return;
    }

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
    else if ((e.key === "t" || e.key === "T") && state.frames.length > 0) {
      setViewMode(state.viewMode === "teststrip" ? (state.prevViewMode === "split" ? "split" : "full") : "teststrip");
    }
    else if (e.key === "0") resetZoom();
    else if (e.key === "+" || e.key === "=") {
      setZoom((state.viewMode === "sheet" ? state.sheetZoom : state.zoom) + 0.25);
    } else if (e.key === "-") {
      setZoom((state.viewMode === "sheet" ? state.sheetZoom : state.zoom) - 0.25);
    } else if (e.key === "j" || e.key === "J") {
      toggleZebraChannel("both");
    } else if ((e.key === "p" || e.key === "P") && state.frames.length > 0) {
      const cur = state.frames[state.activeFrameIndex]?.pickStatus;
      setFramePickStatus(state.activeFrameIndex, cur === "pick" ? null : "pick");
    } else if ((e.key === "x" || e.key === "X") && state.frames.length > 0) {
      const cur = state.frames[state.activeFrameIndex]?.pickStatus;
      setFramePickStatus(state.activeFrameIndex, cur === "reject" ? null : "reject");
    } else if ((e.key === "u" || e.key === "U") && state.frames.length > 0) {
      setFramePickStatus(state.activeFrameIndex, null);
    } else if (e.key === "r" || e.key === "R") {
      rotateCurrentFrame(e.shiftKey ? -90 : 90);
    } else if (e.key === "f" || e.key === "F") {
      if (e.shiftKey) toggleVerticalFlip();
      else toggleHorizontalFlip();
    } else if ((e.key === "c" || e.key === "C") && !e.shiftKey) {
      setCropMode(!state.cropMode);
    } else if (e.key === "Escape" && state.cropMode) {
      setCropMode(false);
    } else if ((e.key === "i" || e.key === "I") && state.appMode === "negative") {
      setEyedropperMode(negativeState.eyedropperMode === "base" ? null : "base");
    } else if ((e.key === "w" || e.key === "W") && state.appMode === "negative") {
      setEyedropperMode(negativeState.eyedropperMode === "scene_wb" ? null : "scene_wb");
    } else if ((e.key === "v" || e.key === "V") && !e.metaKey && !e.ctrlKey && !e.altKey) {
      e.preventDefault();
      toggleEssentialView();
    } else if (
      (e.key === "ArrowUp" || e.key === "ArrowDown") &&
      !e.metaKey &&
      !e.ctrlKey &&
      !e.altKey &&
      state.frames.length > 0 &&
      tag !== "INPUT" &&
      tag !== "SELECT" &&
      tag !== "TEXTAREA" &&
      e.target?.id !== "splitDivider"
    ) {
      e.preventDefault();
      const dir = e.key === "ArrowUp" ? 1 : -1;
      nudgeExposure(dir * (state.appMode === "negative" ? 0.05 : 0.1));
    } else if (
      (e.key === "c" || e.key === "C") &&
      !e.metaKey &&
      !e.ctrlKey &&
      !e.altKey &&
      state.appMode === "negative" &&
      negativeState.filmType === "color"
    ) {
      e.preventDefault();
      nudgeCmyChannel(0, e.shiftKey ? -0.05 : 0.05);
    } else if (
      (e.key === "g" || e.key === "G") &&
      !e.metaKey &&
      !e.ctrlKey &&
      !e.altKey &&
      state.appMode === "negative" &&
      negativeState.filmType === "color"
    ) {
      e.preventDefault();
      nudgeCmyChannel(1, e.shiftKey ? -0.05 : 0.05);
    } else if (
      (e.key === "b" || e.key === "B") &&
      !e.metaKey &&
      !e.ctrlKey &&
      !e.altKey &&
      state.appMode === "negative" &&
      negativeState.filmType === "color"
    ) {
      e.preventDefault();
      nudgeCmyChannel(2, e.shiftKey ? -0.05 : 0.05);
    } else if (e.key === "l" || e.key === "L") {
      toggleSafelight();
    } else if (e.key === "?") {
      const sm = document.getElementById("shortcutsModal");
      if (sm) setModalOpen(sm, !sm.classList.contains("active"));
    }
  });

  const releaseSpacePan = () => {
    if (state.spacePressed) {
      state.spacePressed = false;
      document.getElementById("splitWrapper")?.classList.remove("space-pan-ready");
    }
  };

  window.addEventListener("keyup", (e) => {
    if (e.code === "Space" || e.key === " ") {
      releaseSpacePan();
    }
    if (e.key === "\\" && state.holdingOriginal) {
      state.holdingOriginal = false;
      setViewMode(state.prevViewMode || "split");
    }
  });

  window.addEventListener("blur", releaseSpacePan);
}

function toggleSafelight() {
  state.safelight = !state.safelight;
  document.body.classList.toggle("theme-safelight", state.safelight);
  const toggleBtn = document.getElementById("safelightToggle");
  if (toggleBtn) {
    toggleBtn.classList.toggle("active", state.safelight);
    toggleBtn.setAttribute("aria-pressed", state.safelight ? "true" : "false");
  }
  const imgDev = document.getElementById("imgDeveloped");
  if (imgDev && imgDev.naturalWidth && state.frames.length > 0) {
    renderHistogramFromImage(imgDev);
  }
}

// =============================================================
// EXPORT, SAVE AS, CONTACT SHEET & RECIPE RESTORATION
// =============================================================

function buildExportPrintOptions() {
  return {
    easel_border: state.easelBorder || "none",
    dry_down_comp: Number(state.dryDownComp) || 0.0,
    write_xmp: Boolean(document.getElementById("writeXmpCheck")?.checked),
  };
}

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
            ...buildExportPrintOptions(),
            ...buildNegativePayload(),
          }
        : {
            filename: activeFrame.filename,
            format: state.outputFormat,
            reveal: true,
            analog_meta: analogMeta,
            ...buildExportPrintOptions(),
            ...buildSimulationPayload(),
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
  const srcExt = (activeFrame.filename.match(/\.[^/.]+$/) || [".jpg"])[0].toLowerCase();
  const rawExts = new Set([".cr2", ".cr3", ".nef", ".arw", ".dng", ".orf", ".rw2", ".raf", ".pef"]);
  let ext = ".jpg";
  if (state.outputFormat === "tiff") ext = ".tiff";
  else if (state.outputFormat === "png") ext = ".png";
  else if (state.outputFormat === "dng") ext = ".dng";
  else if (state.outputFormat === "original") {
    if (srcExt === ".png") ext = ".png";
    else if (srcExt === ".tif" || srcExt === ".tiff") ext = ".tiff";
    else if (srcExt === ".webp") ext = ".webp";
    else if (rawExts.has(srcExt)) ext = ".dng";
    else if (srcExt === ".heic" || srcExt === ".heif") ext = ".tiff";
    else ext = ".jpg";
  }
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
            ...buildExportPrintOptions(),
            ...buildNegativePayload(),
          }
        : {
            filename: activeFrame.filename,
            dest_path: chosenPath,
            analog_meta: analogMeta,
            ...buildExportPrintOptions(),
            ...buildSimulationPayload(),
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

let activeBatchPollTimer = null;
let activeBatchJobId = null;

async function developFullRoll() {
  if (state.frames.length === 0 || activeBatchJobId) return;

  const filenames = state.frames.map((f) => f.filename);
  const perFrameRecipes = buildPerFrameRecipesMap();
  const analogMeta = buildAnalogMetaPayload();
  const isNeg = state.appMode === "negative";
  const rollName = getEffectiveRollName();
  const payload = isNeg
    ? {
        app_mode: "negative",
        filenames,
        sheet: true,
        columns: state.sheetColumns,
        format: state.outputFormat,
        roll_name: rollName,
        per_frame_recipes: perFrameRecipes,
        analog_meta: analogMeta,
        ...buildExportPrintOptions(),
        ...buildNegativePayload(),
      }
    : {
        app_mode: "simulation",
        filenames,
        format: state.outputFormat,
        sheet: true,
        columns: state.sheetColumns,
        roll_name: rollName,
        per_frame_recipes: perFrameRecipes,
        analog_meta: analogMeta,
        ...buildExportPrintOptions(),
        ...buildSimulationPayload(),
      };

  const progressModal = document.getElementById("batchProgressModal");
  const counterEl = document.getElementById("batchCounterText");
  const percentEl = document.getElementById("batchPercentText");
  const fillEl = document.getElementById("batchProgressFill");
  const trackEl = document.getElementById("batchProgressTrack");
  const fileEl = document.getElementById("batchCurrentFile");
  const timerEl = document.getElementById("batchTimerText");
  const cancelBtn = document.getElementById("btnCancelBatch");

  if (counterEl) counterEl.textContent = `Preparando ${filenames.length} fotograma(s)…`;
  if (percentEl) percentEl.textContent = "0%";
  if (fillEl) fillEl.style.width = "0%";
  if (trackEl) trackEl.setAttribute("aria-valuenow", "0");
  if (fileEl) fileEl.textContent = "Iniciando cámara oscura de 16 bits…";
  if (timerEl) timerEl.textContent = "0.0s";
  if (cancelBtn) {
    cancelBtn.disabled = false;
    cancelBtn.textContent = "Cancelar revelado";
  }
  setModalOpen(progressModal, true);

  try {
    const startRes = await fetch("/api/batch/develop_roll_start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const startData = await startRes.json();
    if (!startRes.ok || !startData.success || !startData.job_id) {
      throw new Error(startData.error || "Fallo al iniciar el revelado del rollo");
    }

    activeBatchJobId = startData.job_id;
    let pollFailures = 0;
    const MAX_POLL_FAILURES = 5;

    const stopPolling = () => {
      if (activeBatchPollTimer) {
        clearTimeout(activeBatchPollTimer);
        activeBatchPollTimer = null;
      }
      activeBatchJobId = null;
    };

    const pollStatus = async () => {
      if (!activeBatchJobId) return;
      const jobId = activeBatchJobId;
      try {
        const stRes = await fetch(`/api/batch/develop_status/${encodeURIComponent(jobId)}`);
        const st = await stRes.json();
        pollFailures = 0;
        const pct = Math.max(0, Math.min(100, Number(st.percent || 0)));

        if (counterEl) {
          if (st.status === "completed") {
            counterEl.textContent = `¡${st.total} fotograma(s) revelados!`;
          } else {
            counterEl.textContent = `Fotograma ${st.completed || 0} de ${st.total || filenames.length}`;
          }
        }
        if (percentEl) percentEl.textContent = `${pct}%`;
        if (fillEl) fillEl.style.width = `${pct}%`;
        if (trackEl) trackEl.setAttribute("aria-valuenow", String(pct));
        if (fileEl && st.current_file) fileEl.textContent = st.current_file;
        if (timerEl && st.elapsed_seconds != null) timerEl.textContent = `${Number(st.elapsed_seconds).toFixed(1)}s`;

        if (st.status === "completed") {
          stopPolling();
          setModalOpen(progressModal, false);
          state.lastRollResult = st.result;
          const summary = document.getElementById("modalSummary");
          if (summary && st.result) {
            summary.textContent = `Se procesaron ${st.result.total_frames} fotograma(s) en ${st.result.elapsed_seconds}s sin tocar tus archivos originales. Incluye hoja de contactos de archivo.`;
          }
          setModalOpen("resultModal", true);
          return;
        }
        if (st.status === "cancelled") {
          stopPolling();
          setModalOpen(progressModal, false);
          showToast("Revelado cancelado", "Se detuvo el procesamiento por lotes.");
          return;
        }
        if (st.status === "error" || st.status === "not_found" || !stRes.ok) {
          stopPolling();
          setModalOpen(progressModal, false);
          showToast("Error en lote", st.error || "No se pudo completar el rollo.");
          return;
        }
      } catch (pollErr) {
        console.error("Batch poll error:", pollErr);
        pollFailures += 1;
        if (pollFailures >= MAX_POLL_FAILURES) {
          // The previous implementation only logged the failure and kept the
          // interval alive forever, which left the "Revelar rollo" button
          // permanently blocked until the page was reloaded.
          stopPolling();
          setModalOpen(progressModal, false);
          showToast("Error en lote", "Se perdió la conexión con el revelado en curso.");
          return;
        }
      }
      // Recursive timeout instead of setInterval: overlapping polls could let
      // a slow response overwrite a newer progress value, rewinding the bar.
      if (activeBatchJobId && activeBatchJobId === jobId) {
        activeBatchPollTimer = setTimeout(pollStatus, 300);
      }
    };

    if (activeBatchPollTimer) clearTimeout(activeBatchPollTimer);
    await pollStatus();
  } catch (err) {
    setModalOpen(progressModal, false);
    if (activeBatchPollTimer) {
      clearTimeout(activeBatchPollTimer);
      activeBatchPollTimer = null;
    }
    activeBatchJobId = null;
    console.error("Error revelando rollo:", err);
    showToast("Error en lote", err.message || "No se pudo completar el rollo.");
  }
}

function renderContactSheetOverlay(layoutBoxes, sourceFrames = null) {
  const grid = document.getElementById("sheetOverlayGrid");
  if (!grid) return;
  grid.innerHTML = "";
  if (!Array.isArray(layoutBoxes)) return;

  const framesPool = Array.isArray(sourceFrames) && sourceFrames.length > 0 ? sourceFrames : getSheetFrames();

  layoutBoxes.forEach((box) => {
    const mappedFrame = framesPool[box.index] || state.frames[box.index];
    const resolvedIdx = mappedFrame ? state.frames.indexOf(mappedFrame) : box.index;
    const idx = resolvedIdx >= 0 ? resolvedIdx : box.index;
    const frame = state.frames[idx];

    const hotspot = document.createElement("button");
    hotspot.type = "button";
    hotspot.className = "sheet-frame-hotspot";
    hotspot.style.left = `${(box.x_pct * 100).toFixed(3)}%`;
    hotspot.style.top = `${(box.y_pct * 100).toFixed(3)}%`;
    hotspot.style.width = `${(box.w_pct * 100).toFixed(3)}%`;
    hotspot.style.height = `${(box.h_pct * 100).toFixed(3)}%`;
    hotspot.dataset.index = String(idx);
    hotspot.title = frame
      ? `Clic para editar ${frame.name} (Fotograma ${String(idx + 1).padStart(2, "0")}A)`
      : `Clic para editar fotograma #${idx + 1}`;
    hotspot.setAttribute("aria-label", hotspot.title);

    const pill = document.createElement("span");
    pill.className = "sheet-hotspot-pill";
    pill.textContent = `▶ ${String(idx + 1).padStart(2, "0")}A · Editar`;
    hotspot.appendChild(pill);

    hotspot.addEventListener("click", (e) => {
      if (sheetDragMoved > 5) return;
      e.stopPropagation();
      activateFrameByIndex(idx, "full");
    });

    grid.appendChild(hotspot);
  });
}

function buildContactSheetSignature() {
  const sheetFrames = getSheetFrames();
  const effectiveFrames = sheetFrames.length > 0 ? sheetFrames : state.frames;
  const filenames = effectiveFrames.map((f) => f.filename).join(",");
  const recipes = JSON.stringify(buildPerFrameRecipesMap());
  const roll = getEffectiveRollName();
  const cols = state.sheetColumns || 4;
  const filterFlag = state.hideRejectedInSheet ? "filt" : "all";
  if (state.appMode === "negative") {
    return `neg_${roll}_${cols}_${filterFlag}_${filenames}_${recipes}_${JSON.stringify(buildNegativePayload())}`;
  } else {
    return `pos_${roll}_${cols}_${filterFlag}_${filenames}_${recipes}_${state.selectedFilm}_${state.ev}_${state.halation}_${state.grain}_${state.vignette}_${state.date}_${state.rotate}_${state.flip_h}`;
  }
}

async function generateContactSheetPreview() {
  if (state.frames.length === 0) return;
  let sheetFrames = getSheetFrames();
  if (sheetFrames.length === 0) {
    state.hideRejectedInSheet = false;
    updateCullSummaryUI();
    sheetFrames = state.frames;
  }
  const sig = buildContactSheetSignature();
  const sheetImg = document.getElementById("sheetPreview");

  // Instant display from client-side cache if settings didn't change
  if (state.contactSheetCache && state.contactSheetCache.signature === sig && state.contactSheetCache.url) {
    if (sheetImg) {
      sheetImg.src = state.contactSheetCache.url;
    }
    if (state.contactSheetCache.layout) {
      state.sheetLayout = state.contactSheetCache.layout;
      renderContactSheetOverlay(state.sheetLayout, sheetFrames);
    }
    return;
  }

  showLoading(true, "Componiendo hoja de contactos analógica…");
  try {
    const filenames = sheetFrames.map((f) => f.filename);
    const perFrameRecipes = buildPerFrameRecipesMap();
    const isNeg = state.appMode === "negative";
    const endpoint = isNeg ? "/api/negative/contact_sheet_preview" : "/api/contact_sheet_preview";
    const rollName = getEffectiveRollName();
    const payload = isNeg
      ? {
          filenames,
          roll_name: rollName,
          columns: state.sheetColumns,
          per_frame_recipes: perFrameRecipes,
          ...buildNegativePayload(),
        }
      : {
          filenames,
          roll_name: rollName,
          columns: state.sheetColumns,
          per_frame_recipes: perFrameRecipes,
          ...buildSimulationPayload(),
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
      state.sheetLayout = data.layout || [];
      renderContactSheetOverlay(state.sheetLayout, sheetFrames);
      state.contactSheetCache = {
        signature: sig,
        url: data.sheet_url,
        layout: state.sheetLayout,
      };
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
  let sheetFrames = getSheetFrames();
  if (sheetFrames.length === 0) sheetFrames = state.frames;
  const isNeg = state.appMode === "negative";
  const rollName = getEffectiveRollName();
  const safeFileRoll = rollName.replace(/[^a-zA-Z0-9_-]/g, "_").replace(/_+/g, "_") || (isNeg ? "HALURO_NEG" : "HALURO_ROLL");
  const defaultName = `Haluro_Contactos_${safeFileRoll}.jpg`;

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
    const filenames = sheetFrames.map((f) => f.filename);
    const perFrameRecipes = buildPerFrameRecipesMap();
    const endpoint = isNeg ? "/api/negative/save_contact_sheet" : "/api/save_contact_sheet";
    const payload = isNeg
      ? {
          filenames,
          roll_name: rollName,
          columns: state.sheetColumns,
          dest_path: chosenPath,
          reveal: true,
          per_frame_recipes: perFrameRecipes,
          ...buildNegativePayload(),
        }
      : {
          filenames,
          roll_name: rollName,
          columns: state.sheetColumns,
          dest_path: chosenPath,
          reveal: true,
          per_frame_recipes: perFrameRecipes,
          ...buildSimulationPayload(),
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

  setModalOpen(modal, true);
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
      const leadEl = document.createElement("span");
      leadEl.textContent = `${recipeTitle}${resTxt} · `;
      const dateEl = document.createElement("span");
      dateEl.className = "history-meta-date";
      dateEl.textContent = item.mtime;
      metaEl.appendChild(leadEl);
      metaEl.appendChild(dateEl);

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
  document.getElementById("flipHBtn")?.setAttribute("aria-pressed", state.flip_h ? "true" : "false");
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
  renderBorderGuideOverlay();
  drawCurveEditor();
  await requestPreview(true);
  showToast("Receta restaurada", "Todos los parámetros ópticos se han aplicado.");
}

// =============================================================
// DOM LISTENERS WIRING
// =============================================================

function setToggleGroupActive(selector, activeEl, attr = "aria-pressed") {
  document.querySelectorAll(selector).forEach((el) => {
    const isMatch = el === activeEl;
    el.classList.toggle("active", isMatch);
    if (attr) el.setAttribute(attr, isMatch ? "true" : "false");
  });
}

function initUIListeners() {
  // Primary mode tabs & Zen layout toggle
  document.getElementById("tabDarkroomsMode")?.addEventListener("click", () => switchStudioMode("simulation"));
  document.getElementById("tabNegativeMode")?.addEventListener("click", () => switchStudioMode("negative"));
  document.getElementById("uiComplexityBtn")?.addEventListener("click", () => toggleEssentialView());
  document.getElementById("zenToggleBtn")?.addEventListener("click", () => toggleZenSidebars());

  // Undo / Redo toolbar buttons
  document.getElementById("undoBtn")?.addEventListener("click", performUndo);
  document.getElementById("redoBtn")?.addEventListener("click", performRedo);

  // Top bar utilities & export
  document.getElementById("loadSampleBtn")?.addEventListener("click", () => loadSamplePhoto());
  document.getElementById("emptyImportBtn")?.addEventListener("click", () => {
    document.getElementById("fileInput")?.click();
  });
  document.getElementById("emptySampleBtn")?.addEventListener("click", () => loadSamplePhoto());
  document.getElementById("fileInput")?.addEventListener("change", (e) => {
    importFiles(e.target.files);
    e.target.value = "";
  });
  document.getElementById("safelightToggle")?.addEventListener("click", toggleSafelight);
  document.getElementById("historyBtn")?.addEventListener("click", openHistoryModal);
  document.getElementById("shortcutsBtn")?.addEventListener("click", () => {
    setModalOpen("shortcutsModal", true);
  });
  document.getElementById("aboutBtn")?.addEventListener("click", () => {
    setModalOpen("aboutModal", true);
  });

  // Live clipping zebra toggles & culling strip clear action
  document.getElementById("clipShadows")?.addEventListener("click", () => toggleZebraChannel("shadows"));
  document.getElementById("clipHighlights")?.addEventListener("click", () => toggleZebraChannel("highlights"));
  document.getElementById("btnCullClearRejected")?.addEventListener("click", removeRejectedFrames);
  document.getElementById("sheetHideRejectedBtn")?.addEventListener("click", () => {
    const { rejects, total } = getCullCounts();
    if (!state.hideRejectedInSheet && total > 0 && rejects >= total) {
      showToast("Todos descartados", "No hay fotogramas sin descartar para filtrar en la hoja.");
      return;
    }
    state.hideRejectedInSheet = !state.hideRejectedInSheet;
    updateCullSummaryUI();
    if (state.viewMode === "sheet" && state.frames.length > 0) {
      generateContactSheetPreview();
    }
  });

  // Smart update system listeners
  document.getElementById("updateBadgeBtn")?.addEventListener("click", openUpdateModal);
  document.getElementById("closeUpdateModalBtn")?.addEventListener("click", closeUpdateModal);
  document.getElementById("btnDismissUpdate")?.addEventListener("click", closeUpdateModal);
  document.getElementById("btnCheckUpdateManual")?.addEventListener("click", () => checkForUpdates(true));
  document.getElementById("btnDownloadUpdate")?.addEventListener("click", triggerUpdateDownload);

  const exportMenu = document.getElementById("exportMenu");
  const exportMoreBtn = document.getElementById("exportMoreBtn");
  const closeExportMenu = () => {
    exportMenu?.classList.remove("open");
    exportMoreBtn?.setAttribute("aria-expanded", "false");
  };

  exportMoreBtn?.addEventListener("click", (e) => {
    e.stopPropagation();
    const isOpen = exportMenu?.classList.toggle("open");
    exportMoreBtn.setAttribute("aria-expanded", isOpen ? "true" : "false");
  });

  document.addEventListener("click", (e) => {
    if (!e.target.closest("#exportSplit")) closeExportMenu();
  });

  document.getElementById("saveDownloadsBtn")?.addEventListener("click", () => {
    closeExportMenu();
    saveDirectToDownloads();
  });
  document.getElementById("saveAsBtn")?.addEventListener("click", () => {
    closeExportMenu();
    saveAsWithDialog();
  });
  document.getElementById("saveSheetBtn")?.addEventListener("click", () => {
    closeExportMenu();
    saveContactSheetOnly(false);
  });
  document.getElementById("developFullBtn")?.addEventListener("click", () => {
    closeExportMenu();
    developFullRoll();
  });

  document.getElementById("btnCancelBatch")?.addEventListener("click", async () => {
    if (!activeBatchJobId) return;
    const cancelBtn = document.getElementById("btnCancelBatch");
    if (cancelBtn) {
      cancelBtn.disabled = true;
      cancelBtn.textContent = "Cancelando…";
    }
    try {
      await fetch(`/api/batch/develop_cancel/${encodeURIComponent(activeBatchJobId)}`, {
        method: "POST",
      });
    } catch (err) {
      console.error("Error cancelando lote:", err);
    }
  });

  // Contact Sheet interactive toolbar (roll name & columns)
  let sheetRollDebounce = null;
  document.getElementById("sheetRollNameInput")?.addEventListener("input", (e) => {
    state.sheetRollName = e.target.value || "";
    clearTimeout(sheetRollDebounce);
    sheetRollDebounce = setTimeout(() => {
      if (state.viewMode === "sheet" && state.frames.length > 0) {
        generateContactSheetPreview();
      }
    }, 380);
  });
  document.getElementById("sheetRollNameInput")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      clearTimeout(sheetRollDebounce);
      state.sheetRollName = e.target.value || "";
      if (state.viewMode === "sheet" && state.frames.length > 0) {
        generateContactSheetPreview();
      }
      e.target.blur();
    }
  });

  document.querySelectorAll("#sheetColumnsBar .sheet-col-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const cols = parseInt(btn.dataset.cols, 10) || 4;
      if (cols === state.sheetColumns) return;
      state.sheetColumns = cols;
      setToggleGroupActive("#sheetColumnsBar .sheet-col-btn", btn, "aria-checked");
      if (state.viewMode === "sheet" && state.frames.length > 0) {
        generateContactSheetPreview();
      }
    });
  });

  // Catalog search, clear & ISO/catalog sort toggle
  // The search rebuilt all 72 cards (≈576 nodes + 216 listeners) on every
  // keystroke; it is now debounced.
  let searchDebounceTimer = null;
  document.getElementById("filmSearch")?.addEventListener("input", (e) => {
    state.search = e.target.value;
    if (searchDebounceTimer) clearTimeout(searchDebounceTimer);
    searchDebounceTimer = setTimeout(() => {
      searchDebounceTimer = null;
      applyFilters();
    }, 140);
  });
  document.getElementById("clearFilmSearchBtn")?.addEventListener("click", () => {
    const searchEl = document.getElementById("filmSearch");
    if (searchEl) {
      searchEl.value = "";
      searchEl.focus();
    }
    state.search = "";
    applyFilters();
  });
  document.getElementById("filmSortBtn")?.addEventListener("click", () => {
    state.filmSort = state.filmSort === "iso" ? "catalog" : "iso";
    const sortBtn = document.getElementById("filmSortBtn");
    if (sortBtn) {
      const byIso = state.filmSort === "iso";
      sortBtn.textContent = byIso ? "ISO ↑" : "Catálogo";
      sortBtn.classList.toggle("active", byIso);
      sortBtn.setAttribute("aria-pressed", byIso ? "true" : "false");
    }
    applyFilters();
  });

  document.querySelectorAll(".filter-pill").forEach((btn) => {
    btn.addEventListener("click", () => {
      setToggleGroupActive(".filter-pill", btn, "aria-pressed");
      state.category = btn.dataset.category || "all";
      applyFilters();
    });
  });

  const userLutInput = document.getElementById("userLutInput");
  document.getElementById("userLutUploadBtn")?.addEventListener("click", () => {
    if (userLutInput) {
      userLutInput.value = "";
      userLutInput.click();
    }
  });
  userLutInput?.addEventListener("change", (e) => {
    if (e.target.files && e.target.files.length > 0) {
      uploadUserLuts(e.target.files);
    }
  });
  document.getElementById("userLutOpenFolderBtn")?.addEventListener("click", async () => {
    try {
      await fetch("/api/user_luts/open_folder", { method: "POST" });
    } catch (err) {
      console.error("Error abriendo carpeta de LUTs:", err);
    }
  });

  // Viewport modes & geometry
  document.getElementById("viewSplitBtn")?.addEventListener("click", () => setViewMode("split"));
  document.getElementById("viewFullBtn")?.addEventListener("click", () => setViewMode("full"));
  document.getElementById("viewOrigBtn")?.addEventListener("click", () => setViewMode("original"));
  document.getElementById("viewSheetBtn")?.addEventListener("click", () => setViewMode("sheet"));
  document.getElementById("viewTestStripBtn")?.addEventListener("click", () => {
    setViewMode(state.viewMode === "teststrip" ? (state.prevViewMode === "split" ? "split" : "full") : "teststrip");
  });
  document.getElementById("exitTestStripBtn")?.addEventListener("click", () => {
    setViewMode(state.prevViewMode === "split" ? "split" : "full");
  });
  document.querySelectorAll(".test-strip-step-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const step = parseFloat(btn.dataset.step || "0.5");
      if (!Number.isFinite(step)) return;
      state.testStripStepEv = step;
      document.querySelectorAll(".test-strip-step-btn").forEach((b) => {
        const active = b === btn;
        b.classList.toggle("active", active);
        b.setAttribute("aria-pressed", active ? "true" : "false");
      });
      if (state.viewMode === "teststrip") requestPreview(false);
    });
  });

  document.getElementById("rotateLeftBtn")?.addEventListener("click", () => rotateCurrentFrame(-90));
  document.getElementById("rotateRightBtn")?.addEventListener("click", () => rotateCurrentFrame(90));
  document.getElementById("flipHBtn")?.addEventListener("click", toggleHorizontalFlip);
  document.getElementById("flipVBtn")?.addEventListener("click", toggleVerticalFlip);
  document.getElementById("cropToolBtn")?.addEventListener("click", () => setCropMode(!state.cropMode));
  initGeometryTool();
  initSharedDarkroomTools();

  document.getElementById("zoomInBtn")?.addEventListener("click", () => {
    const base = state.viewMode === "sheet" ? state.sheetZoom : state.zoom;
    setZoom(base + 0.25);
  });
  document.getElementById("zoomOutBtn")?.addEventListener("click", () => {
    const base = state.viewMode === "sheet" ? state.sheetZoom : state.zoom;
    setZoom(base - 0.25);
  });
  document.getElementById("zoomResetBtn")?.addEventListener("click", resetZoom);

  // Per-frame recipe copy / paste / roll sync
  document.getElementById("copyRecipeBtn")?.addEventListener("click", copyCurrentRecipe);
  document.getElementById("pasteRecipeBtn")?.addEventListener("click", pasteCopiedRecipe);
  document.getElementById("syncRollBtn")?.addEventListener("click", syncRecipeToRoll);

  // Simulation controls
  document.getElementById("resetSimBtn")?.addEventListener("click", resetSimulationControls);
  document.getElementById("simDevProcessSelect")?.addEventListener("change", (e) => {
    pushUndoSnapshotForFrame();
    state.devProcess = e.target.value || "standard";
    saveActiveFrameRecipe();
    saveUserPreferences();
    requestPreview(false);
  });
  document.getElementById("grainAsaSelect")?.addEventListener("change", (e) => {
    pushUndoSnapshotForFrame();
    state.grainAsa = e.target.value || "auto";
    saveActiveFrameRecipe();
    saveUserPreferences();
    requestPreview(false);
  });

  const bindRange = (sliderId, labelId, formatter, onValue) => {
    const el = document.getElementById(sliderId);
    const lbl = document.getElementById(labelId);
    if (!el) return;
    let armedBeforeSnap = null;
    const armBeforeSnap = () => {
      if (!suppressAutoSliderUndo && !armedBeforeSnap) {
        armedBeforeSnap = captureModeRecipeSnapshot();
      }
    };
    el.addEventListener("pointerdown", armBeforeSnap);
    el.addEventListener("dblclick", armBeforeSnap);
    el.addEventListener("keydown", (ev) => {
      if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End", "PageUp", "PageDown"].includes(ev.key)) {
        armBeforeSnap();
      }
    });
    el.addEventListener("change", () => {
      armedBeforeSnap = null;
    });
    el.addEventListener("pointerup", () => {
      armedBeforeSnap = null;
    });
    el.addEventListener("input", (e) => {
      if (!suppressAutoSliderUndo) {
        pushUndoSnapshotForFrame(
          state.frames[state.activeFrameIndex],
          state.appMode,
          armedBeforeSnap || captureModeRecipeSnapshot()
        );
        armedBeforeSnap = null;
      }
      const val = parseFloat(e.target.value);
      if (lbl) lbl.textContent = formatter(val);
      onValue(val);
      saveActiveFrameRecipe();
      saveUserPreferences();
      // Keyed per control so two sliders moved in quick succession do not
      // cancel each other's pending render.
      triggerDebouncedPreview(el.id || "default");
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
  bindRange("shadowsSlider", "shadowsVal", formatZoneEv, (v) => {
    state.shadows = v;
  });
  bindRange("midsSlider", "midsVal", formatZoneEv, (v) => {
    state.mids = v;
  });
  bindRange("highlightsSlider", "highlightsVal", formatZoneEv, (v) => {
    state.highlights = v;
  });

  document.getElementById("resetToneBtn")?.addEventListener("click", () => {
    resetSlidersWithUndo(
      [
        ["shadowsSlider", "0.0"],
        ["midsSlider", "0.0"],
        ["highlightsSlider", "0.0"],
      ],
      () => {}
    );
  });

  document.getElementById("dateToggle")?.addEventListener("change", (e) => {
    if (!suppressAutoSliderUndo) pushUndoSnapshotForFrame();
    state.date = e.target.checked;
    saveActiveFrameRecipe();
    requestPreview(false);
  });

  // Negative Lab left sidebar controls
  document.getElementById("btnTypeColor")?.addEventListener("click", () => {
    if (negativeState.filmType === "color") return;
    pushUndoSnapshotForFrame();
    negativeState.filmType = "color";
    document.getElementById("btnTypeColor")?.classList.add("active");
    document.getElementById("btnTypeColor")?.setAttribute("aria-pressed", "true");
    document.getElementById("btnTypeBW")?.classList.remove("active");
    document.getElementById("btnTypeBW")?.setAttribute("aria-pressed", "false");
    syncNegProcessPanels();
    updateActiveRecipeBanner();
    renderBorderGuideOverlay();
    drawCurveEditor();
    if (negativeState.profile === "bw") {
      selectNegativeProfile("frontier", true);
    } else {
      saveActiveFrameRecipe();
      requestPreview(false);
    }
  });

  document.getElementById("btnTypeBW")?.addEventListener("click", () => {
    if (negativeState.filmType === "bw") return;
    pushUndoSnapshotForFrame();
    negativeState.filmType = "bw";
    document.getElementById("btnTypeBW")?.classList.add("active");
    document.getElementById("btnTypeBW")?.setAttribute("aria-pressed", "true");
    document.getElementById("btnTypeColor")?.classList.remove("active");
    document.getElementById("btnTypeColor")?.setAttribute("aria-pressed", "false");
    syncNegProcessPanels();
    selectNegativeProfile("bw", true);
  });

  document.getElementById("negSubstrateSelect")?.addEventListener("change", (e) => {
    const nextSub = e.target.value || "c41_orange";
    if (nextSub === negativeState.filmSubstrate) return;
    pushUndoSnapshotForFrame();
    negativeState.filmSubstrate = nextSub;
    syncNegProcessPanels();
    saveActiveFrameRecipe();
    requestPreview(false);
  });

  document.querySelectorAll("#negScanSourceBar .seg-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const nextSrc = btn.dataset.source || "camera_raw";
      if (nextSrc === negativeState.scanSource) return;
      pushUndoSnapshotForFrame();
      setToggleGroupActive("#negScanSourceBar .seg-btn", btn, "aria-pressed");
      negativeState.scanSource = nextSrc;
      saveActiveFrameRecipe();
      requestPreview(false);
    });
  });

  bindRange("negPreSatSlider", "negPreSatVal", (v) => `${v.toFixed(2)}x`, (v) => {
    negativeState.preSaturation = v;
  });

  document.getElementById("btnUploadFlatField")?.addEventListener("click", () => {
    document.getElementById("negFlatFieldInput")?.click();
  });
  document.getElementById("negFlatFieldInput")?.addEventListener("change", async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    showLoading(true, "Analizando toma de campo plano (mesa LED)…");
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch("/api/negative/flat_field/upload", { method: "POST", body: form });
      const data = await res.json();
      if (!res.ok || !data.flat_field_file) {
        throw new Error(data.error || "No se pudo calibrar el campo plano");
      }
      pushUndoSnapshotForFrame();
      negativeState.flatFieldFile = data.flat_field_file;
      negativeState.flatFieldLabel = `${data.name || file.name} (caída esquinas -${data.corner_falloff_pct ?? 0}%)`;
      syncNegProcessPanels();
      saveActiveFrameRecipe();
      await requestPreview(false);
      showToast(
        "Campo plano calibrado",
        `Uniformidad ${data.uniformity_pct ?? 100}% · Compensación activa sobre viñeteo y mesa LED.`
      );
    } catch (err) {
      showToast("Error en campo plano", err.message || "Verifica la imagen en blanco.");
    } finally {
      showLoading(false);
    }
  });
  document.getElementById("btnClearFlatField")?.addEventListener("click", () => {
    if (!negativeState.flatFieldFile) return;
    pushUndoSnapshotForFrame();
    negativeState.flatFieldFile = null;
    negativeState.flatFieldLabel = "";
    syncNegProcessPanels();
    saveActiveFrameRecipe();
    requestPreview(false);
  });
  bindRange("negFlatFieldStrengthSlider", "negFlatFieldStrengthVal", (v) => `${Math.round(v)}%`, (v) => {
    negativeState.flatFieldStrength = v / 100;
  });

  document.querySelectorAll("#negLightSourceBar .seg-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const nextLight = btn.dataset.light || "standard";
      if (nextLight === negativeState.lightSource) return;
      pushUndoSnapshotForFrame();
      setToggleGroupActive("#negLightSourceBar .seg-btn", btn, "aria-pressed");
      negativeState.lightSource = nextLight;
      saveActiveFrameRecipe();
      requestPreview(false);
    });
  });

  document.querySelectorAll("#negColorMethodBar .seg-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const nextMethod = btn.dataset.method || "dynamic";
      if (nextMethod === negativeState.colorMethod) return;
      pushUndoSnapshotForFrame();
      setToggleGroupActive("#negColorMethodBar .seg-btn", btn, "aria-pressed");
      negativeState.colorMethod = nextMethod;
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
      const nextTone = btn.dataset.tone || "standard";
      if (nextTone === negativeState.toneVariant) return;
      pushUndoSnapshotForFrame();
      setToggleGroupActive("#negToneVariantBar .seg-btn", btn, "aria-pressed");
      negativeState.toneVariant = nextTone;
      saveActiveFrameRecipe();
      requestPreview(false);
    });
  });

  document.getElementById("negPrintFinishSelect")?.addEventListener("change", (e) => {
    pushUndoSnapshotForFrame();
    negativeState.printFinish = e.target.value || "none";
    syncNegProcessPanels();
    saveActiveFrameRecipe();
    requestPreview(false);
  });

  bindRange("negFinishAmountSlider", "negFinishAmountVal", (v) => `${Math.round(v)}%`, (v) => {
    negativeState.finishAmount = v / 100;
  });

  document.getElementById("negBwTonerSelect")?.addEventListener("change", (e) => {
    pushUndoSnapshotForFrame();
    negativeState.bwToner = e.target.value || "neutral";
    syncNegProcessPanels();
    updateActiveRecipeBanner();
    renderBorderGuideOverlay();
    drawCurveEditor();
    saveActiveFrameRecipe();
    requestPreview(false);
  });

  bindRange("negBwTonerStrengthSlider", "negBwTonerStrengthVal", (v) => `${Math.round(v)}%`, (v) => {
    negativeState.bwTonerStrength = v / 100;
  });
  bindRange("negBwGrade00Slider", "negBwGrade00Val", fmtSigned, (v) => {
    negativeState.bwGrade00 = v;
  });
  bindRange("negBwGrade5Slider", "negBwGrade5Val", fmtSigned, (v) => {
    negativeState.bwGrade5 = v;
  });
  bindRange("negBwPreflashSlider", "negBwPreflashVal", (v) => `${Math.round(v)}%`, (v) => {
    negativeState.bwPreflash = v / 100;
  });
  document.getElementById("resetBwSplitBtn")?.addEventListener("click", () => {
    resetSlidersWithUndo([
      ["negBwGrade00Slider", "0.00"],
      ["negBwGrade5Slider", "0.00"],
      ["negBwPreflashSlider", "0"],
    ]);
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
    flashBorderGuideOverlay();
  });
  bindRange("negCropSlider", "negCropVal", (v) => `${v.toFixed(1).replace(/\.0$/, "")}%`, (v) => {
    negativeState.cropPct = v / 100;
    flashBorderGuideOverlay();
  });
  document.getElementById("negKeepSprocketsToggle")?.addEventListener("change", (e) => {
    if (!suppressAutoSliderUndo) pushUndoSnapshotForFrame();
    negativeState.keepSprockets = Boolean(e.target.checked);
    syncNegProcessPanels();
    saveActiveFrameRecipe();
    requestPreview(false);
  });
  document.getElementById("negShowBorderGuideToggle")?.addEventListener("change", (e) => {
    negativeState.showBorderGuide = Boolean(e.target.checked);
    renderBorderGuideOverlay();
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
    if (!suppressAutoSliderUndo) pushUndoSnapshotForFrame();
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
      const nextMode = btn.dataset.sharpen || "off";
      if (nextMode === negativeState.sharpenMode) return;
      pushUndoSnapshotForFrame();
      setToggleGroupActive("#negSharpenModeBar .seg-btn", btn, "aria-pressed");
      negativeState.sharpenMode = nextMode;
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

  document.getElementById("btnDustHealTool")?.addEventListener("click", () => {
    setEyedropperMode(negativeState.eyedropperMode === "dust" ? null : "dust");
  });
  document.getElementById("btnDustUndo")?.addEventListener("click", undoLastDustSpot);
  document.getElementById("btnDustClear")?.addEventListener("click", clearAllDustSpots);
  document.getElementById("negDustRadiusSlider")?.addEventListener("input", (e) => {
    const val = Math.max(0.4, Math.min(2.4, parseFloat(e.target.value) || 0.8));
    negativeState.dustRadius = val / 100;
    const lbl = document.getElementById("negDustRadiusVal");
    if (lbl) lbl.textContent = `${val.toFixed(1)}%`;
  });
  updateDustSpotsUI();

  // P9: Easel Border & Paper Dry-Down export controls
  document.getElementById("easelBorderSelect")?.addEventListener("change", (e) => {
    state.easelBorder = e.target.value || "none";
    saveUserPreferences();
  });
  document.getElementById("dryDownSelect")?.addEventListener("change", (e) => {
    state.dryDownComp = parseFloat(e.target.value) || 0.0;
    saveUserPreferences();
  });

  // Output master format selector
  document.querySelectorAll("#outputFormatPills .fmt-pill").forEach((pill) => {
    pill.addEventListener("click", () => {
      setToggleGroupActive("#outputFormatPills .fmt-pill", pill, "aria-checked");
      state.outputFormat = pill.dataset.format || "jpg";
      if (state.maskEditMode) {
    requestAnimationFrame(() => renderLocalMaskOverlay());
  }
  updateOutputFormatHint();
    });
  });
  if (state.maskEditMode) {
    requestAnimationFrame(() => renderLocalMaskOverlay());
  }
  updateOutputFormatHint();

  document.getElementById("openFolderBtn")?.addEventListener("click", async () => {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.open_developed_folder) {
      await window.pywebview.api.open_developed_folder();
      return;
    }
    try {
      const res = await fetch("/api/open_folder", { method: "POST" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
    } catch (err) {
      console.error("open_folder failed:", err);
      showToast("No se pudo abrir la carpeta", "Haluro no pudo abrir el directorio de salida.");
    }
  });

  // Modal actions & backdrop dismissal
  document.getElementById("closeModalBtn")?.addEventListener("click", () => {
    setModalOpen("resultModal", false);
  });
  document.getElementById("closeHistoryBtn")?.addEventListener("click", () => {
    setModalOpen("historyModal", false);
  });
  document.getElementById("closeShortcutsBtn")?.addEventListener("click", () => {
    setModalOpen("shortcutsModal", false);
  });
  document.getElementById("closeAboutBtn")?.addEventListener("click", () => {
    setModalOpen("aboutModal", false);
  });
  document.getElementById("btnCopyAboutInfo")?.addEventListener("click", async () => {
    const verBadge = document.querySelector(".about-version-badge")?.textContent?.trim() || "Versión 2.8.0";
    const text =
      `Haluro — Laboratorio Analógico Digital (${verBadge})\n` +
      "Desarrollador: Fotógrafo César Fernández Ardiles (Oregano, Chile)\n" +
      "Licencia: MIT (Software libre y gratuito)\n" +
      "Emulación: 80 películas químicas + Inversión óptica C-41 / B&N\n" +
      "100% No destructivo · 100% Local y privado\n" +
      "Exportación: TIFF 16-bit real (48-bit RGB) + EXIF analógico";
    // navigator.clipboard requires a secure context: it rejects on plain
    // http://<LAN-IP>, so a failure here must fall back and still give feedback.
    try {
      if (navigator.clipboard && window.isSecureContext && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const ta = document.createElement("textarea");
        ta.value = text;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        ta.remove();
      }
      showToast("Ficha copiada al portapapeles", "Información técnica y de autor de Haluro.");
    } catch (err) {
      console.error("copy about info failed:", err);
      showToast("No se pudo copiar", "El portapapeles no está disponible en este contexto.");
    }
  });

  document.querySelectorAll(".modal-backdrop").forEach((backdrop) => {
    backdrop.addEventListener("click", (e) => {
      if (backdrop.id === "batchProgressModal") return;
      if (e.target === backdrop) setModalOpen(backdrop, false);
    });
  });

  document.getElementById("modalSaveZipBtn")?.addEventListener("click", async () => {
    if (!state.lastRollResult) return;
    try {
      const res = await fetch("/api/save_zip_to_downloads", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ roll_folder: state.lastRollResult.roll_folder }),
      });
      const data = await res.json();
      if (data.success) {
        setModalOpen("resultModal", false);
        showToast("ZIP guardado en Descargas", data.saved_path);
      } else {
        showToast("No se pudo guardar el ZIP", data.error || "Error desconocido.");
      }
    } catch (err) {
      console.error("save_zip_to_downloads failed:", err);
      showToast("No se pudo guardar el ZIP", "Haluro no pudo comprimir el rollo.");
    }
  });

  document.getElementById("modalOpenRollBtn")?.addEventListener("click", () => {
    if (state.lastRollResult?.roll_dir) {
      revealFileInFinder(state.lastRollResult.roll_dir);
    }
  });

  // Selective sync modal actions
  const closeSyncModal = () => setModalOpen("syncRollModal", false);
  document.getElementById("closeSyncRollModalBtn")?.addEventListener("click", closeSyncModal);
  document.getElementById("btnCancelSyncRoll")?.addEventListener("click", closeSyncModal);
  document.getElementById("btnConfirmSyncRoll")?.addEventListener("click", () => {
    const opts = {
      profileTone: Boolean(document.getElementById("syncOptProfileTone")?.checked),
      color: Boolean(document.getElementById("syncOptColor")?.checked),
      optics: Boolean(document.getElementById("syncOptOptics")?.checked),
      baseCrop: Boolean(document.getElementById("syncOptBaseCrop")?.checked),
    };
    closeSyncModal();
    applySyncRecipeToRoll(opts);
  });
}

function selectNegativeProfile(profileKey, skipUndo = false) {
  if (!profileKey) return;
  if (!skipUndo && profileKey !== negativeState.profile) {
    pushUndoSnapshotForFrame();
  }
  negativeState.profile = profileKey;

  if (profileKey === "bw" && negativeState.filmType !== "bw") {
    negativeState.filmType = "bw";
  } else if (profileKey !== "bw" && negativeState.filmType === "bw") {
    negativeState.filmType = "color";
  }
  const btnColor = document.getElementById("btnTypeColor");
  const btnBw = document.getElementById("btnTypeBW");
  btnColor?.classList.toggle("active", negativeState.filmType === "color");
  btnColor?.setAttribute("aria-pressed", negativeState.filmType === "color" ? "true" : "false");
  btnBw?.classList.toggle("active", negativeState.filmType === "bw");
  btnBw?.setAttribute("aria-pressed", negativeState.filmType === "bw" ? "true" : "false");

  document.querySelectorAll("#negProfileList .profile-card").forEach((c) => {
    const sel = c.dataset.profile === profileKey;
    c.classList.toggle("selected", sel);
    c.setAttribute("aria-selected", sel ? "true" : "false");
  });
  syncNegProcessPanels();
  saveActiveFrameRecipe();
  updateActiveRecipeBanner();
  renderBorderGuideOverlay();
  drawCurveEditor();
  requestPreview(false);
}

// =============================================================
// FEEDBACK HELPERS (LOADING, BUSY DOT, FINDER, TOASTS)
// =============================================================

function setRenderBusy(isBusy) {
  document.getElementById("renderDot")?.classList.toggle("busy", Boolean(isBusy));
}

/**
 * Show/hide the processing overlay.
 *
 * A single boolean could not represent two concurrent operations: the first
 * `finally` cleared the overlay while the second was still running. The
 * counter keeps the overlay up until the last operation finishes.
 */
let loadingCount = 0;
function showLoading(visible, message = "Procesando en el laboratorio…") {
  const overlay = document.getElementById("loadingOverlay");
  const msgEl = document.getElementById("loadingMessage");
  if (msgEl && message) msgEl.textContent = message;
  loadingCount = Math.max(0, loadingCount + (visible ? 1 : -1));
  overlay?.classList.toggle("active", loadingCount > 0);
}

async function revealFileInFinder(path) {
  try {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.reveal_file) {
      await window.pywebview.api.reveal_file(path);
      return;
    }
    const res = await fetch("/api/reveal_in_finder", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
  } catch (err) {
    console.error("reveal_in_finder failed:", err);
    showToast("No se pudo mostrar el archivo", "Haluro no pudo abrir el gestor de archivos.");
  }
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

  const hasAction = Boolean(actionLabel && typeof actionCallback === "function");
  container.appendChild(toast);
  setTimeout(() => {
    if (toast.parentNode) toast.remove();
  }, hasAction ? 8500 : 5500);
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
  setModalOpen("aboutModal", false);
  setModalOpen(modal, true);
}

function closeUpdateModal() {
  setModalOpen("updateModal", false);
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
