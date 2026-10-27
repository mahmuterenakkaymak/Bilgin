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

// Veritabanı yoklaması tutmasa bile şablon iner; duyurusu percent-kodlu bu başlıkta taşınır (R6-17).
const NOTE_HEADER = "X-Bilgin-Note";

// Oturumun düştüğünü her ekranın kendi yakalaması yerine kök kapıya bildirir. Giriş isteğinin 401'i
// ("kullanıcı adı veya parola hatalı") beklenen bir yanıttır, formda görünür; handler'a gitmez.
let unauthorized = null;

export function onUnauthorized(handler) {
  unauthorized = handler;
}

// Arayüz dili (R8-16): provider her değişimde buradan yazar, her istek de başlıkla taşır.
// ASSUMPTION: henüz dil çözülmemişse başlık hiç gitmez — sunucunun varsayılanı zaten program dili.
let uiLang = null;

export function setApiLang(lang) {
  uiLang = lang || null;
}

// Boş küme `init`e hiç yazılmaz: gövdesiz GET'in bugünkü başlıksız çağrısı değişmesin.
function headersFor(withBody) {
  const headers = {};
  if (withBody) headers["Content-Type"] = "application/json";
  if (uiLang) headers["Accept-Language"] = uiLang;
  return Object.keys(headers).length ? headers : undefined;
}

export function me() {
  return request("/api/auth/me");
}

// Kişinin kendi tercihi (Contracts "me PUT"): dil düğmesi oturmuş kullanıcıda sunucuya da yazılır.
export function setMyLang(lang) {
  return request("/api/auth/me", { method: "PUT", body: { lang } });
}

export function login({ username, password }) {
  return request(LOGIN_PATH, { method: "POST", body: { username, password } });
}

export function logout() {
  return request("/api/auth/logout", { method: "POST" });
}

// ``conversation_id`` yalnız bir konuşmaya soru sorulurken gider: anahtarı null yazmak yerine hiç
// yazmamak, konuşmasız sorunun gövdesini Run 6'daki hâliyle sürdürür (Contracts "ask body (ext.)").
export function ask({ question, mode = null, choice = null, conversation_id = null }) {
  return request("/api/ask", {
    method: "POST",
    body: { question, mode, choice, ...(conversation_id ? { conversation_id } : {}) },
  });
}

// Konuşmalar (R7-8): liste, turlarıyla tek konuşma, silme. Açmak yalnız depoda yazılı olanı okur.
export function conversationsList() {
  return request("/api/conversations");
}

export function conversationGet(id) {
  return request(`/api/conversations/${encodeURIComponent(id)}`);
}

export function conversationDelete(id) {
  return request(`/api/conversations/${encodeURIComponent(id)}`, { method: "DELETE" });
}

// Geçmişteki bir soru: kayıtlı SQL modelsiz yeniden çalışır, cevap /api/ask ile aynı biçimde gelir.
export function replay(auditId) {
  return request(`/api/replay/${encodeURIComponent(auditId)}`, { method: "POST" });
}

