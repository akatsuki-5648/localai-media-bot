#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ================================================================
# localai_news_bot.py — AIラボ鯖 ローカルAI速報 自動配信（GitHub配布用・独立スクリプト）
# ----------------------------------------------------------------
# 方式: 朝活/激裏型。Google News検索RSS＋実証済みニュース母体を分類別クエリで切って投稿。
#       AI分類は使わず route_id / source で分類を固定（IC倶楽部方式）。
# 設計の正本: 自分/AIニュース15分類_取得クエリ設計_完全再設計版 1.md（2026-07-08）
# 2026-07-09: 初期実運用で「量は出るが質が荒い」ことを確認。
#   方針変更: 公式RSS/GitHub release/APIを主水路にしない。
#   トレンド朝活で効いているニュース母体を15分類のクエリ違いで使い回す。
#
# 使い方:
#   1) pip install feedparser
#   2) Webhookを環境変数で（GitHub Actionsは Secrets 推奨）:
#        DISCORD_LOCALAI_WEBHOOK_{OPENAI,CLAUDE,GEMINI,XAI,COPILOT,META,CHINA,
#                              LOCAL,IMGVID,AUDIO,TOOLS,PAPERS,GENERAL,RELEASE,WORLD}
#   3) ローカルテストは環境変数が無ければ同ディレクトリ localai_media_webhooks.json を fallback（配布時 .gitignore）
#   4) python localai_news_bot.py
#   5) 自動化: .github/workflows で cron '15,45 * * * *'
# 重複排除: 同ディレクトリ localai_media_seen_urls.json / 投稿POSTには User-Agent 必須(無いとCloudflare403)
# ================================================================
import os, sys, io, json, time, re, calendar, urllib.parse, urllib.request, urllib.error
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
try:
    import feedparser
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "feedparser"])
    import feedparser

HERE = os.path.dirname(os.path.abspath(__file__))
SEEN_FILE = os.path.join(HERE, "localai_media_seen_urls.json")
WEBHOOKS_JSON = os.path.join(HERE, "localai_media_webhooks.json")
PER_SOURCE = 3        # ★速報化: 1ソースから拾う上限
PER_CHANNEL = 4       # ★速報化: 1chの1回あたり投稿上限
FRESH_HOURS = 48      # ★速報化: 直近48hの記事だけを速報として拾う(窓外の古い既出は対象外)
NOW = time.time()     # 実行開始時刻(UTC epoch)。時間窓判定の基準
UA = "LocalAiBot/1.0 (+https://discord.com)"
COL_BIZ, COL_FIELD, COL_SUM = 0x00E5FF, 0x00FF9C, 0xFF7A1A

GLOBAL_EXCLUDE = [
    "PR TIMES", "プレスリリース", "アットプレス", "valuepress",
    "株価", "決算", "ホールド評価", "求人", "採用", "セミナー", "イベント開催",
    "ライブ配信", "ウェビナー", "講座", "Investing.com", "ファイナンス", "金融ニュース",
    "使ってみた", "とは？", "とは何か", "徹底解説", "始め方", "初心者", "AIsmiley", "ai-market.jp",
    "キャンペーン", "無料公開", "広告", "Sponsored",
    "料金はいくら", "全プラン比較", "最適な選び方", "おすすめランキング", "資料請求",
    "日記", "使い倒し", "仕事術", "入門",
]

def rss(url, include=None, exclude=None, label=None, title_include=None, title_exclude=None):
    return {"type": "rss", "url": url, "include": include or [], "exclude": exclude or [],
            "label": label, "title_include": title_include or [], "title_exclude": title_exclude or []}

def gn(q, include=None, exclude=None, label=None, title_include=None, title_exclude=None):
    return {"type": "gn", "q": q, "include": include or [], "exclude": exclude or [],
            "label": label, "title_include": title_include or [], "title_exclude": title_exclude or []}

def sitemap(url, include=None, exclude=None, label=None, path_prefix=None, title_include=None, title_exclude=None):
    return {"type": "sitemap", "url": url, "include": include or [], "exclude": exclude or [],
            "label": label, "path_prefix": path_prefix or [], "title_include": title_include or [],
            "title_exclude": title_exclude or []}


LOCAL_TITLE_EXCLUDE = ["Course -", "Bootcamp", "Masterclass", "Udemy", "Coursera",
                       "Tutorial", "使ってみた", "とは?", "始め方", "初心者向け", "入門",
                       "求人", "採用", "セミナー"]
# is_release_version_noise() が参照する
MODEL_RELEASE_TERMS = ["新モデル", "モデル公開", "オープンウェイト", "提供開始", "generally available",
                       "open weights", "GPT", "Claude", "Gemini", "Grok", "Llama", "Qwen", "DeepSeek",
                       "Mistral", "Gemma", "Phi", "released", "release", "launch"]

COL_TTS, COL_MUSIC, COL_VIDEO, COL_IMAGE, COL_FINETUNE = 0x00BFA5, 0xE91E63, 0xFF5722, 0xFFC107, 0x673AB7

