export const API = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';
let csrfToken = '';
export async function csrf() {
  const response = await fetch(`${API}/auth/csrf/`, { credentials: 'include' });
  csrfToken = (await response.json()).csrfToken;
}
export async function api(path, method = 'GET', data) {
  if (method !== 'GET') await csrf();
  const multipart = data instanceof FormData;
  const response = await fetch(`${API}${path}`, {
    method, credentials: 'include',
    headers: { ...(multipart ? {} : { 'Content-Type': 'application/json' }), ...(method !== 'GET' ? { 'X-CSRFToken': csrfToken } : {}) },
    body: data === undefined ? undefined : multipart ? data : JSON.stringify(data),
  });
  if (response.status === 204) return null;
  const text = await response.text();
  let result;
  try { result = text ? JSON.parse(text) : {}; }
  catch { throw new Error(`HTTP ${response.status}: the server returned a non-JSON response. Check backend logs and proxy upload limits; retry with JPEG/PNG files below 5 MB.`); }
  if (!response.ok) {
    const message = typeof result.detail === 'string' ? result.detail : JSON.stringify(result);
    const error = new Error([message, result.action, result.error_id ? `Error ID: ${result.error_id}` : ''].filter(Boolean).join(' '));
    error.status = response.status;
    error.payload = result;
    throw error;
  }
  return result;
}
