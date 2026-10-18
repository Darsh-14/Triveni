// Emoji and pictographs in text the app does not author (model answers, stored questions) are dropped:
// they carry no information the words do not already carry.
const EMOJI = /[\p{Extended_Pictographic}\u{1F1E6}-\u{1F1FF}\u{1F3FB}-\u{1F3FF}\u{FE0F}\u{20E3}]|\u{200D}/gu;

export const stripEmoji = (text: string) => text.replace(EMOJI, "").replace(/[ \t]{2,}/g, " ");
