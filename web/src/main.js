/**
 * DCaaS Server Onboarding PWA — main application logic.
 *
 * The UI is a mobile-first, field-ops flow: scan → location → review →
 * register. Reference data (sites, racks, device types, roles, tenants) is
 * pulled from the backend and rendered as chip rows for touch targets.
 */

import {
  registerServer,
  importServers,
  listServers,
  getSites,
  getLocations,
  getRacks,
  getDeviceTypes,
  getDeviceRoles,
  getPrefixes,
  getTenants,
} from "./services/api.js";
import { startScanner, formatMac } from "./services/scanner.js";

// ── State ──────────────────────────────────────────────────────────────
const state = {
  mac: "",
  password: "",
  site: "",
  location: "",
  rack: "",
  position: null,
  deviceType: "",
  deviceRole: "",
  bmcPrefix: "",
  tenant: "",
};

const cache = {
  sites: [],
  locations: [],
  racks: [],
  deviceTypes: [],
  deviceRoles: [],
  tenants: [],
};

const remembered = {
  site: localStorage.getItem("last_site") || "",
  location: localStorage.getItem("last_location") || "",
  rack: localStorage.getItem("last_rack") || "",
  tenant: localStorage.getItem("last_tenant") || "",
};

let activeScanner = null;
let scanTarget = null;
let locationDataLoaded = false;

// ── DOM refs ───────────────────────────────────────────────────────────
const $ = (sel) => document.querySelector(sel);

const screens = {
  login: $("#login-screen"),
  scan: $("#step-scan"),
  location: $("#step-location"),
  review: $("#step-review"),
  import: $("#panel-import"),
  servers: $("#panel-servers"),
};

const appHeader = $("#app-header");
const appMain = $("#app-main");
const tabbar = $("#tabbar");

// ── Navigation ─────────────────────────────────────────────────────────
function showStep(name) {
  Object.values(screens).forEach((el) => el.classList.remove("active"));
  screens[name].classList.add("active");

  const isLogin = name === "login";
  appHeader.classList.toggle("hidden", isLogin);
  appMain.classList.toggle("hidden", isLogin);
  tabbar.classList.toggle("hidden", isLogin);

  const flowSteps = new Set(["scan", "location", "review"]);
  setActiveTab(flowSteps.has(name) ? "scan" : name);
}

function setActiveTab(key) {
  document.querySelectorAll(".tabbar .tab").forEach((t) => t.classList.remove("on"));
  const active = document.getElementById(`tab-${key}`);
  if (active) active.classList.add("on");
}

// ── Active-location strip ─────────────────────────────────────────────
const locCtx = $("#loc-ctx");
const locCtxSite = $("#loc-ctx-site");
const locCtxRack = $("#loc-ctx-rack");

function updateLocationStrip() {
  const siteName = cache.sites.find((s) => s.slug === state.site)?.name;
  const site = siteName || state.site;
  if (state.site || state.rack) {
    locCtx.classList.remove("hidden");
    locCtxSite.textContent = site || "—";
    locCtxRack.textContent = state.rack || "—";
  } else {
    locCtx.classList.add("hidden");
  }
}

$("#loc-ctx-edit").addEventListener("click", () => {
  ensureLocationLoaded();
  showStep("location");
});

// ── Scan fields ────────────────────────────────────────────────────────
const macInput = $("#mac-input");
const passwordInput = $("#password-input");
const macField = $("#mac-field");
const passwordField = $("#password-field");
const cameraContainer = $("#camera-container");
const cameraPreview = $("#camera-preview");

function updateScanNextButton() {
  $("#next-to-location").disabled = !(state.mac && state.password);
}

function setScanFieldDone(field, done) {
  field.classList.toggle("done", done);
}