export function health(url = "/api/health") {
  return request(url);
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

// Yöneticinin kullanıcı defteri: liste, ekme, güncelleme (rol / etkinlik / parola).
export function usersList() {
  return request("/api/users");
}

export function usersCreate(body) {
  return request("/api/users", { method: "POST", body });
}

export function usersUpdate(id, body) {
  return request(`/api/users/${encodeURIComponent(id)}`, { method: "PUT", body });
}

export function rebuild() {
  return request("/api/index/rebuild", { method: "POST" });
}

export function exportUrl(id, format = "csv") {
  return `/api/export/${encodeURIComponent(id)}.${format}`;
}

// --- Veritabanı haritası ve veri kümeleri (R6-19): hepsi yönetici yolu, hepsi aynı kapıdan geçer.

export function mapInfo() {
  return request("/api/schema-map/info");
}

// Boş şablon düz bir bağlantıyla inebilir; veritabanından doldurulanın duyurusu başlıkta olduğu
// için o fetch edilir — <a href> indirilen dosyanın yanıt başlıklarını okuyamaz. Dil de o yüzden
// bağlantıya yazılır: `<a>` kendi başlık gönderemez, yol `?lang=`ı okur (R8-12).
export function mapTemplateUrl(fromDb = false) {
  const query = new URLSearchParams();
  if (fromDb) query.set("from_db", "1");
  if (uiLang) query.set("lang", uiLang);
  const search = query.toString();
  return `/api/schema-map/template.xlsx${search ? `?${search}` : ""}`;
}

export function mapTemplateDownload(fromDb = false) {
  return requestBlob(mapTemplateUrl(fromDb));
}

export async function mapSampleBlob() {
  const { blob } = await requestBlob("/api/schema-map/sample.xlsx");
  return blob;
}

export function mapPreview({ filename, content_b64 }) {
  return request("/api/schema-map/preview", { method: "POST", body: { filename, content_b64 } });
}

export function mapApply(previewId) {
  return request("/api/schema-map/apply", { method: "POST", body: { preview_id: previewId } });
}

export function mapStatus(previewId) {
  return request(`/api/schema-map/status/${encodeURIComponent(previewId)}`);
}

export function datasetsList() {
  return request("/api/datasets");
}

export function datasetActivate(name) {
  return request("/api/datasets/active", { method: "POST", body: { name } });
}

export function loginScriptUrl(name) {
  return `/api/datasets/${encodeURIComponent(name)}/login-script.sql`;
}

// --- Başlangıç ekranı ve hazır sorular (R7-17, R7-18, R7-20): kartların yükü sunucuda yürür,
// yani burada SQL gönderilen tek bir yol bile yoktur.

export function start() {
  return request("/api/start");
}

export function startRefresh(id) {
  return request(`/api/start/cards/${encodeURIComponent(id)}/refresh`, { method: "POST" });
}

export function startOpen(id) {
  return request(`/api/start/cards/${encodeURIComponent(id)}/open`, { method: "POST" });
}

// Kişisel kart kişinin kendi cevaplanmış sorusundan: ``sql`` gövdede yoktur, gönderilse okunmaz.
export function pinCard({ audit_id, title = "", display = null }) {
  return request("/api/start/cards", { method: "POST", body: { audit_id, title, display } });
}

export function unpinCard(id) {
  return request(`/api/start/cards/${encodeURIComponent(id)}`, { method: "DELETE" });
}

// Yöneticinin defteri: ``pending`` üç değerlidir — true bekleyenler, false onaylılar, yoksa hepsi.
// Bu yüzden ``false`` adres'e yazılır, yalnız yokluk atlanır.
export function readyList({ dataset = null, pending = null } = {}) {
  const query = new URLSearchParams();
  if (dataset) query.set("dataset", dataset);
  if (pending !== null && pending !== undefined) query.set("pending", String(pending));
  const search = query.toString();
  return request(`/api/ready-questions${search ? `?${search}` : ""}`);
}

export function readyCreate(body) {
  return request("/api/ready-questions", { method: "POST", body });
}

export function readyUpdate(id, body) {
  return request(`/api/ready-questions/${encodeURIComponent(id)}`, { method: "PUT", body });
}

export function readyRemove(id) {
  return request(`/api/ready-questions/${encodeURIComponent(id)}`, { method: "DELETE" });
}

// Öneri işi (R7-20): boş küme sunucunun o anki kümesidir, aşama ``job_id`` ile yoklanır.
export function readySuggest(dataset = "") {
  return request("/api/ready-questions/suggest", { method: "POST", body: { dataset } });
}

export function readySuggestStatus(jobId) {
  return request(`/api/ready-questions/suggest/${encodeURIComponent(jobId)}`);
}

// --- Veritabanı bağlantıları (R7-27): sır bu kapıdan yalnız içeri girer. Hiçbir okuma ne parola
// ne bağlantı dizesi taşır; gövdedeki boş ``password`` sunucuda "saklı olanı koru"dur (connForm.js).

export function connectionsList() {
  return request("/api/connections");
}

export function connectionsGet(dataset) {
  return request(`/api/connections/${encodeURIComponent(dataset)}`);
}

export function connectionsSave(dataset, body) {
  return request(`/api/connections/${encodeURIComponent(dataset)}`, { method: "PUT", body });
}

export function connectionsTest(dataset, body) {
  return request(`/api/connections/${encodeURIComponent(dataset)}/test`, { method: "POST", body });
}

async function request(path, { method = "GET", body } = {}) {
  const headers = headersFor(body !== undefined);
  const init = {
    method,
    ...(headers ? { headers } : {}),
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
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

// İndirme iki şeyi birden döndürür: baytlar ve yoklamanın notu. Hata cümlesi JSON gövdede durduğu
// için önce o okunur; kopan bağlantı `request` ile aynı şekilde status 0 olur.
async function requestBlob(path) {
  const headers = headersFor(false);
  try {
    const response = await fetch(path, headers ? { headers } : undefined);
    if (!response.ok) {
      const error = toApiError(response.status, await readBody(response));
      if (response.status === 401 && path !== LOGIN_PATH) unauthorized?.();
      throw error;
    }
    return { blob: await response.blob(), note: readNote(response) };
  } catch (error) {
    throw error instanceof ApiError ? error : new ApiError(0, NETWORK_MESSAGE);
  }
}

function readNote(response) {
  const raw = response.headers?.get?.(NOTE_HEADER);
  if (!raw) return null;
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw; // bozuk yüzde kaçışı olan bir başlık cümlesiz bırakılmaz
  }
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