TTS_TERMS = ["StyleTTS2", "F5-TTS", "Zonos-v", "Kokoro-TTS", "MetaVoice", "KaniTTS",
             "VoiceCraft", "Coqui TTS", "XTTS-v2", "Bark TTS", "VOICEVOX", "VOICEROID",
             "pyopenjtalk", "RVC voice", "So-VITS-SVC", "voice cloning", "音声合成",
             "text-to-speech", "voice synthesis", "Vibevoice", "MegaTTS", "OpenVoice",
             "GPT-SoVITS", "Fish Speech", "Piper TTS", "音声クローン", "TTSモデル"]
# ★2026-09-15 実測: TTS=会社略称(HR Path TTS Digital)/車(Audi TTS)/大学(Voice/Craft)誤ヒット → title_excludeで除去
TTS_EXCLUDE = ["ElevenLabs subscription", "訴訟", "詐欺利用", "HR Path", "TTS digital",
               "TTSクーペ", "アウディ", "goo-net", "TTS Roadster",
               # ★2026-09-16 CDP実測ノイズ: クラウド音声クローン/研修動画/短尺広告
               "音声クローン", "AI音声クローン", "社内研修", "中小企業向け",
               "生成AI活用術", "研修動画", "#Shorts", "自動生成する方法"]
MUSIC_TERMS = ["MusicGen", "AudioCraft", "Stable Audio", "AudioLDM", "Riffusion", "Magenta music",
               "YuE music", "Levo music", "MusicLM", "音楽生成AI", "music generation",
               "text-to-music", "AI音楽", "AI作曲", "Suno open", "Jukebox model",
               "MusicLDM", "MusicHiFi", "AudioBox", "自動作曲", "音楽AI生成"]
MUSIC_EXCLUDE = ["Spotify Wrapped", "Apple Music プラン", "配信サービス開始", "ライブ配信", "訴訟",
                 "音楽業界", "レコード会社", "コンサート",
                 # ★2026-09-16 CDP実測ノイズ: 著名人インタビュー/クラウドSuno
                 "さだまさし", "AI作曲どう見る", "Suno", "MEDIAMIXI",
                 "AI学習にYouTube", "音声データ取得認める", "作曲家インタビュー",
                 "アーティストインタビュー", "配信認める"]
VIDEO_TERMS = ["Wan2.1", "Wan 2.1", "LTX-Video", "LTX Video", "Mochi 1", "CogVideoX", "HunyuanVideo",
               "Pyramid Flow", "Open-Sora", "AnimateDiff", "Stable Video Diffusion", "SVD",
               "EasyAnimate", "VideoCrafter", "VGen video", "動画生成AI", "text-to-video",
               "image-to-video", "AI動画生成", "video generation", "Genmo", "Rhymes Allegro",
               "CausVid", "LivePortrait", "MuseTalk"]
VIDEO_EXCLUDE = ["訴訟", "著作権訴訟", "映画スタジオ提訴", "Sora subscription", "配信サービス",
                 "俳優", "映画館", "興行収入",
                 # ★2026-09-15 実測ノイズ: 数学論文/Codex/AI一般が誤ヒット
                 "Lean 4", "定理証明", "低ランクのテンソル", "テンソルの完成",
                 "Schatten", "シャテンプノーム", "テンソルのスキャン", "Codex",
                 "識別子", "中学生でもわかる", "投稿前予測", "セキュリティ指摘",
                 "AGI", "GPT-5", "GPT-6",
                 # ★2026-09-16 CDP実測ノイズ: クラウドText-to-Videoサービス広告
                 "Creatify", "Boreal", "Creatify Labs", "Text-to-Video AI モデル",
                 "1セント", "40倍の速度", "unite.ai", "毎秒 1 セント"]
# ★2026-09-15 実測: SANA=地名Sana'a/Sana Air Quality誤ヒット → 固有名詞化 "NVIDIA SANA"
IMAGE_TERMS = ["Flux.1", "Flux dev", "Flux schnell", "SD3.5", "Stable Diffusion 3.5",
               "Stable Diffusion 3", "SDXL", "Kolors model", "Playground v2.5", "HiDream",
               "NVIDIA SANA", "SANA text-to-image", "ComfyUI", "A1111", "Automatic1111",
               "Forge WebUI", "SwarmUI", "Fooocus", "InvokeAI", "ControlNet", "IPAdapter",
               "civitai", "AI画像生成", "画像生成AI"]
IMAGE_EXCLUDE = ["訴訟", "著作権訴訟", "ランウェイ", "ファッションブランド", "Marc Jacobs",
                 "コレクション", "ホロライブ", "ときのそら", "ミニスカ", "グラビア", "配信者",
                 "Yemeni", "Air Quality", "Pristine Healthcare",
                 # ★2026-09-16 CDP実測ノイズ: アニメコラボ/化粧品広告
                 "幽遊白書", "幽☆遊☆白書", "蔵馬", "美容ブランド", "La Sana",
                 "美髪", "美髪指南塾", "玩具人", "TOY PEOPLE",
                 "アニメコラボ", "コラボ発売", "タッグを組"]
