// Arayüzün tek ağ kapısı: her yol ya veri döner ya da ekranın okuyacağı ApiError yükseltir.

export class ApiError extends Error {
  constructor(status, message, errors = []) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.errors = errors;
  }
}

const NETWORK_MESSAGE = "Sunucuya ulaşılamadı";

// Giriş yolunu hem `login` hem 401 bekçisi okur: ikisi ayrışırsa oturum düşmesi sessizce kaybolur.
const LOGIN_PATH = "/api/auth/login";

// Oturumun düştüğünü her ekranın kendi yakalaması yerine kök kapıya bildirir. Giriş isteğinin 401'i
// ("kullanıcı adı veya parola hatalı") beklenen bir yanıttır, formda görünür; handler'a gitmez.
let unauthorized = null;

export function onUnauthorized(handler) {
  unauthorized = handler;
}

export function me() {
  return request("/api/auth/me");
}

export function login({ username, password }) {
  return request(LOGIN_PATH, { method: "POST", body: { username, password } });
}

export function logout() {
  return request("/api/auth/logout", { method: "POST" });
}

export function ask({ question, mode = null, choice = null }) {
  return request("/api/ask", { method: "POST", body: { question, mode, choice } });
}

// Geçmişteki bir soru: kayıtlı SQL modelsiz yeniden çalışır, cevap /api/ask ile aynı biçimde gelir.
export function replay(auditId) {
  return request(`/api/replay/${encodeURIComponent(auditId)}`, { method: "POST" });
}

export function health() {
  return request("/api/health");
}

export function examples() {
  return request("/api/examples");
}

export function tables() {
  return request("/api/tables");
}

export function savedList() {
  return request("/api/saved");
}

export function savedAdd({ question, mode = null, sql = null }) {
  return request("/api/saved", { method: "POST", body: { question, mode, sql } });
}

export function savedRemove(id) {
  return request(`/api/saved/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function history() {
  return request("/api/history");
}

export function rulesList() {
  return request("/api/rules");
}

export function rulesCreate(rule) {
  return request("/api/rules", { method: "POST", body: rule });
}

export function rulesUpdate(id, rule) {
  return request(`/api/rules/${encodeURIComponent(id)}`, { method: "PUT", body: rule });
}

export function rulesRemove(id) {
  return request(`/api/rules/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function rebuild() {
  return request("/api/index/rebuild", { method: "POST" });
}

export function exportUrl(id, format = "csv") {
  return `/api/export/${encodeURIComponent(id)}.${format}`;
}

async function request(path, { method = "GET", body } = {}) {
  const init = {
    method,
    ...(body === undefined ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  };
  let response;
  let data;
  try {
    response = await fetch(path, init);
    data = await readBody(response);
  } catch {
    throw new ApiError(0, NETWORK_MESSAGE);
  }
  if (!response.ok) {
    if (response.status === 401 && path !== LOGIN_PATH) unauthorized?.();
    throw toApiError(response.status, data);
  }
  return data;
}

async function readBody(response) {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

// FastAPI hataları iki yerden gelir: `detail` (tek cümle ya da alan listesi) ve alan hatalarının
// üst düzey `errors` anahtarı. Ekran başlığı `message`dan, alanların altındaki yazı `errors`dan okur.
function toApiError(status, data) {
  const errors = fieldErrors(data);
  const detail = typeof data?.detail === "string" && data.detail.trim() ? data.detail.trim() : null;
  return new ApiError(status, errors[0]?.message ?? detail ?? `Sunucu hatası (${status}).`, errors);
}

function fieldErrors(data) {
  const list = Array.isArray(data?.errors) ? data.errors : Array.isArray(data?.detail) ? data.detail : [];
  return list.map(fieldError).filter((error) => error.message);
}

function fieldError(item) {
  if (typeof item === "string") return { field: "", message: item.trim() };
  const loc = Array.isArray(item?.loc) ? item.loc.at(-1) : null;
  const field = item?.field ?? loc ?? "";
  return { field: String(field), message: String(item?.message ?? item?.msg ?? "").trim() };
}