function resetScanFields() {
  state.mac = "";
  state.password = "";
  state.position = null;
  macInput.value = "";
  setScanFieldDone(macField, false);
  $("#clear-mac").classList.add("hidden");
  passwordInput.value = "";
  setScanFieldDone(passwordField, false);
  $("#clear-password").classList.add("hidden");
  if (positionInput) positionInput.value = "";
  updateScanNextButton();
}

function handleScanResult(result) {
  if (scanTarget && scanTarget !== result.type) return;

  if (result.type === "mac") {
    state.mac = result.value;
    macInput.value = formatMac(result.value);
    setScanFieldDone(macField, true);
    $("#clear-mac").classList.remove("hidden");
  } else {
    state.password = result.value;
    passwordInput.value = result.value;
    setScanFieldDone(passwordField, true);
    $("#clear-password").classList.remove("hidden");
  }
  stopCamera();
  updateScanNextButton();
}

function openCamera(target) {
  scanTarget = target;
  cameraContainer.classList.remove("hidden");
  activeScanner = startScanner(cameraPreview, handleScanResult);
}

function stopCamera() {
  if (activeScanner) {
    activeScanner.stop();
    activeScanner = null;
  }
  cameraContainer.classList.add("hidden");
}

function dismissBanner() {
  $("#success-banner").classList.add("hidden");
}

macInput.addEventListener("input", () => {
  dismissBanner();
  const cleaned = macInput.value.replace(/[:\- ]/g, "");
  if (/^[0-9A-Fa-f]{12}$/.test(cleaned)) {
    state.mac = cleaned.toUpperCase();
    setScanFieldDone(macField, true);
    $("#clear-mac").classList.remove("hidden");
  } else {
    state.mac = "";
    setScanFieldDone(macField, false);
  }
  updateScanNextButton();
});

passwordInput.addEventListener("input", () => {
  dismissBanner();
  state.password = passwordInput.value;
  if (state.password) {
    setScanFieldDone(passwordField, true);
    $("#clear-password").classList.remove("hidden");
  } else {
    setScanFieldDone(passwordField, false);
  }
  updateScanNextButton();
});

$("#scan-mac").addEventListener("click", () => openCamera("mac"));
$("#scan-password").addEventListener("click", () => openCamera("password"));
$("#cancel-scan").addEventListener("click", stopCamera);

$("#clear-mac").addEventListener("click", () => {
  state.mac = "";
  macInput.value = "";
  setScanFieldDone(macField, false);
  $("#clear-mac").classList.add("hidden");
  updateScanNextButton();
});

$("#clear-password").addEventListener("click", () => {
  state.password = "";
  passwordInput.value = "";
  setScanFieldDone(passwordField, false);
  $("#clear-password").classList.add("hidden");
  updateScanNextButton();
});

$("#toggle-password").addEventListener("click", () => {
  passwordInput.type = passwordInput.type === "password" ? "text" : "password";
});

// ── Location: chip helpers ─────────────────────────────────────────────
function renderChips(container, items, { selected, onPick, labelFor, keyFor }) {
  container.innerHTML = "";
  if (!items.length) {
    const span = document.createElement("span");
    span.className = "chip-empty";
    span.textContent = container.dataset.emptyLabel || "No options";
    container.appendChild(span);
    return;
  }
  for (const item of items) {
    const key = keyFor(item);
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "chip" + (key === selected ? " on" : "");
    btn.textContent = labelFor(item);
    btn.dataset.value = key;
    btn.addEventListener("click", () => onPick(key, item));
    container.appendChild(btn);
  }
}

// ── Location: selectors ────────────────────────────────────────────────
const siteChips = $("#site-chips");
const locationSelect = $("#location-select");
const rackChips = $("#rack-chips");
const positionInput = $("#position-input");
const deviceTypeChips = $("#device-type-chips");
const deviceRoleChips = $("#device-role-chips");
const prefixSelect = $("#prefix-select");
const tenantSelect = $("#tenant-select");

rackChips.dataset.emptyLabel = "Pick a location first";
siteChips.dataset.emptyLabel = "Loading datacenters…";
deviceTypeChips.dataset.emptyLabel = "Loading…";
deviceRoleChips.dataset.emptyLabel = "Loading…";

