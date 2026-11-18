// Уведомления о заявках с сайта a-gavrish.com (Google Apps Script, веб-приложение).
// Сервер сайта присылает сюда только номер заявки и ссылку на админку, без персональных данных.
// Письмо приходит на почту владельца этого Google-аккаунта.
// Telegram (по желанию): Настройки проекта → Свойства скрипта → добавить TG_TOKEN = токен бота.
function doPost(e) {
  var data = {};
  try { data = JSON.parse(e.postData.contents); } catch (err) {}
  var text = String(data.text || 'Новая заявка с сайта a-gavrish.com').slice(0, 500);
  MailApp.sendEmail(Session.getEffectiveUser().getEmail(), 'Новая заявка с сайта a-gavrish.com', text);

  var props = PropertiesService.getScriptProperties();
  var token = props.getProperty('TG_TOKEN');
  if (token) {
    var chat = props.getProperty('TG_CHAT');
    if (!chat) {
      var upd = JSON.parse(UrlFetchApp.fetch('https://api.telegram.org/bot' + token + '/getUpdates', {muteHttpExceptions: true}).getContentText());
      var msgs = (upd.result || []).filter(function (u) { return u.message && u.message.chat.type === 'private'; });
      if (msgs.length) { chat = String(msgs[msgs.length - 1].message.chat.id); props.setProperty('TG_CHAT', chat); }
    }
    if (chat) {
      UrlFetchApp.fetch('https://api.telegram.org/bot' + token + '/sendMessage',
        {method: 'post', payload: {chat_id: chat, text: text, disable_web_page_preview: 'true'}, muteHttpExceptions: true});
    }
  }
  return ContentService.createTextOutput('ok');
}

// Запустите эту функцию один раз из редактора, чтобы выдать разрешения и проверить, что письмо приходит.
function test() {
  doPost({postData: {contents: JSON.stringify({text: 'Проверка: уведомления с сайта a-gavrish.com работают.'})}});
}
