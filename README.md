# Research Team

> [!WARNING]
> **このソフトウェアはアルファ版です。**
> 仕様・API・動作は予告なく変更される可能性があります。本番環境・重要用途への使用は推奨しません。

ブラウザ制御型のマルチエージェント調査システムです。指定したテーマについてウェブ調査を自動で行い、構造化された Markdown レポートを生成します。

---

## 特徴

- **ブラウザ制御 UI** — Playwright による Chromium 制御。承認バナーでページの取り込み可否をインタラクティブに判断
- **動的エージェント編成** — PM・TeamBuilder・スペシャリストが協調してテーマを分解し調査を実行
- **品質ループ** — 調査結果を自動評価し、品質基準を満たすまで再調査（最大 `MAX_QUALITY_ITERATIONS` 回）
- **多言語検索** — ロケール設定により日本語・中国語・英語等ネイティブクエリで検索
- **プロジェクト管理** — 複数テーマをプロジェクトとして管理し、ワークスペースを分離
- **書籍スタイル出力** — `--style book_chapter` で章・節構成の長文レポートを生成（オプション）
- **中断・再開** — 調査を途中で中断しても、次回起動時に未完了セッションを検出して続きから再開できる

---

## 必要環境

| 項目 | バージョン |
|------|-----------|
| Python | 3.11 以上 |
| Node.js | 18 以上（pi-agent 実行に必要） |
| pi-agent | `@mariozechner/pi-coding-agent` |
| ブラウザ | Chromium（Playwright が自動インストール） |

---

## インストール

```bash
# 1. リポジトリをクローン
git clone <repository-url>
cd research_team

# 2. 仮想環境を作成・有効化
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 3. パッケージをインストール
pip install -e .

# 4. Playwright ブラウザをインストール
playwright install chromium

# 5. pi-agent をインストール（Node.js が必要）
npm install -g @mariozechner/pi-coding-agent
```

### オプション依存

```bash
# Tavily API 検索を使う場合
pip install -e ".[search-api]"

# PDF / Excel 出力を使う場合
pip install -e ".[output-extra]"

# 開発・テスト用
pip install -e ".[dev]"
```

---

## 設定

プロジェクトルートに `.env` ファイルを作成します。`.env.example` をコピーして編集してください。

```bash
cp .env.example .env
```

### 主な設定項目

| 変数名 | デフォルト | 説明 |
|--------|-----------|------|
| `SEARCH_MODE` | `human` | 検索モード: `human` / `tavily` / `serper` |
| `SEARCH_ENGINE_URL` | `https://www.google.com/search?q=` | 検索エンジンの URL プレフィックス（human モード） |
| `TAVILY_API_KEY` | — | Tavily モード使用時に必要 |
| `SERPER_API_KEY` | — | Serper モード使用時に必要 |
| `OPENAI_API_KEY` | — | OpenAI 経由で LLM を使う場合 |
| `ANTHROPIC_API_KEY` | — | Anthropic 経由で LLM を使う場合 |
| `PI_AGENT_BIN` | `pi` | pi-agent バイナリのパスまたはコマンド名 |
| `PI_MODEL` | `github-copilot/claude-sonnet-4.5` | pi-agent が使用する LLM モデル（`<provider>/<model-id>` 形式） |
| `MAX_QUALITY_ITERATIONS` | `3` | 品質ループの最大繰り返し回数 |

**最低限必要な設定（human モード）:**

```env
SEARCH_ENGINE_URL=https://www.google.com/search?q=
```

---

## プロバイダ認証

`PI_MODEL` に指定するプロバイダによって認証方法が異なります。

### GitHub Copilot（デフォルト）

API キー不要。pi をインタラクティブモードで起動し、`/login` で OAuth 認証を行います。認証情報は `~/.pi/agent/` に保存され、以降は research-team からも自動的に利用されます。

```bash
pi         # pi をインタラクティブモードで起動
/login     # コマンドを入力して GitHub Copilot を選択し OAuth 認証を完了する
/quit      # 認証完了後に終了
```

> GitHub アカウントに Copilot のサブスクリプション（Individual / Business / Enterprise）が必要です。

### Anthropic（API キー）

```env
# .env
ANTHROPIC_API_KEY=sk-ant-...
PI_MODEL=anthropic/claude-opus-4-5
```

### OpenAI（API キー）

```env
# .env
OPENAI_API_KEY=sk-...
PI_MODEL=openai/gpt-4o
```

