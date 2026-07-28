/**
 * 與 MediaMTX 做 WHEP 協商：送出我方的 SDP offer，取回對方的 SDP answer。
 *
 * SDP 可以想成通話前互相交換的「自我介紹小紙條」：寫著我聽得懂哪些編碼、
 * 我的位址是什麼、我只想收不想送。兩邊交換完就知道怎麼傳影像。
 *
 * 不走 client.ts：目標是 MediaMTX 而非本專案後端，不需要帶登入 token，
 * 且內容是純文字 SDP（application/sdp）不是 JSON。
 * 放在 api/ 是為了遵守「元件內禁止直接 fetch」的鐵律。
 */
export async function negotiateWhep(whepUrl: string, offerSdp: string): Promise<string> {
  const res = await fetch(whepUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/sdp' },
    body: offerSdp,
  });
  if (!res.ok) {
    throw new Error(`MediaMTX 回應 ${res.status}`);
  }
  return res.text();
}
