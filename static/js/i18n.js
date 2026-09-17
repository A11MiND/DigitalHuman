/* ════════════════════════════════════════════════════════════════
   數字人殿堂 · Digital Human Palace — localization
   Six locales, native names only, no flags.

   Scope: welcome page (login.html) + home page (lobby.html).
   The chat page and the creation wizard are not localized yet, so
   keep new keys here grouped by page to make that easy later.
   ════════════════════════════════════════════════════════════════ */
(function (global) {
  'use strict';

  var STORAGE_KEY = 'dh_locale';
  var DEFAULT_LOCALE = 'zh-Hant';

  /* Order matches the approved design. */
  var LOCALES = [
    { code: 'zh-Hans', native: '简体中文', html: 'zh-Hans' },
    { code: 'zh-Hant', native: '繁體中文', html: 'zh-Hant' },
    { code: 'en',      native: 'English',  html: 'en' },
    { code: 'fr',      native: 'Français', html: 'fr' },
    { code: 'de',      native: 'Deutsch',  html: 'de' },
    { code: 'es',      native: 'Español',  html: 'es' }
  ];

  var STRINGS = {
    'zh-Hans': {
      'brand':            '数字人殿堂',
      'foot.build':       '内部测试版本',
      'nav.start':        '开始对话',
      'hero.line1':       '跨越时空，',
      'hero.line2.pre':   '遇见你的',
      'hero.line2.mark':  '聊天搭子',
      'hero.line2.post':  '。',
      'hero.lede':        '与历史人物即时对话 · 语音互动',
      'hero.cta':         '开始对话',
      'hero.support':     '和伟大的灵魂，聊聊今天的你',
      'hero.note':        '好的对话，让过去与现在相遇。',
      'lang.aria':        '选择语言',
      'create.name':      '创建你的人物',
      'create.sub':       '让想象中的灵魂，与你对话',
      'roster.loading':   '正在恭候先贤…',
      'roster.empty':     '暂时还没有可对话的人物',
      'roster.error':     '无法连接服务器，请稍后再试',
      'card.aria':        '与 {name} 对话',
      'session.premium':  '✦ 高级账户',
      'session.trial':    '体验',
      'session.console':  '后台',
      'session.logout':   '登出',
      'login.title':      '登入殿堂',
      'login.username':   '账号',
      'login.password':   '密码',
      'login.userph':     '请输入账号',
      'login.passph':     '请输入密码',
      'login.submit':     '登入',
      'login.pending':    '登入中',
      'login.close':      '关闭',
      'login.showpw':     '显示密码',
      'login.needboth':   '请填写账号和密码',
      'login.failed':     '登入失败，请重试',
      'login.adminonly':  '管理员账户请前往管理平台登入',
      'login.offline':    '无法连接服务器，请检查网络',
      'login.welcome':    '欢迎回来，{name} · {quota}',
      'login.unlimited':  '不限次数',
      'login.remaining':  '剩余 {n} 次对话',
      'login.note':       '账号由管理员统一开通，如需开通请联系管理员',
      'login.tier1.name': '体验账户',
      'login.tier1.desc': '20 次对话',
      'login.tier2.name': '高级账户',
      'login.tier2.desc': '全套服务 · 不限次数'
    },

    'zh-Hant': {
      'brand':            '數字人殿堂',
      'foot.build':       '內部測試版本',
      'nav.start':        '開始對話',
      'hero.line1':       '跨越時空，',
      'hero.line2.pre':   '遇見你的',
      'hero.line2.mark':  '聊天搭子',
      'hero.line2.post':  '。',
      'hero.lede':        '與歷史人物即時對話 · 語音互動',
      'hero.cta':         '開始對話',
      'hero.support':     '和偉大的靈魂，聊聊今天的你',
      'hero.note':        '好的對話，讓過去與現在相遇。',
      'lang.aria':        '選擇語言',
      'create.name':      '創建你的人物',
      'create.sub':       '讓想像中的靈魂，與你對話',
      'roster.loading':   '靜候先賢降臨…',
      'roster.empty':     '暫時還沒有可對話的人物',
      'roster.error':     '無法連接伺服器，請稍後再試',
      'card.aria':        '與 {name} 對話',
      'session.premium':  '✦ 高級帳戶',
      'session.trial':    '體驗',
      'session.console':  '後台',
      'session.logout':   '登出',
      'login.title':      '登入殿堂',
      'login.username':   '帳號',
      'login.password':   '密碼',
      'login.userph':     '請輸入帳號',
      'login.passph':     '請輸入密碼',
      'login.submit':     '登入',
      'login.pending':    '登入中',
      'login.close':      '關閉',
      'login.showpw':     '顯示密碼',
      'login.needboth':   '請填寫帳號和密碼',
      'login.failed':     '登入失敗，請重試',
      'login.adminonly':  '管理員帳戶請前往管理平台登入',
      'login.offline':    '無法連接伺服器，請檢查網絡',
      'login.welcome':    '歡迎回來，{name} · {quota}',
      'login.unlimited':  '不限次數',
      'login.remaining':  '剩餘 {n} 次對話',
      'login.note':       '帳號由管理員統一開通，如需開通請聯繫管理員',
      'login.tier1.name': '體驗帳戶',
      'login.tier1.desc': '20 次對話',
      'login.tier2.name': '高級帳戶',
      'login.tier2.desc': '全套服務 · 不限次數'
    },

    'en': {
      'brand':            'Digital Human Palace',
      'foot.build':       'Internal preview build',
      'nav.start':        'Start chatting',
      'hero.line1':       'Across time.',
      'hero.line2.pre':   'Into ',
      'hero.line2.mark':  'conversation',
      'hero.line2.post':  '.',
      'hero.lede':        'Real-time conversations with historical figures.',
      'hero.cta':         'Start chatting',
      'hero.support':     'Great minds. A conversation that is yours.',
      'hero.note':        'Good conversations bring past and present together.',
      'lang.aria':        'Choose language',
      'create.name':      'Create a character',
      'create.sub':       'Bring your imagination to life',
      'roster.loading':   'Gathering great minds…',
      'roster.empty':     'No characters available yet',
      'roster.error':     'Could not reach the server. Please try again.',
      'card.aria':        'Chat with {name}',
      'session.premium':  '✦ Premium',
      'session.trial':    'Trial',
      'session.console':  'Console',
      'session.logout':   'Sign out',
      'login.title':      'Sign in',
      'login.username':   'Username',
      'login.password':   'Password',
      'login.userph':     'Enter your username',
      'login.passph':     'Enter your password',
      'login.submit':     'Sign in',
      'login.pending':    'Signing in',
      'login.close':      'Close',
      'login.showpw':     'Show password',
      'login.needboth':   'Please enter your username and password',
      'login.failed':     'Sign-in failed. Please try again.',
      'login.adminonly':  'Administrator accounts sign in from the admin console',
      'login.offline':    'Could not reach the server. Check your connection.',
      'login.welcome':    'Welcome back, {name} · {quota}',
      'login.unlimited':  'unlimited conversations',
      'login.remaining':  '{n} conversations left',
      'login.note':       'Accounts are issued by an administrator. Contact one to get access.',
      'login.tier1.name': 'Trial account',
      'login.tier1.desc': '20 conversations',
      'login.tier2.name': 'Premium account',
      'login.tier2.desc': 'Everything included · unlimited'
    },

    'fr': {
      'brand':            'Digital Human Palace',
      'foot.build':       'Version d’essai interne',
      'nav.start':        'Commencer à discuter',
      'hero.line1':       'À travers le temps.',
      'hero.line2.pre':   'Entrez en ',
      'hero.line2.mark':  'conversation',
      'hero.line2.post':  '.',
      'hero.lede':        'Des conversations en temps réel avec des figures historiques.',
      'hero.cta':         'Commencer à discuter',
      'hero.support':     'De grands esprits. Une conversation qui est la vôtre.',
      'hero.note':        'Les belles conversations réunissent le passé et le présent.',
      'lang.aria':        'Choisir la langue',
      'create.name':      'Créez votre personnage',
      'create.sub':       'Donnez vie à votre imagination',
      'roster.loading':   'Les grands esprits arrivent…',
      'roster.empty':     'Aucun personnage disponible pour le moment',
      'roster.error':     'Serveur injoignable. Veuillez réessayer.',
      'card.aria':        'Discuter avec {name}',
      'session.premium':  '✦ Premium',
      'session.trial':    'Essai',
      'session.console':  'Console',
      'session.logout':   'Se déconnecter',
      'login.title':      'Connexion',
      'login.username':   'Identifiant',
      'login.password':   'Mot de passe',
      'login.userph':     'Saisissez votre identifiant',
      'login.passph':     'Saisissez votre mot de passe',
      'login.submit':     'Se connecter',
      'login.pending':    'Connexion',
      'login.close':      'Fermer',
      'login.showpw':     'Afficher le mot de passe',
      'login.needboth':   'Veuillez saisir votre identifiant et votre mot de passe',
      'login.failed':     'Échec de la connexion. Veuillez réessayer.',
      'login.adminonly':  'Les comptes administrateurs se connectent depuis la console',
      'login.offline':    'Serveur injoignable. Vérifiez votre connexion.',
      'login.welcome':    'Bon retour, {name} · {quota}',
      'login.unlimited':  'conversations illimitées',
      'login.remaining':  '{n} conversations restantes',
      'login.note':       'Les comptes sont créés par un administrateur. Contactez-en un pour obtenir un accès.',
      'login.tier1.name': 'Compte d’essai',
      'login.tier1.desc': '20 conversations',
      'login.tier2.name': 'Compte premium',
      'login.tier2.desc': 'Tout inclus · illimité'
    },

    'de': {
      'brand':            'Digital Human Palace',
      'foot.build':       'Interne Testversion',
      'nav.start':        'Jetzt chatten',
      'hero.line1':       'Über die Zeit hinweg.',
      'hero.line2.pre':   'Mitten ins ',
      'hero.line2.mark':  'Gespräch',
      'hero.line2.post':  '.',
      'hero.lede':        'Gespräche in Echtzeit mit historischen Persönlichkeiten.',
      'hero.cta':         'Jetzt chatten',
      'hero.support':     'Große Geister. Ein Gespräch, das Ihnen gehört.',
      'hero.note':        'Gute Gespräche verbinden Vergangenheit und Gegenwart.',
      'lang.aria':        'Sprache wählen',
      'create.name':      'Figur erstellen',
      'create.sub':       'Erwecken Sie Ihre Fantasie zum Leben',
      'roster.loading':   'Große Geister versammeln sich…',
      'roster.empty':     'Noch keine Figuren verfügbar',
      'roster.error':     'Server nicht erreichbar. Bitte erneut versuchen.',
      'card.aria':        'Mit {name} chatten',
      'session.premium':  '✦ Premium',
      'session.trial':    'Testzugang',
      'session.console':  'Konsole',
      'session.logout':   'Abmelden',
      'login.title':      'Anmelden',
      'login.username':   'Benutzername',
      'login.password':   'Passwort',
      'login.userph':     'Benutzernamen eingeben',
      'login.passph':     'Passwort eingeben',
      'login.submit':     'Anmelden',
      'login.pending':    'Anmeldung läuft',
      'login.close':      'Schließen',
      'login.showpw':     'Passwort anzeigen',
      'login.needboth':   'Bitte Benutzernamen und Passwort eingeben',
      'login.failed':     'Anmeldung fehlgeschlagen. Bitte erneut versuchen.',
      'login.adminonly':  'Administratorkonten melden sich über die Konsole an',
      'login.offline':    'Server nicht erreichbar. Bitte Verbindung prüfen.',
      'login.welcome':    'Willkommen zurück, {name} · {quota}',
      'login.unlimited':  'unbegrenzte Gespräche',
      'login.remaining':  'noch {n} Gespräche',
      'login.note':       'Konten werden von einer Administratorin oder einem Administrator vergeben.',
      'login.tier1.name': 'Testkonto',
      'login.tier1.desc': '20 Gespräche',
      'login.tier2.name': 'Premium-Konto',
      'login.tier2.desc': 'Alles inklusive · unbegrenzt'
    },

    'es': {
      'brand':            'Digital Human Palace',
      'foot.build':       'Versión de prueba interna',
      'nav.start':        'Empezar a chatear',
      'hero.line1':       'A través del tiempo.',
      'hero.line2.pre':   'Hacia la ',
      'hero.line2.mark':  'conversación',
      'hero.line2.post':  '.',
      'hero.lede':        'Conversaciones en tiempo real con figuras históricas.',
      'hero.cta':         'Empezar a chatear',
      'hero.support':     'Grandes mentes. Una conversación que es tuya.',
      'hero.note':        'Las buenas conversaciones unen el pasado y el presente.',
      'lang.aria':        'Elegir idioma',
      'create.name':      'Crea tu personaje',
      'create.sub':       'Da vida a tu imaginación',
      'roster.loading':   'Reuniendo grandes mentes…',
      'roster.empty':     'Todavía no hay personajes disponibles',
      'roster.error':     'No se pudo conectar con el servidor. Inténtalo de nuevo.',
      'card.aria':        'Conversar con {name}',
      'session.premium':  '✦ Premium',
      'session.trial':    'Prueba',
      'session.console':  'Consola',
      'session.logout':   'Cerrar sesión',
      'login.title':      'Iniciar sesión',
      'login.username':   'Usuario',
      'login.password':   'Contraseña',
      'login.userph':     'Introduce tu usuario',
      'login.passph':     'Introduce tu contraseña',
      'login.submit':     'Iniciar sesión',
      'login.pending':    'Iniciando sesión',
      'login.close':      'Cerrar',
      'login.showpw':     'Mostrar contraseña',
      'login.needboth':   'Introduce tu usuario y tu contraseña',
      'login.failed':     'No se pudo iniciar sesión. Inténtalo de nuevo.',
      'login.adminonly':  'Las cuentas de administrador inician sesión en la consola',
      'login.offline':    'No se pudo conectar con el servidor. Revisa tu conexión.',
      'login.welcome':    'Bienvenido de nuevo, {name} · {quota}',
      'login.unlimited':  'conversaciones ilimitadas',
      'login.remaining':  'te quedan {n} conversaciones',
      'login.note':       'Las cuentas las emite un administrador. Contacta con uno para obtener acceso.',
      'login.tier1.name': 'Cuenta de prueba',
      'login.tier1.desc': '20 conversaciones',
      'login.tier2.name': 'Cuenta premium',
      'login.tier2.desc': 'Todo incluido · sin límite'
    }
  };

  /* ── Character display metadata ────────────────────────────────
     Portraits stay language-independent (no baked-in captions), so
     the name and the one-line tagline are localized here. Characters
     with no entry fall back to the name/role the API returns.
     `tint` is the pastel portrait field behind the cutout.

     `art` optionally overrides the portrait with a card-framed cutout
     under /images/cards/. Leave it out and the card falls back to the
     character's own portrait from /api/characters, so nothing 404s
     while the cutouts are still being produced.                     */
  var CHARACTERS = {
    'character-49fd372d': {            /* 李白 */
      tint: '#F8F0CB',
      art: '/images/cards/character-49fd372d.png',
      name: { 'zh-Hans': '李白', 'zh-Hant': '李白', en: 'Li Bai', fr: 'Li Bai', de: 'Li Bai', es: 'Li Bai' },
      sub: {
        'zh-Hans': '把日子聊成诗',
        'zh-Hant': '把日子聊成詩',
        en: 'Turn everyday life into poetry',
        fr: 'Transformer le quotidien en poésie',
        de: 'Aus dem Alltag Poesie machen',
        es: 'Convierte la vida diaria en poesía'
      }
    },
    'qin-shihuang': {
      tint: '#DCEEE3',
      /* No `art` override yet — the generated take read too fierce/severe,
         so this falls back to the character's own portrait for now. */
      name: {
        'zh-Hans': '秦始皇', 'zh-Hant': '秦始皇',
        en: 'Qin Shi Huang', fr: 'Qin Shi Huang', de: 'Qin Shi Huang', es: 'Qin Shi Huang'
      },
      sub: {
        'zh-Hans': '聊天下，也聊雄心',
        'zh-Hant': '聊天下，也聊雄心',
        en: 'Talk ambition and empire',
        fr: 'Parler d’ambition et d’empire',
        de: 'Über Ehrgeiz und Imperium sprechen',
        es: 'Habla de ambición e imperio'
      }
    },
    'elizabeth-i': {
      tint: '#E4DDF6',
      art: '/images/cards/elizabeth-i.png',
      name: {
        'zh-Hans': '伊丽莎白一世', 'zh-Hant': '伊麗莎白一世',
        en: 'Elizabeth I', fr: 'Élisabeth Ire', de: 'Elisabeth I.', es: 'Isabel I'
      },
      sub: {
        'zh-Hans': '听见王冠背后的故事',
        'zh-Hant': '聽見王冠背後的故事',
        en: 'Meet the mind behind the crown',
        fr: 'Rencontrer l’esprit derrière la couronne',
        de: 'Der Geist hinter der Krone',
        es: 'Conoce la mente tras la corona'
      }
    },
    'maryknoll-teacher': {              /* 小瑪老師 */
      tint: '#DDE8F5',
      art: '/images/cards/maryknoll-teacher.png',
      name: {
        'zh-Hans': '小玛老师', 'zh-Hant': '小瑪老師',
        en: 'Mr Ma', fr: 'M. Ma', de: 'Herr Ma', es: 'Sr. Ma'
      },
      sub: {
        'zh-Hans': '陪你聊升学的选择',
        'zh-Hant': '陪你聊升學的選擇',
        en: 'Talk through your next school choice',
        fr: 'Parlez de votre choix d’école',
        de: 'Sprechen Sie über Ihre Schulwahl',
        es: 'Habla sobre tu elección de escuela'
      }
    },
    'character-b4e8368c': {            /* 杜甫 */
      tint: '#E7EEDC',
      name: { 'zh-Hans': '杜甫', 'zh-Hant': '杜甫', en: 'Du Fu', fr: 'Du Fu', de: 'Du Fu', es: 'Du Fu' },
      sub: {
        'zh-Hans': '在乱世里读懂人心',
        'zh-Hant': '在亂世裡讀懂人心',
        en: 'Read the human heart in hard times',
        fr: 'Lire le cœur humain en temps troublés',
        de: 'Das Menschenherz in schweren Zeiten lesen',
        es: 'Leer el corazón humano en tiempos difíciles'
      }
    }
  };

  /* Pastel fields for characters with no explicit entry. */
  var FALLBACK_TINTS = ['#F8F0CB', '#DCEEE3', '#E4DDF6', '#FBE4DC', '#DDE8F5', '#EDE7DD'];

  /* ── State ─────────────────────────────────────────────────────── */

  var current = DEFAULT_LOCALE;
  var listeners = [];

  function isSupported(code) {
    for (var i = 0; i < LOCALES.length; i++) if (LOCALES[i].code === code) return true;
    return false;
  }

  function detect() {
    var saved = '';
    try { saved = localStorage.getItem(STORAGE_KEY) || ''; } catch (_) {}
    if (isSupported(saved)) return saved;

    var tags = (global.navigator && (navigator.languages || [navigator.language])) || [];
    for (var i = 0; i < tags.length; i++) {
      var tag = String(tags[i] || '').toLowerCase();
      if (!tag) continue;
      if (tag.indexOf('zh') === 0) {
        if (/hant|tw|hk|mo/.test(tag)) return 'zh-Hant';
        return 'zh-Hans';
      }
      if (tag.indexOf('en') === 0) return 'en';
      if (tag.indexOf('fr') === 0) return 'fr';
      if (tag.indexOf('de') === 0) return 'de';
      if (tag.indexOf('es') === 0) return 'es';
    }
    return DEFAULT_LOCALE;
  }

  function t(key, vars) {
    var table = STRINGS[current] || STRINGS[DEFAULT_LOCALE];
    var out = table[key];
    if (out == null) out = (STRINGS[DEFAULT_LOCALE][key] != null ? STRINGS[DEFAULT_LOCALE][key] : key);
    if (vars) {
      out = out.replace(/\{(\w+)\}/g, function (m, name) {
        return Object.prototype.hasOwnProperty.call(vars, name) ? String(vars[name]) : m;
      });
    }
    return out;
  }

  /* Localized display for one character coming off /api/characters. */
  function character(ch, index) {
    var meta = CHARACTERS[ch.id];
    var tint = (meta && meta.tint) || FALLBACK_TINTS[(index || 0) % FALLBACK_TINTS.length];
    var name = (meta && meta.name && meta.name[current]) || ch.name || ch.id;
    var sub  = (meta && meta.sub && meta.sub[current]) || ch.role || ch.name_en || '';
    return { name: name, sub: sub, tint: tint, art: (meta && meta.art) || ch.icon };
  }

  /* Rewrites every [data-i18n*] node under `root`. */
  function apply(root) {
    var scope = root || document;

    scope.querySelectorAll('[data-i18n]').forEach(function (el) {
      el.textContent = t(el.getAttribute('data-i18n'));
    });

    scope.querySelectorAll('[data-i18n-attr]').forEach(function (el) {
      el.getAttribute('data-i18n-attr').split(',').forEach(function (pair) {
        var bits = pair.split(':');
        if (bits.length === 2) el.setAttribute(bits[0].trim(), t(bits[1].trim()));
      });
    });

    /* The headline highlight is the one place that needs markup. */
    scope.querySelectorAll('[data-i18n-headline]').forEach(function (el) {
      var mark = document.createElement('span');
      mark.className = 'mark';
      mark.textContent = t('hero.line2.mark');
      el.textContent = '';
      el.appendChild(document.createTextNode(t('hero.line1')));
      el.appendChild(document.createElement('br'));
      el.appendChild(document.createTextNode(t('hero.line2.pre')));
      el.appendChild(mark);
      el.appendChild(document.createTextNode(t('hero.line2.post')));
    });

    var titleKey = document.documentElement.getAttribute('data-title-key');
    if (titleKey) document.title = t(titleKey);
  }

  function set(code, opts) {
    if (!isSupported(code)) return;
    current = code;
    try { localStorage.setItem(STORAGE_KEY, code); } catch (_) {}

    var meta = LOCALES.filter(function (l) { return l.code === code; })[0];
    document.documentElement.lang = meta.html;
    document.documentElement.setAttribute('data-locale', code);

    apply();
    if (!opts || !opts.silent) {
      listeners.forEach(function (fn) { try { fn(code); } catch (_) {} });
    }
  }

  /* ── Language switcher widget ──────────────────────────────────
     Builds the globe pill + closed dropdown into `host`.           */
  function mountSwitcher(host) {
    if (!host) return;

    host.classList.add('lang');
    host.innerHTML =
      '<button type="button" class="lang-btn" aria-haspopup="listbox" aria-expanded="false">' +
        '<svg class="globe" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" ' +
             'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
          '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/>' +
          '<path d="M12 3a15 15 0 0 1 0 18a15 15 0 0 1 0-18z"/>' +
        '</svg>' +
        '<span class="lang-current"></span>' +
        '<svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" ' +
             'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 9l7 7 7-7"/></svg>' +
      '</button>' +
      '<div class="lang-menu" role="listbox"></div>';

    var btn = host.querySelector('.lang-btn');
    var label = host.querySelector('.lang-current');
    var menu = host.querySelector('.lang-menu');

    LOCALES.forEach(function (loc) {
      var item = document.createElement('button');
      item.type = 'button';
      item.className = 'lang-item';
      item.setAttribute('role', 'option');
      item.dataset.code = loc.code;
      item.innerHTML =
        '<span>' + loc.native + '</span>' +
        '<svg class="tick" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" ' +
             'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 12.5l5.5 5.5L20 7"/></svg>';
      item.onclick = function () {
        set(loc.code);
        close();
        btn.focus();
      };
      menu.appendChild(item);
    });

    function refresh() {
      var meta = LOCALES.filter(function (l) { return l.code === current; })[0];
      label.textContent = meta.native;
      btn.setAttribute('aria-label', t('lang.aria'));
      menu.querySelectorAll('.lang-item').forEach(function (item) {
        item.setAttribute('aria-checked', String(item.dataset.code === current));
      });
    }

    function open()  { host.classList.add('open');    btn.setAttribute('aria-expanded', 'true'); }
    function close() { host.classList.remove('open'); btn.setAttribute('aria-expanded', 'false'); }

    btn.onclick = function (e) {
      e.stopPropagation();
      host.classList.contains('open') ? close() : open();
    };
    document.addEventListener('click', function (e) { if (!host.contains(e.target)) close(); });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') close(); });

    onChange(refresh);
    refresh();
  }

  function onChange(fn) { if (typeof fn === 'function') listeners.push(fn); }

  /* ── Boot ──────────────────────────────────────────────────────── */

  function init() { set(detect(), { silent: true }); }

  global.I18N = {
    locales: LOCALES,
    init: init,
    t: t,
    get: function () { return current; },
    set: set,
    apply: apply,
    character: character,
    mountSwitcher: mountSwitcher,
    onChange: onChange
  };

  /* Set <html lang>/data-locale before first paint so the CSS that
     keys off the locale (font stack, headline tracking) is correct. */
  init();
})(window);