### Anthropic Claude Pro/Max・OpenAI ChatGPT Plus/Pro（サブスクリプション）

API キーの代わりにサブスクリプション経由で利用することも可能です。GitHub Copilot 同様に `pi` 起動後に `/login` でプロバイダを選択してください。

### その他のプロバイダ

Azure OpenAI・Google Gemini・Amazon Bedrock など多数のプロバイダに対応しています。詳細は [pi-agent 公式ドキュメント](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/providers.md) を参照してください。

---

## 使い方

### 基本起動

```bash
research-team start
```

または：

```bash
python -m research_team.cli.main start
```

起動するとブラウザが開き、**Research Team Control Panel** が表示されます。

### 起動オプション

```bash
research-team start [OPTIONS]
```

| オプション | 選択肢 | デフォルト | 説明 |
|-----------|--------|-----------|------|
| `--depth` | `quick` / `standard` / `deep` | `standard` | 調査の深さ |
| `--style` | `research_report` / `executive_memo` / `magazine_column` / `book_chapter` | `research_report` | 出力スタイル |
| `--search-mode` | `human` / `tavily` | 環境変数 `SEARCH_MODE` | 検索エンジンの切り替え |
| `--workspace` | パス文字列 | `./workspace` | レポートの出力先ディレクトリ |
| `--output-format` | `markdown` | `markdown` | 出力形式 |

**深さオプションの目安：**

| `--depth` | 最低品質基準 | 用途 |
|-----------|------------|------|
| `quick` | 300 文字 | 素早い概要把握 |
| `standard` | 800 文字 | 通常の調査 |
| `deep` | 2,000 文字 | 深い専門調査 |

### 操作の流れ

1. **起動** — ブラウザに Control Panel が表示される
   - 未完了の調査セッションがある場合、CSM から再開の確認が表示される（「はい」で続きから再開、「いいえ」で最初から）
2. **テーマ入力** — 左ペインのチャット欄に調査テーマを入力して送信
3. **確認** — CSM からの確認メッセージに「はい」と返答して調査開始
4. **承認バナー対応**（human モードのみ） — 調査員がページを取得するたびに右ペインにバナーが表示される
   - **取り込む** — ページ内容を調査データとして使用
   - **スキップ** — このページを除外
5. **完了** — 進捗が止まり、CSM から完了メッセージが届く
6. **追加調査**（任意） — 追加テーマを入力するか「いいえ」でセッション終了

### 出力ファイル

調査完了後、`workspace/` ディレクトリ（またはアクティブプロジェクトの配下）に以下が生成されます。

**共通ディレクトリ構造:**

```
workspace/
└── sessions/
    └── 20260420_120000_テーマ名/
        └── artifacts/
            ├── wbs_run<N>_<date>.md               # WBS・品質目標（スタイルにより粒度が異なる）
            ├── agent_briefing_run<N>_<date>.md    # チーム編成
            ├── <スタイル別成果物>                   # 後述
            ├── review_run<N>_iter<i>_<date>.md    # 品質レビュー記録（品質ループが実行された場合）
            ├── minutes_run<N>_iter<i>_<date>.md   # 打ち合わせ議事録（品質ループが実行された場合）
            ├── discussion_run<N>_<date>.md        # スペシャリスト対談（オプション）
            ├── report_<topic>_<date>.md           # 最終レポート
            ├── manifest_run<N>.json               # ランメタデータ
            ├── run_progress.json                  # 再開用進捗（調査完了時に自動削除）
            └── raw/                               # 検索・フェッチ生データ（ゼロトラスト保存）
                └── <name>_run<N>_<tool>_<idx>_<datetime>.md
```

**スタイル別の最小成果物単位:**

| `--style` | 最小成果物単位 | ファイルパターン |
|-----------|--------------|----------------|
| `research_report`（デフォルト） | スペシャリスト | `specialist_<name>_run<N>_<date>.md` |
| `executive_memo` | スペシャリスト | `specialist_<name>_run<N>_<date>.md` |
| `magazine_column` | スペシャリスト | `specialist_<name>_run<N>_<date>.md` |
| `book_chapter` | 節（section） | `book_<section_id>_run<N>_<date>.md` |

> **設計方針:** WBS の構造と成果物の構造は整合します。`book_chapter` スタイルでは部→章→節の最小粒度まで PM が設計し、節単位で成果物が生成されます。WBS にも節レベルのタスクが表示されます。

**`research_report` / `executive_memo` / `magazine_column` の場合:**