function updateLocationNextButton() {
  const ready =
    state.site &&
    state.location &&
    state.rack &&
    state.position &&
    state.deviceType &&
    state.deviceRole &&
    state.bmcPrefix &&
    state.tenant;
  $("#next-to-review").disabled = !ready;
}

async function loadSites() {
  try {
    cache.sites = await getSites();
    renderSiteChips();
    if (remembered.site && cache.sites.some((s) => s.slug === remembered.site)) {
      await pickSite(remembered.site, { silent: true });
    }
  } catch (err) {
    console.error("Failed to load sites:", err);
    siteChips.innerHTML = `<span class="chip-empty">Failed to load datacenters</span>`;
  }
}

function renderSiteChips() {
  renderChips(siteChips, cache.sites, {
    selected: state.site,
    keyFor: (s) => s.slug,
    labelFor: (s) => s.name,
    onPick: (slug) => pickSite(slug),
  });
}

async function pickSite(slug, opts = {}) {
  state.site = slug;
  state.location = "";
  state.rack = "";
  state.position = null;
  locationSelect.innerHTML = '<option value="">Select location...</option>';
  locationSelect.disabled = true;
  renderSiteChips();
  rackChips.dataset.emptyLabel = "Pick a location first";
  renderRackChips();
  if (positionInput) positionInput.value = "";
  localStorage.setItem("last_site", slug);
  remembered.site = slug;
  updateLocationStrip();
  await loadLocations(slug, opts);
  updateLocationNextButton();
}

async function loadLocations(site, opts = {}) {
  try {
    const locations = await getLocations(site);
    cache.locations = locations;
    locationSelect.innerHTML = '<option value="">Select location...</option>';
    for (const l of locations) {
      const opt = document.createElement("option");
      opt.value = l.slug;
      opt.textContent = l.name;
      locationSelect.appendChild(opt);
    }
    locationSelect.disabled = false;
    if (opts.silent && remembered.location &&
        locations.some((l) => l.slug === remembered.location)) {
      locationSelect.value = remembered.location;
      await pickLocation(remembered.location, { silent: true });
    }
  } catch (err) {
    console.error("Failed to load locations:", err);
  }
}

async function pickLocation(slug, opts = {}) {
  state.location = slug;
  state.rack = "";
  state.position = null;
  localStorage.setItem("last_location", slug);
  remembered.location = slug;
  updateLocationStrip();
  if (slug) await loadRacks(slug, opts);
  updateLocationNextButton();
}

async function loadRacks(location, opts = {}) {
  try {
    cache.racks = await getRacks(location);
    rackChips.dataset.emptyLabel = cache.racks.length ? "" : "No racks in this location";
    renderRackChips();
    if (opts.silent && remembered.rack &&
        cache.racks.some((r) => r.name === remembered.rack)) {
      pickRack(remembered.rack);
    }
  } catch (err) {
    console.error("Failed to load racks:", err);
  }
}

function renderRackChips() {
  renderChips(rackChips, cache.racks, {
    selected: state.rack,
    keyFor: (r) => r.name,
    labelFor: (r) => r.name,
    onPick: (name) => pickRack(name),
  });
}

function pickRack(name) {
  state.rack = name;
  state.position = null;
  if (positionInput) positionInput.value = "";
  localStorage.setItem("last_rack", name);
  remembered.rack = name;
  renderRackChips();
  updateLocationStrip();
  updateLocationNextButton();
}

function pickDeviceType(slug) {
  state.deviceType = slug;
  renderChips(deviceTypeChips, cache.deviceTypes, {
    selected: slug,
    keyFor: (t) => t.slug,
    labelFor: (t) => `${t.manufacturer} ${t.model}`,
    onPick: pickDeviceType,
  });
  updateLocationNextButton();
}

