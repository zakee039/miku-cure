// ── i18n.js ─────────────────────────────────────────────────────────────────
// Miku Cure 三语翻译模块 (中文 / 日本語 / English)
// Usage: const { t, applyI18n, getCurrentLang } = require('./i18n');

const translations = {
  /* ── 中文 ─────────────────────────────────────────────────── */
  zh: {
    // Settings Navigation
    'nav.model':   '模型',
    'nav.general': '通用',
    'nav.about':   '关于',

    // Model Page
    'model.title':          '模型选择',
    'model.engine.label':   '推理引擎',
    'model.cnn.name':       'Custom PyTorch CNN',
    'model.cnn.desc':       '轻量级自训练模型，支持完全离线运行。',
    'model.deepface.name':  'DeepFace（预训练）',
    'model.deepface.desc':  '识别精度更高，需要本地预训练模型文件。',
    'model.mock.name':      '亮度模拟器',
    'model.mock.desc':      '基于画面亮度的模拟模式，无需摄像头。',
    'model.tip':            '切换推理引擎后，后端将自动热重载，无需手动重启。',

    // General Page
    'general.title':       '通用设置',
    'general.size.label':  '窗口大小',
    'general.lang.label':  '界面语言',
    'size.small':          '小（67%）',
    'size.medium':         '中（默认）',
    'size.large':          '大（150%）',
    'lang.zh':             '中文',
    'lang.ja':             '日本語',
    'lang.en':             'English',

    // About Page
    'about.title':         '关于',
    'about.desc':          '一款由实时面部表情识别和 DeepSeek AI 驱动的桌面情绪伴侣。',
    'about.privacy':       '🔒 本系统没有服务器，不会上传任何数据。',
    'about.thanks.label':  '特别鸣谢',
    'about.thanks.desc':   '感谢 miratsu169 的贡献与支持。',
    'about.github':        'github.com/momo325/miku-cure',

    // Main Window — Emotion Badge
    'emotion.neutral':     '中性',
    'emotion.happy':       '开心',
    'emotion.sadness':     '悲伤',
    'emotion.anger':       '愤怒',
    'emotion.fear':        '恐惧',
    'emotion.disgust':     '厌恶',
    'emotion.surprise':    '惊讶',
    'emotion.disconnected':'已断开',
    'emotion.connecting':  '连接中...',

    // Main Window — Buttons & Labels
    'btn.start_focus':     '开始专注',
    'unit.min':            '分',
    'btn.dance':           '跳舞',
    'btn.sing':            '唱歌',
    'btn.bubble_dance':    '💃 跳舞',
    'btn.bubble_sing':     '🎵 唱歌',
    'btn.bubble_dismiss':  '下次吧',
    'player.no_song':      '当前无播放',
    'btn.chat':            '聊天',
    'chat.title':          '与 Miku 聊天',
    'chat.welcome':        '你好呀！今天感觉怎么样呢？',
    'chat.placeholder':    '说点什么...',
    'chat.send':           '发送',
    'chat.analyze_report_msg': 'miku，miku，帮我分析一下报告',

    // Tooltips
    'tip.emotion_badge':   '点击断开/连接摄像头',
    'tip.timer':           '开始专注（番茄钟）',
    'tip.settings':        '打开设置',
    'tip.talent':          'Miku 才艺演示',
    'tip.close':           '关闭挂件',
    'tip.prev':            '上一首',
    'tip.play':            '播放/暂停',
    'tip.next':            '下一首',
    'tip.player_close':    '关闭播放器',
    'tip.dance_next':      '下一个舞蹈',
    'tip.dance_close':     '停止跳舞',
    'tip.pause':           '暂停/继续',
    'tip.stop':            '终止',

    // Status messages (used in renderer.js)
    'status.idle':         '😐 正在静静陪伴你',
    'status.dancing':      '💃 正在为你跳舞中...',
    'status.singing':      '🎵 正在为你唱歌中...',
    'status.paused':       '⏸️ 音乐已暂停',
    'status.interrupted':  '😐 专注被中断啊',
    'status.focus':        '🍅 专注中 ({min}分钟)',
    'status.no_dance':     'Miku 发现没有放跳舞视频哦（在 miku/dance 目录）',
    'status.no_sing':      'Miku 发现没有放歌曲音频哦（在 miku/sing 目录）',

    // Report window
    'report.title':        '专注周期总结报告',
    'report.loading':      '加载中...',
    'report.miku_says':    'Miku的话：',
    'report.btn_sing':     '听miku唱歌',
    'report.btn_dance':    '看miku跳舞',
    'report.btn_close':    '谢谢miku',
    'report.btn_analyze':  '让miku分析',

    // API Settings
    'api.title':           'API 设置',
    'api.active.label':    '当前使用',
    'api.active.api':      '接口',
    'api.active.model':    '模型',
    'api.list.title':      '已配置的 API',
    'api.add':             '添加 API',
    'api.form.name':       '名称',
    'api.form.url':        'Base URL',
    'api.form.key':        'API Key',
    'api.form.models':     '模型列表（逗号分隔）',
    'api.form.save':       '保存',
    'api.form.cancel':     '取消',
    'api.edit':            '编辑',
    'api.delete':          '删除',
    'api.none':            '请添加并选择 API',
    'api.no_model':        '请先选择 API',
    'api.fetching_models': '获取中...',
    'btn.train':           '去训练',
  },

  /* ── 日本語 ─────────────────────────────────────────────────── */
  ja: {
    // Settings Navigation
    'nav.model':   'モデル',
    'nav.general': '一般',
    'nav.about':   'について',

    // Model Page
    'model.title':          'モデル選択',
    'model.engine.label':   '推論エンジン',
    'model.cnn.name':       'Custom PyTorch CNN',
    'model.cnn.desc':       '軽量な自己学習モデル。オフラインで動作します。',
    'model.deepface.name':  'DeepFace（事前学習済み）',
    'model.deepface.desc':  '高精度。ローカルのモデルファイルが必要です。',
    'model.mock.name':      '輝度シミュレーター',
    'model.mock.desc':      '輝度ベースのシミュレーション。カメラ不要。',
    'model.tip':            'エンジンを切り替えると、バックエンドが自動リロードされます。再起動不要。',

    // General Page
    'general.title':       '一般設定',
    'general.size.label':  'ウィンドウサイズ',
    'general.lang.label':  '表示言語',
    'size.small':          '小（67%）',
    'size.medium':         '中（デフォルト）',
    'size.large':          '大（150%）',
    'lang.zh':             '中文',
    'lang.ja':             '日本語',
    'lang.en':             'English',

    // About Page
    'about.title':         'について',
    'about.desc':          'リアルタイム表情認識と DeepSeek AI を搭載したデスクトップ感情コンパニオン。',
    'about.privacy':       '🔒 サーバーがなく、データは一切アップロードされません。',
    'about.thanks.label':  'スペシャルサンクス',
    'about.thanks.desc':   'miratsu169 さんのご貢献とご支援に感謝します。',
    'about.github':        'github.com/momo325/miku-cure',

    // Main Window — Emotion Badge
    'emotion.neutral':     '普通',
    'emotion.happy':       '嬉しい',
    'emotion.sadness':     '悲しい',
    'emotion.anger':       '怒り',
    'emotion.fear':        '恐怖',
    'emotion.disgust':     '嫌悪',
    'emotion.surprise':    '驚き',
    'emotion.disconnected':'切断済み',
    'emotion.connecting':  '接続中...',

    // Main Window — Buttons & Labels
    'btn.start_focus':     '集中開始',
    'unit.min':            '分',
    'btn.dance':           'ダンス',
    'btn.sing':            '歌う',
    'btn.bubble_dance':    '💃 ダンス',
    'btn.bubble_sing':     '🎵 歌う',
    'btn.bubble_dismiss':  '今度ね',
    'player.no_song':      '再生中なし',
    'btn.chat':            'チャット',
    'chat.title':          'ミクとチャット',
    'chat.welcome':        'やっほー！今日はどんな感じ？',
    'chat.placeholder':    '何か話して...',
    'chat.send':           '送信',
    'chat.analyze_report_msg': 'ミク、ミク、レポートを分析して',

    // Tooltips
    'tip.emotion_badge':   'クリックでカメラ切断/接続',
    'tip.timer':           '集中タイマー（ポモドーロ）',
    'tip.settings':        '設定を開く',
    'tip.talent':          'Miku のパフォーマンス',
    'tip.close':           'ウィジェットを閉じる',
    'tip.prev':            '前の曲',
    'tip.play':            '再生/一時停止',
    'tip.next':            '次の曲',
    'tip.player_close':    'プレーヤーを閉じる',
    'tip.dance_next':      '次のダンス',
    'tip.dance_close':     'ダンスを停止',
    'tip.pause':           '一時停止/再開',
    'tip.stop':            '終了',

    // Status messages
    'status.idle':         '😐 静かにそばにいるよ',
    'status.dancing':      '💃 踊っているよ...',
    'status.singing':      '🎵 歌っているよ...',
    'status.paused':       '⏸️ 音楽を一時停止中',
    'status.interrupted':  '😐 集中が中断されました',
    'status.focus':        '🍅 集中中 ({min}分)',
    'status.no_dance':     'ダンス動画が見つかりません（miku/dance フォルダ）',
    'status.no_sing':      '音楽ファイルが見つかりません（miku/sing フォルダ）',

    // Report window
    'report.title':        '集中セッションレポート',
    'report.loading':      '読み込み中...',
    'report.miku_says':    'ミクからひと言：',
    'report.btn_sing':     'ミクに歌ってもらう',
    'report.btn_dance':    'ミクのダンスを見る',
    'report.btn_close':    'ありがとう',
    'report.btn_analyze':  'ミクに分析してもらう',

    // API Settings
    'api.title':           'API 設定',
    'api.active.label':    '現在の設定',
    'api.active.api':      'API',
    'api.active.model':    'モデル',
    'api.list.title':      '登録済み API',
    'api.add':             'API を追加',
    'api.form.name':       '名前',
    'api.form.url':        'Base URL',
    'api.form.key':        'API Key',
    'api.form.models':     'モデル一覧（カンマ区切り）',
    'api.form.save':       '保存',
    'api.form.cancel':     'キャンセル',
    'api.edit':            '編集',
    'api.delete':          '削除',
    'api.none':            'APIを追加して選択してください',
    'api.no_model':        'まず API を選択してください',
    'api.fetching_models': '取得中...',
    'btn.train':           '学習へ',
  },

  /* ── English ─────────────────────────────────────────────────── */
  en: {
    // Settings Navigation
    'nav.model':   'Model',
    'nav.general': 'General',
    'nav.about':   'About',

    // Model Page
    'model.title':          'Model Selection',
    'model.engine.label':   'Inference Engine',
    'model.cnn.name':       'Custom PyTorch CNN',
    'model.cnn.desc':       'Lightweight self-trained model. Works fully offline.',
    'model.deepface.name':  'DeepFace (Pretrained)',
    'model.deepface.desc':  'Higher accuracy. Requires local model files.',
    'model.mock.name':      'Brightness Simulator',
    'model.mock.desc':      'Brightness-based mock mode. No camera needed.',
    'model.tip':            'Switching the engine triggers a hot-reload in the backend — no restart required.',

    // General Page
    'general.title':       'General Settings',
    'general.size.label':  'Window Size',
    'general.lang.label':  'Interface Language',
    'size.small':          'Small (67%)',
    'size.medium':         'Medium (Default)',
    'size.large':          'Large (150%)',
    'lang.zh':             '中文',
    'lang.ja':             '日本語',
    'lang.en':             'English',

    // About Page
    'about.title':         'About',
    'about.desc':          'A desktop emotion companion powered by real-time facial expression recognition and DeepSeek AI.',
    'about.privacy':       '🔒 No server. No data is ever uploaded.',
    'about.thanks.label':  'Special Thanks',
    'about.thanks.desc':   'Thanks to miratsu169 for their contribution and support.',
    'about.github':        'github.com/momo325/miku-cure',

    // Main Window — Emotion Badge
    'emotion.neutral':     'Neutral',
    'emotion.happy':       'Happy',
    'emotion.sadness':     'Sad',
    'emotion.anger':       'Angry',
    'emotion.fear':        'Fearful',
    'emotion.disgust':     'Disgusted',
    'emotion.surprise':    'Surprised',
    'emotion.disconnected':'Disconnected',
    'emotion.connecting':  'Connecting...',

    // Main Window — Buttons & Labels
    'btn.start_focus':     'Start Focus',
    'unit.min':            'min',
    'btn.dance':           'Dance',
    'btn.sing':            'Sing',
    'btn.bubble_dance':    '💃 Dance',
    'btn.bubble_sing':     '🎵 Sing',
    'btn.bubble_dismiss':  'Maybe later',
    'player.no_song':      'Nothing playing',
    'btn.chat':            'Chat',
    'chat.title':          'Chat with Miku',
    'chat.welcome':        'Hello there! How are you feeling today?',
    'chat.placeholder':    'Say something...',
    'chat.send':           'Send',
    'chat.analyze_report_msg': 'Miku, Miku, please analyze my report',

    // Tooltips
    'tip.emotion_badge':   'Click to toggle camera',
    'tip.timer':           'Start Focus Timer (Pomodoro)',
    'tip.settings':        'Open Settings',
    'tip.talent':          'Miku Talent Show',
    'tip.close':           'Close Widget',
    'tip.prev':            'Previous',
    'tip.play':            'Play / Pause',
    'tip.next':            'Next',
    'tip.player_close':    'Close Player',
    'tip.dance_next':      'Next Dance',
    'tip.dance_close':     'Stop Dancing',
    'tip.pause':           'Pause / Resume',
    'tip.stop':            'Stop',

    // Status messages
    'status.idle':         '😐 Quietly keeping you company',
    'status.dancing':      '💃 Dancing for you...',
    'status.singing':      '🎵 Singing for you...',
    'status.paused':       '⏸️ Music paused',
    'status.interrupted':  '😐 Focus session interrupted',
    'status.focus':        '🍅 Focusing ({min} min)',
    'status.no_dance':     'No dance videos found (place in miku/dance folder)',
    'status.no_sing':      'No audio files found (place in miku/sing folder)',

    // Report window
    'report.title':        'Focus Session Report',
    'report.loading':      'Loading...',
    'report.miku_says':    "Miku's note:",
    'report.btn_sing':     'Hear Miku sing',
    'report.btn_dance':    'Watch Miku dance',
    'report.btn_close':    'Thanks Miku!',
    'report.btn_analyze':  'Let Miku Analyze',

    // API Settings
    'api.title':           'API Settings',
    'api.active.label':    'Currently active',
    'api.active.api':      'API',
    'api.active.model':    'Model',
    'api.list.title':      'Configured APIs',
    'api.add':             'Add API',
    'api.form.name':       'Name',
    'api.form.url':        'Base URL',
    'api.form.key':        'API Key',
    'api.form.models':     'Model list (comma-separated)',
    'api.form.save':       'Save',
    'api.form.cancel':     'Cancel',
    'api.edit':            'Edit',
    'api.delete':          'Delete',
    'api.none':            'Please add and select an API',
    'api.no_model':        'Select an API first',
    'api.fetching_models': 'Fetching...',
    'btn.train':           'Go Train',
  }
};

