/**
 * DCaaS Server Onboarding PWA — main application logic.
 */

import {
  registerServer,
  listServers,
  getSites,
  getLocations,
  getRacks,
  getDeviceTypes,
  getDeviceRoles,
  getPrefixes,
  getTenants,
} from "./services/api.js";
import { startScanner, classifyBarcode, formatMac } from "./services/scanner.js";

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
  ipmiPrefix: "",
  tenant: "",
};

// Remember last-used location across scans
const remembered = {
  site: localStorage.getItem("last_site") || "",
  location: localStorage.getItem("last_location") || "",
  rack: localStorage.getItem("last_rack") || "",
  tenant: localStorage.getItem("last_tenant") || "",
};

let activeScanner = null;
let scanTarget = null; // "mac" | "password"

// ── DOM refs ───────────────────────────────────────────────────────────
const $ = (sel) => document.querySelector(sel);
const steps = {
  login: $("#login-screen"),
  scan: $("#step-scan"),
  location: $("#step-location"),
  review: $("#step-review"),
  import: $("#panel-import"),
  servers: $("#panel-servers"),
};

// ── Navigation ─────────────────────────────────────────────────────────
function showStep(name) {
  Object.values(steps).forEach((el) => el.classList.remove("active"));
  steps[name].classList.add("active");
}

// ── Step 1: Scanning ───────────────────────────────────────────────────
const macInput = $("#mac-input");
const passwordInput = $("#password-input");
const cameraContainer = $("#camera-container");
const cameraPreview = $("#camera-preview");

function updateScanNextButton() {
  $("#next-to-location").disabled = !(state.mac && state.password);
}

function resetScanFields() {
  state.mac = "";
  state.password = "";
  state.position = null;
  macInput.value = "";
  macInput.classList.remove("valid");
  $("#clear-mac").classList.add("hidden");
  passwordInput.value = "";
  passwordInput.classList.remove("valid");
  $("#clear-password").classList.add("hidden");
  positionInput.value = "";
  updateScanNextButton();
}