function pickDeviceRole(slug) {
  state.deviceRole = slug;
  renderChips(deviceRoleChips, cache.deviceRoles, {
    selected: slug,
    keyFor: (r) => r.slug,
    labelFor: (r) => r.name,
    onPick: pickDeviceRole,
  });
  updateLocationNextButton();
}

async function loadDeviceTypesChips() {
  try {
    cache.deviceTypes = await getDeviceTypes();
    renderChips(deviceTypeChips, cache.deviceTypes, {
      selected: state.deviceType,
      keyFor: (t) => t.slug,
      labelFor: (t) => `${t.manufacturer} ${t.model}`,
      onPick: pickDeviceType,
    });
  } catch (err) {
    console.error("Failed to load device types:", err);
    deviceTypeChips.innerHTML = `<span class="chip-empty">Failed to load device types</span>`;
  }
}

async function loadDeviceRolesChips() {
  try {
    cache.deviceRoles = await getDeviceRoles();
    renderChips(deviceRoleChips, cache.deviceRoles, {
      selected: state.deviceRole,
      keyFor: (r) => r.slug,
      labelFor: (r) => r.name,
      onPick: pickDeviceRole,
    });
  } catch (err) {
    console.error("Failed to load device roles:", err);
    deviceRoleChips.innerHTML = `<span class="chip-empty">Failed to load roles</span>`;
  }
}

async function loadPrefixes() {
  try {
    const prefixes = await getPrefixes();
    prefixSelect.innerHTML = '<option value="">Select BMC prefix...</option>';
    for (const p of prefixes) {
      const opt = document.createElement("option");
      opt.value = p.prefix;
      opt.textContent = `${p.prefix} — ${p.description}`;
      prefixSelect.appendChild(opt);
    }
  } catch (err) {
    console.error("Failed to load prefixes:", err);
  }
}

async function loadTenants() {
  try {
    cache.tenants = await getTenants();
    tenantSelect.innerHTML = '<option value="">Select tenant...</option>';
    for (const t of cache.tenants) {
      const opt = document.createElement("option");
      opt.value = t.slug;
      opt.textContent = t.name;
      tenantSelect.appendChild(opt);
    }
    if (remembered.tenant && cache.tenants.some((t) => t.slug === remembered.tenant)) {
      tenantSelect.value = remembered.tenant;
      state.tenant = remembered.tenant;
    }
  } catch (err) {
    console.error("Failed to load tenants:", err);
  }
}

async function ensureLocationLoaded() {
  if (locationDataLoaded) return;
  locationDataLoaded = true;
  await Promise.all([
    loadSites(),
    loadDeviceTypesChips(),
    loadDeviceRolesChips(),
    loadPrefixes(),
    loadTenants(),
  ]);
  updateLocationNextButton();
}

locationSelect.addEventListener("change", async () => {
  const slug = locationSelect.value;
  await pickLocation(slug);
});

positionInput.addEventListener("input", () => {
  state.position = positionInput.value ? parseInt(positionInput.value, 10) : null;
  updateLocationStrip();
  updateLocationNextButton();
});

prefixSelect.addEventListener("change", () => {
  state.bmcPrefix = prefixSelect.value;
  updateLocationNextButton();
});

tenantSelect.addEventListener("change", () => {
  state.tenant = tenantSelect.value;
  if (state.tenant) {
    localStorage.setItem("last_tenant", state.tenant);
    remembered.tenant = state.tenant;
  }
  updateLocationNextButton();
});

