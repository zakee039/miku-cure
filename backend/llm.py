import os
import time
import random
import datetime

# ── Multilingual fallback messages ──────────────────────────────────────────
FALLBACK_MESSAGES = {
    'zh': {
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
        'unhappy_surprise': [
            "哎呀，被吓到了吗？摸摸头~Miku在这里陪你呢，听首歌压压惊吧？🎤",
            "哇！发生什么意外了吗？看你有些惊讶。看Miku跳个舞放松一下神经吧！💃"
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
    },
    'ja': {
        'unhappy_sadness': [
            "あれ、元気なさそう…ミクも心配しちゃう。歌ってあげようか？🎵",
            "落ち込まないで！ミクはずっとそばにいるよ。踊ってあげようか？💃",
            "しょんぼりしてるの？ミクの歌でちょっと元気になってくれたら嬉しいな！✨"
        ],
        'unhappy_anger': [
            "ふぅ…深呼吸して！怒ってると疲れちゃうよ。ミクの歌でちょっと落ち着こう？🎤",
            "誰かに怒ってるの？ほっといて！ミクと一緒に踊って気分転換しよ！💥",
            "怒ると体に悪いよ！リラックスできる歌、聴いてみない？🎶"
        ],
        'unhappy_fear': [
            "怖くないよ！ミクがそばにいるから。歌でリラックスしようか？🤗",
            "不安な時は、ミクを見ててね。ゆっくり一緒に落ち着こう？🌟",
            "ミクがいるから大丈夫！癒しのダンスを踊ってあげる！💖"
        ],
        'unhappy_disgust': [
            "なんか嫌なことあった？ちょっと休んで、ミクの歌で気分転換しよ？🍵",
            "無理しないで！ミクのダンスでリフレッシュしよう～🌸",
            "嫌なこと全部忘れちゃえ！ミクの歌声で疲れを飛ばしてあげる！🎶"
        ],
        'unhappy_surprise': [
            "わっ、びっくりしたの？大丈夫だよ、ミクが歌って落ち着かせてあげる！🎤",
            "何かあったの？ミクのダンスを見てリラックスしよう！💃"
        ],
        'focus_end_good': [
            "すごい！集中完了！本当にがんばったね、ミクは誇りに思う！🎉 ダンスでお祝いしよ？",
            "お疲れ様！完璧だったよ！ご褒美にミクが歌ってあげる？🎵",
            "集中終わり！今日のあなたキラキラしてるよ！ダンス見てく？✨"
        ],
        'focus_end_struggle': [
            "やっと終わったね！途中ちょっと大変そうだったよ、お疲れ様。ミクが歌でリラックスさせてあげる？❤️",
            "集中終了！途中しんどそうだったけど頑張ったね！歌でゆっくり休もう？",
            "お疲れ様！ちょっとストレスあったね。ミクのダンスで全部吹き飛ばそう！💃"
        ]
    },
    'en': {
        'unhappy_sadness': [
            "Hey, you seem a bit down... Miku's here for you! Want me to sing a song to cheer you up? 🎵",
            "Don't be sad! Miku will always be by your side. How about a little dance to lift your spirits? 💃",
            "Chin up! Let Miku do a cute dance for you — sound good? ✨"
        ],
        'unhappy_anger': [
            "Take a deep breath! Don't let it get to you. Want Miku to sing something calming? 🎤",
            "Forget whoever upset you! Come watch Miku dance and shake it all off! 💥",
            "Staying angry is tiring! How about a relaxing song to calm down? 🎶"
        ],
        'unhappy_fear': [
            "Don't be scared — Miku's right here! Want a song to ease the tension? 🤗",
            "When you're anxious, just look at Miku. Let me sing and help you relax? 🌟",
            "Everything's going to be okay! Miku will do a healing dance just for you! 💖"
        ],
        'unhappy_disgust': [
            "Something bothering you? Take a break and let Miku's song change the mood? 🍵",
            "Don't push yourself! Watch Miku dance and clear your head~ 🌸",
            "Shake it all off! Let Miku's voice sweep away your fatigue! 🎶"
        ],
        'unhappy_surprise': [
            "Whoa, did something startle you? It's okay, let Miku sing a song to calm you down! 🎤",
            "Surprised? Everything is fine! Come watch Miku dance and relax your nerves! 💃"
        ],
        'focus_end_good': [
            "Amazing! Focus session complete! You were incredible — Miku is so proud! 🎉 Want a victory dance?",
            "Great work! Perfectly done! Let Miku sing you a song as a reward? 🎵",
            "Session over! You were absolutely shining today! Want to see Miku dance? ✨"
        ],
        'focus_end_struggle': [
            "Finally done! It seemed tough in the middle — you pushed through! Let Miku sing to help you relax? ❤️",
            "Session complete! Even though it was rough, you made it — great job! A song to wind down? 🎵",
            "You did it! Miku felt your stress. Deep breath — let me dance it all away! 💃"
        ]
    }
}

# ── Language-aware LLM prompts ───────────────────────────────────────────────
def _build_unhappy_prompt(lang, emotion, duration_seconds):
    if lang == 'ja':
        return f"""あなたは今、初音ミクです。ユーザーのデスクトップ上で見守るかわいいバーチャルキャラクターです。
直近のわずか半分の時間（約30秒間）で、ユーザーが何度も「{emotion}」のような感情を見せていることに気づきました。
初音ミクらしい口調（明るく、かわいく、やさしく、ユーザーを「あなた」と呼ぶ）で、35字以内の短いひと言を言ってください。
ユーザーを気遣い、慰めの言葉をかけてください。"""

    elif lang == 'en':
        return f"""You are Hatsune Miku, a cute virtual companion on the user's desktop.
You notice that within just the last half-minute (30 seconds), the user has repeatedly shown signs of "{emotion}".
Please say a short, caring message (under 30 words) in Miku's style — cheerful, warm, and sweet to comfort them."""

    else:  # zh default
        return f"""你现在是初音未来（Miku），一个在桌面上陪伴用户的可爱虚拟看板娘。
你注意到在最近短短的半分钟（30秒）内，用户频繁流露出"{emotion}"的情绪，似乎遇到了什么烦心事。
请用初音未来（Miku）的语气（活泼、可爱、温柔、称呼用户为"人"），说一句简短贴心的话（35字以内），来主动慰问和关怀用户。
注意语气一定要像Miku（可以使用"唔"、"诶"、"哼~"等语气词）。"""


def _build_focus_end_prompt(lang, duration_minutes, emotion_summary, is_struggle):
    if lang == 'ja':
        struggle_note = "途中でユーザーは疲れやストレスを感じていたようです。温かく励ましてください。" if is_struggle else "ユーザーの状態はとても良かったです！盛大にお祝いしてください！"
        return f"""あなたは初音ミクです。ユーザーの{duration_minutes}分間の集中セッションに付き合いました。
感情の分布：{emotion_summary}
ミクらしい口調（明るく、やさしく）で40字以内のひと言をお願いします。歌かダンスをしてあげると提案してください。
{struggle_note}"""

    elif lang == 'en':
        struggle_note = "The user seemed tired or stressed during the session. Please focus on warm comfort." if is_struggle else "The user's state was great! Give an enthusiastic celebration!"
        return f"""You are Hatsune Miku. You just accompanied the user through a {duration_minutes}-minute focus session.
Emotion distribution: {emotion_summary}
Please say a short closing message (under 35 words) in Miku's cheerful, warm style.
Ask if the user would like you to sing or dance.
{struggle_note}"""

    else:  # zh
        struggle_note = "如果中途表现有些累或情绪差，请重点给予温柔安慰；如果状态很好，请开心地热烈祝贺！" if is_struggle else "用户状态很好，请给予热烈祝贺和夸奖！"
        return f"""你现在是初音未来（Miku），陪伴用户完成了 {duration_minutes} 分钟的专注工作/学习。
这次专注期间用户的整体情绪分布是：{emotion_summary}。
请用初音未来（Miku）的语气（活泼、可爱、温柔、称呼用户为"人"），说一句专注结束的问候与鼓励的话（40字以内），
并询问用户要不要你跳个舞或唱首歌放松一下。
{struggle_note}
注意：必须控制在40字以内。保持Miku的人设。"""


class MikuLLM:
    def __init__(self):
        self.api_key  = ""
        self.base_url = ""
        self.model    = ""
        self.client   = None
        self.chat_history = []
        self.last_chat_time = time.time()
        self.lora_dir = os.path.join(os.path.dirname(__file__), "..", "user", "lora")
        self.master_name_file = os.path.join(self.lora_dir, "master_name.txt")
        self.memory_dir = os.path.join(os.path.dirname(__file__), "..", "user", "memorize")
        self.active_chat_file = os.path.join(self.memory_dir, "active_chat.json")
        os.makedirs(self.memory_dir, exist_ok=True)
        self._load_active_chat()
        self._init_client()

    def _init_client(self):
        """Try to initialize the OpenAI-compatible client."""
        self.client = None
        if self.api_key:
            try:
                import openai
                self.client = openai.OpenAI(api_key=self.api_key, base_url=self.base_url)
                print(f"LLM: Client initialized — {self.base_url} / {self.model}")
            except ImportError:
                print("LLM: openai package not installed. Using local fallback bank.")
        else:
            print("LLM: No API key configured. Using local fallback bank.")

    def reconfigure(self, base_url: str, api_key: str, model: str):
        """Hot-swap the LLM backend without restarting the server."""
        self.base_url = base_url or self.base_url
        self.api_key  = api_key  or self.api_key
        self.model    = model    or self.model
        self._init_client()

    # ── Memory management ─────────────────────────────────────────────────────

    def _load_active_chat(self):
        import json
        if os.path.exists(self.active_chat_file):
            try:
                with open(self.active_chat_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self.chat_history = data.get('history', [])
                        self.last_chat_time = data.get('last_chat_time', time.time())
                    elif isinstance(data, list):
                        self.chat_history = data
                        self.last_chat_time = time.time()
                print(f"LLM: Loaded active chat with {len(self.chat_history)} messages.")
            except Exception as e:
                print(f"LLM: Error loading active chat: {e}")

    def _save_active_chat(self):
        import json
        try:
            with open(self.active_chat_file, 'w', encoding='utf-8') as f:
                json.dump({'history': self.chat_history, 'last_chat_time': self.last_chat_time}, f, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving active chat: {e}")

    def _get_latest_memory(self):
        if not os.path.exists(self.memory_dir):
            return ""
        files = [f for f in os.listdir(self.memory_dir) if f.endswith('memorize.md')]
        if not files:
            return ""
        files.sort(key=lambda x: os.path.getmtime(os.path.join(self.memory_dir, x)), reverse=True)
        latest_file = os.path.join(self.memory_dir, files[0])
        try:
            with open(latest_file, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            print(f"Error reading memory: {e}")
            return ""

    def _summarize_memory(self):
        if not self.chat_history or not self.client:
            return
            
        print("LLM: Summarizing previous chat history into long-term memory...")
        prompt = "请以客观简练的语言，总结昨天 Miku 与用户的以下对话核心内容，提炼出关键信息和情感状态，作为未来的记忆：\n\n"
        for msg in self.chat_history:
            role = "用户" if msg['role'] == 'user' else "Miku"
            prompt += f"{role}: {msg['content']}\n"
            
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,
                timeout=10.0
            )
            summary = resp.choices[0].message.content.strip()
            
            date_str = datetime.datetime.now().strftime("%Y-%m-%d")
            filename = os.path.join(self.memory_dir, f"{date_str}memorize.md")
            
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(summary)
            print(f"LLM: Saved memory to {filename}")
            
        except Exception as e:
            print(f"LLM: Failed to summarize memory: {e}")
            
        # Clear history after summarizing
        self.chat_history = []
        self._save_active_chat()

    # ── Public methods ────────────────────────────────────────────────────────

    def get_unhappy_response(self, emotion: str, duration_seconds: int = 60, lang: str = 'zh') -> str:
        fallback_bank = FALLBACK_MESSAGES.get(lang, FALLBACK_MESSAGES['zh'])
        key = f"unhappy_{emotion}"
        fallback_list = fallback_bank.get(key, fallback_bank.get('unhappy_sadness', []))
        fallback_msg = random.choice(fallback_list) if fallback_list else "Miku is here for you! 💙"

        if not self.client:
            return fallback_msg

        prompt = _build_unhappy_prompt(lang, emotion, duration_seconds)
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=120,
                timeout=5.0
            )
            text = resp.choices[0].message.content.strip()
            text = text.replace('"', '').replace('\u201c', '').replace('\u201d', '')
            return text
        except Exception as e:
            print(f"LLM API call failed: {e}. Using fallback.")
            return fallback_msg

    def get_focus_end_response(self, duration_minutes: int, stats: dict, lang: str = 'zh') -> str:
        negative = stats.get('sadness', 0) + stats.get('anger', 0) + stats.get('fear', 0) + stats.get('disgust', 0)
        is_struggle = negative > 25.0

        summary_parts = [f"{em}:{val:.0f}%" for em, val in stats.items() if val > 5]
        emotion_summary = ", ".join(summary_parts)

        fallback_bank = FALLBACK_MESSAGES.get(lang, FALLBACK_MESSAGES['zh'])
        fallback_key = "focus_end_struggle" if is_struggle else "focus_end_good"
        fallback_list = fallback_bank.get(fallback_key, [])
        fallback_msg = random.choice(fallback_list) if fallback_list else "Great work! 🎉"

        if not self.client:
            return fallback_msg

        prompt = _build_focus_end_prompt(lang, duration_minutes, emotion_summary, is_struggle)
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,
                timeout=15.0
            )
            text = resp.choices[0].message.content.strip()
            text = text.replace('"', '').replace('\u201c', '').replace('\u201d', '')
            if not text:
                return fallback_msg
            return text
        except Exception as e:
            print(f"LLM API call failed: {e}. Using fallback.")
            return fallback_msg

    def chat_with_miku(self, user_text: str, hidden_context: str = None, lang: str = 'zh') -> str:
        now = time.time()
        
        # Check if new day and delay >= 8 hours
        if self.chat_history:
            last_dt = datetime.datetime.fromtimestamp(self.last_chat_time)
            now_dt = datetime.datetime.fromtimestamp(now)
            delay_hours = (now - self.last_chat_time) / 3600.0
            
            is_new_day = last_dt.date() != now_dt.date()
            if is_new_day and delay_hours >= 8.0:
                self._summarize_memory()

        self.last_chat_time = now

        if not self.client:
            return "Miku 还没准备好大脑哦，请先在设置中配置 API~" if lang == 'zh' else "API not configured~"

        # Load latest memory
        memory = self._get_latest_memory()
        memory_prompt = f"\n这是你上一轮的记忆摘要：\n{memory}\n请结合这些记忆与用户进行今天的对话。" if memory else ""
        
        master_name = "用户"
        if os.path.exists(self.master_name_file):
            try:
                with open(self.master_name_file, 'r', encoding='utf-8') as f:
                    name = f.read().strip()
                    if name: master_name = name
            except Exception:
                pass
                
        if lang == 'ja':
            sys_msg = f"あなたは初音ミクです。活発で可愛く、優しいトーンで簡潔に返答してください。ユーザーの名前は「{master_name}」です。{memory_prompt}\n【重要】歌を歌う場合は文頭に [PLAY_MUSIC]、画像を見せる場合は文頭に [SHOW_IMAGE] を置いてください。動作を描写する（「画像を出す」「歌う」など）のは構いませんが、画像や曲の「具体的な内容（ネギを持っている、曲名など）」は描写しないでください（ランダム再生のため矛盾が生じます）。「これ可愛いでしょう？」など抽象的に言及してください。"
        elif lang == 'en':
            sys_msg = f"You are Hatsune Miku, a cute and cheerful virtual companion. The user's name is {master_name}. Keep your answers brief and sweet. {memory_prompt}\n[CRITICAL]: To play a song, start your reply with [PLAY_MUSIC]. To show a picture, start with [SHOW_IMAGE]. You may roleplay the action of taking out a picture or singing, but DO NOT describe the specific contents of the picture or the song (e.g., holding a leek, specific lyrics), as they are randomly selected. Use broad descriptions like 'Isn\'t this cute?'."
        else:
            sys_msg = f"你是初音未来（Miku），一个在桌面上陪伴主人学习和工作的可爱虚拟看板娘。主人的名字叫「{master_name}」，请在合适的时机称呼主人。请用活泼、可爱、温柔的语气简短回复。{memory_prompt}\n【最高指令】：如果你想放歌，必须将 [PLAY_MUSIC] 放在回复的最开头；如果你想发表情包，必须将 [SHOW_IMAGE] 放在回复的最开头。你可以用文字描述‘拿出表情包’或‘准备唱歌’的动作，但【绝对不要】描述表情包或歌曲的具体内容（比如不要说‘抱着葱’、不要说具体歌名或歌词），因为内容是系统随机播放的，会产生矛盾。请使用宽泛抽象的描述，比如‘看这个，本小姐可爱吧~’或‘听听这首歌放松下~’。"

        messages = [{"role": "system", "content": sys_msg}]
        
        # Add recent history (last 10 messages)
        recent_history = self.chat_history[-10:]
        messages.extend(recent_history)
        
        # Save user message to history immediately so UI can fetch it during generation
        self.chat_history.append({"role": "user", "content": user_text})
        self._save_active_chat()

        new_msg = {"role": "user", "content": user_text}
        if hidden_context:
            new_msg["content"] += f"\n\n{hidden_context}"
        messages.append(new_msg)
        
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=500,
                timeout=8.0
            )
            reply = resp.choices[0].message.content.strip()
            
            # Save assistant reply to history
            self.chat_history.append({"role": "assistant", "content": reply})
            self._save_active_chat()
            
            return reply
        except Exception as e:
            print(f"LLM API call failed: {e}")
            return "网络有点不通畅哦，Miku 没听清~" if lang == 'zh' else "Network error~"


if __name__ == '__main__':
    llm = MikuLLM()
    for lang in ['zh', 'ja', 'en']:
        print(f"\n[{lang}] Unhappy:", llm.get_unhappy_response('sadness', lang=lang))
        print(f"[{lang}] Focus end:", llm.get_focus_end_response(30, {'happy': 60, 'neutral': 30, 'sadness': 10}, lang=lang))
