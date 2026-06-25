import os
import datetime

# ── Language configuration for log file names and content ────────────────────
LANG_CONFIG = {
    'zh': {
        'filename_prefix':  '专注报告',
        'duration_unit':    '分钟',
        'report_title':     '专注周期总结报告',
        'session_planned':  '预计专注',
        'session_unit':     '分钟',
        'col_timestamp':    '时间戳',
        'col_emotion':      '情绪状态',
        'col_duration':     '持续时长',
        'col_confidence':   '置信度均值',
        'summary_heading':  '周期情绪分布（自动统计）',
        'col_emotion2':     '情绪',
        'col_percent':      '占比',
        'col_total_dur':    '累计时长',
        'miku_says':        'Miku的话',
        'dur_min':          '分',
        'dur_sec':          '秒',
        'emotions': {
            'happy':    '😊 开心',
            'neutral':  '😐 中性',
            'sadness':  '😔 悲伤',
            'anger':    '😠 愤怒',
            'fear':     '😨 焦虑',
            'disgust':  '🤢 厌恶',
            'surprise': '😲 惊讶',
        }
    },
    'ja': {
        'filename_prefix':  '集中記録',
        'duration_unit':    '分',
        'report_title':     '集中セッションレポート',
        'session_planned':  '予定集中時間',
        'session_unit':     '分',
        'col_timestamp':    '時刻',
        'col_emotion':      '感情',
        'col_duration':     '継続時間',
        'col_confidence':   '信頼度',
        'summary_heading':  'セッション感情分布（自動集計）',
        'col_emotion2':     '感情',
        'col_percent':      '割合',
        'col_total_dur':    '累計時間',
        'miku_says':        'ミクからひと言',
        'dur_min':          '分',
        'dur_sec':          '秒',
        'emotions': {
            'happy':    '😊 嬉しい',
            'neutral':  '😐 普通',
            'sadness':  '😔 悲しい',
            'anger':    '😠 怒り',
            'fear':     '😨 恐怖',
            'disgust':  '🤢 嫌悪',
            'surprise': '😲 驚き',
        }
    },
    'en': {
        'filename_prefix':  'focus-report',
        'duration_unit':    'min',
        'report_title':     'Focus Session Report',
        'session_planned':  'Planned Duration',
        'session_unit':     'min',
        'col_timestamp':    'Timestamp',
        'col_emotion':      'Emotion',
        'col_duration':     'Duration',
        'col_confidence':   'Avg Confidence',
        'summary_heading':  'Emotion Distribution (Auto-summarized)',
        'col_emotion2':     'Emotion',
        'col_percent':      'Share',
        'col_total_dur':    'Total Duration',
        'miku_says':        "Miku's Note",
        'dur_min':          'm',
        'dur_sec':          's',
        'emotions': {
            'happy':    '😊 Happy',
            'neutral':  '😐 Neutral',
            'sadness':  '😔 Sad',
            'anger':    '😠 Angry',
            'fear':     '😨 Fearful',
            'disgust':  '🤢 Disgusted',
            'surprise': '😲 Surprised',
        }
    }
}


class LogEntry:
    def __init__(self, timestamp, emotion, confidence, duration=1):
        self.timestamp  = timestamp   # "HH:MM:SS"
        self.emotion    = emotion     # e.g. "happy"
        self.confidence = confidence  # float
        self.duration   = duration    # seconds


