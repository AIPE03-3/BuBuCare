// 後端「通知人員前往」端點尚未定義（待後端確認），先佔位；串接後改為實際呼叫 api 層。
export async function notifyStaff(eventId: string): Promise<void> {
  console.info(`notifyStaff 尚未串接後端，事件 id：${eventId}`);
}
