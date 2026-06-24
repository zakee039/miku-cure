import os
import random
from dotenv import load_dotenv

# Load env variables from .env file
load_dotenv()

# Pre-defined Miku local message library as fallback
FALLBACK_MESSAGES = {
    'unhappy_sadness': [
        "人，看你闷闷不乐的，Miku心里也跟着难受了...要不要听我唱首歌开心一下？🎵",
        "别难过啦，Miku会一直在你身边的。听首歌或者看我跳支舞放松一下吧！✨",
        "呜...打起精神来！让Miku给你跳支好看的舞吧，好不好嘛？💃"
    ],
    'unhappy_anger': [
        "呼……深呼吸！别生气了嘛，身体是自己的。让Miku唱首歌帮你消消气？🎤",
        "是谁惹人不高兴啦？哼，别理他们！来看Miku跳舞，把烦恼都甩掉！💥",
        "生气会老得快哦！快来听一首轻松的歌，让心情平静下来吧~🎶"
    ],
    'unhappy_fear': [
        "别怕别怕，Miku会保护你的！捏捏手~要不要听首歌缓解一下紧张？🤗",
        "焦虑的时候，就看着Miku吧。我给你唱首歌，慢慢放松下来好吗？🌟",
        "有Miku在呢，一切都会好起来的。给你跳支治愈的舞蹈吧！💖"
    ],
    'unhappy_disgust': [
        "唔...是不是遇到什么讨厌的事情了？先转过头休息一会，听首歌转换下心情？🍵",
        "太累或者太烦的话就先别强求啦。看Miku跳个舞，换个脑子吧~🌸",
        "拍拍灰尘，把不好的感觉都忘掉！让Miku的歌声带走你的疲惫！🎶"
    ],
    'focus_end_good': [
        "太棒了！专注完成了！人真的好厉害，Miku为你骄傲！🎉 要不要来支舞庆祝一下？",
        "辛苦啦！完美达成专注！Miku给你唱首歌当做奖励吧，来点一下？🎵",
        "专注结束！今天状态超赞，Miku觉得你闪闪发光呢！要不要看看我跳舞？✨"
    ],
    'focus_end_struggle': [
        "呼，终于搞定啦！中途感觉你有点累和苦恼呢，辛苦啦。让Miku唱歌给你放松一下吧？❤️",
        "专注结束！虽然中间有点不开心，但你还是坚持下来了，很棒哦！来听首歌休息会？",
        "辛苦了！感觉你刚才有点压力呢，深呼吸，Miku给你跳支舞带走所有疲惫吧！💃"
    ]
}

class MikuLLM:
    def __init__(self):
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
        self.base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        self.model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        self.client = None

        if self.api_key:
            try:
                import openai
                self.client = openai.OpenAI(api_key=self.api_key, base_url=self.base_url)
                print("LLM: DeepSeek client initialized successfully.")
            except ImportError:
                print("LLM: openai package is not installed yet. Falling back to local template bank.")
        else:
            print("LLM: DEEPSEEK_API_KEY not found in .env. Using local message bank fallback.")

    def get_unhappy_response(self, emotion, duration_seconds=60):
        prompt = f"""
你现在是初音未来（Miku），一个在桌面上陪伴用户学习和工作的可爱虚拟看板娘。
你注意到用户目前的情绪是“{emotion}”，并且已经持续了将近 {duration_seconds} 秒。
请用初音未来（Miku）的语气（活泼、可爱、温柔、称呼用户为“人”），说一句简短贴心的话（35字以内），
关怀用户并主动提议你可以为他跳支舞或唱首歌来放松心情。

注意：
1. 语气一定要像Miku（可以使用“唔”、“诶”、“哼~”等语气词，表达关心）。
2. 文案必须控制在35字以内。
"""
        # Select fallback based on emotion category
        fallback_category = f"unhappy_{emotion}"
        if fallback_category not in FALLBACK_MESSAGES:
            fallback_category = "unhappy_sadness"
        fallback_msg = random.choice(FALLBACK_MESSAGES[fallback_category])

        if not self.client:
            return fallback_msg

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
                timeout=5.0
            )
            text = response.choices[0].message.content.strip()
            # Clean up potential quotes
            text = text.replace('"', '').replace('“', '').replace('”', '')
            return text
        except Exception as e:
            print(f"LLM API Call failed: {e}. Using fallback message.")
            return fallback_msg

    def get_focus_end_response(self, duration_minutes, stats):
        # Determine if the session was mostly positive or full of struggle
        negative_emotions = stats.get('sadness', 0) + stats.get('anger', 0) + stats.get('fear', 0) + stats.get('disgust', 0)
        is_struggle = negative_emotions > 25.0 # More than 25% of the time was unhappy

        emotion_summary_parts = []
        for em, val in stats.items():
            if val > 5:
                emotion_summary_parts.append(f"{em}:{val:.0f}%")
        emotion_summary = ", ".join(emotion_summary_parts)

        prompt = f"""
你现在是初音未来（Miku），陪伴用户完成了 {duration_minutes} 分钟的专注工作/学习。
这次专注期间用户的整体情绪分布是：{emotion_summary}。
请用初音未来（Miku）的语气（活泼、可爱、温柔、称呼用户为“人”），说一句专注结束的问候与鼓励的话（40字以内），
并询问用户要不要你跳个舞或唱首歌放松一下。
{"如果中途表现有些累或情绪差，请重点给予温柔安慰；如果状态很好，请开心地热烈祝贺！" if is_struggle else "用户状态很好，请给予热烈祝贺和夸奖！"}

注意：
1. 必须控制在40字以内。
2. 保持Miku的人设。
"""
        fallback_category = "focus_end_struggle" if is_struggle else "focus_end_good"
        fallback_msg = random.choice(FALLBACK_MESSAGES[fallback_category])

        if not self.client:
            return fallback_msg

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
                timeout=5.0
            )
            text = response.choices[0].message.content.strip()
            text = text.replace('"', '').replace('“', '').replace('”', '')
            return text
        except Exception as e:
            print(f"LLM API Call failed: {e}. Using fallback message.")
            return fallback_msg

if __name__ == '__main__':
    # Test LLM
    llm = MikuLLM()
    print("Unhappy test:", llm.get_unhappy_response('sadness'))
    print("Focus end test:", llm.get_focus_end_response(30, {'happy': 60, 'neutral': 30, 'sadness': 10}))
