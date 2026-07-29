import { apiClient } from './client';

/**
 * 跟後端換一張「串流權杖」——只能看指定頻道、60 秒後失效的短命通行證。
 *
 * 為什麼不能直接把登入 token 拿去給 MediaMTX：
 * 登入 token 一整天有效、權限完整，而它會被寫進 MediaMTX 與 nginx 的存取紀錄裡。
 * 短命權杖就算外流，也只能看一個頻道、60 秒。
 *
 * 走 apiClient 是因為這一支打的是「本專案後端」，需要帶登入 token（client.ts 會自動加）。
 */
export async function fetchStreamToken(channel: string): Promise<string> {
  const res = await apiClient.post<{ token: string; expires_in: number }>(
    `/streams/${channel}/token`,
  );
  return res.token;
}

/**
 * 與 MediaMTX 做 WHEP 協商：送出我方的 SDP offer，取回對方的 SDP answer。
 *
 * SDP 可以想成通話前互相交換的「自我介紹小紙條」：寫著我聽得懂哪些編碼、
 * 我的位址是什麼、我只想收不想送。兩邊交換完就知道怎麼傳影像。
 *
 * 不走 client.ts：目標是 MediaMTX 而非本專案後端，內容是純文字 SDP
 * （application/sdp）不是 JSON，帶的也不是登入 token 而是上面換來的串流權杖。
 * 放在 api/ 是為了遵守「元件內禁止直接 fetch」的鐵律。
 */
export async function negotiateWhep(
  whepUrl: string,
  offerSdp: string,
  streamToken: string,
): Promise<string> {
  const res = await fetch(whepUrl, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/sdp',
      // MediaMTX 收到後不會自己驗，而是原封不動轉交給後端 POST /streams/auth 判斷
      Authorization: `Bearer ${streamToken}`,
    },
    body: offerSdp,
  });
  if (!res.ok) {
    throw new Error(`MediaMTX 回應 ${res.status}`);
  }
  return res.text();
}