# ★2026-09-15 実測: 単体LoRA/fine-tuneが裁判ニュース(Mount Dora Trial)誤ヒット → 固有名詞化
FINETUNE_TERMS = ["LoRA training", "LoRA adapter", "LoRA fine", "QLoRA", "DoRA finetune",
                  "LongLoRA", "DPO training", "DPO fine", "IPO training", "KTO training",
                  "ORPO training", "SimPO training", "SFT training", "RLHF training",
                  "RLAIF", "Unsloth", "axolotl fine", "TRL library", "LLaMA-Factory",
                  "Torchtune", "mlx-lm", "PEFT library", "ファインチューニング",
                  "fine-tuning", "fine-tune LLM", "継続事前学習", "instruction tuning",
                  "distillation", "蒸留学習", "synthetic data", "データ合成"]
FINETUNE_EXCLUDE = ["株価", "資金調達", "Trial begins", "Mount Dora", "wesh.com", "FOX 35",
                    "Spectrum News", "trial for", "Killing of", "Orlando",
                    # ★2026-09-15 実測ノイズ: LoRa無線通信/人名Lora/自動車チューニング
                    "LoRa通信", "LoRa無線", "LoRaで通信", "LoRa 通信", "LoRa 無線",
                    "介護施設", "離床", "転倒", "徘徊", "Meshtastic", "エフエージェイ",
                    "LiDAR", "RTH-25", "MeshCore",
                    "Obituary", "訃報", "Cooley", "Gainesville", "Legacy obituary",
                    "日々の信仰", "buzzmusic", "見つけます",
                    "Motor Fan", "ロードスター", "オートエクゼ", "NDロードスター",
                    "エンジン", "リビルト",
                    # ★人名Lora誤ヒット系
                    "Lora A.", "Lora Cooley", "Lora Kelly", "Lora Jean",
                    # ★2026-09-16 CDP実測ノイズ: 動画配信ソフト/CloseBox系
                    "CloseBox", "動画対話システム", "配信用ソフト", "5090で使ったら",
                    "MiniMax H3生成時間", "AI動画対話", "配信ソフトから"]

