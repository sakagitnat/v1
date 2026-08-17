import * as pdfjsLib from "pdfjs-dist";
// Vite-friendly way to point pdf.js at its worker file.
import pdfWorkerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorkerUrl;

export async function extractTextFromPdf(file: File): Promise<string> {
  const buffer = await file.arrayBuffer();
  const pdf = await pdfjsLib.getDocument({ data: buffer }).promise;
  const pages: string[] = [];
  for (let i = 1; i <= pdf.numPages; i++) {
    const page = await pdf.getPage(i);
    const content = await page.getTextContent();
    const text = content.items.map((item: any) => item.str).join(" ");
    pages.push(text);
  }
  return pages.join("\n\n");
}

export interface ParsedVocabLine {
  word: string;
  meaning: string;
}

// Heuristic: looks for lines like "word - meaning", "word: meaning",
// "word — meaning", or tab/multi-space separated "word    meaning".
// This is best-effort — PDFs vary too much for a fully general parser,
// so the UI always shows a preview for the user to review before saving.
export function parseVocabLines(text: string): ParsedVocabLine[] {
  const lines = text.split(/\n+/).map((l) => l.trim()).filter(Boolean);
  const results: ParsedVocabLine[] = [];
  const separators = [/\s+[-–—:]\s+/, /\t+/, /\s{2,}/];

  for (const line of lines) {
    if (line.length > 120) continue; // skip long paragraph lines, not vocab entries
    for (const sep of separators) {
      const parts = line.split(sep);
      if (parts.length === 2 && parts[0].trim() && parts[1].trim()) {
        const word = parts[0].trim();
        const meaning = parts[1].trim();
        // word part should look like a single word/short phrase, not a sentence
        if (word.split(/\s+/).length <= 4 && /^[a-zA-Zก-๙\s'-]+$/.test(word)) {
          results.push({ word, meaning });
          break;
        }
      }
    }
  }
  return results;
}
