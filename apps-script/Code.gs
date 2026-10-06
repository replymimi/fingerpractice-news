/**
 * 「明天要進場」清單的雲端記事本 + 寄信員（Google Apps Script）。
 *
 * - 波段條件檢查頁（/picks/）用它新增、刪除、讀取清單
 * - 每天 07:00 的 GitHub 排程用它讀清單，算好結果後請它寄信
 *
 * 所有請求都要帶 key，key 存在「專案設定 → 指令碼屬性」的 KEY（跟頁面密碼相同）。
 * 收件人寫死在這裡，別人就算拿到 key 也不能拿它寄信給別人。
 * 設定步驟見 README「明天要進場清單」。
 */
const TO = 'thisismimi.yu@gmail.com';
const MAX_ITEMS = 50;

function doPost(e) {
  let req;
  try {
    req = JSON.parse(e.postData.contents);
  } catch (err) {
    return out_({ ok: false, error: 'bad request' });
  }
  const props = PropertiesService.getScriptProperties();
  const key = props.getProperty('KEY');
  if (!key || req.key !== key) return out_({ ok: false, error: 'unauthorized' });

  const lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    let list = JSON.parse(props.getProperty('WATCHLIST') || '[]');

    if (req.action === 'list') {
      // read only
    } else if (req.action === 'add') {
      const code = String(req.code || '').trim().toUpperCase();
      if (!/^[0-9A-Z]{4,6}$/.test(code)) return out_({ ok: false, error: 'bad code' });
      const note = String(req.note || '').slice(0, 200);
      const existing = list.find(function (x) { return x.code === code; });
      if (existing) {
        existing.note = note;
      } else {
        if (list.length >= MAX_ITEMS) return out_({ ok: false, error: 'list full' });
        list.push({ code: code, note: note, added: Utilities.formatDate(new Date(), 'Asia/Taipei', 'yyyy-MM-dd') });
      }
      props.setProperty('WATCHLIST', JSON.stringify(list));
    } else if (req.action === 'remove') {
      list = list.filter(function (x) { return x.code !== req.code; });
      props.setProperty('WATCHLIST', JSON.stringify(list));
    } else if (req.action === 'send') {
      MailApp.sendEmail({ to: TO, subject: String(req.subject || '').slice(0, 200), htmlBody: String(req.html || '') });
    } else {
      return out_({ ok: false, error: 'unknown action' });
    }
    return out_({ ok: true, list: list });
  } finally {
    lock.releaseLock();
  }
}

/** 第一次設定時手動執行一次，讓 Google 詢問「允許寄信」的權限。 */
function authorize() {
  Logger.log('今天還能寄 ' + MailApp.getRemainingDailyQuota() + ' 封信');
}

function out_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