function handleScanResult(result) {
  // When the user chose a specific field, only accept barcodes that match.
  // This handles the case where both barcodes are visible in the camera —
  // keep scanning until the right one is decoded.
  if (scanTarget && scanTarget !== result.type) {
    return; // wrong barcode, keep scanning
  }

  if (result.type === "mac") {
    state.mac = result.value;
    macInput.value = formatMac(result.value);
    macInput.classList.add("valid");
    $("#clear-mac").classList.remove("hidden");
  } else {
    state.password = result.value;
    passwordInput.value = result.value;
    passwordInput.classList.add("valid");
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

// Manual input handlers
macInput.addEventListener("input", () => {
  dismissBanner();
  const cleaned = macInput.value.replace(/[:\- ]/g, "");
  if (/^[0-9A-Fa-f]{12}$/.test(cleaned)) {
    state.mac = cleaned.toUpperCase();
    macInput.classList.add("valid");
    $("#clear-mac").classList.remove("hidden");
  } else {
    state.mac = "";
    macInput.classList.remove("valid");
  }
  updateScanNextButton();
});

passwordInput.addEventListener("input", () => {
  dismissBanner();
  state.password = passwordInput.value;
  if (state.password) {
    passwordInput.classList.add("valid");
    $("#clear-password").classList.remove("hidden");
  } else {
    passwordInput.classList.remove("valid");
  }
  updateScanNextButton();
});

// Button handlers
$("#scan-mac").addEventListener("click", () => openCamera("mac"));
$("#scan-password").addEventListener("click", () => openCamera("password"));
$("#cancel-scan").addEventListener("click", stopCamera);

$("#clear-mac").addEventListener("click", () => {
  state.mac = "";
  macInput.value = "";
  macInput.classList.remove("valid");
  $("#clear-mac").classList.add("hidden");
  updateScanNextButton();
});

$("#clear-password").addEventListener("click", () => {
  state.password = "";
  passwordInput.value = "";
  passwordInput.classList.remove("valid");
  $("#clear-password").classList.add("hidden");
  updateScanNextButton();
});

$("#toggle-password").addEventListener("click", () => {
  passwordInput.type = passwordInput.type === "password" ? "text" : "password";
});

// ── Step 2: Location ───────────────────────────────────────────────────
const siteSelect = $("#site-select");
const locationSelect = $("#location-select");
const rackSelect = $("#rack-select");
const positionInput = $("#position-input");
const deviceTypeSelect = $("#device-type-select");
const deviceRoleSelect = $("#device-role-select");
const prefixSelect = $("#prefix-select");
const tenantSelect = $("#tenant-select");

function updateLocationNextButton() {
  const ready =
    state.site &&
    state.location &&
    state.rack &&
    state.position &&
    state.deviceType &&
    state.deviceRole &&
    state.ipmiPrefix &&
    state.tenant;
  $("#next-to-review").disabled = !ready;
}

async function loadSites() {
  try {
    const sites = await getSites();
    siteSelect.innerHTML = '<option value="">Select datacenter...</option>';
    sites.forEach((s) => {
      const opt = document.createElement("option");
      opt.value = s.slug;
      opt.textContent = `${s.name} (${s.slug})`;
      siteSelect.appendChild(opt);
    });

    if (remembered.site) {
      siteSelect.value = remembered.site;
      if (siteSelect.value) {
        state.site = remembered.site;
        await loadLocations(remembered.site);
      }
    }
  } catch (err) {
    console.error("Failed to load sites:", err);
  }
}

async function loadLocations(site) {
  try {
    const locations = await getLocations(site);
    locationSelect.innerHTML = '<option value="">Select location...</option>';
    locations.forEach((l) => {
      const opt = document.createElement("option");
      opt.value = l.slug;
      opt.textContent = l.name;
      locationSelect.appendChild(opt);
    });
    locationSelect.disabled = false;

    if (remembered.location) {
      locationSelect.value = remembered.location;
      if (locationSelect.value) {
        state.location = remembered.location;
        await loadRacks(remembered.location);
      }
    }
  } catch (err) {
    console.error("Failed to load locations:", err);
  }
}

async function loadRacks(location) {
  try {
    const racks = await getRacks(location);
    rackSelect.innerHTML = '<option value="">Select rack...</option>';
    racks.forEach((r) => {
      const opt = document.createElement("option");
      opt.value = r.name;
      opt.textContent = r.name;
      rackSelect.appendChild(opt);
    });
    rackSelect.disabled = false;

    if (remembered.rack) {
      rackSelect.value = remembered.rack;
      if (rackSelect.value) {
        state.rack = remembered.rack;
      }
    }
  } catch (err) {
    console.error("Failed to load racks:", err);
  }
}

async function loadDeviceTypes() {
  try {
    const types = await getDeviceTypes();
    deviceTypeSelect.innerHTML =
      '<option value="">Select device type...</option>';
    types.forEach((t) => {
      const opt = document.createElement("option");
      opt.value = t.slug;
      opt.textContent = `${t.manufacturer} ${t.model}`;
      deviceTypeSelect.appendChild(opt);
    });
  } catch (err) {
    console.error("Failed to load device types:", err);
  }
}

async function loadDeviceRoles() {
  try {
    const roles = await getDeviceRoles();
    deviceRoleSelect.innerHTML =
      '<option value="">Select device role...</option>';
    roles.forEach((r) => {
      const opt = document.createElement("option");
      opt.value = r.slug;
      opt.textContent = r.name;
      deviceRoleSelect.appendChild(opt);
    });
  } catch (err) {
    console.error("Failed to load device roles:", err);
  }
}

async function loadPrefixes() {
  try {
    const prefixes = await getPrefixes();
    prefixSelect.innerHTML = '<option value="">Select IPMI prefix...</option>';
    prefixes.forEach((p) => {
      const opt = document.createElement("option");
      opt.value = p.prefix;
      opt.textContent = `${p.prefix} — ${p.description}`;
      prefixSelect.appendChild(opt);
    });
  } catch (err) {
    console.error("Failed to load prefixes:", err);
  }
}

async function loadTenants() {
  try {
    const tenants = await getTenants();
    tenantSelect.innerHTML = '<option value="">Select tenant...</option>';
    tenants.forEach((t) => {
      const opt = document.createElement("option");
      opt.value = t.slug;
      opt.textContent = t.name;
      tenantSelect.appendChild(opt);
    });

    if (remembered.tenant) {
      tenantSelect.value = remembered.tenant;
      if (tenantSelect.value) {
        state.tenant = remembered.tenant;
      }
    }
  } catch (err) {
    console.error("Failed to load tenants:", err);
  }
}

siteSelect.addEventListener("change", async () => {
  state.site = siteSelect.value;
  state.location = "";
  state.rack = "";
  locationSelect.innerHTML = '<option value="">Select location...</option>';
  locationSelect.disabled = true;
  rackSelect.innerHTML = '<option value="">Select rack...</option>';
  rackSelect.disabled = true;

  if (state.site) {
    localStorage.setItem("last_site", state.site);
    remembered.site = state.site;
    await loadLocations(state.site);
  }
  updateLocationNextButton();
});

locationSelect.addEventListener("change", async () => {
  state.location = locationSelect.value;
  state.rack = "";
  rackSelect.innerHTML = '<option value="">Select rack...</option>';
  rackSelect.disabled = true;

  if (state.location) {
    localStorage.setItem("last_location", state.location);
    remembered.location = state.location;
    await loadRacks(state.location);
  }
  updateLocationNextButton();
});

rackSelect.addEventListener("change", () => {
  state.rack = rackSelect.value;
  if (state.rack) {
    localStorage.setItem("last_rack", state.rack);
    remembered.rack = state.rack;
  }
  updateLocationNextButton();
});

positionInput.addEventListener("input", () => {
  state.position = positionInput.value ? parseInt(positionInput.value, 10) : null;
  updateLocationNextButton();
});

deviceTypeSelect.addEventListener("change", () => {
  state.deviceType = deviceTypeSelect.value;
  updateLocationNextButton();
});

deviceRoleSelect.addEventListener("change", () => {
  state.deviceRole = deviceRoleSelect.value;
  updateLocationNextButton();
});

prefixSelect.addEventListener("change", () => {
  state.ipmiPrefix = prefixSelect.value;
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
  const items = [
    ["BMC MAC", formatMac(state.mac)],
    ["IPMI Password", "\u2022".repeat(state.password.length)],
    ["Datacenter", state.site],
    ["Location", state.location],
    ["Rack", state.rack],
    ["U Position", state.position],
    ["Device Type", state.deviceType],
    ["Device Role", state.deviceRole],
    ["IPMI Prefix", state.ipmiPrefix],
    ["Tenant", state.tenant],
    ["Device Name", `${state.location}-${state.rack.toLowerCase()}u${state.position}`],
  ];

  dl.innerHTML = items
    .map(([label, val]) => `<dt>${label}</dt><dd>${val}</dd>`)
    .join("");
}

const WORKFLOW_STEPS = [
  { key: "netbox_device_created", label: "Create device in Netbox" },
  { key: "netbox_interface_created", label: "Create IPMI interface" },
  { key: "secret_stored", label: "Store credentials in OpenBao" },
  { key: "ipmi_ip_assigned", label: "Assign IPMI IP via Kea DHCP" },
  { key: "ironic_node_created", label: "Create Metal3 BareMetalHost" },
];

async function submitRegistration() {
  const submitBtn = $("#submit-register");
  const progress = $("#submit-progress");
  const progressFill = $("#progress-fill");
  const stepList = $("#step-list");
  const resultDiv = $("#submit-result");

  submitBtn.disabled = true;
  resultDiv.classList.add("hidden");
  progress.classList.remove("hidden");

  // Build step indicators
  stepList.innerHTML = WORKFLOW_STEPS.map(
    (s) => `<li class="pending" data-key="${s.key}">&#x25CB; ${s.label}</li>`
  ).join("");

  try {
    const result = await registerServer({
      bmc_mac: state.mac,
      ipmi_password: state.password,
      site: state.site,
      location: state.location,
      rack: state.rack,
      position: state.position,
      device_type: state.deviceType,
      device_role: state.deviceRole,
      ipmi_prefix: state.ipmiPrefix,
      tenant: state.tenant,
    });

    // Update step indicators from response
    let completed = 0;
    WORKFLOW_STEPS.forEach((s) => {
      const li = stepList.querySelector(`[data-key="${s.key}"]`);
      if (result.steps[s.key]) {
        li.className = "done";
        li.innerHTML = `&#x2714; ${s.label}`;
        completed++;
      } else {
        li.className = "fail";
        li.innerHTML = `&#x2718; ${s.label}`;
      }
    });
    progressFill.style.width = `${(completed / WORKFLOW_STEPS.length) * 100}%`;

    // Success — redirect back to scan with a banner
    resetScanFields();
    const banner = $("#success-banner");
    banner.innerHTML = `
      &#x2714; Registered <code>${result.device_name}</code>
      <div class="banner-details">
        IPMI IP: ${result.ipmi_ip || "N/A"} &middot; Netbox ID: ${result.netbox_id || "N/A"}
      </div>
    `;
    banner.classList.remove("hidden");
    showStep("scan");
    return;
  } catch (err) {
    resultDiv.classList.remove("hidden");
    resultDiv.className = "result-error";
    resultDiv.innerHTML = `<strong>Registration failed</strong><br />${err.message}`;
    progressFill.style.width = "100%";
    progressFill.style.background = "var(--error)";
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
  const sites = [...new Set(allServers.map((s) => s.site).filter(Boolean))].sort();
  const locations = [...new Set(allServers.map((s) => s.location).filter(Boolean))].sort();
  const types = [...new Set(allServers.map((s) => s.device_type).filter(Boolean))].sort();

  filterSite.innerHTML = '<option value="">All datacenters</option>' +
    sites.map((v) => `<option value="${v}">${v}</option>`).join("");
  filterLocation.innerHTML = '<option value="">All locations</option>' +
    locations.map((v) => `<option value="${v}">${v}</option>`).join("");
  filterDeviceType.innerHTML = '<option value="">All device types</option>' +
    types.map((v) => `<option value="${v}">${v}</option>`).join("");

  const roles = [...new Set(allServers.map((s) => s.device_role).filter(Boolean))].sort();
  const currentRole = filterDeviceRole.value;
  filterDeviceRole.innerHTML = '<option value="">All roles</option>' +
    roles.map((v) => `<option value="${v}">${v}</option>`).join("");
  // Default to "Physical server" on first load
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
    (s) => (!sf || s.site === sf) && (!lf || s.location === lf) && (!tf || s.device_type === tf) && (!rf || s.device_role === rf)
  );

  countEl.textContent = `${filtered.length} of ${allServers.length} servers`;

  if (filtered.length === 0) {
    container.innerHTML = '<p class="empty-state">No servers match the selected filters.</p>';
    return;
  }
  container.innerHTML = filtered
    .map(
      (s) => `
    <div class="server-card">
      <h3>${s.name}</h3>
      <span class="status-badge ${s.status}">${s.status}</span>
      <p class="meta">${s.location} / ${s.rack} / U${s.position || "?"}
        &mdash; ${s.device_role}
        &mdash; ${s.created ? new Date(s.created).toLocaleDateString() : ""}</p>
    </div>`
    )
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
      // Validate required fields
      for (const [i, item] of parsed.entries()) {
        if (!item.device_name || !item.bmc_mac || !item.ipmi_password) {
          throw new Error(
            `Item ${i + 1} missing required fields (device_name, bmc_mac, ipmi_password)`
          );
        }
      }
      importData = parsed;
      importCount.textContent = `${parsed.length} server${parsed.length !== 1 ? "s" : ""} to import`;
      importTableBody.innerHTML = parsed
        .map((s) => {
          const hasNetbox = s.site && s.location && s.rack && s.position != null && s.device_type && s.device_role;
          return `<tr>
            <td>${s.device_name}</td>
            <td><code>${formatMacForDisplay(s.bmc_mac)}</code></td>
            <td>${s.ipmi_ip || (s.ipmi_prefix ? "allocate" : "\u2014")}</td>
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
      importResults.innerHTML = `<strong>Invalid file</strong><br />${err.message}`;
    }
  };
  reader.readAsText(file);
});

function renderImportResult(r) {
  const isOk = r.status === "ok";
  const cssClass = isOk ? "import-result-ok" : "import-result-fail";
  const icon = isOk ? "\u2714" : "\u2718";

  const stepLabels = [
    ["netbox_device_created", "Netbox device"],
    ["netbox_interface_created", "Netbox interface"],
    ["secret_stored", "OpenBao secret"],
    ["ipmi_ip_assigned", "Kea DHCP"],
    ["ironic_node_created", "Metal3 BMH"],
  ];
  const stepBadges = stepLabels
    .map(([key, label]) => {
      const done = r.steps[key];
      return `<span class="step-badge ${done ? "done" : "skip"}">${label}</span>`;
    })
    .join(" ");

  const warningHtml = r.warnings.length
    ? `<div class="result-warnings">${r.warnings.join("<br/>")}</div>`
    : "";
  const errorHtml = r.error
    ? `<div class="result-error-text">${r.error}</div>`
    : "";

  return `<div class="${cssClass}">
    <strong>${icon} ${r.device_name}</strong>
    ${r.ipmi_ip ? ` &mdash; ${r.ipmi_ip}` : ""}
    <div class="step-badges">${stepBadges}</div>
    ${warningHtml}${errorHtml}
  </div>`;
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
  importProgressText.textContent = `Importing ${importData.length} servers...`;

  const total = importData.length;
  let received = 0;
  let ok = 0;
  let failed = 0;

  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${proto}//${location.host}/api/v1/servers/import/ws`);

  ws.onopen = () => {
    ws.send(JSON.stringify(importData));
  };

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);

    if (msg.done) {
      importProgressFill.style.width = "100%";
      if (failed > 0) {
        importProgressFill.style.background = "var(--warning)";
      }
      importProgressText.textContent = `Done: ${ok} succeeded, ${failed} failed`;
      importSubmitBtn.disabled = false;
      return;
    }

    if (msg.error && !msg.device_name) {
      // Validation error from server
      importProgressFill.style.width = "100%";
      importProgressFill.style.background = "var(--error)";
      importProgressText.textContent = "";
      importResults.className = "result-error";
      importResults.innerHTML = `<strong>Import failed</strong><br />${msg.error}`;
      importSubmitBtn.disabled = false;
      return;
    }

    // Per-server result
    received++;
    if (msg.status === "ok") ok++;
    else failed++;

    importProgressFill.style.width = `${(received / total) * 100}%`;
    importProgressText.textContent = `${received} / ${total} — ${ok} ok, ${failed} failed`;
    importResults.insertAdjacentHTML("beforeend", renderImportResult(msg));
  };

  ws.onerror = () => {
    importProgressFill.style.width = "100%";
    importProgressFill.style.background = "var(--error)";
    importProgressText.textContent = "";
    importResults.className = "result-error";
    importResults.innerHTML = `<strong>Import failed</strong><br />WebSocket connection error`;
    importSubmitBtn.disabled = false;
  };

  ws.onclose = (event) => {
    if (!event.wasClean && received === 0) {
      importProgressFill.style.width = "100%";
      importProgressFill.style.background = "var(--error)";
      importProgressText.textContent = "";
      importResults.className = "result-error";
      importResults.innerHTML = `<strong>Import failed</strong><br />Connection closed unexpectedly`;
    }
    importSubmitBtn.disabled = false;
  };
});

// ── Navigation wiring ──────────────────────────────────────────────────
$("#next-to-location").addEventListener("click", () => {
  showStep("location");
  loadSites();
  loadDeviceTypes();
  loadDeviceRoles();
  loadPrefixes();
  loadTenants();
});

$("#back-to-scan").addEventListener("click", () => showStep("scan"));

$("#next-to-review").addEventListener("click", () => {
  buildReview();
  // Reset submit state
  $("#submit-progress").classList.add("hidden");
  $("#submit-result").classList.add("hidden");
  $("#submit-register").disabled = false;
  showStep("review");
});

$("#back-to-location").addEventListener("click", () => showStep("location"));

$("#submit-register").addEventListener("click", submitRegistration);

// ── Nav menu ──
const navMenu = $("#nav-menu");

$("#nav-menu-toggle").addEventListener("click", () => {
  navMenu.classList.toggle("hidden");
});

// Close menu when clicking outside
document.addEventListener("click", (e) => {
  if (!e.target.closest(".nav-menu-wrap")) {
    navMenu.classList.add("hidden");
  }
});

$("#nav-list").addEventListener("click", () => {
  navMenu.classList.add("hidden");
  loadServerList();
  showStep("servers");
});

$("#back-from-list").addEventListener("click", () => showStep("scan"));

$("#nav-import").addEventListener("click", () => {
  navMenu.classList.add("hidden");
  resetImportPanel();
  showStep("import");
});

$("#back-from-import").addEventListener("click", () => showStep("scan"));

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
      showStep("scan");
      return;
    }
  } catch {
    // network error — fall through to login screen
  }
  showStep("login");
}

// ── Init ───────────────────────────────────────────────────────────────
checkAuth();