TOPICS = [
 {"num":"🗣️","name":"ローカルtts速報","env":"TTS","color":COL_TTS,"sources":[
     rss("https://www.reddit.com/r/AIVoicing/hot/.rss?limit=15", include=TTS_TERMS),
     rss("https://www.reddit.com/r/LocalLLaMA/search.rss?q=TTS+OR+voice+cloning&restrict_sr=on&sort=new&limit=20", include=TTS_TERMS),
     gn('StyleTTS2 OR "F5-TTS" OR "Zonos-v" OR "Kokoro TTS" OR MetaVoice OR VoiceCraft OR "Coqui TTS" OR "Fish Speech" OR "GPT-SoVITS"',
        include=TTS_TERMS, exclude=TTS_EXCLUDE, title_exclude=LOCAL_TITLE_EXCLUDE),
     gn('"音声合成AI" OR "VOICEVOX" OR "音声クローニング" OR "音声クローン" OR "TTSモデル"',
        include=TTS_TERMS, exclude=TTS_EXCLUDE, title_exclude=LOCAL_TITLE_EXCLUDE),
     rss("https://news.google.com/rss/search?q=%22StyleTTS%22%20OR%20%22F5-TTS%22%20OR%20%22GPT-SoVITS%22%20OR%20%22VOICEVOX%22%20OR%20%22Fish%20Speech%22%20OR%20%22MetaVoice%22&hl=en-US&gl=US&ceid=US:en",
         include=TTS_TERMS, exclude=TTS_EXCLUDE, title_exclude=LOCAL_TITLE_EXCLUDE),
     gn('site:x.com "StyleTTS" OR "F5-TTS" OR "Zonos" OR "VOICEVOX" OR "GPT-SoVITS" OR "MetaVoice"',
        include=TTS_TERMS, exclude=TTS_EXCLUDE, title_exclude=LOCAL_TITLE_EXCLUDE),
     rss("https://zenn.dev/topics/tts/feed", include=TTS_TERMS),
     rss("https://zenn.dev/topics/voicevox/feed", include=TTS_TERMS + ["合成", "音声"]),
     rss("https://zenn.dev/topics/ai/feed", include=TTS_TERMS + ["音声合成", "TTS"]),
     rss("https://huggingface.co/blog/feed.xml", include=TTS_TERMS + ["audio", "speech"]),
     rss("https://export.arxiv.org/rss/cs.SD", include=TTS_TERMS),
     rss("https://export.arxiv.org/rss/eess.AS", include=TTS_TERMS)]},

 {"num":"🎵","name":"ローカル音楽ai速報","env":"MUSIC","color":COL_MUSIC,"sources":[
     rss("https://www.reddit.com/r/AImusic/hot/.rss?limit=15", include=MUSIC_TERMS),
     rss("https://www.reddit.com/r/LocalLLaMA/search.rss?q=music+generation+OR+MusicGen&restrict_sr=on&sort=new&limit=15",
         include=MUSIC_TERMS),
     gn('MusicGen OR "Stable Audio" OR AudioLDM OR Riffusion OR "text-to-music" OR "AI music generation" OR AudioBox',
        include=MUSIC_TERMS, exclude=MUSIC_EXCLUDE, title_exclude=LOCAL_TITLE_EXCLUDE),
     gn('"音楽生成AI" OR "AI作曲" OR "AI音楽" OR "自動作曲"',
        include=MUSIC_TERMS, exclude=MUSIC_EXCLUDE, title_exclude=LOCAL_TITLE_EXCLUDE),
     rss("https://news.google.com/rss/search?q=MusicGen%20OR%20%22Stable%20Audio%22%20OR%20AudioLDM%20OR%20Riffusion%20OR%20%22music%20generation%22&hl=en-US&gl=US&ceid=US:en",
         include=MUSIC_TERMS, exclude=MUSIC_EXCLUDE, title_exclude=LOCAL_TITLE_EXCLUDE),
     gn('site:x.com "MusicGen" OR "Stable Audio" OR "AudioLDM" OR "Riffusion" OR "AudioBox"',
        include=MUSIC_TERMS, exclude=MUSIC_EXCLUDE, title_exclude=LOCAL_TITLE_EXCLUDE),
     rss("https://zenn.dev/topics/musicgen/feed", include=MUSIC_TERMS),
     rss("https://zenn.dev/topics/ai/feed", include=MUSIC_TERMS + ["音楽", "作曲"]),
     rss("https://huggingface.co/blog/feed.xml", include=MUSIC_TERMS + ["music", "audio"]),
     rss("https://export.arxiv.org/rss/cs.SD", include=MUSIC_TERMS)]},

 {"num":"🎬","name":"ローカル動画ai速報","env":"VIDEO","color":COL_VIDEO,"sources":[
     rss("https://www.reddit.com/r/StableDiffusion/search.rss?q=video+OR+animate+OR+Wan&restrict_sr=on&sort=new&limit=25",
         include=VIDEO_TERMS),
     rss("https://www.reddit.com/r/comfyui/search.rss?q=video+OR+animate&restrict_sr=on&sort=new&limit=15",
         include=VIDEO_TERMS + ["ComfyUI"]),
     gn('"Wan 2.1" OR "LTX-Video" OR "CogVideoX" OR HunyuanVideo OR "Open-Sora" OR AnimateDiff OR "Stable Video Diffusion" OR "Mochi 1" OR "Pyramid Flow"',
        include=VIDEO_TERMS, exclude=VIDEO_EXCLUDE, title_exclude=LOCAL_TITLE_EXCLUDE),
     gn('"動画生成AI" OR "AI動画生成" OR "動画生成モデル"',
        include=VIDEO_TERMS, exclude=VIDEO_EXCLUDE, title_exclude=LOCAL_TITLE_EXCLUDE),
     rss("https://news.google.com/rss/search?q=%22text%20to%20video%22%20OR%20%22image%20to%20video%22%20OR%20%22AnimateDiff%22%20OR%20%22Stable%20Video%22%20OR%20%22Wan%202%22%20OR%20%22CogVideoX%22&hl=en-US&gl=US&ceid=US:en",
         include=VIDEO_TERMS, exclude=VIDEO_EXCLUDE, title_exclude=LOCAL_TITLE_EXCLUDE),
     gn('site:x.com "Wan 2.1" OR "LTX-Video" OR "AnimateDiff" OR "CogVideoX" OR "HunyuanVideo" OR "Mochi"',
        include=VIDEO_TERMS, exclude=VIDEO_EXCLUDE, title_exclude=LOCAL_TITLE_EXCLUDE),
     rss("https://zenn.dev/topics/animatediff/feed", include=VIDEO_TERMS),
     rss("https://zenn.dev/topics/wan/feed", include=VIDEO_TERMS),
     rss("https://zenn.dev/topics/comfyui/feed", include=VIDEO_TERMS + ["ComfyUI 動画", "ComfyUI video"]),
     # ★2026-09-15 削除: Zenn t/ai は幅が広すぎて動画無関係の記事が流入(Codex/Lean 4等)
     rss("https://huggingface.co/blog/feed.xml", include=VIDEO_TERMS + ["video generation", "text-to-video"]),
     rss("https://export.arxiv.org/rss/cs.CV", include=VIDEO_TERMS + ["video generation", "text-to-video", "video diffusion"])]},

 {"num":"🖼️","name":"ローカル画像ai速報","env":"IMAGE","color":COL_IMAGE,"sources":[
     rss("https://www.reddit.com/r/StableDiffusion/hot/.rss?limit=30", include=IMAGE_TERMS),
     rss("https://www.reddit.com/r/comfyui/hot/.rss?limit=15", include=IMAGE_TERMS + ["workflow", "ComfyUI"]),
     rss("https://www.reddit.com/r/FluxAI/hot/.rss?limit=15", include=IMAGE_TERMS + ["Flux"]),
     gn('"Flux.1" OR "SD 3.5" OR "Stable Diffusion 3.5" OR ComfyUI OR SDXL OR "Playground v2.5" OR HiDream OR "NVIDIA SANA" OR "Kolors model"',
        include=IMAGE_TERMS, exclude=IMAGE_EXCLUDE, title_exclude=LOCAL_TITLE_EXCLUDE),
     gn('"画像生成AI" OR "AI画像生成" OR "ComfyUI" OR "Automatic1111"',
        include=IMAGE_TERMS, exclude=IMAGE_EXCLUDE, title_exclude=LOCAL_TITLE_EXCLUDE),
     rss("https://news.google.com/rss/search?q=%22Flux.1%22%20OR%20%22Stable%20Diffusion%22%20OR%20%22SDXL%22%20OR%20%22ComfyUI%22%20OR%20%22Playground%20v2%22&hl=en-US&gl=US&ceid=US:en",
         include=IMAGE_TERMS, exclude=IMAGE_EXCLUDE, title_exclude=LOCAL_TITLE_EXCLUDE),
     gn('site:x.com "Flux.1" OR "SD 3.5" OR "Stable Diffusion" OR "ComfyUI" OR "SDXL" OR "HiDream"',
        include=IMAGE_TERMS, exclude=IMAGE_EXCLUDE, title_exclude=LOCAL_TITLE_EXCLUDE),
     rss("https://zenn.dev/topics/stablediffusion/feed", include=IMAGE_TERMS),
     rss("https://zenn.dev/topics/comfyui/feed", include=IMAGE_TERMS),
     rss("https://zenn.dev/topics/flux/feed", include=IMAGE_TERMS + ["Flux"]),
     rss("https://zenn.dev/topics/lora/feed", include=IMAGE_TERMS + ["画像"]),
     rss("https://zenn.dev/topics/ai/feed", include=IMAGE_TERMS + ["画像生成"]),
     rss("https://huggingface.co/blog/feed.xml", include=IMAGE_TERMS + ["diffusion"]),
     rss("https://export.arxiv.org/rss/cs.CV", include=IMAGE_TERMS),
     rss("https://github.com/comfyanonymous/ComfyUI/releases.atom", include=IMAGE_TERMS + ["support", "improve", "add"]),
     rss("https://github.com/AUTOMATIC1111/stable-diffusion-webui/releases.atom", include=IMAGE_TERMS + ["support", "feature"])]},

 {"num":"🔧","name":"ローカル学習・finetune速報","env":"FINETUNE","color":COL_FINETUNE,"sources":[
     rss("https://www.reddit.com/r/LocalLLaMA/search.rss?q=finetune+OR+LoRA+OR+DPO+OR+Unsloth&restrict_sr=on&sort=new&limit=25",
         include=FINETUNE_TERMS),
     gn('"LoRA training" OR "QLoRA" OR "DPO training" OR "Unsloth" OR "axolotl" OR "LLaMA-Factory" OR mlx-lm OR "ORPO" OR "SimPO" OR "DoRA finetune"',
        include=FINETUNE_TERMS, exclude=FINETUNE_EXCLUDE, title_exclude=LOCAL_TITLE_EXCLUDE),
     gn('"ファインチューニング" OR "LoRA学習" OR "DPO学習" OR "継続事前学習" OR "モデル学習"',
        include=FINETUNE_TERMS, exclude=FINETUNE_EXCLUDE, title_exclude=LOCAL_TITLE_EXCLUDE),
     rss("https://news.google.com/rss/search?q=%22fine-tuning%20LLM%22%20OR%20%22QLoRA%22%20OR%20%22DPO%20training%22%20OR%20%22Unsloth%22%20OR%20%22axolotl%22%20OR%20%22LLaMA-Factory%22&hl=en-US&gl=US&ceid=US:en",
         include=FINETUNE_TERMS, exclude=FINETUNE_EXCLUDE, title_exclude=LOCAL_TITLE_EXCLUDE),
     gn('site:x.com "LoRA" OR "QLoRA" OR "DPO" OR "Unsloth" OR "axolotl" OR "fine-tuning"',
        include=FINETUNE_TERMS, exclude=FINETUNE_EXCLUDE, title_exclude=LOCAL_TITLE_EXCLUDE),
     rss("https://zenn.dev/topics/finetuning/feed", include=FINETUNE_TERMS),
     rss("https://zenn.dev/topics/lora/feed", include=FINETUNE_TERMS),
     rss("https://zenn.dev/topics/dpo/feed", include=FINETUNE_TERMS + ["LLM"]),
     rss("https://zenn.dev/topics/llm/feed", include=FINETUNE_TERMS + ["学習", "fine-tuning"]),
     rss("https://zenn.dev/topics/machinelearning/feed", include=FINETUNE_TERMS),
     rss("https://huggingface.co/blog/feed.xml", include=FINETUNE_TERMS + ["training", "fine-tune"]),
     rss("https://www.together.ai/blog/rss.xml", include=FINETUNE_TERMS),
     rss("https://github.com/unslothai/unsloth/releases.atom", include=FINETUNE_TERMS + ["performance", "fix", "improve"])]},
]

