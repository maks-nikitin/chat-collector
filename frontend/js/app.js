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

  // ---------------- Отрисовка сообщений ----------------

  function formatDuration(sec) {
    if (!sec && sec !== 0) return '';
    sec = Math.round(sec);
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return m + ':' + (s < 10 ? '0' : '') + s;
  }

  function formatSize(bytes) {
    if (!bytes) return '';
    if (bytes < 1024 * 1024) return Math.round(bytes / 1024) + ' КБ';
    return (bytes / (1024 * 1024)).toFixed(1) + ' МБ';
  }

  // Безопасно добавляет текст в элемент, превращая http(s)-ссылки в <a>
  function appendLinkified($el, text) {
    const re = /(https?:\/\/[^\s<>"']+)/g;
    let last = 0;
    let match;
    while ((match = re.exec(text)) !== null) {
      if (match.index > last) $el.append(document.createTextNode(text.slice(last, match.index)));
      let url = match[1];
      let tail = '';
      const trailing = url.match(/[.,;:!?)\]]+$/);
      if (trailing) {
        tail = trailing[0];
        url = url.slice(0, -tail.length);
      }
      $el.append($('<a target="_blank" rel="noopener noreferrer"></a>').attr('href', url).text(url));
      if (tail) $el.append(document.createTextNode(tail));
      last = match.index + match[1].length;
    }
    if (last < text.length) $el.append(document.createTextNode(text.slice(last)));
  }

  function renderReply(reply) {
    const $r = $('<div class="message-reply"></div>');
    if (reply.missing) {
      $r.addClass('missing').append('<div class="reply-text">Исходное сообщение недоступно</div>');
      return $r;
    }
    $r.append($('<div class="reply-sender"></div>').text(reply.sender || ''));
    const preview = reply.text || reply.label || '';
    $r.append($('<div class="reply-text"></div>').text(preview));
    $r.on('click', function () {
      const target = $('#message-list .message').filter(function () {
        return (' ' + $(this).attr('data-ids') + ' ').indexOf(' ' + reply.id + ' ') !== -1;
      }).first();
      if (!target.length) {
        $r.attr('title', 'Исходное сообщение вне загруженного диапазона — увеличьте число сообщений');
        return;
      }
      target[0].scrollIntoView({ behavior: 'smooth', block: 'center' });
      target.addClass('highlight');
      setTimeout(function () { target.removeClass('highlight'); }, 1500);
    });
    return $r;
  }

  function renderMediaItem(md) {
    switch (md.type) {
      case 'photo':
      case 'image':
        return $('<a class="media-link" target="_blank" rel="noopener"></a>')
          .attr('href', md.url)
          .append($('<img class="message-media" loading="lazy" alt="media">').attr('src', md.url));
      case 'sticker':
        return $('<img class="message-sticker" loading="lazy" alt="sticker">').attr('src', md.url);
      case 'video': {
        const $v = $('<video class="message-video" controls preload="none" playsinline></video>').attr('src', md.url);
        if (md.thumb) $v.attr('poster', md.thumb);
        const $wrap = $('<div class="video-wrap"></div>').append($v);
        const info = [formatDuration(md.duration), formatSize(md.size)].filter(Boolean).join(' · ');
        if (info) $wrap.append($('<div class="media-info"></div>').text('Видео · ' + info));
        return $wrap;
      }
      case 'gif':
        return $('<video class="message-video" autoplay loop muted playsinline preload="auto"></video>').attr('src', md.url);
      case 'audio': {
        const $wrap = $('<div class="audio-wrap"></div>');
        const info = [md.name, formatDuration(md.duration), formatSize(md.size)].filter(Boolean).join(' · ');
        if (info) $wrap.append($('<div class="media-info"></div>').text(info));
        $wrap.append($('<audio controls preload="none"></audio>').attr('src', md.url));
        return $wrap;
      }
      case 'file':
        return $('<a class="message-file"></a>')
          .attr('href', md.url)
          .text('📎 ' + (md.name || 'Файл') + (md.size ? ' (' + formatSize(md.size) + ')' : ''));
      default:
        return $();
    }
  }

  function renderMediaBlock(mediaList) {
    const images = mediaList.filter(function (md) { return md.type === 'photo' || md.type === 'image'; });
    // Несколько фото — одной сеткой, как альбом в Telegram
    if (images.length > 1 && images.length === mediaList.length) {
      const cols = images.length === 2 || images.length === 4 ? 2 : 3;
      const $grid = $('<div class="media-grid"></div>').addClass('cols-' + cols);
      images.forEach(function (md) { $grid.append(renderMediaItem(md)); });
      return $grid;
    }
    const $block = $('<div class="media-block"></div>');
    mediaList.forEach(function (md) { $block.append(renderMediaItem(md)); });
    return $block;
  }

  // ---------------- «Богатые» посты (rich_message) ----------------

  function renderRuns($el, runs) {
    (runs || []).forEach(function (r) {
      let $node = $(document.createTextNode(r.t));
      if (r.code) $node = $('<code></code>').append($node);
      if (r.b) $node = $('<strong></strong>').append($node);
      if (r.i) $node = $('<em></em>').append($node);
      if (r.u) $node = $('<u></u>').append($node);
      if (r.s) $node = $('<s></s>').append($node);
      if (r.url && /^(https?:|mailto:|tel:)/i.test(r.url)) {
        $node = $('<a target="_blank" rel="noopener noreferrer"></a>').attr('href', r.url).append($node);
      }
      $el.append($node);
    });
  }

  // убираем лишние переводы строки в начале и конце блока
  function trimRuns(runs) {
    const out = (runs || []).map(function (r) { return $.extend({}, r); });
    while (out.length) {
      out[0].t = out[0].t.replace(/^\s+/, '');
      if (out[0].t) break;
      out.shift();
    }
    while (out.length) {
      const last = out[out.length - 1];
      last.t = last.t.replace(/\s+$/, '');
      if (last.t) break;
      out.pop();
    }
    return out;
  }

  function renderCaption(runs) {
    const t = trimRuns(runs);
    if (!t.length) return $();
    const $c = $('<div class="rich-caption"></div>');
    renderRuns($c, t);
    return $c;
  }

  function renderRich(blocks) {
    const $wrap = $('<div class="rich"></div>');
    let i = 0;
    while (i < blocks.length) {
      const b = blocks[i];

      if (b.type === 'photo') {
        // подряд идущие фото — одной сеткой
        const group = [];
        while (i < blocks.length && blocks[i].type === 'photo') group.push(blocks[i++]);
        $wrap.append(renderMediaBlock(group.map(function (g) { return { type: 'photo', url: g.url }; })));
        group.forEach(function (g) { $wrap.append(renderCaption(g.caption)); });
        continue;
      }
      i++;

      switch (b.type) {
        case 'heading': {
          const $h = $('<div class="rich-heading"></div>').addClass('level-' + (b.level || 3));
          renderRuns($h, trimRuns(b.runs));
          $wrap.append($h);
          break;
        }
        case 'paragraph': {
          const runs = trimRuns(b.runs);
          if (!runs.length) break;
          const $p = $('<div class="rich-paragraph"></div>');
          renderRuns($p, runs);
          $wrap.append($p);
          break;
        }
        case 'quote': {
          const $q = $('<blockquote class="rich-quote"></blockquote>');
          renderRuns($q, trimRuns(b.runs));
          const cap = trimRuns(b.caption);
          if (cap.length) {
            const $cap = $('<div class="rich-caption"></div>');
            renderRuns($cap, cap);
            $q.append($cap);
          }
          $wrap.append($q);
          break;
        }
        case 'code': {
          const $pre = $('<pre class="rich-code"></pre>');
          renderRuns($pre, b.runs);
          $wrap.append($pre);
          break;
        }
        case 'list': {
          const $list = $(b.ordered ? '<ol class="rich-list"></ol>' : '<ul class="rich-list"></ul>');
          if (b.ordered && b.start > 1) $list.attr('start', b.start);
          (b.items || []).forEach(function (item) {
            const $li = $('<li></li>');
            renderRuns($li, trimRuns(item));
            $list.append($li);
          });
          $wrap.append($list);
          break;
        }
        case 'divider':
          $wrap.append('<hr class="rich-divider">');
          break;
        case 'video':
        case 'gif':
        case 'audio':
        case 'file':
          $wrap.append(renderMediaItem(b));
          $wrap.append(renderCaption(b.caption));
          break;
      }
    }
    return $wrap;
  }

  function renderMessages(messages) {
    const $list = $('#message-list').empty();
    if (!messages.length) {
      $list.append('<div class="empty">Сообщений нет</div>');
      return;
    }
    messages.forEach(function (m) {
      // Viber и старый формат ответа: одно вложение в media_url
      let media = m.media || [];
      if (!media.length && m.media_url) media = [{ type: 'photo', url: m.media_url }];

      const $msg = $('<div class="message ' + (m.is_outgoing ? 'outgoing' : 'incoming') + '"></div>');
      $msg.attr('data-ids', (m.ids && m.ids.length ? m.ids : [m.id]).join(' '));

      $msg.append($('<div class="message-sender"></div>').text(m.sender || ''));
      if (m.forward) {
        $msg.append(
          $('<div class="message-forward"></div>')
            .append('<span class="forward-label">Переслано от </span>')
            .append($('<span class="forward-name"></span>').text(m.forward.name))
        );
      }
      if (m.reply) $msg.append(renderReply(m.reply));
      const hasRich = !!(m.rich && m.rich.length);
      if (hasRich) {
        $msg.append(renderRich(m.rich));
      } else {
        if (media.length) $msg.append(renderMediaBlock(media));
        if (m.text) {
          const $text = $('<div class="message-text"></div>');
          appendLinkified($text, m.text);
          $msg.append($text);
        }
      }
      if (!m.text && !media.length && !hasRich) {
        $msg.append($('<div class="message-placeholder"></div>').text(m.placeholder || '[Пустое сообщение]'));
      }
      $msg.append($('<div class="message-date"></div>').text(formatDate(m.date)));
      $list.append($msg);
    });
    // прокручиваем к самому свежему сообщению (скроллится панель, а не список)
    const $panel = $('.main-panel');
    $panel.scrollTop($panel[0].scrollHeight);
  }
});
