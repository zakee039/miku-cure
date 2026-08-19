import os
import datetime
import time
import threading
from dataclasses import dataclass

# ── Language configuration for log file names and content ────────────────────
LANG_CONFIG = {
    'zh': {
        'filename_prefix':  '专注报告',
        'duration_unit':    '分钟',
        'report_title':     '专注周期总结报告',
        'session_planned':  '预计专注',
        'session_actual':   '实际专注',
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
            'contempt': '😒 轻蔑',
        }
    },
    'ja': {
        'filename_prefix':  '集中記録',
        'duration_unit':    '分',
        'report_title':     '集中セッションレポート',
        'session_planned':  '予定集中時間',
        'session_actual':   '実際の集中時間',
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
            'contempt': '😒 軽蔑',
        }
    },
    'en': {
        'filename_prefix':  'focus-report',
        'duration_unit':    'min',
        'report_title':     'Focus Session Report',
        'session_planned':  'Planned Duration',
        'session_actual':   'Actual Duration',
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
            'contempt': '😒 Contempt',
        }
    }
}

# Emotions that must never enter focus statistics
SKIP_EMOTIONS = frozenset({'no_face', '', None})


@dataclass
class LogEntry:
    timestamp: str
    emotion: str
    confidence: float
    duration: float = 0.0
    samples: int = 1


@dataclass(frozen=True)
class SessionEntry:
    timestamp: str
    emotion: str
    confidence: float
    duration: float
    samples: int


@dataclass(frozen=True)
class SessionSnapshot:
    start_time: datetime.datetime
    end_time: datetime.datetime
    planned_minutes: int
    lang: str
    header: str
    log_file: str
    entries: tuple