def gn_url(q):
    return "https://news.google.com/rss/search?q=" + urllib.parse.quote(q) + "&hl=ja&gl=JP&ceid=JP:ja"

def entry_epoch(e):
    # 記事の公開時刻(UTC epoch)。無ければNone。速報化(時刻ソート・時間窓)の心臓部。
    for k in ("published_parsed", "updated_parsed"):
        tm = e.get(k)
        if tm:
            try:
                return calendar.timegm(tm)
            except Exception:
                pass
    return None

def clean(t):
    t = re.sub(r"<[^>]+>", " ", t or "")
    t = t.replace("&nbsp;", " ").replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"').replace("&lt;", "<").replace("&gt;", ">")
    return re.sub(r"\s+", " ", t).strip()

def contains_any(text, terms):
    if not terms: return True
    low = text.lower()
    for term in terms:
        needle = str(term).lower()
        if not needle:
            continue
        if len(needle) <= 2 and needle.isascii() and needle.isalnum():
            if re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", low):
                return True
            continue
        if needle in low:
            return True
    return False

def is_release_version_noise(title):
    t = title.strip()
    low = t.lower()
    if any(x.lower() in low for x in MODEL_RELEASE_TERMS + ["codex", "claude", "gemini", "grok", "llama", "qwen", "deepseek"]):
        return False
    return bool(re.fullmatch(r"v?\d+(\.\d+){1,4}([._-]?(alpha|beta|rc)\.?\d*)?", low) or low in {"stable", "nightly"})