// ── Step 3: Review & Submit ────────────────────────────────────────────
function buildReview() {
  const dl = $("#review-summary");
  const siteName = cache.sites.find((s) => s.slug === state.site)?.name || state.site;
  const locName = cache.locations.find((l) => l.slug === state.location)?.name || state.location;
  const dtype = cache.deviceTypes.find((t) => t.slug === state.deviceType);
  const role = cache.deviceRoles.find((r) => r.slug === state.deviceRole);
  const deviceName =
    state.site && state.rack && state.position
      ? `${state.location || state.site}-${state.rack.toLowerCase()}u${String(state.position).padStart(2, "0")}`
      : "—";

  const rows = [
    { k: "Device name", v: deviceName, derived: true },
    { k: "BMC MAC", v: formatMac(state.mac) },
    { k: "BMC Password", v: "\u2022".repeat(Math.min(state.password.length, 12)) },
    { k: "Location", v: `${siteName} · ${locName}` },
    { k: "Rack · U", v: `${state.rack} · U${state.position}` },
    { k: "Device", v: `${dtype ? dtype.manufacturer + " " + dtype.model : ""} · ${role ? role.name : ""}` },
    { k: "BMC Prefix", v: state.bmcPrefix },
    { k: "Tenant", v: state.tenant, derived: true },
  ];

  dl.innerHTML = rows
    .map(
      (r) =>
        `<div class="review-row"><dt>${r.k}</dt><dd class="${r.derived ? "derived" : ""}">${r.v || "—"}</dd></div>`
    )
    .join("");
}

const WORKFLOW_STEPS = [
  { key: "netbox_device_created", label: "Create device", target: "Netbox" },
  { key: "netbox_interface_created", label: "Create BMC interface", target: "Netbox" },
  { key: "secret_stored", label: "Store credentials", target: "OpenBao" },
  { key: "bmc_ip_assigned", label: "Assign BMC IP", target: "Kea DHCP" },
  { key: "ironic_node_created", label: "Create BareMetalHost", target: "Metal3" },
];

function renderStepList(stepList, statuses) {
  stepList.innerHTML = WORKFLOW_STEPS.map((s) => {
    const st = statuses[s.key] || "pending";
    const dotContent =
      st === "done"
        ? '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M5 13l4 4L19 7"/></svg>'
        : st === "fail"
        ? '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 6l12 12M6 18L18 6"/></svg>'
        : "";
    return `<li class="${st}" data-key="${s.key}">
      <span class="dot">${dotContent}</span>
      <span class="lbl">${s.label}</span>
      <span class="target">${s.target}</span>
    </li>`;
  }).join("");
}

async function submitRegistration() {
  const submitBtn = $("#submit-register");
  const progress = $("#submit-progress");
  const progressFill = $("#progress-fill");
  const stepList = $("#step-list");
  const resultDiv = $("#submit-result");

  submitBtn.disabled = true;
  resultDiv.classList.add("hidden");
  progress.classList.remove("hidden");

  const statuses = Object.fromEntries(WORKFLOW_STEPS.map((s) => [s.key, "pending"]));
  renderStepList(stepList, statuses);

  try {
    const result = await registerServer({
      bmc_mac: state.mac,
      bmc_password: state.password,
      site: state.site,
      location: state.location,
      rack: state.rack,
      position: state.position,
      device_type: state.deviceType,
      device_role: state.deviceRole,
      bmc_prefix: state.bmcPrefix,
      tenant: state.tenant,
    });

    let completed = 0;
    for (const s of WORKFLOW_STEPS) {
      statuses[s.key] = result.steps[s.key] ? "done" : "fail";
      if (result.steps[s.key]) completed++;
    }
    renderStepList(stepList, statuses);
    progressFill.style.width = `${(completed / WORKFLOW_STEPS.length) * 100}%`;

    resetScanFields();
    const banner = $("#success-banner");
    banner.innerHTML = `
      <div>&#x2714; Registered <code>${result.device_name}</code></div>
      <div class="banner-details">
        BMC IP ${result.bmc_ip || "N/A"} · Netbox #${result.netbox_id || "N/A"}
      </div>
    `;
    banner.classList.remove("hidden");
    showStep("scan");
  } catch (err) {
    resultDiv.classList.remove("hidden");
    resultDiv.className = "result-error";
    resultDiv.innerHTML = `<strong>Registration failed</strong>${err.message}`;
    progressFill.style.width = "100%";
    progressFill.style.background = "var(--err)";
  } finally {
    submitBtn.disabled = false;
  }
}