```
artifacts/
├── wbs_run1_20260420.md
├── agent_briefing_run1_20260420.md
├── specialist_AIエンジニア_run1_20260420.md   # スペシャリストごとに1ファイル
├── specialist_市場アナリスト_run1_20260420.md
├── discussion_run1_20260420.md              # 対談（生成された場合）
├── review_run1_iter1_20260420.md
├── report_テーマ名_20260420.md
└── manifest_run1.json
```

**`book_chapter` の場合:**

```
artifacts/
├── wbs_run1_20260420.md                     # 部・章・節レベルのタスクを含む
├── agent_briefing_run1_20260420.md
├── book_ch1-sec1_run1_20260420.md           # 節ごとに1ファイル
├── book_ch1-sec2_run1_20260420.md
├── book_ch2-sec1_run1_20260420.md
├── discussion_run1_20260420.md
├── report_テーマ名_20260420.md              # 全セクション統合レポート
└── manifest_run1.json
```

---

## プロジェクト管理

複数の調査テーマをプロジェクトとして管理できます。

```bash
# 新規プロジェクト作成（自動でアクティブになる）
research-team project init "東京の登山スポット"

# プロジェクト一覧（▶ がアクティブ）
research-team project list

# プロジェクト切り替え（ID の前方一致で指定可）
research-team project switch abc12345

# プロジェクトをアーカイブ
research-team project archive abc12345
```

アクティブプロジェクトがある場合、`start` で生成されるファイルはそのプロジェクトの配下に保存されます：

```
workspace/projects/<project-id>/files/artifacts/
```

---

## アーキテクチャ

```
[ユーザー]
    │
    │ research-team start
    ▼
[cli/main.py]
    ├── ControlUI 起動（Playwright Chromium）
    └── ResearchCoordinator.run_interactive()
           │
           ├── [テーマ確認ループ]
           │    └── CSM ↔ ユーザー: テーマ・深さ確認
           │
           └── [調査ループ]
                ├── PMAgent: WBS・品質目標定義
                ├── TeamBuilder: スペシャリスト編成（最大3名）
                ├── DynamicAgentFactory: スペシャリスト生成・実行
                │    └── web_search / web_fetch
                │         └── HumanSearchEngine → 承認バナー
                ├── QualityLoop: 品質評価 → 不合格なら再調査
                └── MarkdownOutput: レポート保存
```

### 主要コンポーネント

| モジュール | 役割 |
|-----------|------|
| `orchestrator/coordinator.py` | 調査全体の制御・エージェント間の協調 |
| `agents/dynamic/factory.py` | テーマに応じた専門家エージェントの動的生成 |
| `search/human.py` | Playwright 経由のブラウザ検索・承認フロー |
| `pi_bridge/client.py` | pi-agent（LLM ランタイム）との RPC 通信 |
| `ui/control_ui.py` | ブラウザ上の制御パネル（チャット・承認 UI） |
| `output/markdown.py` | Markdown レポートの生成・保存 |
| `project/manager.py` | プロジェクト CRUD・アクティブ状態管理 |

---

## 開発

### テスト実行

```bash
# ユニットテスト（推奨）
python -m pytest tests/unit/ -x -q

# 全テスト（integration / e2e を含む）
python -m pytest -x -q
```

テストマーカー：

| マーカー | 説明 | デフォルト |
|---------|------|-----------|
| `unit` | 外部依存なしの単体テスト | 実行 |
| `integration` | 外部サービスが必要 | スキップ |
| `e2e` | pi-agent + GitHub Copilot ログインが必要 | スキップ |
| `interactive` | 実ブラウザと手動操作が必要 | スキップ |

### 診断スクリプト

```bash
# UI + Coordinator の動作確認（ダミーサーバー使用）
python scripts/diag.py

# Google DOM 抽出の確認
python scripts/diagnose_google_dom.py

# 統合トレーステスト
python scripts/trace_test.py
```

### ログ

実行ログは起動ディレクトリの `rt_run.log` に出力されます（デバッグレベル）。

---

## ドキュメント

| ファイル | 内容 |
|---------|------|
| `docs/us1_guide.md` | ユーザー操作ガイド（テーマ確認フロー）+ CLI リファレンス |
| `docs/us2_guide.md` | WBS 表示・追加リクエストループの仕様 |
| `docs/requirements.md` | システム要件・設計制約 |
| `AGENTS.md` | AI エージェント向け開発ルール（テスト必須条件等） |

---

## ライセンス

MIT
