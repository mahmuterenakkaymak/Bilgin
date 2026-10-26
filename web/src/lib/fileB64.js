// Yükleme dosyasının base64'ü (R6-19): /api/schema-map/preview gövdeyi base64 ister.
// Dönüşüm dilimlerle yapılır — String.fromCharCode(...bytes) tek seferde on binlerce argüman
// aldığı için çağrı yığınını taşırır; 0x8000 hem güvenli hem de base64'un 3'lü öbeğine böler.

const CHUNK = 0x8000;
const XLSX_SUFFIX = ".xlsx";
const XLSX_NAME = /\.xlsx$/i;

export function arrayBufferToBase64(buffer) {
  const bytes = buffer instanceof Uint8Array ? buffer : new Uint8Array(buffer ?? 0);
  let binary = "";
  for (let start = 0; start < bytes.length; start += CHUNK) {
    binary += String.fromCharCode(...bytes.subarray(start, start + CHUNK));
  }
  return btoa(binary);
}

// Ad denetimi yüklemeyi bekletmeden uyarı vermek içindir; sunucunun hükmü içeriğe bakar (R6-16),
// yani burada geçen bir ad reddedilebilir — burada geçmeyen bir ad ise hiç gönderilmez.
export function isXlsxName(name) {
  const value = typeof name === "string" ? name.trim() : "";
  return value.length > XLSX_SUFFIX.length && XLSX_NAME.test(value);
}