// ── Server list ────────────────────────────────────────────────────────
let allServers = [];

const filterSite = $("#filter-site");
const filterLocation = $("#filter-location");
const filterDeviceType = $("#filter-device-type");
const filterDeviceRole = $("#filter-device-role");

function populateFilterOptions() {
  const uniq = (key) => [...new Set(allServers.map((s) => s[key]).filter(Boolean))].sort();
  const sites = uniq("site");
  const locations = uniq("location");
  const types = uniq("device_type");
  const roles = uniq("device_role");

  filterSite.innerHTML =
    '<option value="">All datacenters</option>' +
    sites.map((v) => `<option value="${v}">${v}</option>`).join("");
  filterLocation.innerHTML =
    '<option value="">All locations</option>' +
    locations.map((v) => `<option value="${v}">${v}</option>`).join("");
  filterDeviceType.innerHTML =
    '<option value="">All types</option>' +
    types.map((v) => `<option value="${v}">${v}</option>`).join("");

  const currentRole = filterDeviceRole.value;
  filterDeviceRole.innerHTML =
    '<option value="">All roles</option>' +
    roles.map((v) => `<option value="${v}">${v}</option>`).join("");
  if (!currentRole && roles.includes("Physical server")) {
    filterDeviceRole.value = "Physical server";
  } else {
    filterDeviceRole.value = currentRole;
  }
}

function renderServerList() {
  const container = $("#server-list");
  const countEl = $("#server-count");
  const sf = filterSite.value;
  const lf = filterLocation.value;
  const tf = filterDeviceType.value;
  const rf = filterDeviceRole.value;

  const filtered = allServers.filter(
    (s) =>
      (!sf || s.site === sf) &&
      (!lf || s.location === lf) &&
      (!tf || s.device_type === tf) &&
      (!rf || s.device_role === rf)
  );

  countEl.textContent = `${filtered.length} of ${allServers.length} servers`;

  if (filtered.length === 0) {
    container.innerHTML = '<p class="empty-state">No servers match the selected filters.</p>';
    return;
  }
  container.innerHTML = filtered
    .map((s) => {
      const parts = [];
      if (s.rack || s.position) parts.push(`<span class="dim">rack</span> ${s.rack || "?"}·U${s.position || "?"}`);
      if (s.device_role) parts.push(`<span class="dim">role</span> ${s.device_role}`);
      if (s.bmc_ip) parts.push(`<span class="dim">ip</span> ${s.bmc_ip}`);
      if (s.created) parts.push(`<span class="dim">added</span> ${new Date(s.created).toLocaleDateString()}`);
      return `
      <div class="server-card">
        <h3>${s.name}</h3>
        <span class="status-badge ${s.status}">${s.status}</span>
        <p class="meta">${parts.join(" · ")}</p>
      </div>`;
    })
    .join("");
}

filterSite.addEventListener("change", renderServerList);
filterLocation.addEventListener("change", renderServerList);
filterDeviceType.addEventListener("change", renderServerList);
filterDeviceRole.addEventListener("change", renderServerList);

async function loadServerList() {
  const container = $("#server-list");
  try {
    allServers = await listServers();
    populateFilterOptions();
    renderServerList();
  } catch (err) {
    container.innerHTML = `<p class="empty-state">Failed to load servers: ${err.message}</p>`;
  }
}

// ── Bulk Import ─────────────────────────────────────────────────────────
let importData = null;

const importFileInput = $("#import-file");
const importFileName = $("#import-file-name");
const importPreview = $("#import-preview");
const importCount = $("#import-count");
const importTableBody = $("#import-table-body");
const importSubmitBtn = $("#import-submit");
const importProgress = $("#import-progress");
const importProgressFill = $("#import-progress-fill");
const importProgressText = $("#import-progress-text");
const importResults = $("#import-results");

