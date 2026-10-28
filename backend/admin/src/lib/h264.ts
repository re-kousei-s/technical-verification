// H.264（Annex B）のデータを少しだけ読む。デコーダを作るときに、キーフレームと SPS が要る。

/** NAL ユニットを順に見て、キーフレーム（種類 5）と SPS（種類 7）を探す */
export function scanNals(buf: Uint8Array): { key: boolean; sps: Uint8Array | null } {
  let key = false;
  let sps: Uint8Array | null = null;
  for (let i = 0; i + 3 < buf.length; i++) {
    if (buf[i] === 0 && buf[i + 1] === 0 && buf[i + 2] === 1) {
      const type = buf[i + 3] & 0x1f;
      if (type === 5) key = true;
      if (type === 7) sps = buf.subarray(i + 3, i + 7); // [NAL ヘッダ, profile, 制約, level]
      i += 2;
    }
  }
  return { key, sps };
}

const hex2 = (n: number) => n.toString(16).padStart(2, "0");

/** SPS の先頭 3 バイトが、コーデック名（avc1.xxxxxx）になる。SPS が無ければ無難な値を返す */
export const codecName = (sps: Uint8Array | null) =>
  sps ? `avc1.${hex2(sps[1])}${hex2(sps[2])}${hex2(sps[3])}` : "avc1.42001f";
