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
};

// Remember last-used location across scans
const remembered = {
  site: localStorage.getItem("last_site") || "",
  location: localStorage.getItem("last_location") || "",
  rack: localStorage.getItem("last_rack") || "",
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

// Manual input handlers
macInput.addEventListener("input", () => {
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

function updateLocationNextButton() {
  const ready =
    state.site &&
    state.location &&
    state.rack &&
    state.position &&
    state.deviceType &&
    state.deviceRole &&
    state.ipmiPrefix;
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

    resultDiv.classList.remove("hidden");
    resultDiv.className = "result-success";
    const warningsHtml = result.warnings && result.warnings.length
      ? `<div class="result-warnings">${result.warnings.map((w) => `<p>&#x26A0; ${w}</p>`).join("")}</div>`
      : "";
    resultDiv.innerHTML = `
      <strong>Server registered successfully</strong><br />
      Device: <code>${result.device_name}</code><br />
      IPMI IP: <code>${result.ipmi_ip || "N/A"}</code><br />
      Netbox ID: <code>${result.netbox_id || "N/A"}</code>
      ${warningsHtml}
    `;
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
async function loadServerList() {
  const container = $("#server-list");
  try {
    const servers = await listServers();
    if (servers.length === 0) {
      container.innerHTML = '<p class="empty-state">No servers registered yet.</p>';
      return;
    }
    container.innerHTML = servers
      .map(
        (s) => `
      <div class="server-card">
        <h3>${s.device_name}</h3>
        <span class="status-badge ${s.status}">${s.status}</span>
        <p class="meta">${s.site} / ${s.rack} / U${s.position}
          &mdash; ${new Date(s.created_at).toLocaleString()}</p>
      </div>`
      )
      .join("");
  } catch (err) {
    container.innerHTML = `<p class="empty-state">Failed to load servers: ${err.message}</p>`;
  }
}

// ── Navigation wiring ──────────────────────────────────────────────────
$("#next-to-location").addEventListener("click", () => {
  showStep("location");
  loadSites();
  loadDeviceTypes();
  loadDeviceRoles();
  loadPrefixes();
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

$("#nav-list").addEventListener("click", () => {
  loadServerList();
  showStep("servers");
});

$("#back-from-list").addEventListener("click", () => showStep("scan"));

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
