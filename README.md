# localai-media-bot

**AIラボ ローカルAI (Media: TTS/Music/Video/Image/Finetune)**

★2026-09-15 新設。`akatsuki-5648/ailab-news-bot` からRSS負荷分散のためローカルAI系のみを2リポに分割 (core/media)。

## 対象CH (このリポ)

TTS / MUSIC / VIDEO / IMAGE / FINETUNE

## つかいかた

1. `.github/workflows/localai_news_notify.yml` の cron が15分毎に発火。
2. 各CHの Webhook URL は GitHub Secrets `DISCORD_LOCALAI_WEBHOOK_{env}` に登録。
3. 重複回避: `localai_media_seen_urls.json` に投稿済みURL/タイトルを保存 → 自己commit/push で永続化。

## 関連

- 姉妹リポ: [ailab-news-bot](https://github.com/akatsuki-5648/ailab-news-bot) (15分類・グローバルAIニュース)
- 姉妹リポ: [discord-rss-notifier](https://github.com/akatsuki-5648/discord-rss-notifier) (IC倶楽部・crypto・market)
- 姉妹リポ: [localai-core-bot](https://github.com/akatsuki-5648/localai-core-bot)

## 設計原則

- 外部翻訳APIを実行時に叩かない (`argostranslate` runner内ローカル推論)
- 公式RSS/API/changelog は補助 (主水路は Google News検索RSS + subreddit)
- FRESH_HOURS=48 の時間窓、PER_SOURCE=3、PER_CHANNEL=4 で速報化