def canonical_title(title):
    t = re.sub(r"\s+-\s+[^|]+(?:\s+\|.*)?$", "", title or "")
    t = re.sub(r"\s*\([^)]{2,50}\)\s*$", "", t)
    t = re.sub(r"\s*（[^）]{2,50}）\s*$", "", t)
    return re.sub(r"\s+", " ", t).strip().lower()

def title_from_url(url):
    path = urllib.parse.urlparse(url).path.strip("/")
    slug = path.split("/")[-1] if path else urllib.parse.urlparse(url).netloc
    slug = urllib.parse.unquote(slug)
    return re.sub(r"[-_]+", " ", slug).strip().title()

def fetch_sitemap(src):
    try:
        req = urllib.request.Request(src["url"], headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=15) as resp:
            xml = resp.read(500000).decode("utf-8", "replace")
    except Exception as e:
        print("    sitemap失敗:", src["url"][:50], e); return []
    include = src.get("include") or []
    exclude = GLOBAL_EXCLUDE + (src.get("exclude") or [])
    title_include = src.get("title_include") or []
    title_exclude = src.get("title_exclude") or []
    seen_titles = set()
    prefixes = src.get("path_prefix") or []
    entries = []
    for block in re.findall(r"<url>(.*?)</url>", xml, re.S):
        loc_m = re.search(r"<loc>(.*?)</loc>", block, re.S)
        if not loc_m: continue
        loc = clean(loc_m.group(1))
        parsed = urllib.parse.urlparse(loc)
        path = parsed.path or "/"
        if prefixes and not any(path.startswith(prefix) for prefix in prefixes): continue
        title = title_from_url(loc)
        lastmod_m = re.search(r"<lastmod>(.*?)</lastmod>", block, re.S)
        lastmod = clean(lastmod_m.group(1)) if lastmod_m else ""
        filter_text = " ".join([title, path])
        if title_include and not contains_any(title, title_include): continue
        if title_exclude and contains_any(title, title_exclude): continue
        if include and not contains_any(filter_text, include): continue
        if exclude and contains_any(filter_text, exclude): continue
        summ = f"official page updated: {lastmod[:10]}" if lastmod else ""
        entries.append((lastmod, title, loc, summ, src.get("label") or parsed.netloc))
    entries.sort(key=lambda x: x[0], reverse=True)
    return [(title, loc, summ, label) for lastmod, title, loc, summ, label in entries[:PER_SOURCE]]

# ---- 日本語化（英語タイトル/要約をGoogle翻訳で和訳・失敗時は原文＝重要ニュースは英語でも可）----
# ★deep_translator(内部でrequests使用)はライブラリ側にtimeoutを渡す口が無く、
#   GitHub Actionsのクラウド側IPからだと接続がハングして戻ってこないことがある
#   （ローカルでは問題なくAction上でだけ無限待ちした実例2026-07-08）。
#   スレッド+timeoutで包んでも、ワーカースレッド自体が本当にハングした場合は
#   Pythonプロセス終了時のスレッドjoin待ちで結局終わらない恐れがある。
#   なので外部ライブラリを経由せず urllib.request.urlopen(timeout=...) で
#   Google翻訳の非公式エンドポイントを直接叩く＝ソケットレベルの本物のタイムアウトにする。
_JP_RE = re.compile(r"[ぁ-んァ-ヶ一-龠]")
_TR_TIMEOUT_SEC = 8
_TR_MAX_FAIL = 3          # 1エンジンがこの回数連続で失敗したら、そのエンジンだけ以後スキップ(他は生かす)

def is_ja(t):
    if not t: return True
    return len(_JP_RE.findall(t)) >= max(3, int(len(t) * 0.12))   # 既に日本語なら翻訳しない

# ---- 翻訳（★GIT内で完結。外部の翻訳APIサービスを実行時に一切叩かない）----
# 2026-09-03 Hikârư制約: 「GIT+Discord完結」。外部翻訳API(Google非公式/MyMemory/Gemini等)は使わない。
#   旧実装は Google翻訳の非公式endpointを叩いていたが、GitHub ActionsのIPから弾かれ
#   (ログ実物「翻訳サーバー応答なし(6s×3回連続) → 以後は原文のまま投稿」)、
#   実機で英語のまま98件・論文は21件中14件が未翻訳という状態を作っていた。
#   → argostranslate(CTranslate2ベース)でrunner内ローカル推論に変更。
#     実測: モデル準備10.9s、翻訳は1件目7.1s(ロード込)、2件目以降 0.06〜0.10s。
_ARGOS = None   # None=未初期化 / True=使える / False=使えない