function resetImportPanel() {
  importData = null;
  importFileInput.value = "";
  importFileName.textContent = "No file selected";
  importPreview.classList.add("hidden");
  importProgress.classList.add("hidden");
  importResults.classList.add("hidden");
  importResults.innerHTML = "";
}

function formatMacForDisplay(mac) {
  const clean = mac.replace(/[:\- ]/g, "").toUpperCase();
  return clean.replace(/(.{2})(?=.)/g, "$1:");
}

importFileInput.addEventListener("change", () => {
  const file = importFileInput.files[0];
  if (!file) return;

  importFileName.textContent = file.name;
  importResults.classList.add("hidden");
  importProgress.classList.add("hidden");

  const reader = new FileReader();
  reader.onload = (e) => {
    try {
      const parsed = JSON.parse(e.target.result);
      if (!Array.isArray(parsed) || parsed.length === 0) {
        throw new Error("File must contain a non-empty JSON array");
      }
      for (const [i, item] of parsed.entries()) {
        if (!item.device_name || !item.bmc_mac || !item.bmc_password) {
          throw new Error(
            `Item ${i + 1} missing required fields (device_name, bmc_mac, bmc_password)`
          );
        }
      }
      importData = parsed;
      importCount.textContent = `${parsed.length} server${parsed.length !== 1 ? "s" : ""} to import`;
      importTableBody.innerHTML = parsed
        .map((s) => {
          const hasNetbox =
            s.site && s.location && s.rack && s.position != null && s.device_type && s.device_role;
          return `<tr>
            <td>${s.device_name}</td>
            <td><code>${formatMacForDisplay(s.bmc_mac)}</code></td>
            <td>${s.bmc_ip || (s.bmc_prefix ? "allocate" : "\u2014")}</td>
            <td>${hasNetbox ? "yes" : "skip"}</td>
          </tr>`;
        })
        .join("");
      importPreview.classList.remove("hidden");
    } catch (err) {
      importData = null;
      importPreview.classList.add("hidden");
      importResults.classList.remove("hidden");
      importResults.className = "result-error";
      importResults.innerHTML = `<strong>Invalid file</strong>${err.message}`;
    }
  };
  reader.readAsText(file);
});

function renderImportResult(r) {
  const isOk = r.status === "ok";
  const cssClass = isOk ? "import-result-ok" : "import-result-fail";
  const icon = isOk ? "\u2714" : "\u2718";

  const stepLabels = [
    ["netbox_device_created", "NB"],
    ["netbox_interface_created", "IF"],
    ["secret_stored", "OB"],
    ["bmc_ip_assigned", "KE"],
    ["ironic_node_created", "M3"],
  ];
  const stepBadges = stepLabels
    .map(([key, label]) => {
      const done = r.steps[key];
      return `<span class="step-badge ${done ? "done" : "skip"}">${label}</span>`;
    })
    .join(" ");

  const warningHtml = r.warnings?.length
    ? `<div class="result-warnings">${r.warnings.join("<br/>")}</div>`
    : "";
  const errorHtml = r.error ? `<div class="result-error-text">${r.error}</div>` : "";

  return `<div class="${cssClass}">
    <strong>${icon} ${r.device_name}</strong>
    ${r.bmc_ip ? ` &mdash; ${r.bmc_ip}` : ""}
    <div class="step-badges">${stepBadges}</div>
    ${warningHtml}${errorHtml}
  </div>`;
}

function importShowDone(ok, failed) {
  importProgressFill.style.width = "100%";
  if (failed > 0) importProgressFill.style.background = "var(--warn)";
  importProgressText.textContent = `Done · ${ok} succeeded, ${failed} failed`;
  importSubmitBtn.disabled = false;
}

