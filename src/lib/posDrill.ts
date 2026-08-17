export interface POSQuestion {
  id: string;
  sentence: string; // contains ___ for the blank
  word: string;
  correctAnswer: "noun" | "verb" | "adjective" | "adverb" | "preposition" | "conjunction";
}

export const POS_LABEL: Record<POSQuestion["correctAnswer"], string> = {
  noun: "คำนาม (Noun)",
  verb: "คำกริยา (Verb)",
  adjective: "คำคุณศัพท์ (Adjective)",
  adverb: "คำวิเศษณ์ (Adverb)",
  preposition: "คำบุพบท (Preposition)",
  conjunction: "คำสันธาน (Conjunction)",
};

export const POS_DRILL: POSQuestion[] = [
  { id: "p1", sentence: "She ___ to the market every morning.", word: "walks", correctAnswer: "verb" },
  { id: "p2", sentence: "The ___ was extremely difficult.", word: "exam", correctAnswer: "noun" },
  { id: "p3", sentence: "He answered the question ___.", word: "correctly", correctAnswer: "adverb" },
  { id: "p4", sentence: "That is a ___ idea.", word: "brilliant", correctAnswer: "adjective" },
  { id: "p5", sentence: "The cat is sitting ___ the table.", word: "under", correctAnswer: "preposition" },
  { id: "p6", sentence: "I wanted to go, ___ it rained.", word: "but", correctAnswer: "conjunction" },
  { id: "p7", sentence: "They ___ the project last week.", word: "finished", correctAnswer: "verb" },
  { id: "p8", sentence: "Her ___ was clearly visible.", word: "happiness", correctAnswer: "noun" },
];