def _argos_ready():
    global _ARGOS
    if _ARGOS is not None:
        return _ARGOS
    try:
        import argostranslate.package as P
        import argostranslate.translate as T
        codes = {l.code for l in T.get_installed_languages()}
        if not ("en" in codes and "ja" in codes):
            P.update_package_index()
            pkgs = [p for p in P.get_available_packages()
                    if p.from_code == "en" and p.to_code == "ja"]
            if not pkgs:
                print("    argostranslate: en->ja パッケージが見つからない")
                _ARGOS = False
                return _ARGOS
            P.install_from_path(pkgs[0].download())
        _ARGOS = True
    except Exception as e:
        print(f"    argostranslate 準備失敗: {type(e).__name__}: {str(e)[:80]}")
        _ARGOS = False
    return _ARGOS

def to_ja(t):
    """英文を日本語へ。runner内のローカル推論のみを使い、外部APIは叩かない。
       失敗時は原文のまま返す(重要ニュースは英語でも出す)。"""
    if not t or is_ja(t):
        return t
    if not _argos_ready():
        return t
    try:
        import argostranslate.translate as T
        out = T.translate(t[:1500], "en", "ja")
        return out if (out and is_ja(out)) else t
    except Exception:
        return t

def load_webhooks():
    m = {}
    for k, v in os.environ.items():
        if k.startswith("DISCORD_LOCALAI_WEBHOOK_"):
            m[k.replace("DISCORD_LOCALAI_WEBHOOK_", "")] = v
    if not m and os.path.exists(WEBHOOKS_JSON):
        for r in json.load(io.open(WEBHOOKS_JSON, encoding="utf-8")):
            if r.get("webhook_url"):
                m[r["env"].replace("DISCORD_LOCALAI_WEBHOOK_", "")] = r["webhook_url"]
    return m

def load_seen():
    try: return set(json.load(io.open(SEEN_FILE, encoding="utf-8")))
    except Exception: return set()

def save_seen(s):
    io.open(SEEN_FILE, "w", encoding="utf-8").write(json.dumps(sorted(s), ensure_ascii=False))

def fetch(src):
    if src["type"] == "sitemap":
        return fetch_sitemap(src)
    url = gn_url(src["q"]) if src["type"] == "gn" else src["url"]
    try:
        f = feedparser.parse(url)
    except Exception as e:
        print("    fetch失敗:", url[:50], e); return []
    feed_label = clean((f.feed.get("title", "") if getattr(f, "feed", None) else "")) or urllib.parse.urlparse(url).netloc
    include = src.get("include") or src.get("must") or []
    exclude = GLOBAL_EXCLUDE + (src.get("exclude") or [])
    title_include = src.get("title_include") or []
    title_exclude = src.get("title_exclude") or []
    # ★速報化: 全エントリを公開時刻で新しい順にソート(先頭 f.entries[:PER_SOURCE*5] 固定を廃止)。
    #          時刻が取れないものは後ろに回す(フィード順)。
    dated = [(entry_epoch(e), e) for e in (getattr(f, "entries", []) or [])]
    dated.sort(key=lambda x: (x[0] is not None, x[0] or 0.0), reverse=True)
    out = []
    seen_titles = set()
    for ts, e in dated:
        # ★時間窓: 公開時刻が分かるものは直近 FRESH_HOURS 時間だけを速報として通す。古いものは捨てる。
        if ts is not None and (NOW - ts) > FRESH_HOURS * 3600:
            continue
        title = clean(e.get("title", ""))
        if not title: continue
        summ = clean(e.get("summary", "") or e.get("description", ""))
        entry_source = e.get("source", {})
        if isinstance(entry_source, dict):
            entry_source = clean(entry_source.get("title", ""))
        else:
            entry_source = ""
        filter_text = " ".join([title, summ, entry_source])
        if is_release_version_noise(title): continue
        title_key = canonical_title(title)
        if title_key in seen_titles: continue
        if title_include and not contains_any(title, title_include): continue
        if title_exclude and contains_any(title, title_exclude): continue
        if include and not contains_any(filter_text, include): continue
        if exclude and contains_any(filter_text, exclude): continue
        seen_titles.add(title_key)
        if len(summ) < 25 or summ[:18] == title[:18]: summ = ""
        summ = summ[:160] + ("…" if len(summ) > 160 else "")
        out.append((title, e.get("link", ""), summ, src.get("label") or entry_source or feed_label))
        if len(out) >= PER_SOURCE: break
    return out

