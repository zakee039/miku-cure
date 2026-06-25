import os
import datetime

class LogEntry:
    def __init__(self, timestamp, emotion, confidence, duration=1):
        self.timestamp = timestamp  # string "HH:MM:SS"
        self.emotion = emotion      # string (e.g. "happy")
        self.confidence = confidence # float
        self.duration = duration    # int (seconds)

class EmotionLogger:
    EMOTION_CHINESE = {
        'happy': '😊 开心',
        'neutral': '😐 中性',
        'sadness': '😔 悲伤',
        'anger': '😠 愤怒',
        'fear': '😨 焦虑',
        'disgust': '🤢 厌恶',
        'surprise': '😲 惊讶'
      }

    def __init__(self, log_dir=None):
        if log_dir is None:
            # Default to logs/ in project root
            log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
            
        self.log_dir = log_dir
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir)
            
        self.log_file = None
        self.current_session_entries = []
        self.session_start_time = None
        self.session_duration_minutes = 30

    def start_session(self, duration_minutes=30):
        self.current_session_entries = []
        self.session_duration_minutes = duration_minutes
        self.session_start_time = datetime.datetime.now()
        
        date_str = self.session_start_time.strftime("%Y%m%d")
        daily_log_dir = os.path.join(self.log_dir, date_str)
        if not os.path.exists(daily_log_dir):
            os.makedirs(daily_log_dir)
        
        # 专注报告{时分}_{持续时长}_{年月日}.md (Target duration initially)
        time_str = self.session_start_time.strftime("%H%M")
        filename = f"专注报告{time_str}_{duration_minutes}分钟_{date_str}.md"
        self.log_file = os.path.join(daily_log_dir, filename)
        
        start_str = self.session_start_time.strftime("%Y-%m-%d %H:%M:%S")
        self.current_session_header = f"# 专注周期总结报告\n\n## Session {start_str}（预计专注 {duration_minutes} 分钟）\n\n"
        self.current_session_header += "| 时间戳 | 情绪状态 | 持续时长 | 置信度均值 |\n"
        self.current_session_header += "| :--- | :--- | :--- | :--- |\n"
        
        self._write_file()
        print(f"Started logging session at {start_str} to {filename}")

    def log_emotion(self, emotion, confidence):
        if self.session_start_time is None:
            return  # No active session
            
        now_str = datetime.datetime.now().strftime("%H:%M:%S")
        
        if not self.current_session_entries:
            entry = LogEntry(now_str, emotion, confidence)
            self.current_session_entries.append(entry)
        else:
            last = self.current_session_entries[-1]
            if last.emotion == emotion:
                # Same emotion: update duration and running confidence average
                last.confidence = (last.confidence * last.duration + confidence) / (last.duration + 1)
                last.duration += 1
            else:
                # New emotion: append new entry
                entry = LogEntry(now_str, emotion, confidence)
                self.current_session_entries.append(entry)
                
        self._write_file()

    def _format_duration(self, seconds):
        m = seconds // 60
        s = seconds % 60
        return f"{m:02d}:{s:02d}"

    def _write_file(self):
        if not self.log_file:
            return
            
        table_rows = []
        for entry in self.current_session_entries:
            emotion_zh = self.EMOTION_CHINESE.get(entry.emotion, entry.emotion)
            dur_str = self._format_duration(entry.duration)
            table_rows.append(f"| {entry.timestamp} | {emotion_zh} | {dur_str} | {entry.confidence:.2f} |")
            
        session_markdown = self.current_session_header + "\n".join(table_rows) + "\n"
        
        try:
            with open(self.log_file, 'w', encoding='utf-8') as f:
                f.write(session_markdown)
        except Exception as e:
            print(f"Error writing to log file: {e}")

    def end_session(self, completed=True, miku_comment=""):
        if self.session_start_time is None:
            return {}
            
        end_time = datetime.datetime.now()
        duration_seconds = int((end_time - self.session_start_time).total_seconds())
        
        # Calculate emotion statistics
        emotion_durations = {}
        for entry in self.current_session_entries:
            emotion_durations[entry.emotion] = emotion_durations.get(entry.emotion, 0) + entry.duration
            
        total_seconds = sum(emotion_durations.values()) or 1
        
        stats = {}
        for emotion in self.EMOTION_CHINESE.keys():
            dur = emotion_durations.get(emotion, 0)
            stats[emotion] = (dur / total_seconds) * 100
            
        # Append stats summary block to the file
        summary_md = "\n## 周期情绪分布（自动统计）\n"
        summary_md += "| 情绪 | 占比 | 累计时长 |\n"
        summary_md += "| :--- | :--- | :--- |\n"
        for emotion, seconds in emotion_durations.items():
            if seconds > 0:
                emotion_zh = self.EMOTION_CHINESE.get(emotion, emotion)
                percent = (seconds / total_seconds) * 100
                dur_str = f"{seconds // 60}分{seconds % 60}秒"
                summary_md += f"| {emotion_zh} | {percent:.1f}% | {dur_str} |\n"
            
        summary_md += f"\n## Miku的话\n> \"{miku_comment}\"\n\n---\n\n"
        
        try:
            if self.log_file:
                with open(self.log_file, 'a', encoding='utf-8') as f:
                    f.write(summary_md)
                
                # Rename the file to reflect actual duration
                actual_minutes = duration_seconds // 60
                date_str = self.session_start_time.strftime("%Y%m%d")
                time_str = self.session_start_time.strftime("%H%M")
                new_filename = f"专注报告{time_str}_{actual_minutes}分钟_{date_str}.md"
                new_log_file = os.path.join(self.log_dir, date_str, new_filename)
                
                if new_log_file != self.log_file and os.path.exists(self.log_file):
                    os.rename(self.log_file, new_log_file)
                    self.log_file = new_log_file
                    
        except Exception as e:
            print(f"Error finalizing session in log file: {e}")
            
        self.session_start_time = None
        self.current_session_entries = []
        
        return stats, duration_seconds // 60

if __name__ == '__main__':
    # Test Logger
    import time
    logger = EmotionLogger()
    logger.start_session(duration_minutes=1)
    logger.log_emotion('neutral', 0.9)
    time.sleep(1)
    logger.log_emotion('neutral', 0.95)
    logger.log_emotion('happy', 0.85)
    stats = logger.end_session(completed=True, miku_comment="太棒了，你今天很专注！")
    print("Stats calculated:", stats)