// ── Utilities ────────────────────────────────────────────────────────────────

/** Get the currently saved language code (defaults to 'zh'). */
function getCurrentLang() {
  try { return localStorage.getItem('miku-language') || 'zh'; } catch { return 'zh'; }
}

/**
 * Translate a key for the current language, with optional variable substitution.
 * e.g. t('status.focus', { min: 25 }) => '🍅 专注中 (25分钟)'
 */
function t(key, vars) {
  const lang = getCurrentLang();
  const dict = translations[lang] || translations['zh'];
  let str = dict[key] ?? translations['zh'][key] ?? key;
  if (vars) {
    Object.entries(vars).forEach(([k, v]) => {
      str = str.replace(new RegExp(`\\{${k}\\}`, 'g'), v);
    });
  }
  return str;
}

/**
 * Apply translations to all elements with data-i18n / data-i18n-title attributes
 * in the current document. Safe to call on DOMContentLoaded or after language change.
 */
function applyI18n() {
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    el.textContent = t(key);
  });
  document.querySelectorAll('[data-i18n-title]').forEach(el => {
    el.title = t(el.getAttribute('data-i18n-title'));
  });
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    el.placeholder = t(el.getAttribute('data-i18n-placeholder'));
  });
}

module.exports = { translations, t, getCurrentLang, applyI18n };