def collect_topic_items(t, seen, sleep_sec=0.4):
    # ★2026-09-08 修正: タイトルのキーは【部屋ごと】に持つ。
    #   2026-09-05にタイトル併用を入れた時、seenが全トピック共通の1つの集合なので
    #   「同じ記事は15部屋のどこか1つにしか出せない」状態になっていた。
    #   実測(9/8): タイトルで止まっていた7件は【7件とも別の部屋にだけ出ていた】
    #     例: 「M365 CopilotでもGPT-6 Astra利用可能に」→チャッピーに出て★copilotに出せない
    #         「Gemini 3.8 Flash提供開始」→geminiに出て★新モデルリリースに出せない
    #   15分類は「分類が重なる記事は両方に出る」のが仕様なので、部屋名を接頭辞に付ける。
    #   ★URLの方は従来どおり全部屋共通のまま（同じURLは1回だけ、は元からの設計）。
    room = t["env"] + "|"
    source_hits = []
    keys = set()
    for src in t["sources"]:
        rows = []
        for title, link, summ, srclabel in fetch(src):
            title_key = canonical_title(title)
            # ★2026-09-05 実測: Google Newsは同じ記事に【URLを3種類】振ってくる。
            #   seenがlinkしか持っていなかったため、同じ記事が媒体違いで何度も流れていた。
            #   実測(直近100件×15CH): URLだけ=121件しか止まらない / タイトルも見る=256件(+135)。
            #   誤爆の確認: 同じキーで原文が違った81組は【全部が媒体名の違いだけ】=同じ記事。
            #              12字未満の短いキーで重複扱いになったのは1組のみ(それも原文1種類)。
            if (not link or link in seen or (room + title_key) in seen
                    or link in keys or title_key in keys):
                continue
            keys.add(link)
            keys.add(title_key)
            rows.append((title, link, summ, srclabel))
        if rows:
            source_hits.append(rows)
        if sleep_sec:
            time.sleep(sleep_sec)

    picked = []
    picked_keys = set()
    def add_item(item):
        key = item[1] or canonical_title(item[0])
        if key in picked_keys:
            return
        picked_keys.add(key)
        picked.append(item)

    # Google Newsだけで枠を埋めない。朝活方式として、実証済み母体を分類別に混ぜる。
    for rows in source_hits:
        if len(picked) >= PER_CHANNEL:
            break
        add_item(rows[0])

    if len(picked) < PER_CHANNEL:
        for rows in source_hits:
            for item in rows[1:]:
                if len(picked) >= PER_CHANNEL:
                    break
                add_item(item)
            if len(picked) >= PER_CHANNEL:
                break
    return picked[:PER_CHANNEL]

def post(url, header, items, color):
    embeds = []
    for title, link, summ, src in items:
        emb = {"title": title[:250], "url": link, "color": color, "footer": {"text": src[:100]}}
        if summ: emb["description"] = summ
        embeds.append(emb)
    body = {"content": header, "embeds": embeds[:10]}
    r = urllib.request.Request(url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "User-Agent": UA}, method="POST")
    # ★2026-09-03: 旧実装は while True で429を無限リトライしており、Discord側のレート制限が
    #   続くと run が終わらなくなる(実測: 1runが16分以上 in_progress のまま残り、concurrencyで
    #   後続の【自動起動run】が cancelled になった＝自動配信が殺された)。
    #   リトライ回数・1回の待ち・累計待ちの3つに上限を入れて必ず抜ける。
    MAX_RETRY = 5
    total_wait = 0.0
    for attempt in range(MAX_RETRY):
        try:
            with urllib.request.urlopen(r, timeout=20) as x: return x.status
        except urllib.error.HTTPError as e:
            if e.code == 429:
                try: retry = float(json.loads(e.read()).get("retry_after", 1.0))
                except Exception: retry = 1.0
                retry = min(retry, 10.0)                      # 1回の待ちの上限
                total_wait += retry + 0.3
                if attempt >= MAX_RETRY - 1 or total_wait > 30:
                    return f"429:give_up(try{attempt+1},wait{total_wait:.0f}s)"
                time.sleep(retry + 0.3); continue
            return f"{e.code}:{e.read().decode('utf-8','replace')[:120]}"
        except Exception as e:
            return f"ERR:{type(e).__name__}"
    return "429:give_up"

def main():
    hooks = load_webhooks(); seen = load_seen()
    _ORDER = ['VIDEO', 'MUSIC', 'TTS', 'FINETUNE', 'IMAGE']
    globals()["TOPICS"] = sorted(TOPICS, key=lambda t: _ORDER.index(t["env"]) if t["env"] in _ORDER else 99)
    print(f"webhooks={len(hooks)} seen={len(seen)} topics={len(TOPICS)}")
    for t in TOPICS:
        url = hooks.get(t["env"])
        if not url:
            print(f"{t['num']} {t['name']} … webhook未設定スキップ"); continue
        picked = collect_topic_items(t, seen)
        if not picked:
            print(f"{t['num']} {t['name']} … 新規なし"); continue
        # ★翻訳の【前】のキーを先に取る。to_ja後に取ると日本語で保存して英語で照合するズレが出る。
        keys_before = [canonical_title(ti) for (ti, _, _, _) in picked]
        picked = [(to_ja(ti), li, to_ja(su), sr) for (ti, li, su, sr) in picked]  # 英語→日本語（失敗時は原文）
        st = post(url, f"**{t['num']}｜{t['name']}**", picked, t["color"])
        room = t["env"] + "|"             # ★部屋ごとに持つ（分類をまたぐ掲載は殺さない）
        for (ti, link, _, _), k0 in zip(picked, keys_before):
            seen.add(link)
            seen.add(room + k0)               # ★翻訳前（同じ英語記事が別フィードから来た時に効く）
            seen.add(room + canonical_title(ti))  # ★翻訳後（Discordに出ている形と一致させる）
        print(f"{t['num']} {t['name']} … {len(picked)}件 ({st})")
        time.sleep(1.3)
    save_seen(seen); print("seen保存:", len(seen))

if __name__ == "__main__":
    main()