class EmotionLogger:
    def __init__(self, log_dir=None, flush_interval_sec=15.0, max_sample_gap_sec=3.0):
        if log_dir is None:
            # Packaged apps may set MIKU_USER_DIR; logs still live under project/logs by default
            root = os.environ.get('MIKU_RESOURCES') or os.path.dirname(os.path.dirname(__file__))
            log_dir = os.path.join(root, 'logs')
        self.log_dir = log_dir
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir)

        self.log_file                 = None
        self.current_session_entries  = []
        self.session_start_time       = None
        self.session_duration_minutes = 30
        self.current_session_header   = ""
        self._lang                    = 'zh'
        self._session_lang            = None
        self._dirty                   = False
        self._last_flush              = 0.0
        self.flush_interval_sec       = flush_interval_sec
        self.max_sample_gap_sec       = max(0.1, float(max_sample_gap_sec))
        self._last_observation_at     = None
        self._last_observation_emotion = None
        self._lock                    = threading.RLock()

    @property
    def lang(self):
        return self._lang

    @lang.setter
    def lang(self, value):
        self._lang = value if value in LANG_CONFIG else 'zh'

    def _cfg(self) -> dict:
        return LANG_CONFIG.get(self._lang, LANG_CONFIG['zh'])

    def start_session(self, duration_minutes: int = 30):
        with self._lock:
            if self.session_start_time is not None:
                raise RuntimeError('A focus session is already active')
            cfg = self._cfg()
            self._session_lang = self._lang
            self.current_session_entries = []
            self.session_duration_minutes = int(duration_minutes)
            self.session_start_time = datetime.datetime.now()
            self._dirty = False
            self._last_flush = time.monotonic()
            self._last_observation_at = None
            self._last_observation_emotion = None

            date_str = self.session_start_time.strftime("%Y%m%d")
            daily_dir = os.path.join(self.log_dir, date_str)
            os.makedirs(daily_dir, exist_ok=True)

            time_str = self.session_start_time.strftime("%H%M%S")
            filename = (
                f"{cfg['filename_prefix']}{time_str}"
                f"_{duration_minutes}{cfg['duration_unit']}"
                f"_{date_str}.md"
            )
            self.log_file = self._unique_path(os.path.join(daily_dir, filename))

            start_str = self.session_start_time.strftime("%Y-%m-%d %H:%M:%S")
            self.current_session_header = (
                f"# {cfg['report_title']}\n\n"
                f"## Session {start_str}"
                f"（{cfg['session_planned']} {duration_minutes} {cfg['session_unit']}）\n\n"
                f"| {cfg['col_timestamp']} | {cfg['col_emotion']} | {cfg['col_duration']} | {cfg['col_confidence']} |\n"
                f"| :--- | :--- | :--- | :--- |\n"
            )
            self._write_file_locked()
            print(f"Logger: Session started → {os.path.basename(self.log_file)}")

    def _close_observation_locked(self, now_mono):
        if self._last_observation_at is None:
            return
        elapsed = max(0.0, now_mono - self._last_observation_at)
        if (
            self._last_observation_emotion not in SKIP_EMOTIONS
            and elapsed <= self.max_sample_gap_sec
            and self.current_session_entries
            and self.current_session_entries[-1].emotion == self._last_observation_emotion
        ):
            self.current_session_entries[-1].duration += elapsed

    def break_observation(self):
        """End the current measured segment without attributing a later gap."""
        with self._lock:
            if self.session_start_time is None:
                return
            self._close_observation_locked(time.monotonic())
            self._last_observation_at = None
            self._last_observation_emotion = None
            self._dirty = True

    def log_emotion(self, emotion: str, confidence: float, observed_at=None):
        """Record elapsed wall time between observations, not detector sample count."""
        now_mono = time.monotonic() if observed_at is None else float(observed_at)
        with self._lock:
            if self.session_start_time is None:
                return

            self._close_observation_locked(now_mono)
            if emotion in SKIP_EMOTIONS:
                self._last_observation_emotion = None
            else:
                confidence = max(0.0, min(1.0, float(confidence)))
                now_str = datetime.datetime.now().strftime("%H:%M:%S")
                if not self.current_session_entries or self.current_session_entries[-1].emotion != emotion:
                    self.current_session_entries.append(LogEntry(now_str, emotion, confidence))
                else:
                    last = self.current_session_entries[-1]
                    last.confidence = (
                        (last.confidence * last.samples + confidence) / (last.samples + 1)
                    )
                    last.samples += 1
                self._last_observation_emotion = emotion

            self._last_observation_at = now_mono
            self._dirty = True
            if time.monotonic() - self._last_flush >= self.flush_interval_sec:
                self._write_file_locked()

    def detach_session(self):
        """Atomically detach an immutable session so a new one can start immediately."""
        with self._lock:
            if self.session_start_time is None:
                return None
            self._close_observation_locked(time.monotonic())
            if self._dirty:
                self._write_file_locked()
            snapshot = SessionSnapshot(
                start_time=self.session_start_time,
                end_time=datetime.datetime.now(),
                planned_minutes=self.session_duration_minutes,
                lang=self._session_lang or self._lang,
                header=self.current_session_header,
                log_file=self.log_file,
                entries=tuple(
                    SessionEntry(
                        entry.timestamp,
                        entry.emotion,
                        entry.confidence,
                        entry.duration,
                        entry.samples,
                    )
                    for entry in self.current_session_entries
                ),
            )
            self.session_start_time = None
            self.current_session_entries = []
            self.current_session_header = ''
            self.log_file = None
            self._session_lang = None
            self._last_observation_at = None
            self._last_observation_emotion = None
            self._dirty = False
            return snapshot

    @staticmethod
    def _emotion_stats(snapshot, cfg):
        durations = {}
        samples = {}
        for entry in snapshot.entries:
            if entry.emotion in SKIP_EMOTIONS:
                continue
            durations[entry.emotion] = durations.get(entry.emotion, 0.0) + entry.duration
            samples[entry.emotion] = samples.get(entry.emotion, 0) + entry.samples
        total = sum(durations.values())
        if total > 0:
            stats = {
                em: (durations.get(em, 0.0) / total) * 100
                for em in cfg['emotions'].keys()
            }
        else:
            sample_total = sum(samples.values()) or 1
            stats = {
                em: (samples.get(em, 0) / sample_total) * 100
                for em in cfg['emotions'].keys()
            }
        return durations, stats

    def stats_for_snapshot(self, snapshot):
        if snapshot is None:
            return {}
        cfg = LANG_CONFIG.get(snapshot.lang, LANG_CONFIG['zh'])
        return self._emotion_stats(snapshot, cfg)[1]

    def end_session(
        self,
        completed: bool = True,
        miku_comment: str = "",
        paused_seconds: int = 0,
        min_save_seconds: int = 0,
    ):
        snapshot = self.detach_session()
        if snapshot is None:
            return {}, 0
        stats, actual_minutes, final_path = self.finalize_session(
            snapshot,
            completed=completed,
            miku_comment=miku_comment,
            paused_seconds=paused_seconds,
            min_save_seconds=min_save_seconds,
        )
        with self._lock:
            if self.session_start_time is None:
                self.log_file = final_path
        return stats, actual_minutes

    def finalize_session(
        self,
        snapshot,
        completed=True,
        miku_comment='',
        paused_seconds=0,
        min_save_seconds=0,
    ):
        """Finalize a detached session without touching any newer active session."""
        if snapshot is None:
            return {}, 0, None
        cfg = LANG_CONFIG.get(snapshot.lang, LANG_CONFIG['zh'])
        wall_seconds = max(0, int((snapshot.end_time - snapshot.start_time).total_seconds()))
        duration_seconds = max(0, wall_seconds - max(0, int(paused_seconds)))
        emotion_durations, stats = self._emotion_stats(snapshot, cfg)
        total_seconds = sum(emotion_durations.values()) or 1.0
        actual_minutes = duration_seconds // 60

        # Drop accidental ultra-short sessions (no useful report)
        if min_save_seconds and duration_seconds < min_save_seconds:
            try:
                if snapshot.log_file and os.path.exists(snapshot.log_file):
                    os.remove(snapshot.log_file)
                    print(f"Logger: Discarded short session ({duration_seconds}s < {min_save_seconds}s)")
            except Exception as e:
                print(f"Logger: Failed to discard short session: {e}")
            return stats, actual_minutes, None

        summary_md  = f"\n## {cfg['summary_heading']}\n"
        summary_md += f"**{cfg['session_actual']}: {actual_minutes} {cfg['session_unit']}**\n"
        if paused_seconds > 0:
            pm, ps = divmod(int(paused_seconds), 60)
            summary_md += f"**Paused: {pm}{cfg['dur_min']}{ps}{cfg['dur_sec']}**\n"
        summary_md += "\n"
        summary_md += f"| {cfg['col_emotion2']} | {cfg['col_percent']} | {cfg['col_total_dur']} |\n"
        summary_md += "| :--- | :--- | :--- |\n"
        for emotion, seconds in emotion_durations.items():
            if seconds > 0:
                label   = cfg['emotions'].get(emotion, emotion)
                percent = (seconds / total_seconds) * 100
                whole_seconds = max(0, int(round(seconds)))
                dur_str = f"{whole_seconds // 60}{cfg['dur_min']}{whole_seconds % 60}{cfg['dur_sec']}"
                summary_md += f"| {label} | {percent:.1f}% | {dur_str} |\n"

        summary_md += f'\n## {cfg["miku_says"]}\n> "{miku_comment}"\n\n---\n\n'

        try:
            final_path = snapshot.log_file
            if final_path:
                with open(final_path, 'a', encoding='utf-8') as f:
                    f.write(summary_md)

                date_str = snapshot.start_time.strftime("%Y%m%d")
                time_str = snapshot.start_time.strftime("%H%M%S")
                new_name  = (
                    f"{cfg['filename_prefix']}{time_str}"
                    f"_{actual_minutes}{cfg['duration_unit']}"
                    f"_{date_str}.md"
                )
                new_path = os.path.join(self.log_dir, date_str, new_name)
                if new_path != final_path and os.path.exists(final_path):
                    with self._lock:
                        new_path = self._unique_path(new_path, exclude=final_path)
                        os.rename(final_path, new_path)
                        final_path = new_path
        except Exception as e:
            print(f"Logger: Error finalizing session — {e}")
            final_path = snapshot.log_file
        return stats, actual_minutes, final_path

    def _format_duration(self, seconds: float) -> str:
        m, s = divmod(max(0, int(round(seconds))), 60)
        return f"{m:02d}:{s:02d}"

    @staticmethod
    def _unique_path(path, exclude=None):
        if path == exclude or not os.path.exists(path):
            return path
        stem, ext = os.path.splitext(path)
        index = 2
        while True:
            candidate = f"{stem}_{index}{ext}"
            if candidate == exclude or not os.path.exists(candidate):
                return candidate
            index += 1

    def _write_file(self):
        with self._lock:
            self._write_file_locked()

    def _write_file_locked(self):
        if not self.log_file:
            return
        cfg = LANG_CONFIG.get(self._session_lang or self._lang, LANG_CONFIG['zh'])
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
            self._dirty = False
            self._last_flush = time.monotonic()
        except Exception as e:
            print(f"Logger: Write error — {e}")


if __name__ == '__main__':
    for lang in ['zh', 'ja', 'en']:
        print(f"\n=== Testing lang={lang} ===")
        logger = EmotionLogger()
        logger.lang = lang
        logger.start_session(duration_minutes=1)
        logger.log_emotion('neutral', 0.9)
        logger.log_emotion('no_face', 0.0)  # should be skipped
        logger.log_emotion('happy', 0.85)
        logger.log_emotion('contempt', 0.7)
        stats, mins = logger.end_session(completed=True, miku_comment="Test!")
        print("Stats:", stats, "Duration:", mins)