class EmotionLogger:
    def __init__(self, log_dir=None):
        if log_dir is None:
            log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
        self.log_dir = log_dir
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir)

        self.log_file                 = None
        self.current_session_entries  = []
        self.session_start_time       = None
        self.session_duration_minutes = 30
        self.current_session_header   = ""
        self._lang                    = 'zh'

    @property
    def lang(self):
        return self._lang

    @lang.setter
    def lang(self, value):
        self._lang = value if value in LANG_CONFIG else 'zh'

    def _cfg(self) -> dict:
        return LANG_CONFIG.get(self._lang, LANG_CONFIG['zh'])

    # ── Session control ───────────────────────────────────────────────────────

    def start_session(self, duration_minutes: int = 30):
        cfg = self._cfg()
        self.current_session_entries  = []
        self.session_duration_minutes = duration_minutes
        self.session_start_time       = datetime.datetime.now()

        date_str = self.session_start_time.strftime("%Y%m%d")
        daily_dir = os.path.join(self.log_dir, date_str)
        if not os.path.exists(daily_dir):
            os.makedirs(daily_dir)

        time_str = self.session_start_time.strftime("%H%M")
        filename = (
            f"{cfg['filename_prefix']}{time_str}"
            f"_{duration_minutes}{cfg['duration_unit']}"
            f"_{date_str}.md"
        )
        self.log_file = os.path.join(daily_dir, filename)

        start_str = self.session_start_time.strftime("%Y-%m-%d %H:%M:%S")
        self.current_session_header = (
            f"# {cfg['report_title']}\n\n"
            f"## Session {start_str}"
            f"（{cfg['session_planned']} {duration_minutes} {cfg['session_unit']}）\n\n"
            f"| {cfg['col_timestamp']} | {cfg['col_emotion']} | {cfg['col_duration']} | {cfg['col_confidence']} |\n"
            f"| :--- | :--- | :--- | :--- |\n"
        )
        self._write_file()
        print(f"Logger: Session started → {filename}")

    def log_emotion(self, emotion: str, confidence: float):
        if self.session_start_time is None:
            return
        now_str = datetime.datetime.now().strftime("%H:%M:%S")
        if not self.current_session_entries:
            self.current_session_entries.append(LogEntry(now_str, emotion, confidence))
        else:
            last = self.current_session_entries[-1]
            if last.emotion == emotion:
                last.confidence = (last.confidence * last.duration + confidence) / (last.duration + 1)
                last.duration  += 1
            else:
                self.current_session_entries.append(LogEntry(now_str, emotion, confidence))
        self._write_file()

    def end_session(self, completed: bool = True, miku_comment: str = ""):
        if self.session_start_time is None:
            return {}, 0

        cfg = self._cfg()
        end_time         = datetime.datetime.now()
        duration_seconds = int((end_time - self.session_start_time).total_seconds())

        emotion_durations: dict = {}
        for entry in self.current_session_entries:
            emotion_durations[entry.emotion] = emotion_durations.get(entry.emotion, 0) + entry.duration

        total_seconds = sum(emotion_durations.values()) or 1
        stats = {em: (emotion_durations.get(em, 0) / total_seconds) * 100
                 for em in cfg['emotions'].keys()}

        # Build summary block
        summary_md  = f"\n## {cfg['summary_heading']}\n"
        summary_md += f"| {cfg['col_emotion2']} | {cfg['col_percent']} | {cfg['col_total_dur']} |\n"
        summary_md += "| :--- | :--- | :--- |\n"
        for emotion, seconds in emotion_durations.items():
            if seconds > 0:
                label   = cfg['emotions'].get(emotion, emotion)
                percent = (seconds / total_seconds) * 100
                dur_str = f"{seconds // 60}{cfg['dur_min']}{seconds % 60}{cfg['dur_sec']}"
                summary_md += f"| {label} | {percent:.1f}% | {dur_str} |\n"

        summary_md += f'\n## {cfg["miku_says"]}\n> "{miku_comment}"\n\n---\n\n'

        try:
            if self.log_file:
                with open(self.log_file, 'a', encoding='utf-8') as f:
                    f.write(summary_md)

                # Rename to reflect actual duration
                actual_minutes = duration_seconds // 60
                date_str  = self.session_start_time.strftime("%Y%m%d")
                time_str  = self.session_start_time.strftime("%H%M")
                new_name  = (
                    f"{cfg['filename_prefix']}{time_str}"
                    f"_{actual_minutes}{cfg['duration_unit']}"
                    f"_{date_str}.md"
                )
                new_path = os.path.join(self.log_dir, date_str, new_name)
                if new_path != self.log_file and os.path.exists(self.log_file):
                    os.rename(self.log_file, new_path)
                    self.log_file = new_path
        except Exception as e:
            print(f"Logger: Error finalizing session — {e}")

        self.session_start_time      = None
        self.current_session_entries = []
        return stats, duration_seconds // 60

    # ── Internal ──────────────────────────────────────────────────────────────

    def _format_duration(self, seconds: int) -> str:
        m, s = divmod(seconds, 60)
        return f"{m:02d}:{s:02d}"

    def _write_file(self):
        if not self.log_file:
            return
        cfg = self._cfg()
        rows = []
        for entry in self.current_session_entries:
            label   = cfg['emotions'].get(entry.emotion, entry.emotion)
            dur_str = self._format_duration(entry.duration)
            rows.append(
                f"| {entry.timestamp} | {label} | {dur_str} | {entry.confidence:.2f} |"
            )
        content = self.current_session_header + "\n".join(rows) + "\n"
        try:
            with open(self.log_file, 'w', encoding='utf-8') as f:
                f.write(content)
        except Exception as e:
            print(f"Logger: Write error — {e}")


if __name__ == '__main__':
    import time
    for lang in ['zh', 'ja', 'en']:
        print(f"\n=== Testing lang={lang} ===")
        logger = EmotionLogger()
        logger.lang = lang
        logger.start_session(duration_minutes=1)
        logger.log_emotion('neutral', 0.9)
        time.sleep(0.1)
        logger.log_emotion('happy', 0.85)
        stats, mins = logger.end_session(completed=True, miku_comment="Test!")
        print("Stats:", stats, "Duration:", mins)
