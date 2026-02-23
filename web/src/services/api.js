/**
 * API client for the onboarding server.
 *
 * Authentication is handled via session cookies (set by the BFF auth flow).
 */

const BASE = "/api/v1";

async function request(method, path, body) {
  const opts = {
    method,
    headers: { "Content-Type": "application/json" },
  };
  if (body !== undefined) {
    opts.body = JSON.stringify(body);
  }
  const resp = await fetch(`${BASE}${path}`, opts);
  if (resp.status === 401) {
    window.location.href = "/auth/login";
    return;
  }
  if (!resp.ok) {
    const detail = await resp.json().catch(() => ({}));
    throw new Error(detail.detail?.message || detail.detail || resp.statusText);
  }
  return resp.json();
}

// Registration
export function registerServer(payload) {
  return request("POST", "/servers/register", payload);
}

// Server list / status
export function listServers() {
  return request("GET", "/servers");
}

export function getServerStatus(id) {
  return request("GET", `/servers/${id}/status`);
}

// Reference data
export function getSites() {
  return request("GET", "/reference/sites");
}

export function getLocations(site) {
  return request("GET", `/reference/locations?site=${encodeURIComponent(site)}`);
}

export function getRacks(location) {
  return request("GET", `/reference/racks?location=${encodeURIComponent(location)}`);
}

export function getDeviceTypes() {
  return request("GET", "/reference/device-types");
}

export function getDeviceRoles() {
  return request("GET", "/reference/device-roles");
}

export function getPrefixes() {
  return request("GET", "/reference/prefixes");
}
