// Kartın çip şeridi: olguların tamamı değil, cevabın üç özeti. Okunur okunuşu olmayan olgu çip
// olmaz; tek hücrelik cevapta üç olgu aynı sayıyı söyler, şeritte bir kez okunur. Dönen öğeler
// girdi dizisinin kendi referanslarıdır — kanıt paneli "çipte olmayanlar"ı bu kimlikle ayırır.
const CHIP_FACTS = ["total", "max", "mean"];

export function chipFacts(facts) {
  const readable = (Array.isArray(facts) ? facts : []).filter((fact) => fact?.label && fact?.display);
  const picked = [];
  for (const name of CHIP_FACTS) {
    const fact = readable.find((item) => item.name === name);
    if (fact && !picked.some((item) => item.display === fact.display)) picked.push(fact);
  }
  return picked;
}