function importShowError(message) {
  importProgressFill.style.width = "100%";
  importProgressFill.style.background = "var(--err)";
  importProgressText.textContent = "";
  importResults.className = "result-error";
  importResults.innerHTML = `<strong>Import failed</strong>${message}`;
  importSubmitBtn.disabled = false;
}

function importViaWebSocket(data) {
  const total = data.length;
  let received = 0;
  let ok = 0;
  let failed = 0;

  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${proto}//${location.host}/api/v1/servers/import/ws`);

  ws.onopen = () => ws.send(JSON.stringify(data));

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);

    if (msg.done) {
      importShowDone(ok, failed);
      return;
    }

    if (msg.error && !msg.device_name) {
      importShowError(msg.error);
      return;
    }

    received++;
    if (msg.status === "ok") ok++;
    else failed++;

    importProgressFill.style.width = `${(received / total) * 100}%`;
    importProgressText.textContent = `${received} / ${total} · ${ok} ok, ${failed} failed`;
    importResults.insertAdjacentHTML("beforeend", renderImportResult(msg));
  };

  ws.onerror = () => {
    if (received > 0) {
      importShowError("WebSocket connection lost");
      return;
    }
    console.warn("WebSocket failed, falling back to REST import");
    importViaREST(data);
  };

  ws.onclose = () => {
    importSubmitBtn.disabled = false;
  };
}

async function importViaREST(data) {
  const total = data.length;
  try {
    const results = await importServers(data);
    let ok = 0;
    let failed = 0;
    results.forEach((r, i) => {
      if (r.status === "ok") ok++;
      else failed++;
      importProgressFill.style.width = `${((i + 1) / total) * 100}%`;
      importProgressText.textContent = `${i + 1} / ${total} · ${ok} ok, ${failed} failed`;
      importResults.insertAdjacentHTML("beforeend", renderImportResult(r));
    });
    importShowDone(ok, failed);
  } catch (err) {
    importShowError(err.message);
  }
}

importSubmitBtn.addEventListener("click", () => {
  if (!importData) return;

  importSubmitBtn.disabled = true;
  importProgress.classList.remove("hidden");
  importResults.classList.remove("hidden");
  importResults.className = "";
  importResults.innerHTML = "";
  importProgressFill.style.width = "0%";
  importProgressFill.style.background = "";
  importProgressText.textContent = `Importing ${importData.length} servers…`;

  importViaWebSocket(importData);
});

// ── Navigation wiring ──────────────────────────────────────────────────
$("#next-to-location").addEventListener("click", () => {
  showStep("location");
  ensureLocationLoaded();
});

$("#back-to-scan").addEventListener("click", () => showStep("scan"));

$("#next-to-review").addEventListener("click", () => {
  buildReview();
  $("#submit-progress").classList.add("hidden");
  $("#submit-result").classList.add("hidden");
  $("#submit-register").disabled = false;
  showStep("review");
});

$("#back-to-location").addEventListener("click", () => showStep("location"));

$("#submit-register").addEventListener("click", submitRegistration);

// Tab bar
$("#tab-scan").addEventListener("click", () => showStep("scan"));
$("#tab-servers").addEventListener("click", () => {
  loadServerList();
  showStep("servers");
});
$("#tab-import").addEventListener("click", () => {
  resetImportPanel();
  showStep("import");
});

// ── Auth ────────────────────────────────────────────────────────────────
const userNameEl = $("#user-name");
const logoutBtn = $("#logout-btn");

logoutBtn.addEventListener("click", async () => {
  await fetch("/auth/logout", { method: "POST" });
  window.location.reload();
});

async function checkAuth() {
  try {
    const resp = await fetch("/auth/userinfo");
    if (resp.ok) {
      const user = await resp.json();
      userNameEl.textContent = user.name || user.sub || "";
      userNameEl.classList.remove("hidden");
      logoutBtn.classList.remove("hidden");
      updateLocationStrip();
      showStep("scan");
      return;
    }
  } catch {
    // network error — fall through to login screen
  }
  showStep("login");
}

checkAuth();
