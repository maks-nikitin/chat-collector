$(function () {
  let currentPhone = localStorage.getItem('tg_phone') || '';
  let currentService = 'telegram';
  let currentChatId = null;
  let phoneCodeHash = '';

  function escapeHtml(str) {
    return $('<div>').text(str || '').html();
  }

  function formatDate(iso) {
    try {
      return new Date(iso).toLocaleString('ru-RU');
    } catch (e) {
      return iso;
    }
  }

  function showAuthError(msg) {
    $('#auth-error').text(msg).show();
  }

  function hideAuthError() {
    $('#auth-error').hide();
  }

  // ---------------- Авторизация Telegram ----------------

  $('#btn-send-code').on('click', function () {
    hideAuthError();
    const phone = $('#input-phone').val().trim();
    if (!phone) {
      showAuthError('Введите номер телефона в международном формате');
      return;
    }
    $(this).prop('disabled', true).text('Отправка...');
    $.ajax({
      url: '/api/telegram/auth/send_code',
      method: 'POST',
      contentType: 'application/json',
      data: JSON.stringify({ phone: phone }),
    })
      .done(function (res) {
        phoneCodeHash = res.phone_code_hash;
        currentPhone = phone;
        $('#step-phone').hide();
        $('#step-code').show();
      })
      .fail(function (xhr) {
        showAuthError((xhr.responseJSON && xhr.responseJSON.detail) || 'Ошибка отправки кода');
      })
      .always(function () {
        $('#btn-send-code').prop('disabled', false).text('Отправить код');
      });
  });

  $('#btn-verify-code').on('click', function () {
    hideAuthError();
    const code = $('#input-code').val().trim();
    if (!code) {
      showAuthError('Введите код подтверждения');
      return;
    }
    $(this).prop('disabled', true).text('Проверка...');
    $.ajax({
      url: '/api/telegram/auth/verify_code',
      method: 'POST',
      contentType: 'application/json',
      data: JSON.stringify({ phone: currentPhone, code: code, phone_code_hash: phoneCodeHash }),
    })
      .done(function (res) {
        if (res.status === 'password_required') {
          $('#step-code').hide();
          $('#step-password').show();
        } else {
          onAuthSuccess();
        }
      })
      .fail(function (xhr) {
        showAuthError((xhr.responseJSON && xhr.responseJSON.detail) || 'Неверный код');
      })
      .always(function () {
        $('#btn-verify-code').prop('disabled', false).text('Подтвердить код');
      });
  });

  $('#btn-verify-password').on('click', function () {
    hideAuthError();
    const password = $('#input-password').val();
    $(this).prop('disabled', true).text('Вход...');
    $.ajax({
      url: '/api/telegram/auth/verify_password',
      method: 'POST',
      contentType: 'application/json',
      data: JSON.stringify({ phone: currentPhone, password: password }),
    })
      .done(function () {
        onAuthSuccess();
      })
      .fail(function (xhr) {
        showAuthError((xhr.responseJSON && xhr.responseJSON.detail) || 'Неверный пароль');
      })
      .always(function () {
        $('#btn-verify-password').prop('disabled', false).text('Войти');
      });
  });

  function onAuthSuccess() {
    localStorage.setItem('tg_phone', currentPhone);
    $('#auth-screen').hide();
    $('#app-screen').show();
    loadChats();
  }

  $('#btn-logout').on('click', function () {
    localStorage.removeItem('tg_phone');
    location.reload();
  });

  if (currentPhone) {
    onAuthSuccess();
  }

  // ---------------- Переключение вкладок ----------------

  $('.tab-btn').on('click', function () {
    $('.tab-btn').removeClass('active');
    $(this).addClass('active');
    currentService = $(this).data('service');
    currentChatId = null;
    $('#join-box').toggle(currentService === 'telegram');
    $('#message-list').html('<div class="empty">Выберите чат слева</div>');
    loadChats();
  });
  $('#join-box').toggle(currentService === 'telegram');

  // ---------------- Список чатов ----------------

  $('#btn-join').on('click', function () {
    const identifier = $('#input-join').val().trim();
    const $status = $('#join-status');
    if (!identifier) {
      $status.removeClass('ok').addClass('error').text('Введите username или ссылку').show();
      return;
    }
    $(this).prop('disabled', true).text('Добавление...');
    $.ajax({
      url: '/api/telegram/join',
      method: 'POST',
      contentType: 'application/json',
      data: JSON.stringify({ phone: currentPhone, identifier: identifier }),
    })
      .done(function (res) {
        $status.removeClass('error').addClass('ok').text('Добавлено: ' + res.name).show();
        $('#input-join').val('');
        loadChats();
      })
      .fail(function (xhr) {
        $status
          .removeClass('ok')
          .addClass('error')
          .text((xhr.responseJSON && xhr.responseJSON.detail) || 'Не удалось добавить чат')
          .show();
      })
      .always(function () {
        $('#btn-join').prop('disabled', false).text('Добавить чат');
      });
  });

  function loadChats() {
    $('#chat-list').html('<div class="loading">Загрузка...</div>');

    if (currentService === 'viber') {
      $.get('/api/viber/chats')
        .done(function (res) {
          if (!res.configured) {
            $('#chat-list').html(
              '<div class="empty">Viber не настроен: токен бота не получить ' +
              'без коммерческой заявки (с 5.02.2024 Viber отменил бесплатную ' +
              'регистрацию ботов). Раздел остаётся в проекте на случай, если ' +
              'токен появится — заполните VIBER_BOT_TOKEN в .env.</div>'
            );
            return;
          }
          renderChatList(res.chats || []);
        })
        .fail(function () {
          $('#chat-list').html('<div class="error">Не удалось загрузить список чатов</div>');
        });
      return;
    }

    $.get('/api/telegram/chats?phone=' + encodeURIComponent(currentPhone) + '&limit=50')
      .done(function (res) {
        renderChatList(res.chats || []);
      })
      .fail(function () {
        $('#chat-list').html('<div class="error">Не удалось загрузить список чатов</div>');
      });
  }

  function renderChatList(chats) {
    const $list = $('#chat-list').empty();
    if (!chats.length) {
      $list.append('<div class="empty">Чатов не найдено</div>');
      return;
    }
    chats.forEach(function (chat) {
      const $item = $(
        '<div class="chat-item" data-id="' + escapeHtml(chat.id) + '">' +
          '<div class="chat-name">' + escapeHtml(chat.name) + '</div>' +
          '<div class="chat-last">' + escapeHtml(chat.last_message || '') + '</div>' +
        '</div>'
      );
      $item.on('click', function () {
        $('.chat-item').removeClass('active');
        $item.addClass('active');
        currentChatId = chat.id;
        loadMessages(chat.id);
      });
      $list.append($item);
    });
  }

  // ---------------- Сообщения ----------------

  function getMessageLimit() {
    let n = parseInt($('#input-limit').val(), 10);
    if (isNaN(n) || n < 1) n = 1;
    if (n > 500) n = 500;
    $('#input-limit').val(n);
    return n;
  }

  $('#btn-refresh').on('click', function () {
    if (currentChatId !== null) {
      loadMessages(currentChatId);
    }
  });

  $('#input-limit').on('keydown', function (e) {
    if (e.key === 'Enter' && currentChatId !== null) {
      loadMessages(currentChatId);
    }
  });

  function loadMessages(chatId) {
    $('#message-list').html('<div class="loading">Загрузка сообщений...</div>');
    const limit = getMessageLimit();
    const url =
      currentService === 'telegram'
        ? '/api/telegram/messages?phone=' + encodeURIComponent(currentPhone) + '&chat_id=' + encodeURIComponent(chatId) + '&limit=' + limit
        : '/api/viber/messages?user_id=' + encodeURIComponent(chatId) + '&limit=' + limit;

    $.get(url)
      .done(function (res) {
        renderMessages(res.messages || []);
      })
      .fail(function () {
        $('#message-list').html('<div class="error">Не удалось загрузить сообщения</div>');
      });
  }

  function renderMessages(messages) {
    const $list = $('#message-list').empty();
    if (!messages.length) {
      $list.append('<div class="empty">Сообщений нет</div>');
      return;
    }
    messages.forEach(function (m) {
      const $msg = $('<div class="message ' + (m.is_outgoing ? 'outgoing' : 'incoming') + '"></div>');
      $msg.append('<div class="message-sender">' + escapeHtml(m.sender) + '</div>');
      if (m.text) {
        $msg.append('<div class="message-text">' + escapeHtml(m.text) + '</div>');
      }
      if (m.media_url) {
        $msg.append('<img class="message-media" src="' + m.media_url + '" alt="media">');
      }
      $msg.append('<div class="message-date">' + formatDate(m.date) + '</div>');
      $list.append($msg);
    });
    $list.scrollTop($list[0].scrollHeight);
  }
});
